"""Conservative OCR grayscale and a separately enhanced detection branch."""

import math
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageDraw

from .config import PipelineConfig, PreprocessConfig, parse_pages
from .pdf import file_sha256, render_page, transform_points, validate_document
from .runtime import RunContext, write_json


def expanded_rotation(width: int, height: int, angle: float) -> tuple[np.ndarray, tuple[int, int]]:
    if abs(angle) < 1e-10:
        return np.eye(3), (width, height)
    affine = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1)
    matrix = np.vstack([affine, [0, 0, 1]])
    corners = transform_points([(0, 0), (width, 0), (width, height), (0, height)], matrix)
    minimum, maximum = corners.min(axis=0), corners.max(axis=0)
    matrix[:2, 2] -= minimum
    size = tuple(int(math.ceil(value)) for value in maximum - minimum)
    return matrix, size


def estimate_deskew(gray: np.ndarray, config: PreprocessConfig) -> dict:
    """Return a correction angle; positive follows OpenCV counterclockwise convention."""
    result = {"estimated_skew_degrees": 0.0, "applied_correction_degrees": 0.0,
              "needs_review": False, "score_gain": 0.0}
    if config.angle_override is not None:
        return {**result, "applied_correction_degrees": config.angle_override, "reason": "manual_override"}
    if not config.deskew:
        return {**result, "reason": "disabled"}
    height, width = gray.shape
    ratio = min(1.0, 1400 / width)
    small = cv2.resize(gray, (max(1, round(width * ratio)), max(1, round(height * ratio))), interpolation=cv2.INTER_AREA)
    sh, sw = small.shape
    roi = small[int(sh * .08):max(int(sh * .85), int(sh * .08) + 1),
                int(sw * .10):max(int(sw * .90), int(sw * .10) + 1)]
    if min(roi.shape) < 32 or np.ptp(roi) < 10:
        return {**result, "needs_review": True, "reason": "insufficient_foreground"}
    _, ink = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    fraction = np.count_nonzero(ink) / ink.size
    result["foreground_fraction"] = float(fraction)
    if np.count_nonzero(ink) < 100 or fraction < .002 or fraction > .45:
        return {**result, "needs_review": True, "reason": "insufficient_or_dense_foreground"}
    rh, rw = ink.shape

    def score(angle):
        affine = cv2.getRotationMatrix2D((rw / 2, rh / 2), float(angle), 1)
        rotated = cv2.warpAffine(ink, affine, (rw, rh), flags=cv2.INTER_NEAREST, borderValue=0)
        profile = (rotated.astype(np.float32) / 255).sum(axis=1)
        return float(np.square(np.diff(profile)).sum() / max(profile.sum(), 1))

    baseline = score(0)
    coarse = np.linspace(-config.max_skew_degrees, config.max_skew_degrees,
                         int(math.ceil(2 * config.max_skew_degrees / .25)) + 1)
    best = max(((score(angle), float(angle)) for angle in coarse), key=lambda pair: (pair[0], -abs(pair[1])))
    fine = np.arange(max(-config.max_skew_degrees, best[1] - .25),
                     min(config.max_skew_degrees, best[1] + .25) + .00001, .05)
    best = max([best] + [(score(angle), float(angle)) for angle in fine], key=lambda pair: (pair[0], -abs(pair[1])))
    correction = round(best[1], 4)
    gain = (best[0] - baseline) / max(baseline, 1e-6)
    result.update({"estimated_skew_degrees": -correction, "candidate_correction_degrees": correction,
                   "baseline_score": baseline, "best_score": best[0], "score_gain": gain,
                   "estimation_size_pixels": [sw, sh], "estimation_roi": [0.10, 0.08, 0.90, 0.85]})
    if abs(correction) >= config.max_skew_degrees - .05:
        return {**result, "needs_review": True, "reason": "search_boundary"}
    if abs(correction) < config.deskew_min_angle:
        return {**result, "reason": "already_horizontal"}
    if gain < config.deskew_min_gain:
        return {**result, "needs_review": True, "reason": "insufficient_score_gain"}
    # Disjoint comparable peaks imply ambiguous periodicity/graphics rather than reliable text alignment.
    other_scores = [score(a) for a in coarse if abs(a - correction) >= .75]
    if other_scores and max(other_scores) >= best[0] * .98:
        return {**result, "needs_review": True, "reason": "ambiguous_peaks"}
    return {**result, "applied_correction_degrees": correction, "reason": "projection_score"}


