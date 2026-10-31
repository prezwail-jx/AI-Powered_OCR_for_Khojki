import copy
import json
from pathlib import Path

import cv2
import numpy as np
import pymupdf
import pytest
from PIL import Image

from khojki_ocr.cli import main
from khojki_ocr.config import LineDetectionConfig
from khojki_ocr.line_detection import detect_page, load_page_input, save_detection, _split_projection_row
from khojki_ocr.pdf import file_sha256
from khojki_ocr.reference import GUJARATI, render_glyph

WORD = "\U00011208\U0001122C\U0001123A\U0001120A\U0001122D\U0001123A\U00011221\U0001122F"


def place(canvas, text, x, y, size=32, font=None):
    kwargs = {"name": font} if font else {}
    glyph = render_glyph(text, size=size, **kwargs).convert("L")
    canvas.paste(glyph, (x, y))
    # The renderer uses a six-pixel white margin.
    return [x + 6, y + 6, x + glyph.width - 6, y + glyph.height - 6]


def synthetic_page(two_columns=False, numbered=False, heading=False, border=False, noise=False):
    canvas = Image.new("L", (1000, 1200), "white")
    expected = []
    if heading:
        expected.append(place(canvas, WORD * 4, 100, 65, size=30))
    for x in ([70, 570] if two_columns else [100]):
        for y in [220, 350, 480, 610]:
            box = place(canvas, WORD if two_columns else WORD * 3, x, y)
            if numbered:
                num = place(canvas, "\u0AE7", 870, y + 5, font=GUJARATI)
                box[2], box[3] = num[2], max(box[3], num[3])
            expected.append(box)
    image = np.array(canvas)
    if border:
        cv2.rectangle(image, (15, 20), (980, 1100), 0, 2)
    if noise:
        rng = np.random.default_rng(7)
        ys = rng.integers(0, 1150, 2500)
        xs = rng.integers(0, 1000, 2500)
        image[ys, xs] = 150
    return image, expected


def covers(actual, expected, allowance=3):
    return (actual[0] <= expected[0] + allowance and actual[1] <= expected[1] + allowance
            and actual[2] >= expected[2] - allowance and actual[3] >= expected[3] - allowance)


def test_single_column_khojki_with_noise_and_border():
    image, expected = synthetic_page(border=True, noise=True)
    result = detect_page(image, LineDetectionConfig())
    assert len(result["lines"]) == 4
    assert all(covers(line["box"], box) for line, box in zip(result["lines"], expected))
    assert any(region["type"] == "suspected_decoration" for region in result["excluded_regions"])
    assert result["gutter"] is None
    assert all("decoration_overlap" not in line["flags"] for line in result["lines"])


def test_two_columns_read_left_then_right_after_full_width_heading():
    image, expected = synthetic_page(two_columns=True, heading=True)
    result = detect_page(image, LineDetectionConfig())
    assert result["gutter"] is not None
    assert len(result["lines"]) == 9
    assert result["lines"][0]["block"] == "spanning"
    assert [r["block"] for r in result["lines"][1:]] == ["left"] * 4 + ["right"] * 4
    assert all(covers(line["box"], box) for line, box in zip(result["lines"], expected))


def test_trailing_numbers_are_not_a_second_column():
    image, expected = synthetic_page(numbered=True)
    result = detect_page(image, LineDetectionConfig())
    assert result["gutter"] is None
    assert len(result["lines"]) == 4
    assert all(line["has_trailing_number_candidate"] for line in result["lines"])
    assert all(covers(line["box"], box) for line, box in zip(result["lines"], expected))
    assert all(line["classification"] == "body" for line in result["lines"])


def test_staggered_columns_keep_independent_line_bands():
    canvas = Image.new("L", (1000, 1200), "white")
    expected = []
    for x, offset in [(70, 0), (570, 70)]:
        for y in (220, 350, 480, 610):
            expected.append(place(canvas, WORD, x, y + offset))
    result = detect_page(np.array(canvas), LineDetectionConfig())
    assert result["gutter"] is not None
    assert len(result["lines"]) == 8
    assert all(covers(line["box"], box) for line, box in zip(result["lines"], expected))


