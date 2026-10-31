import copy
import hashlib
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import openai
import pytest
from PIL import Image

from khojki_ocr.budget import BudgetError, BudgetLedger, reservation_cost, usage_cost
from khojki_ocr.cache import CacheError, ResponseCache
from khojki_ocr.cli import main
from khojki_ocr.config import PipelineConfig, PricingConfig, ProviderConfig, RecognitionConfig
from khojki_ocr.providers.base import ImageInput, PreparedRequest
from khojki_ocr.providers.deepseek import DeepSeekAdapter
from khojki_ocr.providers.openai import OpenAIAdapter
from khojki_ocr.recognition import classify_response, prepare_requests, recognize_one, recognize_run
from khojki_ocr.runtime import RunContext
from khojki_ocr.schemas import OCRPayload, ProviderResponse, TokenUsage
from khojki_ocr.storage import content_hash

TEXT = "\U00011208\U0001122C\U0001123A\u0AE8"
VALID = {"text": TEXT, "uncertain_spans": [], "unreadable": False}
ROOT = Path(__file__).resolve().parents[1]


def png_input(label="TARGET LINE", value=180):
    buffer = io.BytesIO()
    Image.new("L", (64, 32), value).save(buffer, format="PNG")
    data = buffer.getvalue()
    return ImageInput(label, data, hashlib.sha256(data).hexdigest(), 64, 32)


def settings(provider="openai", priced=True):
    model = "gpt-6.1-sol" if provider == "openai" else "deepseek-flash"
    # Deliberately fictitious unit-test rates, never saved in project defaults.
    rates = PricingConfig(model=model, input_per_million_usd="1", output_per_million_usd="2",
                          source_url="https://example.invalid/test-rates", checked_on=date(2026, 1, 1),
                          max_input_tokens=1000, input_bound_basis="unit-test bound, not a real estimate")
    return ProviderConfig(model=model, base_url="https://api.openai.com/v1" if provider == "openai" else "https://api.deepseek.com",
                          max_output_tokens=100, pricing=rates if priced else None)


def request(provider="openai", priced=True):
    return PreparedRequest("line-1", provider, settings(provider, priced),
                           (png_input(), png_input("REFERENCE CHART: example (not target text)", 200)))


def reply(payload=None, state="completed", usage=True, model="gpt-6.1-sol"):
    return ProviderResponse(state=state, raw_text=json.dumps(VALID if payload is None else payload, ensure_ascii=True),
                            returned_model=model, request_id="mock-request-1",
                            usage=TokenUsage(input_tokens=100, output_tokens=10, cached_input_tokens=20, reasoning_tokens=3) if usage else None,
                            usage_warning=not usage)


class StubAdapter:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.preflights = 0

    def preflight(self, req):
        self.preflights += 1

    def send(self, req):
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def infrastructure(tmp_path, cap="15"):
    return ResponseCache(tmp_path / "cache"), BudgetLedger(tmp_path / "budget.json", Decimal(cap)), RecognitionConfig(retry_base_seconds=0)


