"""Offline T10 provenance/budget checks. This script never sends requests."""

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from khojki_ocr.cache import ResponseCache
from khojki_ocr.config import load_config
from khojki_ocr.recognition import batch_stop_reason, cached_result, prepare_requests
from khojki_ocr.review import prediction_hash, verify_bundle
from khojki_ocr.runtime import RunContext
from khojki_ocr.schemas import RecognitionResult
from khojki_ocr.storage import atomic_json

SELECTION = Path("data/evaluation/selection.json")
CONFIG = Path("configs/openai.yaml")
PILOT = Path("outputs/20261030T185807Z-806667a839b0/results/openai-p0017-l006-2dcc97e9dc05.json")


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preflight(selection=SELECTION, maximum_new_calls=9):
    config = load_config(CONFIG, {})
    assert config.recognition.max_attempts == 1 and config.openai.base_url == "https://api.openai.com/v1"
    assert config.openai.model == "gpt-6.1-sol" and config.recognition.budget_usd == Decimal("15")
    requests = prepare_requests(selection, config, "openai", 10)
    assert len(requests) == read(selection)["line_count"] == 10
    assert all(r["ground_truth"] is None for r in read(selection)["lines"])
    cache = ResponseCache(config.recognition.cache_dir)
    states = []
    for request in requests:
        with cache.lock(request.cache_key):
            result = cached_result(request, cache)
        assert result is None or batch_stop_reason(result) is None
        states.append({"line_id": request.line_id, "cache_key": request.cache_key, "cache_hit": result is not None})
    first = cached_result(requests[0], cache)
    pilot = RecognitionResult.model_validate_json(PILOT.read_bytes())
    assert first is not None and prediction_hash(first) == prediction_hash(pilot)
    ledger = read(config.recognition.ledger_path)
    files = [selection, CONFIG, PILOT, config.recognition.reference_dir / "manifest.json"]
    report = {"stage": "t10_offline_preflight", "api_calls": 0, "requests": states,
              "selection_path": str(selection),
              "files": {str(path): sha(path) for path in files}, "ledger": ledger,
              "ledger_sha256": sha(config.recognition.ledger_path),
              "maximum_new_calls": sum(not row["cache_hit"] for row in states)}
    assert 0 <= report["maximum_new_calls"] <= maximum_new_calls <= 9
    run = RunContext(Path("outputs"))
    atomic_json(run.directory / "preflight.json", report)
    print(f"Preflight passed; maximum new calls={report['maximum_new_calls']}; {run.directory / 'preflight.json'}")


def verify(baseline, batch, replay, bundle):
    before = read(baseline)
    selection = Path(before.get("selection_path", str(SELECTION)))
    config = load_config(CONFIG, {})
    assert all(sha(Path(path)) == digest for path, digest in before["files"].items())
    old = before["ledger"]["entries"]
    ledger = read(config.recognition.ledger_path)
    assert ledger["entries"][:len(old)] == old and ledger["cap_usd"] == "15"
    new = ledger["entries"][len(old):]
    source, cached = read(batch / "manifest.json"), read(replay / "manifest.json")
    assert len(source["requests"]) == len(cached["requests"]) == 10
    assert source["api_calls"] == len(new) <= before["maximum_new_calls"]
    assert all(e["provider"] == "openai" for e in new)
    assert source["results"][0]["cache_hit"]
    assert cached["cache_only"] and cached["api_calls"] == 0
    assert source["budget"]["accounted_usd"] == str(sum((Decimal(e["accounted_usd"]) for e in ledger["entries"]), Decimal(0)))
    assert Decimal(source["budget"]["accounted_usd"]) <= Decimal("15")
    replay_by_id = {r["line_id"]: r for r in cached["results"]}
    for record in source["results"]:
        result = RecognitionResult.model_validate_json((batch / record["file"]).read_bytes())
        repeated = RecognitionResult.model_validate_json((replay / replay_by_id[result.line_id]["file"]).read_bytes())
        if result.status in ("succeeded", "needs_review"):
            assert repeated.cache_hit and prediction_hash(result) == prediction_hash(repeated)
    review, _, entries = verify_bundle(bundle)
    assert len(entries) == 10 and review["source_recognition_run"] == str(batch.resolve())
    assert all(e.review_status == "pending" and not e.ground_truth_confirmed for e in entries)
    assert all(row["ground_truth"] is None for row in read(selection)["lines"])
    for name, digest in source["exports"]["files"].items():
        assert sha(batch / name) == digest
    attempts_file = batch / "attempts.jsonl"
    attempts = [json.loads(line) for line in attempts_file.read_text().splitlines()] if attempts_file.exists() else []
    assert len(attempts) == source["api_calls"]
    report = {"stage": "t10_offline_verification", "api_calls": source["api_calls"], "cache_only_calls": 0,
              "preflight": str(baseline), "recognition_run": str(batch), "replay_run": str(replay),
              "review_bundle": str(bundle), "candidate_count": review["candidate_count"],
              "not_run_count": review["not_run_count"], "stop_reason": source["stop_reason"],
              "new_accounted_usd": str(sum((Decimal(e["accounted_usd"]) for e in new), Decimal(0))),
              "new_unknown_attempts": sum(e["state"] != "usage_estimate" for e in new),
              "budget": source["budget"], "all_human_pending": True,
              "new_input_tokens": sum(e.get("usage", {}).get("input_tokens", 0) for e in new),
              "new_output_tokens": sum(e.get("usage", {}).get("output_tokens", 0) for e in new),
              "new_elapsed_seconds": sum(a["elapsed_seconds"] for a in attempts)}
    run = RunContext(Path("outputs"))
    atomic_json(run.directory / "verification.json", report)
    print(json.dumps({**report, "verification_file": str(run.directory / "verification.json")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("preflight")
    prepare.add_argument("--selection", type=Path, default=SELECTION)
    prepare.add_argument("--maximum-new-calls", type=int, default=9)
    check = sub.add_parser("verify")
    for name in ("baseline", "batch", "replay", "bundle"):
        check.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.command == "preflight":
        preflight(args.selection, args.maximum_new_calls)
    else:
        verify(args.baseline, args.batch, args.replay, args.bundle)
