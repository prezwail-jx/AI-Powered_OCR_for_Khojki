"""Isolated one-attempt DeepSeek experiments, never evaluation Ground Truth."""

import argparse
import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image

from .budget import BudgetLedger, reservation_cost
from .cache import ResponseCache
from .config import load_config
from .providers.base import ImageInput, PreparedRequest
from .providers.deepseek import DeepSeekAdapter
from .recognition import prepare_requests, recognize_one
from .reference import SERIF, render_glyph
from .runtime import RunContext, redact
from .storage import atomic_json, canonical_json
from .unicode_rules import asset_bytes, character_table, normalize_text

DIAGNOSIS_VERSION = "deepseek-diagnosis-1.0"
TARGET_ONLY_PROMPT = """Protocol: khojki-target-only-diagnostic-v1.
Transcribe ONLY the single image labeled TARGET LINE into Khojki Unicode text.
Do not translate, transliterate, paraphrase, infer words, or complete missing text.
Preserve all visible vowel marks, Khojki word separators, punctuation and any
Gujarati digits. Do not invent absent digits. Do not output an alphabet, a table,
a codepoint list or dotted circles. Use atomic Khojki vowel letters and signs.
Return JSON with exactly: text (string), uncertain_spans (array of objects with
start, end, alternatives, reason), unreadable (boolean). Offsets are zero-based
Unicode code points in raw text, end exclusive. State uncertainty with short
reasons. If there is no defensible reading, return empty text, no spans and
unreadable=true. Do not include explanations or long reasoning outside JSON.
"""
# Deliberately artificial syllable sequence, rendered without any visible labels.
# This oracle is only used AFTER inference and is never inserted in a request.
SYNTHETIC_TEXT = "\U00011208\U0001122C\U0001123A\U0001120A\U0001122D\U0001123A\U00011221\U0001122F\U0001123A\U00011224\U00011230"
BASELINE_OUTPUT = "".join(chr(cp) for cp in [0x1122C, 0x1122D, 0x1122E, 0x1122F, *range(0x11234, 0x1123F)])
OPENAI_CONTROL = Path("outputs/20261030T185807Z-806667a839b0/results/openai-p0017-l006-2dcc97e9dc05.json")
VARIANTS = ("D1", "D1b", "D2", "D3")


@dataclass(frozen=True)
class DiagnosticCase:
    variant: str
    request: PreparedRequest
    metadata: dict
    expected: str | None = None


