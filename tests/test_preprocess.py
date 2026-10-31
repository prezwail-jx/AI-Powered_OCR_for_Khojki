import json
import math

import cv2
import numpy as np
import pymupdf
import pytest
from PIL import Image

from khojki_ocr.cli import main
from khojki_ocr.config import PreprocessConfig
from khojki_ocr.pdf import map_box, render_page, transform_points
from khojki_ocr.preprocess import estimate_deskew, expanded_rotation, preprocess_image


def synthetic_lines():
    image = np.full((950, 750), 255, np.uint8)
    for row in range(130, 820, 55):
        for col in range(100, 650, 29):
            cv2.rectangle(image, (col, row), (col + 17, row + 14), 0, -1)
            cv2.circle(image, (col + 5, row - 5), 2, 0, -1)
    return image


@pytest.mark.parametrize("angle", [-3.0, -1.5, 1.5, 3.0])
def test_deskew_correction_sign_and_accuracy(angle):
    clean = synthetic_lines()
    h, w = clean.shape
    tilted = cv2.warpAffine(clean, cv2.getRotationMatrix2D((w/2, h/2), angle, 1), (w, h), borderValue=255)
    decision = estimate_deskew(tilted, PreprocessConfig())
    assert decision["reason"] == "projection_score"
    assert decision["applied_correction_degrees"] == pytest.approx(-angle, abs=.15)


def test_deskew_safe_fallbacks_and_override():
    blank = np.full((400, 400), 255, np.uint8)
    assert estimate_deskew(blank, PreprocessConfig())["applied_correction_degrees"] == 0
    assert estimate_deskew(blank, PreprocessConfig())["needs_review"]
    horizontal = estimate_deskew(synthetic_lines(), PreprocessConfig())
    assert horizontal["applied_correction_degrees"] == 0
    assert horizontal["reason"] == "already_horizontal"
    assert estimate_deskew(blank, PreprocessConfig(deskew=False))["reason"] == "disabled"
    assert estimate_deskew(blank, PreprocessConfig(angle_override=2.0))["applied_correction_degrees"] == 2
    clean = synthetic_lines()
    tilted = cv2.warpAffine(clean, cv2.getRotationMatrix2D((375, 475), 5, 1), (750, 950), borderValue=255)
    boundary = estimate_deskew(tilted, PreprocessConfig())
    assert boundary["reason"] == "search_boundary"
    assert boundary["applied_correction_degrees"] == 0


@pytest.mark.parametrize("angle", [-5.0, 0, 5.0])
def test_rotation_expands_and_round_trip(angle):
    matrix, (width, height) = expanded_rotation(500, 700, angle)
    corners = np.array([(0, 0), (500, 0), (500, 700), (0, 700)])
    mapped = transform_points(corners, matrix)
    assert mapped.min() >= -1e-8
    assert np.all(mapped[:, 0] <= width + 1e-8)
    assert np.all(mapped[:, 1] <= height + 1e-8)
    assert np.allclose(transform_points(mapped, np.linalg.inv(matrix)), corners, atol=1e-8)
    box = map_box([10, 20, 80, 110], matrix)
    assert len(box["polygon"]) == 4


def test_ocr_branch_never_receives_detection_filters():
    gray = synthetic_lines()
    rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
    original = rgb.copy()
    images, metadata = preprocess_image(rgb, 300, PreprocessConfig(deskew=False, denoise=True))
    assert np.array_equal(images["raw"], original)
    assert np.array_equal(images["gray-original"], gray)
    assert np.array_equal(images["gray"], gray)
    assert set(np.unique(images["binary"])) == {0, 255}
    assert images["gray"].ndim == 2
    assert metadata["actual_adaptive_block_size"] % 2 == 1
    repeated, _ = preprocess_image(rgb, 300, PreprocessConfig(deskew=False, denoise=True))
    assert all(np.array_equal(images[k], repeated[k]) for k in images)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("dpi", [300, 400])
def test_render_dimensions_crop_and_actual_marker_mapping(rotation, dpi):
    with pymupdf.open() as document:
        page = document.new_page(width=440, height=600)
        page.draw_rect(pymupdf.Rect(130, 170, 150, 190), color=(1, 0, 0), fill=(1, 0, 0))
        page.set_cropbox(pymupdf.Rect(40, 50, 400, 550))
        page.set_rotation(rotation)
        rgb, metadata = render_page(document, 1, dpi, 40000000)
        assert rgb.shape == (math.ceil(page.rect.height * dpi/72), math.ceil(page.rect.width * dpi/72), 3)
        expected = transform_points([(100, 130)], metadata["page_to_raw"])[0]
        red = (rgb[:, :, 0] > 240) & (rgb[:, :, 1] < 10) & (rgb[:, :, 2] < 10)
        ys, xs = np.nonzero(red)
        # Pixel centers lie at i+.5 in edge-coordinate convention.
        assert np.allclose([xs.mean() + .5, ys.mean() + .5], expected, atol=1.0)
        assert np.allclose(transform_points([expected], metadata["raw_to_page"]), [[100, 130]], atol=1e-8)


