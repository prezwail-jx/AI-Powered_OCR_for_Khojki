"""Geometric line detection; no OCR, language or confidence claims."""

import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from PIL import Image

from .config import LineDetectionConfig, PipelineConfig, parse_pages
from .pdf import file_sha256, map_box
from .runtime import RunContext, write_json

ALGORITHM_VERSION = "opencv-lines-1.0"


def _union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _height(box):
    return box[3] - box[1]


def _overlap(a, b):
    return max(0, min(a[3], b[3]) - max(a[1], b[1]))


def _spans(values):
    padded = np.pad(np.asarray(values, dtype=np.int8), (1, 1))
    transitions = np.diff(padded)
    return list(zip(np.flatnonzero(transitions == 1).tolist(), np.flatnonzero(transitions == -1).tolist()))


def _rows(components, char_height, config):
    rows = []
    for component in sorted(components, key=lambda c: ((c["box"][1] + c["box"][3]) / 2, c["box"][0])):
        box = component["box"]
        center = (box[1] + box[3]) / 2
        matches = [r for r in rows if _overlap(box, r["box"]) >= .25 * min(_height(box), _height(r["box"]))
                   and abs(center - r["center"]) <= config.row_center_tolerance * max(char_height, _height(box))]
        if matches:
            row = min(matches, key=lambda r: abs(center - r["center"]))
            row["components"].append(component)
            row["box"] = _union([row["box"], box])
            row["center"] = float(np.median([(c["box"][1] + c["box"][3]) / 2 for c in row["components"]]))
        else:
            rows.append({"box": box.copy(), "center": center, "components": [component]})
    return sorted(rows, key=lambda r: r["center"])


def _segments(row, gap):
    segments = []
    for component in sorted(row["components"], key=lambda c: c["box"][0]):
        if segments and component["box"][0] - segments[-1][2] <= gap:
            segments[-1] = _union([segments[-1], component["box"]])
        else:
            segments.append(component["box"].copy())
    return segments


def _merge_fragment_rows(rows, char_height):
    """Reunite upper/lower fragments whose line bands substantially overlap."""
    changed = True
    while changed:
        changed = False
        for i, left in enumerate(rows):
            for j in range(i + 1, len(rows)):
                right = rows[j]
                a, b = left["box"], right["box"]
                xoverlap = max(0, min(a[2], b[2]) - max(a[0], b[0]))
                if (_overlap(a, b) >= .35 * min(_height(a), _height(b))
                        and xoverlap >= .2 * min(a[2] - a[0], b[2] - b[0])
                        and abs(left["center"] - right["center"]) <= 1.6 * char_height):
                    left["components"] += right["components"]
                    left["box"] = _union([a, b])
                    left["center"] = float(np.median([(c["box"][1] + c["box"][3]) / 2 for c in left["components"]]))
                    rows.pop(j)
                    changed = True
                    break
            if changed:
                break
    return sorted(rows, key=lambda row: row["center"])


def _split_projection_row(row, subject, char_height):
    """Split a tall candidate only at a stable gap between two substantial bands."""
    x0, y0, x1, y1 = row["box"]
    if y1 - y0 < 2.5 * char_height:
        return [row]
    profile = np.count_nonzero(subject[y0:y1, x0:x1], axis=1)
    gaps = [(start, end) for start, end in _spans(profile == 0)
            if start > 0 and end < len(profile) and end - start >= .25 * char_height]
    for start, end in sorted(gaps, key=lambda gap: gap[1] - gap[0], reverse=True):
        cut = y0 + (start + end) / 2
        if any(c["box"][1] < cut < c["box"][3] for c in row["components"]):
            continue
        parts = [[c for c in row["components"] if (c["box"][1]+c["box"][3])/2 < cut],
                 [c for c in row["components"] if (c["box"][1]+c["box"][3])/2 >= cut]]
        if any(len(part) < 3 or np.median([_height(c["box"]) for c in part]) < .65 * char_height for part in parts):
            continue
        return [{**row, "box": _union([c["box"] for c in part]), "components": part,
                 "center": float(np.median([(c["box"][1]+c["box"][3])/2 for c in part])),
                 "projection_split": True} for part in parts]
    return [row]


