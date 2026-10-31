"""Batch control regressions: all transports are fake and network is forbidden."""

import hashlib
import json

import openai
import pytest

from khojki_ocr import recognition
from khojki_ocr.cache import ResponseCache
from khojki_ocr.cli import build_parser
from khojki_ocr.recognition import classify_response, prepare_requests, recognize_run
from khojki_ocr.runtime import RunContext
from khojki_ocr.schemas import TokenUsage
from test_recognition import StubAdapter, http_error, mock_inputs, reply


def seed(selection, config, count=1):
    cache = ResponseCache(config.recognition.cache_dir)
    requests = prepare_requests(selection, config, "openai", 2)
    for request in requests[:count]:
        cache.put(classify_response(request, reply()))
    return requests


def batch(tmp_path, selection, config, responses=(), **kwargs):
    run = RunContext(tmp_path / "runs")
    adapter = StubAdapter(responses)
    adapter.build_payload = lambda request: None
    manifest = recognize_run(selection, config, "openai", 2, False, run,
                             adapters={"openai": adapter}, **kwargs)
    return run, manifest, adapter


@pytest.mark.parametrize("response,reason", [
    (TimeoutError("private"), "timeout"), (http_error(401), "authentication_error"),
    (http_error(404), "model_unavailable"), (http_error(429), "rate_limited"),
    (http_error(503), "transport_error"), (reply(usage=False), "usage_missing_or_invalid"),
    (reply().model_copy(update={"billing_metadata": {"service_tier": "priority"}}), "unexpected_service_tier"),
    (reply().model_copy(update={"usage": TokenUsage(input_tokens=2000, output_tokens=10)}), "token_bound_exceeded"),
])
def test_system_or_new_billing_errors_stop_batch_without_discarding_rows(tmp_path, response, reason):
    selection, config = mock_inputs(tmp_path)
    config.recognition.max_attempts = 1
    config.openai.openai_service_tier = "default"
    run, manifest, adapter = batch(tmp_path, selection, config, [response])
    assert adapter.calls == 1 and manifest["api_calls"] == 1
    assert manifest["status"] == "completed_with_errors" and manifest["stop_reason"].startswith(reason)
    assert len(manifest["requests"]) == 2 and len(manifest["results"]) == 1
    assert manifest["requests"][1]["status"] == "not_executed"
    rows = [json.loads(line) for line in (run.directory / "predictions.jsonl").read_text().splitlines()]
    assert len(rows) == 2 and rows[1]["status"] == "not_executed" and rows[1]["machine_text"] is None
    assert rows[1]["not_executed_reason"] == manifest["stop_reason"]


@pytest.mark.parametrize("response", [reply(state="truncated"), reply(state="refused"),
                                     reply(payload={"text": "", "unreadable": False, "uncertain_spans": []}),
                                     reply(payload={"invalid": "schema"})])
def test_content_failure_with_known_usage_continues_without_retry(tmp_path, response):
    selection, config = mock_inputs(tmp_path)
    config.recognition.max_attempts = 1
    run, manifest, adapter = batch(tmp_path, selection, config, [response, reply()])
    assert adapter.calls == 2 and manifest["api_calls"] == 2 and manifest["stop_reason"] is None
    assert manifest["status"] == "completed_with_errors"
    assert manifest["results"][1]["status"] == "succeeded"
    assert manifest["exports"]["rows"] == 2


@pytest.mark.parametrize("corrupt", [False, True])
def test_first_cache_guard_blocks_all_paid_calls(tmp_path, corrupt):
    selection, config = mock_inputs(tmp_path)
    config.recognition.max_attempts = 1
    requests = seed(selection, config, count=0)
    if corrupt:
        (config.recognition.cache_dir / f"{requests[0].cache_key}.json").write_text("broken")
    _, manifest, adapter = batch(tmp_path, selection, config, require_first_cache_hit=True)
    assert manifest["api_calls"] == adapter.calls == adapter.preflights == 0
    assert manifest["budget_before"]["attempts"] == manifest["budget"]["attempts"] == 0
    assert all(row["status"] == "not_executed" for row in manifest["requests"])