@pytest.mark.parametrize("provider", ["openai", "deepseek"])
def test_actual_sdk_serialization_and_response_parsing_use_mock_transport(provider, tmp_path):
    req = request(provider)
    observed = []

    def handler(http_request):
        body = json.loads(http_request.content)
        observed.append(body)
        assert http_request.method == "POST"
        if provider == "openai":
            assert http_request.url.path == "/v1/responses"
            assert body["text"]["format"]["strict"] is True
            assert body["store"] is False and body["stream"] is False
            assert body["max_output_tokens"] == 100
            assert body["input"][1]["content"][0]["text"] == "TARGET LINE"
            assert body["input"][1]["content"][1]["detail"] == "original"
            assert body["input"][1]["content"][3]["image_url"].startswith("data:image/png;base64,")
            data = {"id": "resp-mock", "object": "response", "created_at": 1, "model": req.settings.model, "status": "completed",
                    "output": [{"id": "msg-mock", "type": "message", "role": "assistant", "status": "completed",
                                "content": [{"type": "output_text", "text": json.dumps(VALID), "annotations": []}]}],
                    "usage": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110,
                              "input_tokens_details": {"cached_tokens": 20}, "output_tokens_details": {"reasoning_tokens": 3}}}
        else:
            assert http_request.url.path == "/chat/completions"
            assert body["thinking"]["type"] == "disabled" and "extra_body" not in body
            assert body["response_format"] == {"type": "json_object"}
            assert body["max_tokens"] == 100 and body["stream"] is False
            assert body["messages"][1]["content"][0]["text"] == "TARGET LINE"
            assert body["messages"][1]["content"][1]["image_url"]["detail"] == "original"
            assert "JSON schema:" in body["messages"][0]["content"]
            data = {"id": "chat-mock", "object": "chat.completion", "created": 1, "model": req.settings.model,
                    "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps(VALID)}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110,
                              "prompt_cache_hit_tokens": 20, "completion_tokens_details": {"reasoning_tokens": 3}}}
        return httpx.Response(200, json=data, headers={"x-request-id": "http-mock-id"})

    with openai.OpenAI(api_key="fake-unit-test-key", base_url=req.settings.base_url, max_retries=0,
                       http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        assert client.max_retries == 0
        adapter = OpenAIAdapter(client) if provider == "openai" else DeepSeekAdapter(client)
        cache, ledger, cfg = infrastructure(tmp_path)
        result = recognize_one(req, adapter, cache, ledger, cfg)
    assert len(observed) == 1 and result.status == "succeeded"
    assert result.candidate.text == TEXT
    assert result.unicode_report["characters"][0]["codepoint"] == "U+11208"
    assert result.codepoints == [f"U+{ord(char):04X}" for char in TEXT]
    assert result.usage.cached_input_tokens == 20 and result.usage.reasoning_tokens == 3
    assert ledger.summary()["accounted_usd"] == "0.00012"
    assert "fake-unit-test-key" not in (tmp_path / "budget.json").read_text()
    assert "fake-unit-test-key" not in next((tmp_path / "cache").glob("*.json")).read_text()


@pytest.mark.parametrize("payload,status", [
    ({**VALID, "text": "abc"}, "needs_review"),
    ({**VALID, "text": ""}, "empty_output"),
    ({**VALID, "text": "   "}, "empty_output"),
    ({**VALID, "unreadable": True}, "needs_review"),
    ({**VALID, "unreadable": "false"}, "schema_error"),
    ({**VALID, "extra": "not allowed"}, "schema_error"),
    ({"text": TEXT}, "schema_error"),
    ({**VALID, "uncertain_spans": [{"start": 0, "end": 1, "alternatives": ["\U0001120A"], "reason": "ambiguous"}]}, "needs_review"),
    ({**VALID, "uncertain_spans": [{"start": 0, "end": 100, "alternatives": [], "reason": "outside"}]}, "schema_error"),
    ({**VALID, "uncertain_spans": [{"start": 1, "end": 1, "alternatives": [], "reason": "empty"}]}, "schema_error"),
    # A surrogate is not a valid Unicode string under the strict output contract.
    # Keep the raw escaped response, but never promote it to a candidate.
    ({**VALID, "text": "\ud800"}, "schema_error"),
])
def test_output_contract_and_unicode_validation(payload, status):
    result = classify_response(request(), reply(payload))
    assert result.status == status
    assert result.raw_response_text == json.dumps(payload, ensure_ascii=True)


@pytest.mark.parametrize("raw", ["   ", "not JSON", '```json\n{}\n```', '{"text":"x","text":"y","uncertain_spans":[],"unreadable":false}', '{"text":NaN,"uncertain_spans":[],"unreadable":false}'])
def test_invalid_json_is_not_repaired_into_success(raw):
    response = reply().model_copy(update={"raw_text": raw})
    assert classify_response(request(), response).status in ("empty_output", "schema_error")


@pytest.mark.parametrize("state", ["refused", "truncated", "transport_error", "schema_error"])
def test_noncompleted_response_never_parses_as_success(state):
    result = classify_response(request(), reply(state=state))
    assert result.status == state and result.candidate is None


def test_cache_reuse_identity_invalidation_and_corruption(tmp_path, monkeypatch):
    req = request()
    cache, ledger, cfg = infrastructure(tmp_path)
    adapter = StubAdapter([reply()])
    first = recognize_one(req, adapter, cache, ledger, cfg)
    assert not first.cache_hit
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    second = recognize_one(replace(req, line_id="same-image-other-line-id"), StubAdapter([]), cache, ledger, cfg)
    assert second.cache_hit and second.line_id == "same-image-other-line-id"
    assert second.cost["current_call_usd"] == "0" and second.attempts == []
    assert ledger.summary()["attempts"] == 1
    changes = [replace(req, system_prompt=req.system_prompt + " different"),
               replace(req, images=(png_input(value=170), *req.images[1:])),
               replace(req, images=(req.images[0], png_input("REFERENCE CHART: example", 210))),
               replace(req, settings=req.settings.model_copy(update={"model": "other-model"})),
               replace(req, settings=req.settings.model_copy(update={"base_url": "https://example.invalid/v1"})),
               replace(req, settings=req.settings.model_copy(update={"max_output_tokens": 101})),
               replace(req, settings=req.settings.model_copy(update={"image_detail": "high"}))]
    assert all(changed.cache_key != req.cache_key for changed in changes)
    # Pricing and credentials cannot change the model answer or request identity.
    assert replace(req, settings=req.settings.model_copy(update={"pricing": None})).cache_key == req.cache_key
    path = cache.directory / f"{req.cache_key}.json"
    data = json.loads(path.read_text())
    data["result"]["raw_response_text"] = "tampered"
    path.write_text(json.dumps(data))
    blocked = recognize_one(req, StubAdapter([]), cache, ledger, cfg)
    assert blocked.status == "cache_error" and ledger.summary()["attempts"] == 1


def test_missing_prices_or_insufficient_budget_means_zero_model_calls(tmp_path):
    cache, ledger, cfg = infrastructure(tmp_path, ".001")
    adapter = StubAdapter([])
    assert recognize_one(request(priced=False), adapter, cache, ledger, cfg).status == "budget_blocked"
    assert adapter.preflights == 0
    assert recognize_one(request(), adapter, cache, ledger, cfg).status == "budget_blocked"
    assert adapter.calls == 0 and ledger.summary()["attempts"] == 0


def http_error(status, retry_after="0"):
    response = httpx.Response(status, request=httpx.Request("POST", "https://example.invalid"), headers={"retry-after": retry_after})
    cls = openai.RateLimitError if status == 429 else openai.AuthenticationError if status == 401 else openai.InternalServerError if status >= 500 else openai.NotFoundError
    return cls("SENSITIVE-RAW-ERROR-MUST-NOT-BE-STORED", response=response, body={"private": "secret"})


def test_retry_after_then_success_holds_unknown_first_charge(tmp_path):
    cache, ledger, cfg = infrastructure(tmp_path)
    delays = []
    adapter = StubAdapter([http_error(429, "2"), reply()])
    result = recognize_one(request(), adapter, cache, ledger, cfg, sleep=delays.append)
    assert result.status == "succeeded" and adapter.calls == 2 and delays == [2]
    assert result.cost["current_call_usd"] is None
    assert ledger.summary()["accounted_usd"] == "0.00132"
    assert ledger.summary()["unknown_or_reserved_attempts"] == 1
    assert "SENSITIVE-RAW-ERROR" not in json.dumps(result.model_dump())


@pytest.mark.parametrize("error,status", [(TimeoutError("private"), "timeout"), (http_error(401), "authentication_error"),
                                          (http_error(404), "model_unavailable"), (http_error(503, "999"), "transport_error")])
def test_timeout_auth_and_long_server_wait_do_not_blindly_retry(tmp_path, error, status):
    cache, ledger, cfg = infrastructure(tmp_path)
    adapter = StubAdapter([error])
    result = recognize_one(request(), adapter, cache, ledger, cfg, sleep=lambda _: pytest.fail("Must not retry"))
    assert result.status == status and adapter.calls == 1
    assert ledger.summary()["accounted_usd"] == "0.0012"
    assert ledger.summary()["unknown_or_reserved_attempts"] == 1


def test_retry_limit_and_per_attempt_reservation(tmp_path):
    cache, ledger, cfg = infrastructure(tmp_path)
    adapter = StubAdapter([http_error(503), http_error(503)])
    result = recognize_one(request(), adapter, cache, ledger, cfg, sleep=lambda _: None)
    assert result.status == "transport_error" and adapter.calls == 2
    assert ledger.summary()["attempts"] == 2 and ledger.summary()["accounted_usd"] == "0.0024"
    cache2, ledger2, cfg2 = infrastructure(tmp_path / "tight", ".0015")
    adapter2 = StubAdapter([http_error(429)])
    result = recognize_one(request(), adapter2, cache2, ledger2, cfg2, sleep=lambda _: None)
    assert result.status == "budget_blocked" and adapter2.calls == 1
    assert result.cost["accounted_this_call_usd"] == "0.0012"


def test_usage_missing_and_token_bound_breach_are_not_free(tmp_path):
    cache, ledger, cfg = infrastructure(tmp_path)
    result = recognize_one(request(), StubAdapter([reply(usage=False)]), cache, ledger, cfg)
    assert result.status == "needs_review" and ledger.summary()["accounted_usd"] == "0.0012"
    assert ledger.summary()["unknown_or_reserved_attempts"] == 1
    cache2, ledger2, cfg2 = infrastructure(tmp_path / "breach")
    over = reply().model_copy(update={"usage": TokenUsage(input_tokens=2000, output_tokens=10)})
    result2 = recognize_one(request(), StubAdapter([over]), cache2, ledger2, cfg2)
    assert result2.status == "needs_review"
    assert ledger2.summary()["accounted_usd"] == "0.00202"
    assert recognize_one(replace(request(), line_id="new", system_prompt="changed"), StubAdapter([]), cache2, ledger2, cfg2).status == "budget_blocked"


def test_cache_lock_prevents_duplicate_concurrent_calls(tmp_path):
    cache, ledger, cfg = infrastructure(tmp_path)

    class SlowAdapter(StubAdapter):
        def send(self, req):
            time.sleep(.05)
            return super().send(req)

    adapter = SlowAdapter([reply()])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: recognize_one(request(), adapter, cache, ledger, cfg), range(2)))
    assert adapter.calls == 1 and sum(r.cache_hit for r in results) == 1
    assert ledger.summary()["attempts"] == 1


