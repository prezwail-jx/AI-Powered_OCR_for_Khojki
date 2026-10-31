import copy
import json

import openai
import pytest

from khojki_ocr.cli import main
from khojki_ocr.config import ProviderConfig
from khojki_ocr.ground_truth import freeze_truth, verify_truth
from khojki_ocr.providers.base import ImageInput, PreparedRequest
from khojki_ocr.review import build_review, verify_bundle
from khojki_ocr.runtime import RunContext
from khojki_ocr.storage import canonical_json
from test_review import source, references


@pytest.fixture
def ready(source, references, tmp_path):
    selection = json.loads(source["selection"].read_text())
    for row in selection["lines"][1:]:
        target = ImageInput.read(source["selection"].parent / row["image_path"], "TARGET LINE", row["image_sha256"])
        request = PreparedRequest(row["line_id"], "openai", ProviderConfig(model="gpt-6.1-sol", base_url="https://api.openai.com/v1"), (target,))
        result = source["result"].model_copy(update={"line_id": row["line_id"], "cache_key": request.cache_key})
        path = source["run"] / f"{row['line_id']}.json"
        path.write_text(canonical_json(result.model_dump(mode="json")))
        source["manifest"]["requests"].append({"line_id": row["line_id"], "provider": "openai", "cache_key": request.cache_key,
            "request_identity": request.identity()})
        source["manifest"]["results"].append({"line_id": row["line_id"], "provider": "openai", "status": result.status, "file": path.name})
    (source["run"] / "manifest.json").write_text(canonical_json(source["manifest"]))
    run = RunContext(source["outputs"])
    build_review(source["selection"], source["run"], run, references, source["journal"])
    manifest, digest, entries = verify_bundle(run.directory)
    approval = {"stage": "explicit_human_confirmation", "selection_id": manifest["selection_id"],
        "selection_sha256": manifest["selection_sha256"], "review_manifest_sha256": digest,
        "reviewer": "Synthetic test reviewer", "recorded_at": "2026-10-30T22:30:00+00:00",
        "annotation_duration_seconds": None, "method": "model_assisted_user_visual_review",
        "statements": ["Synthetic confirmation, never real Ground Truth"], "lines": [
            {"line_id": e.line_id, "image_sha256": e.image_sha256, "prediction_sha256": e.prediction_sha256,
             "human_text": e.machine_text, "confirmed": True} for e in entries]}
    # Confirm one deliberate single-codepoint edit; preserve both raw inputs.
    text = approval["lines"][0]["human_text"]
    approval["lines"][0]["human_text"] = text[:1] + text[2:]
    approvals_path = tmp_path / "approvals.json"
    approvals_path.write_text(json.dumps(approval, ensure_ascii=False))
    return source, run.directory, approvals_path, approval, tmp_path / "annotations/ground_truth.jsonl"


def freeze(ready, **kwargs):
    source, bundle, approval, _, output = ready
    return freeze_truth(source["selection"], bundle, approval, output, "truth-v1", confirm=kwargs.get("confirm", True))


def test_freeze_requires_explicit_flag_and_preserves_predictions(ready, monkeypatch):
    source, bundle, approval, _, output = ready
    monkeypatch.setattr(openai, "OpenAI", lambda *a, **kw: pytest.fail("Truth freeze is offline"))
    with pytest.raises(ValueError, match="Explicit --confirm"):
        freeze(ready, confirm=False)
    before = {p: p.read_bytes() for p in source["run"].glob("*.json")}
    manifest, rows = freeze(ready)
    assert len(rows) == manifest["line_count"] == 3 and manifest["modified_line_count"] == 1
    assert manifest["annotation_duration_seconds"] is None and all(row["confirmed"] for row in rows)
    assert rows[0]["human_edits"][0]["operation"] == "delete"
    assert rows[0]["human_edits"][0]["raw_start"] == 1
    assert rows[0]["machine_text"] != rows[0]["text"]
    assert not rows[1]["human_edits"] and not rows[2]["human_edits"]
    assert all(p.read_bytes() == data for p, data in before.items())
    assert rows[0]["text"] in output.read_text(encoding="utf-8")
    assert verify_truth(output) == (manifest, rows)
    with pytest.raises(ValueError, match="never overwrite"):
        freeze(ready)


@pytest.mark.parametrize("kind", ["missing", "duplicate", "unconfirmed", "image", "prediction", "selection", "review", "unicode"])
def test_invalid_or_partial_human_approval_cannot_freeze(ready, kind):
    source, bundle, approval_path, approval, output = ready
    approval = copy.deepcopy(approval)
    if kind == "missing":
        approval["lines"].pop()
    elif kind == "duplicate":
        approval["lines"].append(approval["lines"][0])
    elif kind == "unconfirmed":
        approval["lines"][0]["confirmed"] = False
    elif kind in ("image", "prediction"):
        approval["lines"][0][kind + "_sha256"] = "0" * 64
    elif kind == "selection":
        approval["selection_sha256"] = "0" * 64
    elif kind == "review":
        approval["review_manifest_sha256"] = "0" * 64
    else:
        approval["lines"][0]["human_text"] = "unverified Latin substitute"
    approval_path.write_text(json.dumps(approval))
    with pytest.raises(ValueError):
        freeze(ready)
    assert not output.exists() and not output.parent.exists()


@pytest.mark.parametrize("artifact", ["truth", "source", "approval"])
def test_frozen_truth_or_provenance_tampering_is_detected(ready, artifact):
    _, _, _, _, output = ready
    _, rows = freeze(ready)
    if artifact == "truth":
        output.write_bytes(output.read_bytes() + b" ")
    elif artifact == "source":
        path = output.parent / "versions/truth-v1" / rows[0]["source_prediction_file"]
        path.write_text("{}")
    else:
        (output.parent / "versions/truth-v1/confirmation.json").write_text("{}")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_truth(output)


def test_freeze_cli_requires_confirm_and_verifies_offline(ready, capsys):
    source, bundle, approval, _, output = ready
    args = ["freeze-truth", "--selection", str(source["selection"]), "--bundle", str(bundle),
            "--confirmation", str(approval), "--output", str(output), "--version", "truth-v1"]
    with pytest.raises(SystemExit):
        main(args)
    assert main([*args, "--confirm"]) == 0
    assert "3 lines" in capsys.readouterr().out
    assert main(["verify-truth", "--truth", str(output)]) == 0