def preprocess_image(rgb: np.ndarray, dpi: int, config: PreprocessConfig) -> tuple[dict, dict]:
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("Expected uint8 RGB image")
    original = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    deskew = estimate_deskew(original, config)
    height, width = original.shape
    matrix, size = expanded_rotation(width, height, deskew["applied_correction_degrees"])
    if size[0] * size[1] > config.max_page_pixels:
        raise ValueError("Expanded rotation exceeds max_page_pixels; explicitly choose a smaller DPI")
    gray = (cv2.warpAffine(original, matrix[:2], size, flags=cv2.INTER_CUBIC, borderValue=255)
            if abs(deskew["applied_correction_degrees"]) > 1e-10 else original.copy())
    # Denoising is strictly confined to detection; it never changes the OCR grayscale.
    detection = cv2.GaussianBlur(gray, (3, 3), 0) if config.denoise else gray
    enhanced = cv2.createCLAHE(clipLimit=config.clahe_clip_limit,
                              tileGridSize=(config.clahe_grid_size, config.clahe_grid_size)).apply(detection)
    block = max(3, round(config.adaptive_block_size * dpi / 300))
    block += 1 if block % 2 == 0 else 0
    binary = cv2.adaptiveThreshold(enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, block, config.adaptive_c)
    images = {"raw": rgb, "gray-original": original, "gray": gray, "enhanced": enhanced, "binary": binary}
    metadata = {"deskew": deskew, "raw_to_processed": matrix.tolist(),
                "processed_to_raw": np.linalg.inv(matrix).tolist(), "processed_size_pixels": list(size),
                "actual_adaptive_block_size": block, "binary_convention": "0 ink, 255 background",
                "ocr_branch": "grayscale plus at most one expanded rotation; no CLAHE, denoise or binarization",
                "detection_branch": "optional 3x3 Gaussian, CLAHE, adaptive threshold",
                "parameters": config.model_dump(mode="json"),
                "versions": {"opencv": cv2.__version__, "numpy": np.__version__}}
    return images, metadata


def make_comparison(images: dict) -> Image.Image:
    panels = []
    for name in ("raw", "gray", "binary"):
        image = Image.fromarray(images[name]).convert("RGB")
        image.thumbnail((600, 900))
        panel = Image.new("RGB", (620, 940), "white")
        ImageDraw.Draw(panel).text((10, 10), name, fill="black")
        panel.paste(image, (10, 35))
        panels.append(panel)
    canvas = Image.new("RGB", (620 * len(panels), 940), "white")
    for index, panel in enumerate(panels):
        canvas.paste(panel, (index * 620, 0))
    return canvas