def _gutter(rows, width, char_height, config):
    votes = np.zeros(width, dtype=int)
    for row in rows:
        segments = _segments(row, config.gutter_min_char_heights * char_height)
        for left, right in zip(segments, segments[1:]):
            # A narrow right group is likely a trailing number, not a text column.
            if left[2] - row["box"][0] >= 4 * char_height and row["box"][2] - right[0] >= 4 * char_height:
                votes[left[2]:right[0]] += 1
    minimum_votes = max(2, math.ceil(len(rows) * .35))
    candidates = [(x0, x1) for x0, x1 in _spans(votes >= minimum_votes)
                  if x1 - x0 >= config.gutter_min_char_heights * char_height
                  and x0 > width * .15 and x1 < width * .85]
    if candidates:
        return max(candidates, key=lambda span: (span[1] - span[0]) * int(votes[span[0]:span[1]].max()))
    # Staggered columns need not share a single baseline. Look for a persistent
    # vertical gap, requiring substantial text and overlapping y spans on both sides.
    occupancy = np.zeros(width, dtype=int)
    for row in rows:
        for segment in _segments(row, config.gutter_min_char_heights * char_height):
            occupancy[segment[0]:segment[2]] += 1
    fallback = []
    for x0, x1 in _spans(occupancy <= max(0, int(len(rows) * .1))):
        if x1 - x0 < config.gutter_min_char_heights * char_height or x0 <= width * .15 or x1 >= width * .85:
            continue
        left, right = [], []
        for row in rows:
            for destination, subset in ((left, [c["box"] for c in row["components"] if c["box"][2] <= x0]),
                                        (right, [c["box"] for c in row["components"] if c["box"][0] >= x1])):
                if subset:
                    box = _union(subset)
                    if box[2] - box[0] >= 4 * char_height:
                        destination.append(box)
        if len(left) >= 2 and len(right) >= 2:
            a, b = _union(left), _union(right)
            if _overlap(a, b) >= .3 * min(_height(a), _height(b)):
                fallback.append((x0, x1))
    return max(fallback, key=lambda span: span[1] - span[0]) if fallback else None