def test_shared_ledger_survives_restart_and_concurrent_reservations(tmp_path):
    ledger = BudgetLedger(tmp_path / "shared.json", Decimal(".0015"))

    def reserve(index):
        try:
            return ledger.reserve(str(index), "openai", settings())[0]
        except BudgetError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(reserve, range(2)))
    assert sum(value is not None for value in outcomes) == 1
    reopened = BudgetLedger(ledger.path, Decimal(".0015"))
    assert reopened.summary()["accounted_usd"] == "0.0012"
    assert reopened.summary()["unknown_or_reserved_attempts"] == 1
    with pytest.raises(BudgetError):
        BudgetLedger(ledger.path, Decimal("15")).summary()
    with pytest.raises(BudgetError):
        reservation_cost(settings().model_copy(update={"pricing": settings("deepseek").pricing}))


def test_usage_details_are_subsets_and_not_double_billed():
    usage = TokenUsage(input_tokens=100, output_tokens=10, cached_input_tokens=80, reasoning_tokens=8)
    assert usage_cost(settings(), usage) == Decimal(".00012")
    with pytest.raises(ValueError):
        TokenUsage(input_tokens=5, output_tokens=10, cached_input_tokens=6)


def test_nullable_usage_details_preserve_known_totals_without_invented_counts():
    from khojki_ocr.providers.base import parse_usage

    usage, warning = parse_usage({"input_tokens": 100, "output_tokens": 10,
                                  "input_tokens_details": {"cached_tokens": None},
                                  "output_tokens_details": {"reasoning_tokens": None}}, "openai")
    assert usage is not None and not warning
    assert usage.cached_input_tokens is None and usage.reasoning_tokens is None
    assert usage_cost(settings(), usage) == Decimal(".00012")