def test_small_marks_recovered_and_margin_letters_not_discarded():
    image = np.full((1200, 1000), 255, np.uint8)
    # First two letters lie inside the outer 12% but are adjacent to real text.
    for y in [170, 350, 530, 710, 890]:
        for x in range(40, 800, 45):
            cv2.rectangle(image, (x, y), (x + 23, y + 31), 0, -1)
        cv2.circle(image, (50, y - 10), 2, 0, -1)
    result = detect_page(image, LineDetectionConfig())
    assert len(result["lines"]) == 5
    assert all(line["box"][0] <= 40 and line["box"][1] <= y - 8 for line, y in zip(result["lines"], [170, 350, 530, 710, 890]))


def test_ambiguous_small_mark_is_recorded_not_silently_dropped():
    image = np.full((800, 800), 255, np.uint8)
    for y in (100, 150):
        for x in (100, 150, 200, 250):
            cv2.rectangle(image, (x, y), (x + 20, y + 25), 0, -1)
    cv2.circle(image, (150, 137), 2, 0, -1)
    result = detect_page(image, LineDetectionConfig())
    assert len(result["lines"]) == 2
    assert all("ambiguous_mark" in row["flags"] for row in result["lines"])
    assert any(region["type"] == "ambiguous_mark" for region in result["excluded_regions"])


def test_complex_layout_does_not_claim_verified_reading_order():
    canvas = Image.new("L", (1650, 1200), "white")
    for x in (70, 620, 1170):
        for y in (250, 400, 550):
            place(canvas, WORD, x, y)
    result = detect_page(np.array(canvas), LineDetectionConfig())
    assert result["lines"]
    assert any("complex_layout_review" in warning for warning in result["warnings"])


def test_tall_candidate_splits_only_between_substantial_text_bands():
    subject = np.zeros((300, 600), np.uint8)
    components = []
    for y in (80, 160):
        for x in (50, 100, 150, 200):
            subject[y:y + 30, x:x + 20] = 255
            components.append({"box": [x, y, x + 20, y + 30]})
    row = {"box": [50, 80, 220, 190], "components": components, "block": "single", "center": 135}
    parts = _split_projection_row(row, subject, 30)
    assert len(parts) == 2
    assert parts[0]["box"] == [50, 80, 220, 110]
    assert parts[1]["box"] == [50, 160, 220, 190]
    # A small diacritic band above a real text band is not another line.
    for component in components[:4]:
        component["box"][3] = component["box"][1] + 5
    assert len(_split_projection_row(row, subject, 30)) == 1


def test_page_number_and_heading_remain_candidates():
    canvas = Image.new("L", (1000, 1200), "white")
    place(canvas, "\u0AE7", 450, 20, font=GUJARATI)
    for y in (300, 450, 600):
        place(canvas, WORD * 3, 100, y)
    result = detect_page(np.array(canvas), LineDetectionConfig())
    assert len(result["lines"]) == 4
    assert result["lines"][0]["classification"] == "isolated_page_number_candidate"


def test_blank_and_faint_noise_have_no_reliable_lines():
    for value in [0, 255]:
        result = detect_page(np.full((800, 600), value, np.uint8), LineDetectionConfig())
        assert not result["lines"] and result["warnings"]
    rng = np.random.default_rng(8)
    image = rng.integers(245, 256, (800, 600), dtype=np.uint8)
    assert not detect_page(image, LineDetectionConfig())["lines"]


def test_crops_are_original_gray_bounds_valid_ids_repeat(tmp_path):
    gray, _ = synthetic_page(numbered=True)
    config = LineDetectionConfig(max_work_width=800)
    metadata = {"page_number": 1, "pdf_sha256": "source-test", "artifacts": {"gray": {"sha256": "gray-test"}},
                "processed_to_page": [[.24, 0, 0], [0, .24, 0], [0, 0, 1]]}
    result = detect_page(gray, config)
    lines = save_detection(gray, metadata, result, tmp_path / "first", config, Path("source-run"))
    again = save_detection(gray, metadata, detect_page(gray, config), tmp_path / "second", config, Path("other-run"))
    assert [r["line_id"] for r in lines] == [r["line_id"] for r in again]
    assert len(lines) == 4
    for line in lines:
        x0, y0, x1, y1 = line["crop_box"]
        assert 0 <= x0 < x1 <= gray.shape[1] and 0 <= y0 < y1 <= gray.shape[0]
        assert np.array_equal(np.array(Image.open(tmp_path / "first" / line["crop_path"])), gray[y0:y1, x0:x1])
        assert len(line["page_coordinates"]["polygon"]) == 4