def build_case(variant, config, selection, directory: Path):
    if variant not in VARIANTS:
        raise ValueError("Unknown diagnostic variant")
    baseline = prepare_requests(selection, config, "deepseek", 1)[0]
    metadata = {"diagnosis_version": DIAGNOSIS_VERSION, "variant": variant,
                "source_line_id": baseline.line_id, "source_target_sha256": baseline.images[0].sha256,
                "baseline_cache_key": baseline.cache_key, "synthetic": variant == "D1b",
                "not_ground_truth_for_scans": True}
    if variant == "D1":
        req = replace(baseline, images=(baseline.images[0],), system_prompt=TARGET_ONLY_PROMPT)
        metadata.update({"change": "Target only; reference-dependent prompt clauses removed",
                         "confound": "Image package and necessary prompt wording both differ from D0; no single-run causal proof"})
        return DiagnosticCase(variant, req, metadata)
    if variant == "D1b":
        directory.mkdir(parents=True, exist_ok=True)
        glyph = render_glyph(SYNTHETIC_TEXT, size=120)
        image = Image.new("RGB", (glyph.width + 80, glyph.height + 80), "white")
        image.paste(glyph, (40, 40))
        path = directory / "synthetic-target.png"
        image.save(path)
        target = ImageInput.read(path, "TARGET LINE", hashlib.sha256(path.read_bytes()).hexdigest())
        req = replace(baseline, line_id="diagnostic-synthetic-khojki-v1", images=(target,), system_prompt=TARGET_ONLY_PROMPT)
        metadata.update({"change": "D1 prompt and target-only presentation; clean synthetic target replaces historical scan",
                         "font": SERIF, "font_sha256": hashlib.sha256(asset_bytes("fonts", SERIF)).hexdigest(),
                         "confound": "Modern synthetic syllables differ from historical text/font; performance does not generalize automatically"})
        atomic_json(directory / "synthetic-oracle.json", {"expected_text": SYNTHETIC_TEXT, "image_sha256": target.sha256,
                    "note": "Diagnostic oracle only; not sent to the model and not part of real evaluation selection"})
        return DiagnosticCase(variant, req, metadata, SYNTHETIC_TEXT)
    if variant == "D2":
        marks = next((image for image in baseline.images[1:] if image.label.startswith("REFERENCE CHART: marks.png ")), None)
        if marks is None:
            raise ValueError("D2 requires the verified marks.png reference")
        req = replace(baseline, images=(baseline.images[0], marks))
        metadata.update({"change": "Same D0 prompt/settings/target; reference package reduced to marks.png only",
                         "confound": "A symbol chart alone is not a full alphabet; failure does not prove visual incapacity"})
        return DiagnosticCase(variant, req, metadata)
    req = replace(baseline, images=(*baseline.images[1:], baseline.images[0]))
    metadata.update({"change": "Same D0 prompt and image bytes; only reference/target order changes, target last",
                     "confound": "Single stochastic trial; improvement is evidence consistent with ordering sensitivity, not proof"})
    return DiagnosticCase(variant, req, metadata)