def test_frozen_selection_and_reference_dry_run_without_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(openai, "OpenAI", lambda *a, **kw: pytest.fail("SDK client must not be constructed in dry-run"))
    # Existing generated references are not assumed for installed copies: generate
    # a reference package from bundled fonts/data in the test's temporary folder.
    from khojki_ocr.reference import build_reference

    references = tmp_path / "references"
    build_reference(references)
    config = PipelineConfig(recognition=RecognitionConfig(reference_dir=references, cache_dir=tmp_path / "cache", ledger_path=tmp_path / "ledger.json"))
    selection = ROOT / "data/evaluation/selection.json"
    requests = prepare_requests(selection, config, "both", 1)
    assert len(requests) == 2 and all(len(r.images) == 9 for r in requests)
    run = RunContext(tmp_path / "runs")
    manifest = recognize_run(selection, config, "both", 1, True, run)
    assert manifest["api_calls"] == 0 and manifest["status"] == "prepared"
    assert not (tmp_path / "ledger.json").exists() and not (tmp_path / "cache").exists()
    assert all(not r["budget_ready"] and r["reservation_estimate_usd"] is None for r in manifest["requests"])
    assert "base64" not in (run.directory / "manifest.json").read_text()
    assert "ground_truth" not in requests[0].system_prompt.lower()
    with pytest.raises(ValueError):
        prepare_requests(selection, config, "both", 0)