def detect_page(gray: np.ndarray, config: LineDetectionConfig, excluded_regions=()) -> dict:
    """Return work-image boxes and masks; all original pixels remain untouched."""
    if gray.ndim != 2 or gray.dtype != np.uint8:
        raise ValueError("Expected uint8 grayscale detection input")
    h, w = gray.shape
    scale = min(1.0, config.max_work_width / w)
    ww, wh = max(1, round(w * scale)), max(1, round(h * scale))
    work = cv2.resize(gray, (ww, wh), interpolation=cv2.INTER_AREA)
    sx, sy = ww / w, wh / h
    excluded = []
    if min(work.shape) < 16 or np.ptp(work) < config.min_intensity_range:
        return {"lines": [], "excluded_regions": [], "warnings": ["no_reliable_text"],
                "work_mask": np.zeros_like(work), "subject_mask": np.zeros_like(work),
                "work_scale": [sx, sy], "char_height": 0, "gutter": None}

    background = cv2.GaussianBlur(work, (0, 0), max(3, ww * config.background_sigma_ratio))
    normalized = cv2.divide(work, np.maximum(background, 1), scale=200)
    _, ink = cv2.threshold(normalized, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    for region in excluded_regions:
        b = region["processed_box"]
        x0, y0 = max(0, math.floor(b[0] * sx)), max(0, math.floor(b[1] * sy))
        x1, y1 = min(ww, math.ceil(b[2] * sx)), min(wh, math.ceil(b[3] * sy))
        ink[y0:y1, x0:x1] = 0
        excluded.append({**region, "work_box": [x0, y0, x1, y1]})

    # Suppress straight border evidence in the detection mask only.
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, round(ww * .3)), 1)))
    vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, round(wh * .25)))))
    border = cv2.bitwise_or(horizontal, vertical)
    count, _, stats, _ = cv2.connectedComponentsWithStats(border)
    for x, y, cw, ch, area in stats[1:]:
        if area:
            excluded.append({"type": "suspected_decoration", "work_box": [int(x), int(y), int(x + cw), int(y + ch)],
                             "reason": "long_straight_line; detection-only suppression"})
    border = cv2.dilate(border, np.ones((3, 3), np.uint8))
    cleaned = cv2.bitwise_and(ink, cv2.bitwise_not(border))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(cleaned)
    components = [{"label": index, "box": [int(x), int(y), int(x + cw), int(y + ch)], "area": int(area)}
                  for index, (x, y, cw, ch, area) in enumerate(stats[1:], 1)]
    min_height = max(4, wh * config.min_component_height_ratio)
    plausible = [c for c in components if min_height <= _height(c["box"]) <= wh * .09
                 and 2 <= c["box"][2] - c["box"][0] <= ww * .4
                 and c["area"] >= min_height ** 2 * .2
                 and .08 <= (c["box"][2] - c["box"][0]) / _height(c["box"]) <= 7]
    if not plausible:
        return {"lines": [], "excluded_regions": excluded, "warnings": ["no_reliable_text"],
                "work_mask": ink, "subject_mask": np.zeros_like(work),
                "work_scale": [sx, sy], "char_height": 0, "gutter": None}
    char_height = float(np.median([_height(c["box"]) for c in plausible]))
    anchors = [c for c in plausible if .45 * char_height <= _height(c["box"]) <= 2.3 * char_height
               and c["area"] >= .06 * char_height ** 2]
    # Repeated isolated motifs along the outer margins must not drag body boxes
    # across an entire decorative frame. Adjacent ordinary word letters do not
    # qualify because the gap to other text is too small.
    for side in ("left", "right"):
        edge = [c for c in anchors if (c["box"][2] < .12 * ww if side == "left" else c["box"][0] > .88 * ww)
                and c["box"][2] - c["box"][0] < 1.5 * char_height]
        isolated = []
        for c in edge:
            neighbors = [d for d in anchors if d is not c
                         and (d["box"][0] >= c["box"][2] if side == "left" else d["box"][2] <= c["box"][0])
                         and _overlap(c["box"], d["box"]) > .2 * min(_height(c["box"]), _height(d["box"]))]
            gap = min((max(0, d["box"][0] - c["box"][2], c["box"][0] - d["box"][2]) for d in neighbors), default=ww)
            if gap > 1.5 * char_height:
                isolated.append(c)
        if len(isolated) >= 4 and max(c["box"][3] for c in isolated) - min(c["box"][1] for c in isolated) > .45 * wh:
            rejected = {c["label"] for c in isolated}
            anchors = [c for c in anchors if c["label"] not in rejected]
            for c in isolated:
                cleaned[labels == c["label"]] = 0
                excluded.append({"type": "suspected_decoration", "work_box": c["box"], "reason": "repeated_isolated_margin_track"})
    excluded_labels = {c["label"] for c in components if cleaned[c["box"][1]:c["box"][3], c["box"][0]:c["box"][2]].max(initial=0) == 0}
    anchor_labels = {c["label"] for c in anchors}
    subject = np.where(np.isin(labels, list(anchor_labels)), 255, 0).astype(np.uint8)
    # A short horizontal closing joins character fragments but never joins rows vertically.
    joined = cv2.morphologyEx(subject, cv2.MORPH_CLOSE, np.ones((1, max(2, round(char_height * .6))), np.uint8))
    projection = np.count_nonzero(joined, axis=1)
    projection_bands = _spans(projection > 0)
    initial_rows = _merge_fragment_rows(_rows(anchors, char_height, config), char_height)
    gutter = _gutter(initial_rows, ww, char_height, config)
    candidate_rows = []
    for row in initial_rows:
        if gutter:
            g0, g1 = gutter
            middle = (g0 + g1) / 2
            across = any(c["box"][0] < g1 and c["box"][2] > g0 for c in row["components"])
            if across:
                candidate_rows.append({**row, "block": "spanning"})
            else:
                for block, subset in (("left", [c for c in row["components"] if (c["box"][0]+c["box"][2])/2 < middle]),
                                      ("right", [c for c in row["components"] if (c["box"][0]+c["box"][2])/2 >= middle])):
                    if subset:
                        # Staggered baselines in separate columns may overlap in
                        # global y bands; regroup independently after splitting.
                        candidate_rows.extend({**subrow, "block": block} for subrow in
                                              _merge_fragment_rows(_rows(subset, char_height, config), char_height))
        else:
            candidate_rows.append({**row, "block": "single"})

    candidate_rows = [part for row in candidate_rows for part in _split_projection_row(row, subject, char_height)]
    substantial_heights = [_height(row["box"]) for row in candidate_rows if len(row["components"]) >= 3]
    typical_line_height = float(np.median(substantial_heights)) if substantial_heights else char_height
    lines = []
    for row in candidate_rows:
        box = row["box"]
        if len(row["components"]) < 2 and box[2] - box[0] > 8 * _height(box):
            excluded.append({"type": "suspected_decoration", "work_box": box, "reason": "single_wide_ornament"})
            continue
        flags = ["projection_split_review"] if row.get("projection_split") else []
        if _height(box) > 1.8 * typical_line_height:
            flags.append("possible_merge")
        if row["block"] == "spanning" and box[1] > wh * .2:
            flags.append("reading_order_review")
        segments = _segments(row, config.gutter_min_char_heights * char_height)
        trailing = len(segments) > 1 and segments[-1][2] - segments[-1][0] < 2.5 * char_height and segments[0][2] - segments[0][0] > 4 * char_height
        if box[2] - box[0] < 3 * char_height and len(row["components"]) <= 3 and (box[1] < wh * .1 or box[3] > wh * .88):
            kind = "isolated_page_number_candidate"
        elif box[1] < wh * .12:
            kind = "suspected_header"
        elif (box[1] < wh * .25 and np.median([_height(c["box"]) for c in row["components"]]) > 1.35 * char_height) or row["block"] == "spanning":
            kind = "suspected_heading"
        elif len(row["components"]) < 3:
            kind = "uncertain"
            flags.append("few_text_anchors")
        else:
            kind = "body"
        median_aspect = float(np.median([(c["box"][2] - c["box"][0]) / _height(c["box"]) for c in row["components"]]))
        if box[2] - box[0] > .4 * ww and median_aspect > 2.5:
            kind = "uncertain"
            flags.append("suspected_decoration")
        if (box[0] < .12 * ww and box[2] > .88 * ww
                and (box[3] < .15 * wh or box[1] > .80 * wh) and not trailing):
            kind = "uncertain"
            flags.append("possible_border_decoration")
        if (box[1] < .25 * wh and 3 <= len(row["components"]) <= 8
                and box[2] - box[0] > 5 * char_height
                and max(c["box"][2] - c["box"][0] for c in row["components"]) > 3 * char_height):
            kind = "uncertain"
            flags.append("possible_decoration")
        lines.append({"box": box.copy(), "anchor_box": box.copy(), "block": row["block"], "classification": kind,
                      "components": row["components"], "flags": flags, "has_trailing_number_candidate": trailing,
                      "recovered_marks": 0})

    # Retain nearby small components, independently of whether they helped find the line.
    discarded_small = 0
    for component in components:
        if component["label"] in anchor_labels or component["label"] in excluded_labels:
            continue
        box = component["box"]
        if _height(box) > 1.3 * char_height or box[2] - box[0] > 2 * char_height:
            continue
        if component["area"] < max(2, .002 * char_height ** 2):
            discarded_small += 1
            continue
        matches = []
        for index, line in enumerate(lines):
            base = line["anchor_box"]
            xgap = max(0, base[0] - box[2], box[0] - base[2])
            ygap = max(0, base[1] - box[3], box[1] - base[3])
            if xgap <= .5 * char_height and ygap <= config.mark_recovery_margin * char_height:
                distance = abs((box[1] + box[3] - base[1] - base[3]) / 2)
                matches.append((distance, index))
        matches.sort()
        if matches:
            chosen = matches[0][1]
            if len(matches) > 1 and abs(matches[0][0] - matches[1][0]) < .2 * char_height:
                for _, index in matches[:2]:
                    lines[index]["flags"].append("ambiguous_mark")
                excluded.append({"type": "ambiguous_mark", "work_box": box, "reason": "nearest_line_ambiguous; retained in nearest candidate"})
            lines[chosen]["box"] = _union([lines[chosen]["box"], box])
            lines[chosen]["recovered_marks"] += 1
        else:
            discarded_small += 1

    excluded.append({"type": "unassociated_small_components", "count": discarded_small,
                     "reason": "Not used for line anchors; original grayscale and candidate mask remain available"})
    # A spanning heading acts as a section boundary: read the left then right column in each section.
    spans = sorted([line for line in lines if line["block"] == "spanning"], key=lambda line: line["box"][1])
    ordered = []
    remaining = [line for line in lines if line["block"] != "spanning"]
    for span in spans:
        before = [line for line in remaining if line["box"][1] < span["box"][1]]
        ordered.extend(sorted(before, key=lambda line: (line["block"], line["box"][1], line["box"][0])))
        remaining = [line for line in remaining if line not in before]
        ordered.append(span)
    ordered.extend(sorted(remaining, key=lambda line: (line["block"], line["box"][1], line["box"][0])))
    for line in ordered:
        box = line["box"]
        for decoration in excluded:
            if decoration["type"] == "suspected_decoration":
                b = decoration["work_box"]
                if min(box[2], b[2]) > max(box[0], b[0]) and min(box[3], b[3]) > max(box[1], b[1]):
                    if not decoration["reason"].startswith("long_straight_line") or np.any(border[box[1]:box[3], box[0]:box[2]]):
                        line["flags"].append("decoration_overlap")
        if box[0] <= 1 or box[1] <= 1 or box[2] >= ww - 1 or box[3] >= wh - 1:
            line["flags"].append("touching_page_edge")
        line["flags"] = sorted(set(line["flags"]))
    warnings = [] if ordered else ["no_reliable_text"]
    multi_segment_rows = sum(len([segment for segment in _segments(row, config.gutter_min_char_heights * char_height)
                                  if segment[2] - segment[0] >= 4 * char_height]) >= 3 for row in initial_rows)
    if gutter and multi_segment_rows >= 2:
        warnings.append("complex_layout_review: more than two substantial groups; automatic order needs confirmation")
    return {"lines": ordered, "excluded_regions": excluded, "warnings": warnings,
            "work_mask": ink, "subject_mask": subject, "work_scale": [sx, sy],
            "char_height": char_height, "gutter": list(gutter) if gutter else None,
            "projection_bands": projection_bands, "typical_line_height": typical_line_height}