def edit_distance(left, right):
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(previous[j] + 1, current[-1] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def longest_shared_substring(left, right):
    previous = [0] * (len(right) + 1)
    best = 0
    for a in left:
        current = [0] * (len(right) + 1)
        for j, b in enumerate(right, 1):
            if a == b:
                current[j] = previous[j - 1] + 1
                best = max(best, current[j])
        previous = current
    return best


def diagnostic_metrics(text, expected=None, unverified_control=None):
    if text is None:
        return {"candidate_extracted": False, "synthetic_cer": None,
                "note": "No contract-valid candidate extracted; do not invent a scan CER"}
    table = character_table()
    khojki = [ord(char) for char in text if table.get(ord(char), {}).get("script") == "Khojki"]
    letters = sum(table[cp]["category"] == "Lo" for cp in khojki)
    digits = [char for char in text if 0xAE6 <= ord(char) <= 0xAEF]
    run = longest_shared_substring(text, BASELINE_OUTPUT)
    metrics = {"candidate_extracted": True, "codepoint_count": len(text), "khojki_codepoints": len(khojki),
               "khojki_base_letters": letters, "base_letter_ratio": letters / len(khojki) if khojki else 0,
               "gujarati_digits": digits, "ends_with_gujarati_digit": bool(text.strip()) and 0xAE6 <= ord(text.strip()[-1]) <= 0xAEF,
               "dotted_circle_present": "\u25cc" in text, "signs_only": bool(khojki) and letters == 0,
               "shared_chart_sequence_length": run, "chart_like_run": run >= 5,
               "note": "Structural diagnostics only; these are not scan accuracy, confidence or acceptance thresholds"}
    nfc = normalize_text(text)["nfc_text"]
    if expected is not None:
        oracle = normalize_text(expected)["nfc_text"]
        distance = edit_distance(nfc, oracle)
        metrics.update({"synthetic_exact_match": nfc == oracle, "synthetic_edit_distance": distance,
                        "synthetic_reference_codepoints": len(oracle), "synthetic_cer": distance / len(oracle),
                        "synthetic_cer_scope": "Only this programmatically rendered diagnostic control, never the real scan"})
    elif unverified_control is not None:
        control = normalize_text(unverified_control)["nfc_text"]
        distance = edit_distance(nfc, control)
        metrics["unverified_openai_agreement"] = {"edit_distance": distance,
            "normalized_disagreement": distance / max(len(nfc), len(control), 1), "not_ground_truth": True}
    return metrics


def run_case(variant, config, selection, run, dry_run=True, adapter=None):
    if config.recognition.max_attempts != 1:
        raise ValueError("Diagnostic experiments require max_attempts=1")
    case = build_case(variant, config, selection, run.directory)
    adapter = adapter or DeepSeekAdapter()
    adapter.build_payload(case.request)  # Validate construction without creating an SDK client.
    manifest = {"run_id": run.run_id, "stage": "deepseek_diagnosis", "status": "running", "dry_run": dry_run,
                "api_calls": 0, "case": case.metadata, "request_identity": case.request.identity(),
                "cache_key": case.request.cache_key, "image_count": len(case.request.images),
                "attempt_reservation_usd": str(reservation_cost(case.request.settings)),
                "ground_truth_written": False, "selection_sha256": hashlib.sha256(selection.read_bytes()).hexdigest()}
    atomic_json(run.directory / "manifest.json", manifest)
    if dry_run:
        manifest["status"] = "prepared_not_executed"
        atomic_json(run.directory / "manifest.json", manifest)
        return manifest
    ledger = BudgetLedger(config.recognition.ledger_path, config.recognition.budget_usd)

    def emit(attempt):
        with (run.directory / "attempts.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(attempt) + "\n")
        manifest["api_calls"] += 1
        atomic_json(run.directory / "manifest.json", manifest)

    try:
        result = recognize_one(case.request, adapter, ResponseCache(config.recognition.cache_dir), ledger,
                               config.recognition, on_attempt=emit)
        atomic_json(run.directory / "result.json", result.model_dump(mode="json"))
        control = None
        if case.expected is None and OPENAI_CONTROL.is_file():
            record = json.loads(OPENAI_CONTROL.read_text(encoding="utf-8"))
            if record.get("candidate"):
                control = record["candidate"]["text"]
                manifest["comparison_only_openai_sha256"] = hashlib.sha256(OPENAI_CONTROL.read_bytes()).hexdigest()
        metrics = diagnostic_metrics(result.candidate.text if result.candidate else None, case.expected, control)
        atomic_json(run.directory / "metrics.json", metrics)
        blocked = result.status in {"timeout", "authentication_error", "model_unavailable", "rate_limited", "transport_error",
                                    "budget_blocked", "cache_error", "request_error"} or result.cost.get("status") == "unknown_or_reserved"
        manifest.update({"status": "paused" if blocked else "completed", "recognition_status": result.status,
                         "cache_hit": result.cache_hit, "cost": result.cost, "budget": ledger.summary(),
                         "metrics": "metrics.json", "result": "result.json"})
        atomic_json(run.directory / "manifest.json", manifest)
        run.log(f"Diagnostic {variant}: {result.status}; calls={manifest['api_calls']}; no retries/batch")
        return manifest
    except Exception:
        manifest["status"] = "failed"
        atomic_json(run.directory / "manifest.json", manifest)
        raise
    finally:
        adapter.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=VARIANTS, required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/smoke.yaml"))
    parser.add_argument("--selection", type=Path, default=Path("data/evaluation/selection.json"))
    parser.add_argument("--output-dir", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    run = None
    try:
        config = load_config(args.config, {"output_dir": args.output_dir})
        run = RunContext(config.output_dir)
        manifest = run_case(args.variant, config, args.selection, run, args.dry_run)
        print(redact(f"DeepSeek {args.variant}: {manifest['status']}; API calls={manifest['api_calls']}. Manifest: {run.directory / 'manifest.json'}"))
        return 1 if manifest["status"] == "paused" else 0
    except Exception as exc:
        if run is not None:
            run.error(exc)
        print(redact(f"Diagnosis failed: {exc}"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