def test_reference_and_selection_corruption_stops_before_clients(tmp_path):
    source = ROOT / "data/evaluation/selection.json"
    selection = json.loads(source.read_text())
    selection["lines"][0]["image_path"] = str((source.parent / selection["lines"][0]["image_path"]).resolve())
    selection["lines"][0]["image_sha256"] = "wrong"
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(selection))
    with pytest.raises(ValueError):
        prepare_requests(path, PipelineConfig(), "openai", 1)


def test_missing_mode_is_not_implicitly_paid():
    with pytest.raises(SystemExit) as exc:
        main(["recognize", "--provider", "openai"])
    assert exc.value.code == 2


def mock_inputs(tmp_path):
    from khojki_ocr.unicode_rules import asset_bytes

    directory = tmp_path / "inputs"
    directory.mkdir()
    records = []
    for index, value in enumerate((180, 170), 1):
        image = png_input(value=value)
        name = f"line-{index}.png"
        (directory / name).write_bytes(image.data)
        records.append({"line_id": f"line-{index}", "image_path": name, "image_sha256": image.sha256,
                        "crop_review_status": "user_confirmed_complete", "ground_truth": "DO_NOT_SEND_GROUND_TRUTH"})
    selection = directory / "selection.json"
    selection.write_text(json.dumps({"line_count": 2, "lines": records}))
    references = directory / "references"
    references.mkdir()
    ref = png_input("reference", value=200)
    (references / "ref.png").write_bytes(ref.data)
    (references / "manifest.json").write_text(json.dumps({"unicode_version": "17.0.0",
        "policy_sha256": hashlib.sha256(asset_bytes("unicode", "transcription_rules.json")).hexdigest(),
        "characters_sha256": hashlib.sha256(asset_bytes("unicode", "characters.json")).hexdigest(),
        "sheets": [{"file": "ref.png", "sha256": ref.sha256}]}))
    config = PipelineConfig(openai=settings(), deepseek=settings("deepseek"),
                            recognition=RecognitionConfig(reference_dir=references, reference_files=["ref.png"],
                                cache_dir=tmp_path / "cache", ledger_path=tmp_path / "ledger.json", retry_base_seconds=0))
    return selection, config


def test_batch_keeps_failures_and_cache_resume_without_answers_leaking(tmp_path):
    selection, config = mock_inputs(tmp_path)
    requests = prepare_requests(selection, config, "openai", 2)
    adapter = OpenAIAdapter(SimpleNamespace())
    assert "DO_NOT_SEND_GROUND_TRUTH" not in json.dumps(adapter.build_payload(requests[0]))
    queue = [reply(state="truncated"), reply()]

    class InjectedAdapter(OpenAIAdapter):
        def send(self, req):
            return queue.pop(0)

    adapter = InjectedAdapter(SimpleNamespace())
    run = RunContext(tmp_path / "runs")
    first = recognize_run(selection, config, "openai", 2, False, run, adapters={"openai": adapter})
    assert first["status"] == "completed_with_errors" and first["api_calls"] == 2
    assert [result["status"] for result in first["results"]] == ["truncated", "succeeded"]
    assert all((run.directory / r["file"]).exists() for r in first["results"])
    assert len((run.directory / "attempts.jsonl").read_text().splitlines()) == 2
    queue.append(reply())
    second_run = RunContext(tmp_path / "runs")
    second = recognize_run(selection, config, "openai", 2, False, second_run, adapters={"openai": adapter})
    assert second["status"] == "completed" and second["api_calls"] == 1
    assert second["results"][1]["cache_hit"] is True
    assert "DO_NOT_SEND_GROUND_TRUTH" in selection.read_text()  # Never edited as OCR output.