def make_detail_comparison(images: dict, raw_to_processed) -> tuple[Image.Image, list[dict]]:
    """Native-pixel crops aligned back to raw coordinates, for small-mark review."""
    height, width = images["gray-original"].shape
    crop_w, crop_h = min(420, width), min(180, height)
    locations = [(0.15, 0.13), (0.20, 0.42), (0.75, 0.82)]
    canvas = Image.new("RGB", (crop_w * 3, (crop_h + 45) * len(locations)), "white")
    draw = ImageDraw.Draw(canvas)
    records = []
    inverse = np.linalg.inv(raw_to_processed)
    for row, (fx, fy) in enumerate(locations):
        x = min(round(width * fx), width - crop_w)
        y = min(round(height * fy), height - crop_h)
        crop_matrix = np.array([[1, 0, -x], [0, 1, -y], [0, 0, 1]], dtype=float) @ inverse
        patches = [images["raw"][y:y + crop_h, x:x + crop_w],
                   cv2.warpPerspective(images["gray"], crop_matrix, (crop_w, crop_h), flags=cv2.INTER_CUBIC, borderValue=255),
                   cv2.warpPerspective(images["binary"], crop_matrix, (crop_w, crop_h), flags=cv2.INTER_NEAREST, borderValue=255)]
        for column, (name, patch) in enumerate(zip(("Raw RGB", "OCR gray (aligned)", "Detection binary (aligned)"), patches)):
            draw.text((column * crop_w + 5, row * (crop_h + 45) + 5), f"{name}: x={x}, y={y}", fill="black")
            canvas.paste(Image.fromarray(patch).convert("RGB"), (column * crop_w, row * (crop_h + 45) + 35))
        records.append({"raw_box": [x, y, x + crop_w, y + crop_h], "display_scale": 1,
                        "note": "OCR/binary patches inverse-aligned for inspection; inversion adds display-only interpolation"})
    return canvas, records


def _save_page(images, metadata, directory: Path, dpi: int) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    artifacts = {}
    for name, pixels in images.items():
        path = directory / f"{name}.png"
        Image.fromarray(pixels).save(path, dpi=(dpi, dpi))
        artifacts[name] = {"file": path.name, "sha256": file_sha256(path)}
    comparison = directory / "comparison.png"
    make_comparison(images).save(comparison)
    artifacts["comparison"] = {"file": comparison.name, "sha256": file_sha256(comparison)}
    detail_path = directory / "detail-comparison.png"
    detail, regions = make_detail_comparison(images, metadata["raw_to_processed"])
    detail.save(detail_path)
    artifacts["detail-comparison"] = {"file": detail_path.name, "sha256": file_sha256(detail_path)}
    metadata["inspection_regions"] = regions
    metadata["artifacts"] = artifacts
    write_json(directory / "metadata.json", metadata)
    return {"page_number": metadata["page_number"], "metadata": str(directory.name + "/metadata.json"),
            "needs_review": metadata["deskew"]["needs_review"]}


def preprocess_pdf(config: PipelineConfig, run: RunContext) -> dict:
    pages = parse_pages(config.pages)
    manifest = {"run_id": run.run_id, "stage": "page_preprocessing", "status": "running",
                "ocr_performed": False, "api_calls": 0, "selected_pages": pages,
                "config": config.model_dump(mode="json"), "pages": []}
    manifest_path = run.directory / "manifest.json"
    write_json(manifest_path, manifest)
    try:
        manifest["pdf_sha256"] = file_sha256(config.pdf)
        with pymupdf.open(config.pdf) as document:
            validate_document(document, pages)
            manifest["pdf_page_count"] = document.page_count
            for number in pages:
                run.log(f"Preprocessing page {number} at {config.dpi} DPI")
                rgb, render_metadata = render_page(document, number, config.dpi, config.preprocess.max_page_pixels)
                images, metadata = preprocess_image(rgb, config.dpi, config.preprocess)
                matrix = np.asarray(metadata["raw_to_processed"]) @ np.asarray(render_metadata["page_to_raw"])
                metadata.update(render_metadata)
                metadata.update({"pdf_sha256": manifest["pdf_sha256"], "page_to_processed": matrix.tolist(),
                                 "processed_to_page": np.linalg.inv(matrix).tolist()})
                directory = run.directory / "pages" / f"page-{number:04}"
                record = _save_page(images, metadata, directory, config.dpi)
                record["metadata"] = str(Path("pages") / record["metadata"])
                manifest["pages"].append(record)
                write_json(manifest_path, manifest)
                run.log(f"Page {number}: correction={metadata['deskew']['applied_correction_degrees']}, reason={metadata['deskew']['reason']}")
                del images, rgb
        manifest["status"] = "completed"
        write_json(manifest_path, manifest)
        return manifest
    except Exception:
        manifest["status"] = "failed"
        write_json(manifest_path, manifest)
        raise