def _within(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Input artifact path is outside its run directory")
    return path


def load_page_input(root: Path, record: dict, manifest: dict) -> tuple[np.ndarray, dict]:
    path = _within(root, record["metadata"])
    metadata = json.loads(path.read_text(encoding="utf-8"))
    if metadata["pdf_sha256"] != manifest["pdf_sha256"] or metadata["page_number"] != record["page_number"]:
        raise ValueError("Page metadata does not match source manifest")
    for name in ("gray", "binary"):
        artifact = metadata["artifacts"][name]
        file = _within(path.parent, artifact["file"])
        if file_sha256(file) != artifact["sha256"]:
            raise ValueError(f"Input artifact hash mismatch: {name}")
        with Image.open(file) as image:
            if list(image.size) != metadata["processed_size_pixels"] or image.mode != "L":
                raise ValueError(f"Input artifact dimensions/mode mismatch: {name}")
            if name == "gray":
                gray = np.array(image)
    forward, inverse = np.asarray(metadata["page_to_processed"]), np.asarray(metadata["processed_to_page"])
    if forward.shape != (3, 3) or inverse.shape != (3, 3) or not np.all(np.isfinite(forward)) or not np.all(np.isfinite(inverse)) or not np.allclose(forward @ inverse, np.eye(3), atol=1e-6):
        raise ValueError("Invalid or inconsistent coordinate matrices")
    return gray, metadata


def caption_regions(pdf: Path | None, metadata: dict) -> tuple[list, list]:
    if pdf is None:
        return [], ["source_caption_unverified: original PDF unavailable"]
    regions = []
    with pymupdf.open(pdf) as document:
        page = document[metadata["page_number"] - 1]
        image_rects = [rect for item in page.get_images() for rect in page.get_image_rects(item[0])]
        for block in page.get_text("blocks"):
            text = block[4]
            letters = [c for c in text if c.isalpha()]
            box = pymupdf.Rect(block[:4])
            unrotated = page.rect * page.derotation_matrix
            if len(letters) < 15 or sum(c.isascii() for c in letters) / len(letters) < .9 or box.y0 < unrotated.height * .8 or not image_rects:
                continue
            if any((box & rect).get_area() > box.get_area() * .1 for rect in image_rects):
                continue
            regions.append({"type": "source_caption", "processed_box": map_box(list(box), metadata["page_to_processed"])["bbox"],
                            "page_box": list(box), "reason": "Latin PDF text block below scan and outside embedded image"})
    return regions, []


def save_detection(gray, metadata, result, directory, config, source_run):
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "crops").mkdir()
    height, width = gray.shape
    sx, sy = result["work_scale"]
    char_height = result["char_height"]
    lines = []
    overlay = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
    for index, candidate in enumerate(result["lines"], 1):
        b = candidate["box"]
        content = [max(0, math.floor(b[0] / sx)), max(0, math.floor(b[1] / sy)),
                   min(width, math.ceil(b[2] / sx)), min(height, math.ceil(b[3] / sy))]
        padded = [max(0, math.floor((b[0] - char_height * config.crop_padding_x) / sx)),
                  max(0, math.floor((b[1] - char_height * config.crop_padding_y) / sy)),
                  min(width, math.ceil((b[2] + char_height * config.crop_padding_x) / sx)),
                  min(height, math.ceil((b[3] + char_height * config.crop_padding_y) / sy))]
        # Restrict padding at neighboring lines, but never shrink the detected content.
        flags = candidate["flags"].copy()
        for other in result["lines"]:
            if other is candidate or min(b[2], other["box"][2]) <= max(b[0], other["box"][0]):
                continue
            ob = other["box"]
            if ob[3] <= b[1]:
                padded[1] = max(padded[1], min(content[1], math.ceil((ob[3] + b[1]) / 2 / sy)))
            elif ob[1] >= b[3]:
                padded[3] = min(padded[3], max(content[3], math.floor((ob[1] + b[3]) / 2 / sy)))
            elif _overlap(ob, b) > 0:
                flags.append("overlapping_line_content")
        if padded[0] == 0 or padded[1] == 0 or padded[2] == width or padded[3] == height:
            flags.append("possible_truncation")
        identity = {"pdf_sha256": metadata["pdf_sha256"], "page": metadata["page_number"],
                    "gray_sha256": metadata["artifacts"]["gray"]["sha256"], "content_box": content,
                    "config": config.model_dump(), "algorithm": ALGORITHM_VERSION}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:12]
        line_id = f"p{metadata['page_number']:04}-l{index:03}-{digest}"
        crop_path = directory / "crops" / f"{line_id}.png"
        Image.fromarray(gray[padded[1]:padded[3], padded[0]:padded[2]]).save(crop_path)
        lines.append({"line_id": line_id, "page_number": metadata["page_number"], "reading_order": index,
                      "block": candidate["block"], "classification": candidate["classification"],
                      "content_box": content, "crop_box": padded, "page_coordinates": map_box(padded, metadata["processed_to_page"]),
                      "source_run": str(source_run), "pdf_sha256": metadata["pdf_sha256"],
                      "crop_path": f"crops/{line_id}.png", "crop_sha256": file_sha256(crop_path),
                      "has_trailing_number_candidate": candidate["has_trailing_number_candidate"],
                      "flags": sorted(set(flags)), "needs_review": bool(flags) or candidate["classification"] != "body",
                      "geometry": {"anchor_count": len(candidate["components"]), "recovered_components": candidate["recovered_marks"],
                                   "char_height_work_pixels": char_height},
                      "note": "Geometric candidates and classes are not OCR confidence or verified text"})
        color = (230, 100, 0) if lines[-1]["needs_review"] else (0, 155, 60)
        cv2.rectangle(overlay, tuple(padded[:2]), tuple(padded[2:]), color, max(1, round(width / 1500)))
        cv2.putText(overlay, f"{index}:{candidate['classification']}", (padded[0], max(20, padded[1] - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, max(.5, width / 3000), color, max(1, round(width / 1800)))
    Image.fromarray(overlay).save(directory / "lines-overlay.png")
    layout = cv2.cvtColor(result["subject_mask"], cv2.COLOR_GRAY2RGB)
    if result["gutter"]:
        g0, g1 = result["gutter"]
        cv2.rectangle(layout, (g0, 0), (g1, layout.shape[0] - 1), (255, 0, 0), 2)
    for index, candidate in enumerate(result["lines"], 1):
        box = candidate["box"]
        cv2.rectangle(layout, tuple(box[:2]), tuple(box[2:]), (0, 180, 0), 1)
        cv2.putText(layout, str(index), tuple(box[:2]), cv2.FONT_HERSHEY_SIMPLEX, .5, (255, 150, 0), 1)
    Image.fromarray(layout).save(directory / "layout-overlay.png")
    Image.fromarray(result["work_mask"]).save(directory / "detection-mask.png")
    with (directory / "lines.jsonl").open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    exclusions = []
    for region in result["excluded_regions"]:
        converted = region.copy()
        if "work_box" in region:
            b = region["work_box"]
            processed = [max(0, math.floor(b[0] / sx)), max(0, math.floor(b[1] / sy)),
                         min(width, math.ceil(b[2] / sx)), min(height, math.ceil(b[3] / sy))]
            converted["processed_box"] = processed
            converted["page_coordinates"] = map_box(processed, metadata["processed_to_page"])
        exclusions.append(converted)
    write_json(directory / "excluded-regions.json", exclusions)
    write_json(directory / "detection.json", {"algorithm": ALGORITHM_VERSION, "config": config.model_dump(),
               "work_scale": result["work_scale"], "char_height": char_height,
               "gutter": result["gutter"], "warnings": result["warnings"], "line_count": len(lines),
               "projection_bands": result.get("projection_bands", []), "typical_line_height": result.get("typical_line_height", 0),
               "versions": {"opencv": cv2.__version__, "numpy": np.__version__}})
    return lines


def detect_run(input_run: Path, config: PipelineConfig, run: RunContext, pages: str | None = None) -> dict:
    source = json.loads((input_run / "manifest.json").read_text(encoding="utf-8"))
    if source.get("stage") != "page_preprocessing" or not source.get("pages"):
        raise ValueError("Input must be a T04 preprocessing run with completed page records")
    selected = parse_pages(pages) if pages else [record["page_number"] for record in source["pages"]]
    records = {record["page_number"]: record for record in source["pages"]}
    if any(page not in records for page in selected):
        raise ValueError("Requested pages are not available in input run")
    original = Path(source["config"]["pdf"])
    candidates = [original, input_run.resolve().parent.parent / original] if not original.is_absolute() else [original]
    pdf = next((path for path in candidates if path.is_file() and file_sha256(path) == source["pdf_sha256"]), None)
    manifest = {"run_id": run.run_id, "stage": "line_detection", "status": "running", "api_calls": 0,
                "ocr_performed": False, "input_run": str(input_run.resolve()),
                "input_manifest_sha256": file_sha256(input_run / "manifest.json"), "pdf_sha256": source["pdf_sha256"],
                "algorithm": ALGORITHM_VERSION, "config": config.line_detection.model_dump(), "pages": []}
    write_json(run.directory / "manifest.json", manifest)
    try:
        for number in selected:
            run.log(f"Detecting lines in page {number}")
            gray, metadata = load_page_input(input_run, records[number], source)
            captions, warnings = caption_regions(pdf, metadata)
            result = detect_page(gray, config.line_detection, captions)
            result["warnings"].extend(warnings)
            if source.get("status") != "completed" or metadata["deskew"].get("needs_review"):
                result["warnings"].append("upstream_preprocessing_needs_review")
            directory = run.directory / "pages" / f"page-{number:04}"
            lines = save_detection(gray, metadata, result, directory, config.line_detection, input_run.resolve())
            manifest["pages"].append({"page_number": number, "lines": f"pages/page-{number:04}/lines.jsonl",
                                      "line_count": len(lines), "warnings": result["warnings"],
                                      "needs_review": bool(result["warnings"]) or any(line["needs_review"] for line in lines)})
            write_json(run.directory / "manifest.json", manifest)
            run.log(f"Page {number}: {len(lines)} line candidates, char_height={result['char_height']}")
        manifest["status"] = "completed"
        write_json(run.directory / "manifest.json", manifest)
        return manifest
    except Exception:
        manifest["status"] = "failed"
        write_json(run.directory / "manifest.json", manifest)
        raise
