import copy
import hashlib
import json
import shutil
from pathlib import Path

import openai
import pytest
from PIL import Image
from pydantic import ValidationError

from khojki_ocr.error_analysis import (AttributionBundle, _analyze, analyze_run, freeze_challenge_set,
                                       validate_challenge_set, verify_error_analysis)
from khojki_ocr.runtime import RunContext
from khojki_ocr.storage import canonical_json

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def analysis(tmp_path):
    run = RunContext(tmp_path)
    analyze_run(ROOT, ROOT / "data/annotations/error-attribution-v1.json",
                ROOT / "data/challenges/t13/frozen/manifest.json",
                ROOT / "outputs/20261030T230213Z-afd44e1b89db", run)
    return run.directory


def test_formal_t13_analysis_recomputes_offline(monkeypatch, analysis):
    monkeypatch.setattr(openai, "OpenAI", lambda *args, **kwargs: pytest.fail("T13 must stay offline"))
    _, summary, cases = verify_error_analysis(ROOT, analysis)
    assert summary["main_cer"] == {"numerator": 1, "denominator": 253, "decimal": "0.003952569170"}
    assert summary["main_attribution_counts"] == {
        "line_detection": 0, "character_recognition": 1, "unicode_mapping": 0, "unknown_or_mixed": 0}
    assert summary["qualitative_detection_cases"] == summary["qualitative_manuscript_cases"] == 2
    main = next(case for case in cases if case["scope"] == "main_ocr_error")
    assert main["stage"] == "character_recognition" and main["character_pixel_box"] is None
    assert main["edit"] == {"operation": "insertion", "hypothesis_index": 21, "codepoint": "U+11235"}


def test_frozen_manuscripts_have_no_recognition_or_cer_fields():
    manifest = validate_challenge_set(ROOT, ROOT / "data/challenges/t13/frozen/manifest.json")
    assert len({line["pdf_page"] for line in manifest["lines"]}) == 2
    assert all(line["included_in_main_metrics"] is False for line in manifest["lines"])
    assert manifest["recognition_performed"] is manifest["ground_truth_available"] is manifest["cer_available"] is False


def test_challenge_freeze_is_hash_bound_atomic_and_non_overwriting(tmp_path):
    root = tmp_path / "project"
    page1 = root / "run/pages/page-0001"
    page2 = root / "run/pages/page-0002"
    page1.mkdir(parents=True)
    page2.mkdir(parents=True)
    lines = []
    for index, page in enumerate((page1, page2), 1):
        crop = page / f"line-{index}.png"
        Image.new("L", (80, 20), 240 - index).save(crop)
        digest = hashlib.sha256(crop.read_bytes()).hexdigest()
        record = {"line_id": f"line-{index}", "page_number": index, "reading_order": 1,
                  "classification": "body", "crop_sha256": digest, "flags": [], "crop_path": crop.name}
        lines_path = page / "lines.jsonl"
        lines_path.write_text(canonical_json(record) + "\n")
        lines.append({"challenge_id": f"manuscript-0{index}", "line_id": f"line-{index}", "pdf_page": index,
                      "reading_order": 1, "source_lines_path": str(lines_path.relative_to(root)),
                      "source_lines_sha256": hashlib.sha256(lines_path.read_bytes()).hexdigest(),
                      "source_crop_path": str(crop.relative_to(root)), "source_crop_sha256": digest,
                      "selection_reason": "synthetic test body line", "known_detection_limits": []})
    selection = {"selection_version": "test", "scope": "qualitative_manuscript_detection_only",
                 "api_calls": 0, "ground_truth_available": False, "recognition_performed": False,
                 "cer_available": False, "lines": lines}
    selection_path = root / "selection.json"
    selection_path.write_text(json.dumps(selection))
    output = root / "frozen"
    manifest = freeze_challenge_set(root, selection_path, output)
    assert manifest["line_count"] == 2 and (output / "contact-sheet.png").is_file()
    assert validate_challenge_set(root, output / "manifest.json") == manifest
    with pytest.raises(ValueError, match="never overwrite"):
        freeze_challenge_set(root, selection_path, output)


def test_attribution_schema_rejects_unknown_stage_and_duplicate_case():
    payload = json.loads((ROOT / "data/annotations/error-attribution-v1.json").read_text())
    payload["cases"][0]["stage"] = "visual_guess"
    with pytest.raises(ValidationError):
        AttributionBundle.model_validate(payload)
    payload = json.loads((ROOT / "data/annotations/error-attribution-v1.json").read_text())
    payload["cases"].append(copy.deepcopy(payload["cases"][0]))
    with pytest.raises(ValidationError, match="Duplicate"):
        AttributionBundle.model_validate(payload)


def test_analysis_artifact_tampering_is_detected(tmp_path, analysis):
    copied = tmp_path / "analysis"
    shutil.copytree(analysis, copied)
    summary = copied / "summary.json"
    summary.write_bytes(summary.read_bytes() + b" ")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        verify_error_analysis(ROOT, copied)


def test_evidence_hash_mismatch_is_rejected(tmp_path):
    attribution = json.loads((ROOT / "data/annotations/error-attribution-v1.json").read_text())
    attribution["cases"][0]["evidence"][0]["sha256"] = "0" * 64
    path = tmp_path / "attribution.json"
    path.write_text(json.dumps(attribution))
    with pytest.raises(ValueError, match="Evidence hash mismatch"):
        _analyze(ROOT, path, ROOT / "data/challenges/t13/frozen/manifest.json",
                 ROOT / "outputs/20261030T230213Z-afd44e1b89db")


@pytest.mark.parametrize("change", ["missing_evidence", "blank_reason", "qualitative_in_cer", "wrong_edit", "wrong_line"])
def test_invalid_attribution_is_rejected(tmp_path, change):
    payload = json.loads((ROOT / "data/annotations/error-attribution-v1.json").read_text())
    main = payload["cases"][0]
    if change == "missing_evidence":
        main["evidence"] = []
    elif change == "blank_reason":
        main["support"] = [" "]
    elif change == "qualitative_in_cer":
        payload["cases"][1]["included_in_main_cer"] = True
    elif change == "wrong_edit":
        main["edit"]["hypothesis_index"] = 20
    else:
        main["line_id"] = "unrelated-line"
    path = tmp_path / "attribution.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        _analyze(ROOT, path, ROOT / "data/challenges/t13/frozen/manifest.json",
                 ROOT / "outputs/20261030T230213Z-afd44e1b89db")


def test_analysis_core_outputs_repeat_identically(tmp_path, analysis):
    run = RunContext(tmp_path)
    analyze_run(ROOT, ROOT / "data/annotations/error-attribution-v1.json",
                ROOT / "data/challenges/t13/frozen/manifest.json",
                ROOT / "outputs/20261030T230213Z-afd44e1b89db", run)
    for name in ("summary.json", "cases.jsonl", "report.md"):
        assert (analysis / name).read_bytes() == (run.directory / name).read_bytes()