def test_reference_manifest_and_image_hashes_are_enforced(tmp_path):
    selection, config = mock_inputs(tmp_path)
    path = config.recognition.reference_dir / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["unicode_version"] = "16.0.0"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Unicode"):
        prepare_requests(selection, config, "openai", 1)
    manifest["unicode_version"] = "17.0.0"
    path.write_text(json.dumps(manifest))
    (path.parent / "ref.png").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash mismatch"):
        prepare_requests(selection, config, "openai", 1)


def test_client_factory_is_lazy_and_disables_sdk_retries(monkeypatch):
    captured = []

    def factory(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(openai, "OpenAI", factory)
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-local-key")
    adapter = OpenAIAdapter()
    assert not captured
    adapter.preflight(request())
    assert captured[0]["max_retries"] == 0 and captured[0]["timeout"] == 60
    assert captured[0]["api_key"] == "unit-test-local-key"
    adapter.preflight(request())
    assert len(captured) == 1
    changed = replace(request(), settings=settings().model_copy(update={"timeout_seconds": 90}))
    adapter.preflight(changed)
    assert len(captured) == 2 and captured[-1]["timeout"] == 90


def test_invalid_usage_refusal_and_truncation_in_actual_adapters():
    bad_usage = {"input_tokens": 10, "output_tokens": 3, "input_tokens_details": {"cached_tokens": 11}}
    payload = {"id": "response", "model": "gpt-6.1-sol", "status": "completed", "usage": bad_usage,
               "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "Not transcribing"}]}]}
    adapter = OpenAIAdapter(SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: payload)))
    result = adapter.send(request())
    assert result.state == "refused" and result.usage is None and result.usage_warning
    payload["status"] = "incomplete"
    payload["output"] = [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(VALID)}]}]
    assert adapter.send(request()).state == "truncated"
    data = {"model": "deepseek-flash", "choices": [{"finish_reason": "stop", "message": {"content": "    ", "reasoning_content": "DO_NOT_PERSIST_REASONING"}}], "usage": None}
    other = DeepSeekAdapter(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: data))))
    response = other.send(request("deepseek"))
    assert classify_response(request("deepseek"), response).status == "empty_output"
    assert "DO_NOT_PERSIST_REASONING" not in response.model_dump_json()


