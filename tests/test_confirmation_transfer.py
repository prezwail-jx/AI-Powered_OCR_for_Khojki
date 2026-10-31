import copy
import json
from types import SimpleNamespace

import pytest

from scripts import transfer_review_confirmations as module

ORDERS = {6, 7, 9, 10, 11, 12, 13, 14, 16}


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    old, new = tmp_path / "old", tmp_path / "new"
    for path in (old, new):
        path.mkdir()
        (path / "manifest.json").write_text("{}")
    entries = [SimpleNamespace(line_id=f"line-{n}", evaluation_order=i + 1, detection_reading_order=n,
        image_sha256=f"image-{n}", prediction_sha256=f"prediction-{n}", machine_text=f"text-{n}")
        for i, n in enumerate(sorted(ORDERS | {15}))]
    replacement = [copy.copy(e) for e in entries if e.detection_reading_order != 15]
    replacement.append(SimpleNamespace(line_id="line-18", evaluation_order=10, detection_reading_order=18,
        image_sha256="image-18", prediction_sha256="prediction-18", machine_text="text-18"))
    monkeypatch.setattr(module, "verify_bundle", lambda path:
        ({"selection_id": "source-v1" if path == old else "target-v2"}, None, entries if path == old else replacement))
    checkpoint = tmp_path / "checkpoint.md"
    checkpoint.write_text("source-v1\nB：其他 9 行也已逐字符核对正确，只剩 l015 的疑点。", encoding="utf-8")
    return old, new, checkpoint, replacement, tmp_path / "confirmations/checkpoint.json"


def test_only_unchanged_nine_receive_confirmation_and_replacement_stays_pending(inputs):
    old, new, checkpoint, entries, output = inputs
    module.transfer(old, new, checkpoint, ORDERS, output)
    report = json.loads(output.read_bytes())
    assert report["confirmed_count"] == 9 and report["pending_count"] == 1
    assert not report["ground_truth_frozen"] and report["rows"][-1]["human_status"] == "pending"
    assert report["rows"][-1]["user_accepted_text"] is None
    assert all(r["human_status"] == "user_reported_confirmed" for r in report["rows"][:-1])
    assert (output.parent / report["confirmation_snapshot"]).read_bytes() == checkpoint.read_bytes()
    with pytest.raises(ValueError, match="do not overwrite"):
        module.transfer(old, new, checkpoint, ORDERS, output)


@pytest.mark.parametrize("field", ["image_sha256", "prediction_sha256", "machine_text"])
def test_confirmation_cannot_follow_changed_image_or_prediction(inputs, field):
    old, new, checkpoint, entries, output = inputs
    setattr(entries[0], field, "changed")
    with pytest.raises(ValueError, match="changed image/prediction/text"):
        module.transfer(old, new, checkpoint, ORDERS, output)
    assert not output.exists() and not output.parent.exists()


def test_explicit_confirmation_evidence_is_required(inputs):
    old, new, checkpoint, entries, output = inputs
    checkpoint.write_text("No explicit user confirmation")
    with pytest.raises(ValueError, match="Explicit user confirmation"):
        module.transfer(old, new, checkpoint, ORDERS, output)
    assert not output.exists()
