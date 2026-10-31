"""Verify the real T11 freeze and unchanged inference inputs; no model calls."""

import hashlib
import json
from pathlib import Path

from khojki_ocr.ground_truth import verify_truth
from khojki_ocr.runtime import RunContext
from khojki_ocr.storage import atomic_json

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    truth = ROOT / "data/annotations/ground_truth.jsonl"
    manifest, records = verify_truth(truth)
    guard = json.loads((ROOT / "data/annotations/confirmations/t11-source-guard.json").read_bytes())
    assert all(digest(ROOT / name) == value for name, value in guard["files"].items())
    prior_cache = {name for name in guard["files"] if name.startswith(".cache/recognition/")}
    current_cache = {str(p.relative_to(ROOT)) for p in (ROOT / ".cache/recognition").glob("*.json")}
    assert prior_cache == current_cache
    assert manifest["selection_id"] == "page17-ten-lines-v1" and manifest["truth_version"] == "ground-truth-v1"
    assert len(records) == 10 and [r["detection_reading_order"] for r in records] == [6, 7, 9, 10, 11, 12, 13, 14, 15, 16]
    changed = [r for r in records if r["human_edits"]]
    assert len(changed) == 1 and changed[0]["line_id"] == "p0017-l015-e38c91e25be6"
    record = changed[0]
    assert record["text"] == record["machine_text"][:21] + record["machine_text"][22:]
    assert record["human_edits"] == [{"operation": "delete", "raw_start": 21, "raw_end": 22,
        "truth_start": 21, "truth_end": 21, "removed": "\U00011235", "inserted": "",
        "removed_codepoints": ["U+11235"], "inserted_codepoints": []}]
    assert all(r["text"] == r["machine_text"] for r in records if r is not record)
    assert all(r["confirmed"] and r["ground_truth_status"] == "confirmed" for r in records)
    assert manifest["annotation_duration_seconds"] is None  # user did not report timing
    ledger = json.loads((ROOT / ".cache/api-budget.json").read_bytes())
    report = {"stage": "t11_freeze_verification", "status": "completed", "api_calls": 0,
        "truth_version": manifest["truth_version"], "selection_id": manifest["selection_id"], "line_count": len(records),
        "modified_line_count": len(changed), "unchanged_line_count": len(records) - len(changed),
        "human_edit": record["human_edits"][0], "all_rows_confirmed": True,
        "truth_file_sha256": digest(truth), "active_manifest_sha256": digest(truth.with_suffix(".manifest.json")),
        "source_guard_file_count": len(guard["files"]), "sources_cache_and_budget_unchanged": True,
        "ledger_attempts_unchanged": len(ledger["entries"]), "annotation_duration_seconds": None,
        "method": "model_assisted_user_visual_review", "cer_computed": False,
        "note": "User explicitly accepted l015 option B and restored v1; v2/line18 retained as additional experiment, not this main truth set."}
    run = RunContext(ROOT / "outputs")
    atomic_json(run.directory / "verification.json", report)
    print(json.dumps({**report, "verification_file": str((run.directory / "verification.json").relative_to(ROOT))}, indent=2))


if __name__ == "__main__":
    main()