def test_rotation_matrix_composition_with_render():
    with pymupdf.open() as document:
        page = document.new_page(width=144, height=216)
        page.set_rotation(90)
        rgb, rendered = render_page(document, 1, 300, 40000000)
        images, metadata = preprocess_image(rgb, 300, PreprocessConfig(angle_override=-2.0))
        combined = np.asarray(metadata["raw_to_processed"]) @ np.asarray(rendered["page_to_raw"])
        points = [[10, 20], [80, 110], [140, 200]]
        mapped = transform_points(points, combined)
        assert np.allclose(transform_points(mapped, np.linalg.inv(combined)), points, atol=1e-8)
        assert images["gray"].shape[0] > rgb.shape[0]


def test_memory_guard_and_invalid_config():
    with pymupdf.open() as document:
        document.new_page(width=144, height=216)
        with pytest.raises(ValueError, match="max_page_pixels"):
            render_page(document, 1, 300, 1000)
    for settings in ({"adaptive_block_size": 50}, {"angle_override": float("nan")}, {"max_skew_degrees": 30}):
        with pytest.raises(ValueError):
            PreprocessConfig(**settings)


def test_cli_pdf_artifacts_and_failure_records(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    path = tmp_path / "input.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=144, height=216)
        page.insert_text((15, 40), "Example page")
        document.new_page(width=144, height=216)
        document.save(path)
    output = tmp_path / "outputs"
    args = ["preprocess", "--pdf", str(path), "--pages", "1-2", "--output-dir", str(output), "--dpi", "300", "--angle", "0"]
    assert main(args) == 0
    manifest = json.loads(next(output.glob("*/manifest.json")).read_text())
    assert manifest["status"] == "completed" and len(manifest["pages"]) == 2
    assert manifest["api_calls"] == 0 and not manifest["ocr_performed"]
    run = next(output.iterdir())
    metadata = json.loads((run / manifest["pages"][0]["metadata"]).read_text())
    assert len(metadata["artifacts"]) == 7
    assert len(metadata["inspection_regions"]) == 3
    for record in metadata["artifacts"].values():
        with Image.open(run / "pages/page-0001" / record["file"]) as image:
            image.verify()
    assert main(args + ["--pages", "3"]) == 1
    failed = [json.loads(p.read_text()) for p in output.glob("*/manifest.json") if "failed" in p.read_text()]
    assert len(failed) == 1 and failed[0]["status"] == "failed"
    assert len(list(output.glob("*/error.json"))) == 1
    assert main(args + ["--angle", "nan"]) == 2


def test_corrupt_and_encrypted_inputs(tmp_path):
    corrupt = tmp_path / "bad.pdf"
    corrupt.write_bytes(b"not a PDF")
    assert main(["preprocess", "--pdf", str(corrupt), "--output-dir", str(tmp_path / "bad")]) == 1
    encrypted = tmp_path / "encrypted.pdf"
    with pymupdf.open() as document:
        document.new_page()
        document.save(encrypted, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="reader")
    assert main(["preprocess", "--pdf", str(encrypted), "--output-dir", str(tmp_path / "encrypted")]) == 1


def test_completed_page_survives_later_failure(tmp_path, monkeypatch):
    from khojki_ocr import preprocess

    source = tmp_path / "two-pages.pdf"
    with pymupdf.open() as document:
        document.new_page(width=100, height=100)
        document.new_page(width=100, height=100)
        document.save(source)
    original = preprocess.render_page

    def fail_second(document, number, *args):
        if number == 2:
            raise ValueError("Simulated page failure")
        return original(document, number, *args)

    monkeypatch.setattr(preprocess, "render_page", fail_second)
    output = tmp_path / "runs"
    assert main(["preprocess", "--pdf", str(source), "--pages", "1-2", "--output-dir", str(output)]) == 1
    path = next(output.glob("*/manifest.json"))
    manifest = json.loads(path.read_text())
    assert manifest["status"] == "failed"
    assert [p["page_number"] for p in manifest["pages"]] == [1]
    assert (path.parent / manifest["pages"][0]["metadata"]).exists()