def test_tight_spacing_and_page_edge_crop_flags(tmp_path):
    gray = np.full((800, 800), 255, np.uint8)
    for y in (120, 157, 194):
        for x in range(0, 600, 35):
            cv2.rectangle(gray, (x, y), (x + 20, y + 25), 0, -1)
    config = LineDetectionConfig()
    result = detect_page(gray, config)
    assert len(result["lines"]) == 3
    metadata = {"page_number": 1, "pdf_sha256": "source", "artifacts": {"gray": {"sha256": "gray"}},
                "processed_to_page": np.eye(3).tolist()}
    lines = save_detection(gray, metadata, result, tmp_path / "edge", config, Path("input-run"))
    assert all("touching_page_edge" in line["flags"] and "possible_truncation" in line["flags"] for line in lines)
    assert all(first["crop_box"][3] <= second["crop_box"][1] for first, second in zip(lines, lines[1:]))


def make_input_run(tmp_path):
    pdf = tmp_path / "input.pdf"
    gray, _ = synthetic_page(numbered=True)
    scan_path = tmp_path / "scan.png"
    Image.fromarray(gray).save(scan_path)
    with pymupdf.open() as document:
        page = document.new_page(width=500, height=640)
        page.insert_image(pymupdf.Rect(0, 0, 500, 600), filename=str(scan_path))
        page.insert_text((10, 622), "Harvard University source caption for testing", fontsize=7)
        document.save(pdf)
    outputs = tmp_path / "preprocessed"
    assert main(["preprocess", "--pdf", str(pdf), "--pages", "1", "--dpi", "144", "--angle", "0", "--output-dir", str(outputs)]) == 0
    return next(outputs.iterdir())


def test_detection_cli_and_caption_exclusion(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    source = make_input_run(tmp_path)
    output = tmp_path / "detected"
    assert main(["detect-lines", "--input-run", str(source), "--output-dir", str(output)]) == 0
    manifest = json.loads(next(output.glob("*/manifest.json")).read_text())
    assert manifest["stage"] == "line_detection" and manifest["status"] == "completed"
    assert manifest["api_calls"] == 0 and not manifest["ocr_performed"]
    page = next(output.glob("*/pages/page-0001"))
    excluded = json.loads((page / "excluded-regions.json").read_text())
    assert any(r["type"] == "source_caption" for r in excluded)
    lines = [json.loads(line) for line in (page / "lines.jsonl").read_text().splitlines()]
    assert len(lines) == 4
    assert all(line["content_box"][3] < 1200 for line in lines)
    assert main(["detect-lines", "--input-run", str(source), "--pages", "2", "--output-dir", str(output)]) == 1


def test_corrupt_inputs_and_coordinates_rejected(tmp_path):
    source = make_input_run(tmp_path)
    manifest = json.loads((source / "manifest.json").read_text())
    record = manifest["pages"][0]
    gray, metadata = load_page_input(source, record, manifest)
    assert gray.shape == (1280, 1000)
    with pytest.raises(ValueError, match="outside"):
        load_page_input(source, {**record, "metadata": "../outside.json"}, manifest)
    original = source / record["metadata"]
    invalid = copy.deepcopy(metadata)
    invalid["processed_to_page"] = [[0] * 3] * 3
    original.write_text(json.dumps(invalid))
    with pytest.raises(ValueError, match="matrices"):
        load_page_input(source, record, manifest)
    original.write_text(json.dumps(metadata))
    path = original.parent / metadata["artifacts"]["gray"]["file"]
    path.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_page_input(source, record, manifest)


def test_missing_original_pdf_keeps_caption_for_review(tmp_path):
    source = make_input_run(tmp_path)
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["config"]["pdf"] = str(tmp_path / "absent.pdf")
    manifest_path.write_text(json.dumps(manifest))
    output = tmp_path / "detection"
    assert main(["detect-lines", "--input-run", str(source), "--output-dir", str(output)]) == 0
    completed = json.loads(next(output.glob("*/manifest.json")).read_text())
    assert any("source_caption_unverified" in w for w in completed["pages"][0]["warnings"])
    excluded = json.loads(next(output.glob("*/pages/page-0001/excluded-regions.json")).read_text())
    assert not any(r["type"] == "source_caption" for r in excluded)
