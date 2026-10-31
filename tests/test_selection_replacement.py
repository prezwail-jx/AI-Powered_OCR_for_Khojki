import copy
import json
from pathlib import Path

import pytest

from scripts.replace_evaluation_line import replace_selection

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data/evaluation/selection.json"


def replace(tmp_path, **kwargs):
    return replace_selection(BASE, tmp_path / "v2", 15, 18, 13, "page17-ten-lines-v2", "User requests replacement of unresolved line15",
                             crop_confirmed=kwargs.pop("crop_confirmed", True), **kwargs)


def test_replacement_preserves_nine_rows_and_correct_actual_number(tmp_path):
    before = BASE.read_bytes()
    prior = json.loads(before)
    newer = replace(tmp_path)
    assert BASE.read_bytes() == before and newer["line_count"] == 10
    assert newer["selected_reading_orders"] == [6, 7, 9, 10, 11, 12, 13, 14, 16, 18]
    assert newer["lines"][-1]["trailing_number_value_for_reference"] == 13  # not evaluation_order + 1
    assert newer["lines"][-1]["ground_truth"] is None
    assert newer["supersedes"]["removed_line_id"].startswith("p0017-l015-")
    retained = {r["line_id"]: r for r in prior["lines"] if r["detection_reading_order"] != 15}
    for row in newer["lines"][:-1]:
        original = copy.deepcopy(retained[row["line_id"]])
        original["evaluation_order"] = row["evaluation_order"]
        assert row == original
        assert (tmp_path / "v2" / row["image_path"]).read_bytes() == (BASE.parent / row["image_path"]).read_bytes()


def test_replacement_refuses_overwrite_and_unapproved_crop(tmp_path):
    with pytest.raises(ValueError, match="explicit user"):
        replace(tmp_path, crop_confirmed=False)
    assert not (tmp_path / "v2").exists()
    replace(tmp_path)
    with pytest.raises(ValueError, match="never overwrite"):
        replace(tmp_path)


def test_modified_detection_provenance_is_rejected_before_creating_selection(tmp_path):
    prior = json.loads(BASE.read_bytes())
    prior["source_lines_sha256"] = "wrong"
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(prior))
    with pytest.raises(ValueError, match="provenance changed"):
        replace_selection(path, tmp_path / "v2", 15, 18, 13, "v2", "reason", crop_confirmed=True)
    assert not (tmp_path / "v2").exists()