def test_guarded_batch_keeps_first_prediction_and_exports_exact_bytes(tmp_path):
    selection, config = mock_inputs(tmp_path)
    config.recognition.max_attempts = 1
    requests = seed(selection, config)
    before = selection.read_bytes()
    run, manifest, adapter = batch(tmp_path, selection, config, [reply()], require_first_cache_hit=True)
    assert adapter.calls == 1 and manifest["api_calls"] == 1 and manifest["results"][0]["cache_hit"]
    assert manifest["status"] == "completed" and selection.read_bytes() == before
    rows = [json.loads(line) for line in (run.directory / "predictions.jsonl").read_text().splitlines()]
    for row in rows:
        assert not row["ground_truth_confirmed"] and row["ground_truth"] is None and row["human_status"] == "pending"
        assert (run.directory / row["text_file"]).read_bytes() == row["machine_text"].encode("utf-8")
        assert row["source_sha256"] == hashlib.sha256((run.directory / row["source_file"]).read_bytes()).hexdigest()
    assert rows[0]["cache_key"] == requests[0].cache_key
    for name, digest in manifest["exports"]["files"].items():
        assert hashlib.sha256((run.directory / name).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("count,corrupt", [(2, False), (1, False), (2, True)])
def test_cache_only_never_constructs_clients_or_ledger_or_retries_missing(tmp_path, monkeypatch, count, corrupt):
    selection, config = mock_inputs(tmp_path)
    requests = seed(selection, config, count)
    if corrupt:
        (config.recognition.cache_dir / f"{requests[-1].cache_key}.json").write_text("broken")
    def forbidden(*args, **kwargs):
        pytest.fail("Cache-only must not construct clients, adapters or budget ledgers")
    monkeypatch.setattr(openai, "OpenAI", forbidden)
    monkeypatch.setattr(recognition, "OpenAIAdapter", forbidden)
    monkeypatch.setattr(recognition, "DeepSeekAdapter", forbidden)
    monkeypatch.setattr(recognition, "BudgetLedger", forbidden)
    _, manifest, adapter = batch(tmp_path, selection, config, cache_only=True)
    assert adapter.calls == adapter.preflights == manifest["api_calls"] == 0
    assert not config.recognition.ledger_path.exists()
    assert manifest["results"][0]["cache_hit"]
    assert manifest["results"][1]["status"] == ("succeeded" if count == 2 and not corrupt else "cache_error")


def test_cache_only_preserves_existing_ledger_bytes_and_prediction_identity(tmp_path):
    from khojki_ocr.review import prediction_hash
    selection, config = mock_inputs(tmp_path)
    config.recognition.max_attempts = 1
    run, manifest, _ = batch(tmp_path, selection, config, [reply(), reply()])
    before = config.recognition.ledger_path.read_bytes()
    replay, replay_manifest, _ = batch(tmp_path, selection, config, cache_only=True)
    assert config.recognition.ledger_path.read_bytes() == before and replay_manifest["api_calls"] == 0
    from khojki_ocr.schemas import RecognitionResult
    for first, second in zip(manifest["results"], replay_manifest["results"]):
        a = RecognitionResult.model_validate_json((run.directory / first["file"]).read_bytes())
        b = RecognitionResult.model_validate_json((replay.directory / second["file"]).read_bytes())
        assert prediction_hash(a) == prediction_hash(b)


def test_cache_only_cli_is_mutually_exclusive_with_paid_execute():
    parser = build_parser()
    assert parser.parse_args(["recognize", "--provider", "openai", "--cache-only"]).cache_only
    with pytest.raises(SystemExit):
        parser.parse_args(["recognize", "--provider", "openai", "--cache-only", "--execute"])


@pytest.mark.parametrize("component", ["ledger", "cache"])
def test_persistence_failure_stops_before_next_call(tmp_path, monkeypatch, component):
    from khojki_ocr.budget import BudgetLedger
    selection, config = mock_inputs(tmp_path)
    config.recognition.max_attempts = 1
    def fail(*args, **kwargs):
        raise OSError("simulated write failure")
    monkeypatch.setattr(BudgetLedger if component == "ledger" else ResponseCache,
                        "settle" if component == "ledger" else "put", fail)
    _, manifest, adapter = batch(tmp_path, selection, config, [reply()])
    assert manifest["api_calls"] == adapter.calls == 1
    assert "persistence_failed" in manifest["stop_reason"] or "cache_write_failed" in manifest["stop_reason"]
    assert manifest["requests"][1]["status"] == "not_executed"


def test_budget_blocked_batch_never_dispatches(tmp_path):
    selection, config = mock_inputs(tmp_path)
    config.recognition.budget_usd = "0.001"
    _, manifest, adapter = batch(tmp_path, selection, config)
    assert adapter.calls == manifest["api_calls"] == 0
    assert manifest["stop_reason"] == "budget_blocked"
    assert manifest["requests"][1]["status"] == "not_executed"
