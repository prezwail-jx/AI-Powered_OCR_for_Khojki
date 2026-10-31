"""Verified request preparation, independent transcription and attempt accounting."""

import json
import hashlib
import re
import time
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
from pathlib import Path

import openai

from .budget import BudgetError, BudgetLedger, money, rate_ready, reservation_cost
from .cache import CacheError, ResponseCache
from .config import PipelineConfig
from .providers.base import ImageInput, PreparedRequest
from .providers.deepseek import DeepSeekAdapter
from .providers.openai import OpenAIAdapter
from .schemas import OCRPayload, RecognitionResult
from .storage import atomic_json, canonical_json
from .unicode_rules import UNICODE_VERSION, asset_bytes, validate_text
from .runtime import redact


def _inside(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Image path is outside its manifest directory")
    return path


def load_selection(path: Path):
    selection = json.loads(path.read_text(encoding="utf-8"))
    records = selection["lines"]
    if not records or len(records) != selection["line_count"] or len({r["line_id"] for r in records}) != len(records):
        raise ValueError("Selection count/identity mismatch")
    result = []
    for record in records:
        if not isinstance(record["line_id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", record["line_id"]):
            raise ValueError("Invalid selection line identifier")
        if record["crop_review_status"] != "user_confirmed_complete":
            raise ValueError("Unapproved crop in evaluation selection")
        image = ImageInput.read(_inside(path.parent, record["image_path"]), "TARGET LINE", record["image_sha256"])
        # No Ground Truth, expected number or other-model output enters a request.
        result.append((record["line_id"], image))
    return result


def load_references(config):
    directory = config.reference_dir
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if (manifest["unicode_version"] != UNICODE_VERSION or
            manifest["policy_sha256"] != hashlib.sha256(asset_bytes("unicode", "transcription_rules.json")).hexdigest() or
            manifest["characters_sha256"] != hashlib.sha256(asset_bytes("unicode", "characters.json")).hexdigest()):
        raise ValueError("Reference package Unicode data/policy mismatch")
    entries = {entry["file"]: entry for entry in manifest["sheets"]}
    return tuple(ImageInput.read(_inside(directory, name), f"REFERENCE CHART: {name} (not target text)", entries[name]["sha256"])
                 for name in config.reference_files)


def prepare_requests(selection: Path, config: PipelineConfig, provider: str, limit: int):
    if limit < 1:
        raise ValueError("Limit must be positive")
    selected = load_selection(selection)
    references = load_references(config.recognition)
    providers = ["openai", "deepseek"] if provider == "both" else [provider]
    if any(name not in ("openai", "deepseek") for name in providers):
        raise ValueError("Unknown provider")
    requests = []
    for line_id, image in selected[:limit]:
        for name in providers:
            images = (image, *references)
            if name == "deepseek" and (len(images) > 600 or any(max(i.width, i.height) > (4096 if len(images) >= 15 else 8192) or len(i.data) > 32 * 1024 ** 2 for i in images)):
                raise ValueError("DeepSeek image size/count limit exceeded")
            if sum(4 * ((len(i.data) + 2) // 3) for i in images) > 46 * 1024 ** 2:
                raise ValueError("Inline image payload too large; reduce an explicitly configured reference package")
            requests.append(PreparedRequest(line_id, name, getattr(config, name).model_copy(deep=True), images))
    return requests


def _strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("Non-finite JSON constant")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def classify_response(request, response):
    result = RecognitionResult(line_id=request.line_id, provider=request.provider, requested_model=request.settings.model,
                               returned_model=response.returned_model, cache_key=request.cache_key,
                               status=response.state if response.state != "completed" else "schema_error",
                               raw_response_text=response.raw_text, usage=response.usage, request_id=response.request_id,
                               billing_metadata=response.billing_metadata)
    if request.provider == "openai":
        tier = response.billing_metadata.get("service_tier")
        if request.settings.openai_service_tier == "default" and tier not in (None, "default"):
            result.warnings.append("unexpected_service_tier; review billing before further calls")
        if request.settings.openai_cache_mode == "explicit" and response.billing_metadata.get("cache_write_tokens") not in (None, 0):
            result.warnings.append("unexpected_cloud_cache_write; review billing before further calls")
    if response.usage_warning:
        result.warnings.append("usage_missing_or_invalid")
    if not response.returned_model:
        result.warnings.append("returned_model_missing")
    elif response.returned_model != request.settings.model:
        result.warnings.append("returned_model_differs_from_requested_alias")
    if response.state != "completed":
        return result
    if not response.raw_text.strip():
        result.status = "empty_output"
        return result
    try:
        result.candidate = OCRPayload.model_validate(_strict_json(response.raw_text))
    except (ValueError, TypeError):
        result.status = "schema_error"
        return result
    result.unicode_report = validate_text(result.candidate.text)
    result.codepoints = [item["codepoint"] for item in result.unicode_report["characters"]]
    if not result.candidate.text.strip():
        result.status = "empty_output"
    elif result.candidate.unreadable or result.candidate.uncertain_spans or result.unicode_report["needs_review"] or result.warnings:
        result.status = "needs_review"
    else:
        result.status = "succeeded"
    return result


def transport_error(exc):
    status_code = getattr(exc, "status_code", None)
    if isinstance(exc, (openai.APITimeoutError, TimeoutError)):
        return "timeout", False
    if status_code == 429:
        return "rate_limited", True
    if status_code in (401, 403):
        return "authentication_error", False
    if status_code == 404:
        return "model_unavailable", False
    if isinstance(status_code, int) and status_code >= 500:
        return "transport_error", True
    if isinstance(status_code, int) and 400 <= status_code < 500:
        return "request_error", False
    return "transport_error", False


def safe_error_details(exc):
    """Only selected, redacted diagnostic fields; never dump the SDK body/headers."""
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return {}
    details = body.get("error", body)
    if not isinstance(details, dict):
        return {}
    safe = {}
    for name in ("code", "param", "type", "message"):
        value = details.get(name)
        if isinstance(value, str):
            value = redact(value)
            value = re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+", "[IMAGE_DATA_REDACTED]", value)
            safe[f"provider_error_{name}"] = value[:500]
    return safe


def retry_delay(exc, number, config):
    response = getattr(exc, "response", None)
    value = response.headers.get("retry-after") if response is not None else None
    if value:
        try:
            seconds = float(value)
        except ValueError:
            try:
                seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                seconds = config.retry_base_seconds * 2 ** (number - 1)
    else:
        seconds = config.retry_base_seconds * 2 ** (number - 1)
    import math

    if not math.isfinite(seconds) or seconds > config.max_retry_delay_seconds:
        return None  # Never retry earlier than a server's longer requested delay.
    return max(0, seconds)


def cached_result(request, cache):
    cached = cache.get(request.cache_key)
    if cached is None:
        return None
    if cached.provider != request.provider or cached.requested_model != request.settings.model:
        raise CacheError("Cache provider/model mismatch")
    return cached.model_copy(update={"line_id": request.line_id, "cache_hit": True, "attempts": [], "elapsed_seconds": 0.0,
                                     "cost": {"status": "cache_hit", "current_call_usd": "0", "historical_response_cost": cached.cost}})


def batch_stop_reason(result):
    if result.status in {"timeout", "rate_limited", "transport_error", "budget_blocked", "authentication_error",
                         "request_error", "model_unavailable", "cache_error"}:
        return result.status
    for warning in result.warnings:
        if warning.startswith(("unexpected_service_tier", "unexpected_cloud_cache_write", "billing_assumptions_unverified",
                               "accounting_persistence_failed", "token_bound_exceeded", "cache_write_failed",
                               "usage_missing_or_invalid", "returned_model_differs_from_requested_alias", "returned_model_missing")):
            return warning
    if result.cost.get("status") == "unknown_or_reserved":
        return "new_charge_unknown_or_reserved"
    return None


def recognize_one(request, adapter, cache, ledger, config, sleep=time.sleep, on_attempt=None):
    started = time.monotonic()
    base = dict(line_id=request.line_id, provider=request.provider, requested_model=request.settings.model, cache_key=request.cache_key)

    def failed(status, warning):
        return RecognitionResult(**base, status=status, warnings=[warning], cost={"status": "not_called", "current_call_usd": "0"})

    if getattr(adapter, "provider", request.provider) != request.provider:
        return failed("request_error", "adapter_protocol_does_not_match_provider")
    try:
        with cache.lock(request.cache_key):
            cached = cached_result(request, cache)
            if cached is not None:
                return cached
            try:
                rate_ready(request.settings)
                reservation_cost(request.settings)
            except BudgetError:
                return failed("budget_blocked", "verified_pricing_and_input_bound_required")
            try:
                adapter.preflight(request)
            except Exception:
                return failed("authentication_error", "client_preflight_failed; check local credentials/configuration")
            attempts = []
            result = None
            for number in range(1, config.max_attempts + 1):
                try:
                    reservation_id, reserved = ledger.reserve(request.cache_key, request.provider, request.settings)
                except BudgetError:
                    result = failed("budget_blocked", "budget_reservation_failed; previous unknown charges remain held")
                    break
                attempt_start = time.monotonic()
                attempt = {"number": number, "reservation_id": reservation_id, "reserved_usd": str(reserved),
                           "provider": request.provider, "line_id": request.line_id, "cache_key": request.cache_key}
                retry, delay = False, None
                try:
                    response = adapter.send(request)
                except Exception as exc:
                    status, retry = transport_error(exc)
                    result = failed(status, "provider_request_failed; inspect status/request ID, never log raw SDK exceptions")
                    attempt.update({"status": status, "error_type": type(exc).__name__,
                                    "http_status": getattr(exc, "status_code", None), "request_id": getattr(exc, "request_id", None)})
                    attempt.update(safe_error_details(exc))
                    delay = retry_delay(exc, number, config) if retry else None
                    usage = None
                else:
                    result = classify_response(request, response)
                    usage = response.usage
                    attempt.update({"status": result.status, "usage": usage.model_dump() if usage else None,
                                    "request_id": response.request_id})
                    if any(w.startswith("unexpected_service_tier") or w.startswith("unexpected_cloud_cache_write") for w in result.warnings):
                        # Preserve returned usage, but don't settle against rates
                        # whose tier/cache assumptions the response contradicts.
                        usage = None
                        result.warnings.append("billing_assumptions_unverified; reservation retained")
                try:
                    entry = ledger.settle(reservation_id, usage, request.settings)
                except (BudgetError, OSError):
                    entry = {"state": "reserved", "accounted_usd": str(reserved)}
                    result.warnings.append("accounting_persistence_failed; reservation retained, no retry")
                    if result.status == "succeeded":
                        result.status = "needs_review"
                    retry = False
                if entry.get("bound_exceeded"):
                    result.warnings.append("token_bound_exceeded; reconcile pricing/bounds before further calls")
                    if result.status == "succeeded":
                        result.status = "needs_review"
                attempt.update({"elapsed_seconds": time.monotonic() - attempt_start,
                                "cost_state": entry["state"], "accounted_usd": entry["accounted_usd"]})
                attempts.append(attempt)
                if on_attempt is not None:
                    on_attempt(attempt)
                if not retry or delay is None or number == config.max_attempts:
                    break
                sleep(delay)
            result.attempts = attempts
            result.elapsed_seconds = time.monotonic() - started
            total = sum((money(a["accounted_usd"]) for a in attempts), Decimal(0))
            uncertain = any(a["cost_state"] != "usage_estimate" for a in attempts)
            result.cost = {"status": "unknown_or_reserved" if uncertain else "usage_estimate" if attempts else "not_called",
                           "accounted_this_call_usd": str(total), "current_call_usd": None if uncertain else str(total)}
            try:
                cache.put(result)
            except OSError:
                result.warnings.append("cache_write_failed; result retained, no automatic request retry")
            return result
    except (CacheError, TimeoutError) as exc:
        return failed("cache_error", "cache_unavailable_or_corrupt; no automatic paid retry")


def recognize_run(selection: Path, config: PipelineConfig, provider, limit, dry_run, run, adapters=None,
                  *, cache_only=False, require_first_cache_hit=False):
    if dry_run and cache_only:
        raise ValueError("Dry-run and cache-only are mutually exclusive")
    if require_first_cache_hit and (provider != "openai" or config.recognition.max_attempts != 1):
        raise ValueError("Guarded OpenAI batch requires provider=openai and max_attempts=1")
    requests = prepare_requests(selection, config, provider, limit)
    adapters = {} if cache_only else adapters or {"openai": OpenAIAdapter(), "deepseek": DeepSeekAdapter()}
    manifest = {"run_id": run.run_id, "stage": "recognition_request_preparation" if dry_run else "recognition",
                "status": "running", "dry_run": dry_run, "cache_only": cache_only, "api_calls": 0, "requests": [], "results": [],
                "require_first_cache_hit": require_first_cache_hit, "stop_reason": None,
                "selection_path": str(selection.resolve()), "ground_truth_written": False,
                "selection_sha256": hashlib.sha256(selection.read_bytes()).hexdigest(),
                "reference_manifest_sha256": hashlib.sha256((config.recognition.reference_dir / "manifest.json").read_bytes()).hexdigest(),
                "api_calls_note": "Adapter dispatch attempts, not billing confirmations"}
    atomic_json(run.directory / "manifest.json", manifest)
    try:
        cache = None if dry_run else ResponseCache(config.recognition.cache_dir)
        ledger = None if dry_run or cache_only else BudgetLedger(config.recognition.ledger_path, config.recognition.budget_usd)
        if ledger is not None:
            manifest["budget_before"] = ledger.summary()
        for request in requests:
            # Request construction is pure; no SDK client is constructed here.
            if not cache_only:
                adapters[request.provider].build_payload(request)
            try:
                estimate = str(reservation_cost(request.settings))
            except BudgetError:
                estimate = None
            summary = {"line_id": request.line_id, "provider": request.provider, "model": request.settings.model,
                       "cache_key": request.cache_key, "protocol": request.identity()["protocol"],
                       "images": [image.summary() for image in request.images], "image_count": len(request.images),
                       "request_identity": request.identity(),
                       "reservation_estimate_usd": estimate, "budget_ready": estimate is not None,
                       "status": "prepared_not_executed" if dry_run else "prepared"}
            manifest["requests"].append(summary)
        atomic_json(run.directory / "manifest.json", manifest)
        if require_first_cache_hit and not dry_run:
            try:
                with cache.lock(requests[0].cache_key):
                    first = cached_result(requests[0], cache)
                manifest["stop_reason"] = "required_first_cache_missing" if first is None else batch_stop_reason(first)
            except (CacheError, TimeoutError):
                manifest["stop_reason"] = "required_first_cache_invalid"
        for request, summary in zip(requests, manifest["requests"]):
            if not dry_run and manifest["stop_reason"] and not cache_only:
                summary.update({"status": "not_executed", "not_executed_reason": manifest["stop_reason"]})
            elif not dry_run:
                def emit(attempt):
                    with (run.directory / "attempts.jsonl").open("a", encoding="utf-8") as handle:
                        handle.write(canonical_json(attempt) + "\n")
                    manifest["api_calls"] += 1
                    atomic_json(run.directory / "manifest.json", manifest)

                if require_first_cache_hit and request is requests[0] and not cache_only:
                    result = first
                elif cache_only:
                    try:
                        with cache.lock(request.cache_key):
                            result = cached_result(request, cache)
                        if result is None:
                            raise CacheError("missing")
                    except (CacheError, TimeoutError):
                        result = RecognitionResult(line_id=request.line_id, provider=request.provider,
                            requested_model=request.settings.model, cache_key=request.cache_key, status="cache_error",
                            warnings=["cache_only_missing_or_invalid; no API fallback"],
                            cost={"status": "not_called", "current_call_usd": "0"})
                else:
                    result = recognize_one(request, adapters[request.provider], cache, ledger, config.recognition, on_attempt=emit)
                path = run.directory / "results" / f"{request.provider}-{request.line_id}.json"
                atomic_json(path, result.model_dump(mode="json"))
                manifest["results"].append({"line_id": request.line_id, "provider": request.provider, "status": result.status,
                                            "cache_hit": result.cache_hit, "file": str(path.relative_to(run.directory))})
                summary["status"] = result.status
                if not cache_only:
                    manifest["stop_reason"] = batch_stop_reason(result)
                run.log(f"Recognition {request.provider} {request.line_id}: {result.status}; cache_hit={result.cache_hit}")
            atomic_json(run.directory / "manifest.json", manifest)
        if ledger is not None:
            manifest["budget"] = ledger.summary()
        manifest["status"] = "prepared" if dry_run else "completed_with_errors" if manifest["stop_reason"] or any(r["status"] not in ("succeeded", "needs_review") for r in manifest["results"]) else "completed"
        if not dry_run:
            from .batch_export import export_results

            manifest["exports"] = export_results(run.directory, manifest)
        atomic_json(run.directory / "manifest.json", manifest)
        return manifest
    except Exception:
        manifest["status"] = "failed"
        atomic_json(run.directory / "manifest.json", manifest)
        raise
    finally:
        for adapter in adapters.values():
            if hasattr(adapter, "close"):
                adapter.close()