@pytest.mark.parametrize("status", [429, 503])
def test_sdk_itself_does_not_add_hidden_retries(tmp_path, status):
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(status, json={"error": {"message": "mock retryable failure", "type": "test"}}, headers={"retry-after": "0"})

    with openai.OpenAI(api_key="fake-unit-test-key", max_retries=0,
                       http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        cache, ledger, cfg = infrastructure(tmp_path)
        result = recognize_one(request(), OpenAIAdapter(client), cache, ledger, cfg, sleep=lambda _: None)
    assert len(seen) == 2 and len(result.attempts) == 2
    assert ledger.summary()["attempts"] == 2


def test_wrong_adapter_or_unavailable_credentials_does_not_reserve(tmp_path, monkeypatch):
    cache, ledger, cfg = infrastructure(tmp_path)
    assert recognize_one(request(), DeepSeekAdapter(), cache, ledger, cfg).status == "request_error"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert recognize_one(request(), OpenAIAdapter(), cache, ledger, cfg).status == "authentication_error"
    assert ledger.summary()["attempts"] == 0


def test_accounting_failure_retains_reservation_and_candidate(tmp_path, monkeypatch):
    cache, ledger, cfg = infrastructure(tmp_path)

    def unavailable(*args, **kwargs):
        raise OSError("mock disk failure")

    monkeypatch.setattr(ledger, "settle", unavailable)
    adapter = StubAdapter([reply()])
    result = recognize_one(request(), adapter, cache, ledger, cfg)
    assert result.status == "needs_review" and result.candidate.text == TEXT
    assert adapter.calls == 1 and ledger.summary()["accounted_usd"] == "0.0012"
    assert ledger.summary()["unknown_or_reserved_attempts"] == 1


def test_schema_or_policy_version_invalidates_cache_identity(monkeypatch):
    from khojki_ocr.providers import base

    req = request()
    original = req.cache_key
    monkeypatch.setattr(base, "SCHEMA_VERSION", "ocr-test-new-version")
    assert req.cache_key != original
    changed = req.cache_key
    get_asset = base.asset_bytes
    monkeypatch.setattr(base, "asset_bytes", lambda group, name: get_asset(group, name) + b" " if name == "transcription_rules.json" else get_asset(group, name))
    assert req.cache_key != changed


def test_smoke_config_has_single_attempt_standard_no_cloud_writes_and_safe_bound():
    from khojki_ocr.config import load_config

    cfg = load_config(ROOT / "configs/smoke.yaml")
    assert cfg.recognition.max_attempts == 1
    assert cfg.openai.timeout_seconds == cfg.deepseek.timeout_seconds == 180
    assert cfg.openai.openai_service_tier == "default"
    assert cfg.openai.openai_cache_mode == "explicit"
    assert reservation_cost(cfg.openai) == Decimal("3.74944")
    assert reservation_cost(cfg.deepseek) == Decimal("0.6049152")
    assert reservation_cost(cfg.openai) + reservation_cost(cfg.deepseek) < cfg.recognition.budget_usd


def test_standard_and_explicit_only_caching_are_serialized_without_breakpoints():
    req = request()
    cfg = req.settings.model_copy(update={"openai_service_tier": "default", "openai_cache_mode": "explicit"})
    configured = replace(req, settings=cfg)
    assert configured.cache_key != req.cache_key
    observed = []

    def handler(http_request):
        payload = json.loads(http_request.content)
        observed.append(payload)
        assert payload["service_tier"] == "default"
        assert payload["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
        assert "prompt_cache_breakpoint" not in json.dumps(payload)
        return httpx.Response(200, json={"id": "resp-policy-mock", "object": "response", "model": cfg.model,
            "status": "completed", "service_tier": "default",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(VALID)}]}],
            "usage": {"input_tokens": 100, "output_tokens": 10, "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0}}})

    with openai.OpenAI(api_key="fake-unit-test-key", max_retries=0,
                       http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        response = OpenAIAdapter(client).send(configured)
    assert len(observed) == 1
    assert response.billing_metadata["service_tier"] == "default"
    assert response.billing_metadata["cache_write_tokens"] == 0
    assert classify_response(configured, response).status == "succeeded"


def test_selected_error_details_are_redacted_without_raw_sdk_dump(monkeypatch):
    from khojki_ocr.recognition import safe_error_details

    key = "sk-" + "unit-test-sensitive-key"
    monkeypatch.setenv("OPENAI_API_KEY", key)
    exc = SimpleNamespace(body={"error": {"message": f"Invalid {key} data:image/png;base64,YWJj", "code": "invalid_request", "param": "text.format"}},
                          response=SimpleNamespace(headers={"Authorization": "Bearer should-never-be-dumped"}))
    safe = safe_error_details(exc)
    value = json.dumps(safe)
    assert key not in value and "YWJj" not in value and "should-never-be-dumped" not in value
    assert safe["provider_error_code"] == "invalid_request"
    assert "[REDACTED]" in safe["provider_error_message"]


def test_provider_masked_key_fragments_are_fully_removed_without_full_key():
    from khojki_ocr.recognition import safe_error_details

    exc = SimpleNamespace(body={"message": "Incorrect API key provided: key_SAMPLE********TAIL. Visit the API dashboard.",
                               "code": "invalid_api_key"})
    safe = safe_error_details(exc)
    assert "key_SAMPLE" not in safe["provider_error_message"]
    assert "TAIL" not in safe["provider_error_message"]
    assert safe["provider_error_code"] == "invalid_api_key"


@pytest.mark.parametrize("billing", [{"service_tier": "priority"}, {"cache_write_tokens": 100}])
def test_contradicted_smoke_billing_assumptions_keep_reservation(tmp_path, billing):
    req = request()
    req = replace(req, settings=req.settings.model_copy(update={"openai_service_tier": "default", "openai_cache_mode": "explicit"}))
    response = reply().model_copy(update={"billing_metadata": billing})
    cache, ledger, cfg = infrastructure(tmp_path)
    result = recognize_one(req, StubAdapter([response]), cache, ledger, cfg)
    assert result.status == "needs_review" and result.usage.input_tokens == 100
    assert ledger.summary()["accounted_usd"] == "0.0012"
    assert ledger.summary()["unknown_or_reserved_attempts"] == 1
