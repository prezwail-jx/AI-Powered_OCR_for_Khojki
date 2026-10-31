"""Deterministic offline codepoint CER over frozen predictions and truth."""

import hashlib
import json
from collections import Counter
from decimal import Decimal, getcontext
from pathlib import Path

import unicodedata2 as unicodedata

from .ground_truth import verify_truth
from .review import parse_json, prediction_hash
from .runtime import RunContext
from .relocation import source_path
from .schemas import RecognitionResult
from .storage import atomic_json, canonical_json

POLICY_VERSION = "cer-codepoint-nfc-1.0"
MAIN_PROVIDER = "openai"
MAIN_MODEL = "gpt-6.1-sol"
DEEPSEEK_CASES = {
    "D0": ("outputs/20261030T173809Z-e8fce2637d69", "results/deepseek-p0017-l006-2dcc97e9dc05.json"),
    "D1": ("outputs/20261030T192243Z-3082922123ed", "result.json"),
    "D2": ("outputs/20261030T192359Z-cc62c395b6fd", "result.json"),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fraction(numerator, denominator):
    if denominator <= 0:
        raise ValueError("CER reference must be nonempty")
    getcontext().prec = 28
    return {"numerator": numerator, "denominator": denominator,
            "decimal": format(Decimal(numerator) / Decimal(denominator), ".12f")}


def character(value):
    if value is None:
        return None
    return {"text": value, "codepoint": f"U+{ord(value):04X}", "name": unicodedata.name(value, "UNASSIGNED")}


def align(reference, hypothesis):
    """Levenshtein alignment; tie order is substitution, deletion, insertion."""
    if not reference:
        raise ValueError("CER reference must be nonempty")
    rows, columns = len(reference) + 1, len(hypothesis) + 1
    distance = [[0] * columns for _ in range(rows)]
    previous = [[None] * columns for _ in range(rows)]
    for i in range(1, rows):
        distance[i][0], previous[i][0] = i, "deletion"
    for j in range(1, columns):
        distance[0][j], previous[0][j] = j, "insertion"
    for i in range(1, rows):
        for j in range(1, columns):
            if reference[i - 1] == hypothesis[j - 1]:
                distance[i][j], previous[i][j] = distance[i - 1][j - 1], "match"
                continue
            candidates = [(distance[i - 1][j - 1] + 1, 0, "substitution"),
                          (distance[i - 1][j] + 1, 1, "deletion"),
                          (distance[i][j - 1] + 1, 2, "insertion")]
            value, _, operation = min(candidates)
            distance[i][j], previous[i][j] = value, operation
    i, j, operations = len(reference), len(hypothesis), []
    while i or j:
        operation = previous[i][j]
        if operation in ("match", "substitution"):
            i, j = i - 1, j - 1
            ref, hyp = reference[i], hypothesis[j]
        elif operation == "deletion":
            i -= 1
            ref, hyp = reference[i], None
        elif operation == "insertion":
            j -= 1
            ref, hyp = None, hypothesis[j]
        else:
            raise ValueError("Alignment backtrace is incomplete")
        operations.append({"operation": operation, "reference_index": i if ref is not None else i,
                           "hypothesis_index": j if hyp is not None else j,
                           "reference": character(ref), "hypothesis": character(hyp)})
    operations.reverse()
    counts = Counter(op["operation"] for op in operations)
    edits = counts["substitution"] + counts["deletion"] + counts["insertion"]
    if edits != distance[-1][-1]:
        raise ValueError("Alignment edit count and distance disagree")
    return {"reference_length": len(reference), "hypothesis_length": len(hypothesis),
            "distance": edits, "substitutions": counts["substitution"], "deletions": counts["deletion"],
            "insertions": counts["insertion"], "matches": counts["match"], "cer": fraction(edits, len(reference)),
            "exact_match": reference == hypothesis, "alignment": operations}


def evaluate_pair(reference_raw, hypothesis_raw):
    reference = unicodedata.normalize("NFC", reference_raw)
    hypothesis = unicodedata.normalize("NFC", hypothesis_raw)
    metrics = align(reference, hypothesis)
    metrics.update({"reference_raw": reference_raw, "hypothesis_raw": hypothesis_raw,
                    "reference_nfc": reference, "hypothesis_nfc": hypothesis,
                    "reference_nfc_changed": reference != reference_raw,
                    "hypothesis_nfc_changed": hypothesis != hypothesis_raw})
    return metrics


def _archive(truth):
    pointer = parse_json(truth.with_suffix(".manifest.json").read_bytes())
    return (truth.parent / pointer["archive"]).resolve()


def _main_lines(truth):
    truth_manifest, records = verify_truth(truth)
    archive = _archive(truth)
    lines = []
    for record in records:
        path = archive / record["source_prediction_file"]
        result = RecognitionResult.model_validate(parse_json(path.read_bytes()))
        if (result.line_id != record["line_id"] or result.provider != MAIN_PROVIDER
                or result.requested_model != MAIN_MODEL or result.candidate is None
                or prediction_hash(result) != record["prediction_sha256"]
                or sha(path.read_bytes()) != record["source_prediction_sha256"]
                or result.candidate.text != record["machine_text"]):
            raise ValueError("Frozen original prediction does not match truth provenance")
        metrics = evaluate_pair(record["text"], result.candidate.text)
        lines.append({"line_id": record["line_id"], "evaluation_order": record["evaluation_order"],
            "pdf_page": record["pdf_page"], "detection_reading_order": record["detection_reading_order"],
            "provider": result.provider, "requested_model": result.requested_model, "recognition_status": result.status,
            "uncertain_span_count": len(result.candidate.uncertain_spans), "prediction_sha256": record["prediction_sha256"],
            "truth_sha256": record["text_sha256"], "source_prediction_sha256": record["source_prediction_sha256"],
            **metrics})
    return truth_manifest, records, lines


def summarize(lines):
    if not lines:
        raise ValueError("Evaluation requires at least one line")
    total = {name: sum(line[name] for line in lines) for name in
             ("reference_length", "hypothesis_length", "distance", "substitutions", "deletions", "insertions")}
    macro = sum(Decimal(line["cer"]["numerator"]) / Decimal(line["cer"]["denominator"]) for line in lines) / Decimal(len(lines))
    substitutions, insertions, deletions = Counter(), Counter(), Counter()
    for line in lines:
        for operation in line["alignment"]:
            if operation["operation"] == "substitution":
                substitutions[(operation["reference"]["codepoint"], operation["hypothesis"]["codepoint"])] += 1
            elif operation["operation"] == "insertion":
                insertions[operation["hypothesis"]["codepoint"]] += 1
            elif operation["operation"] == "deletion":
                deletions[operation["reference"]["codepoint"]] += 1
    return {"line_count": len(lines), **total, "micro_cer": fraction(total["distance"], total["reference_length"]),
            "macro_cer": {"line_count": len(lines), "decimal": format(macro, ".12f")},
            "exact_line_count": sum(line["exact_match"] for line in lines),
            "exact_line_rate": fraction(sum(line["exact_match"] for line in lines), len(lines)),
            "recognition_failure_count": sum(line["recognition_status"] not in ("succeeded", "needs_review") for line in lines),
            "empty_hypothesis_count": sum(line["hypothesis_length"] == 0 for line in lines),
            "normalization_changed_line_count": sum(line["reference_nfc_changed"] or line["hypothesis_nfc_changed"] for line in lines),
            "substitution_confusions": [{"reference": a, "hypothesis": b, "count": n} for (a, b), n in sorted(substitutions.items())],
            "inserted_codepoints": [{"codepoint": code, "count": count} for code, count in sorted(insertions.items())],
            "deleted_codepoints": [{"codepoint": code, "count": count} for code, count in sorted(deletions.items())]}


def deepseek_appendix(root, first_truth):
    cases = []
    for variant, (directory, result_name) in DEEPSEEK_CASES.items():
        run = root / directory
        manifest = parse_json((run / "manifest.json").read_bytes())
        result_path = run / result_name
        result = RecognitionResult.model_validate(parse_json(result_path.read_bytes()))
        if variant == "D0":
            request = next(r for r in manifest["requests"] if r["provider"] == "deepseek")
            target = next(image for image in request["images"] if image["label"] == "TARGET LINE")
        else:
            if manifest["case"]["variant"] != variant or manifest["case"]["synthetic"] is not False:
                raise ValueError("Historical DeepSeek case metadata mismatch")
            target = next(image for image in manifest["request_identity"]["images"] if image["label"] == "TARGET LINE")
        if (result.line_id != first_truth["line_id"] or target["sha256"] != first_truth["image_sha256"]
                or result.provider != "deepseek" or result.candidate is None):
            raise ValueError("DeepSeek real-scan case does not bind to frozen first line")
        metrics = evaluate_pair(first_truth["text"], result.candidate.text)
        cases.append({"variant": variant, "scope": "exploratory_real_scan_first_line_only",
            "included_in_main_metrics": False, "recognition_status": result.status,
            "input_image_sha256": target["sha256"], "result_sha256": sha(result_path.read_bytes()),
            "configuration_note": "Historical diagnostic with a variant-specific prompt/image package; not a common model aggregate.", **metrics})
    synthetic = parse_json((root / "outputs/20261030T192315Z-0737de969846/metrics.json").read_bytes())
    cases.extend([{"variant": "D1b", "scope": "synthetic_control_only", "included_in_main_metrics": False,
                   "synthetic_cer": synthetic["synthetic_cer"], "synthetic_edit_distance": synthetic["synthetic_edit_distance"],
                   "synthetic_reference_codepoints": synthetic["synthetic_reference_codepoints"],
                   "note": synthetic["synthetic_cer_scope"]},
                  {"variant": "D3", "scope": "cancelled_before_dispatch", "included_in_main_metrics": False,
                   "status": "not_run", "api_calls": 0}])
    return cases


def render_report(summary, lines, appendix):
    rows = "\n".join(f"| {line['evaluation_order']} | {line['detection_reading_order']} | {line['reference_length']} | "
                     f"{line['substitutions']} | {line['deletions']} | {line['insertions']} | {line['cer']['decimal']} | "
                     f"{'yes' if line['exact_match'] else 'no'} |" for line in lines)
    deep = "\n".join(f"| {case['variant']} | {case['scope']} | " +
                     (f"{case['cer']['decimal']} | {case['distance']} |" if "cer" in case else
                      f"{case.get('synthetic_cer', 'not run')} | {case.get('synthetic_edit_distance', 'n/a')} |") for case in appendix)
    return f"""# T12 Offline OCR Evaluation

## Main result

This is selected-crop transcription CER for ten user-selected printed rows, not
whole-page detection recall or collection accuracy. Reference text is
model-assisted and user-confirmed, not independent blind expert transcription.

- Micro CER: **{summary['micro_cer']['decimal']}** ({summary['distance']}/{summary['reference_length']})
- Macro CER: **{summary['macro_cer']['decimal']}**
- Exact lines: **{summary['exact_line_count']}/{summary['line_count']}** ({summary['exact_line_rate']['decimal']})
- Errors: substitutions {summary['substitutions']}, deletions {summary['deletions']}, insertions {summary['insertions']}
- Recognition failures / empty hypotheses: {summary['recognition_failure_count']} / {summary['empty_hypothesis_count']}

| Eval row | Overlay | Ref chars | S | D | I | CER | Exact |
|---:|---:|---:|---:|---:|---:|---:|---|
{rows}

The only observed main-set error event must not be generalized as a stable error
distribution. A model-extra character is an insertion relative to the reference,
even though the human correction action deletes it from the prediction.

## Historical DeepSeek appendix (not main metrics)

| Case | Scope | CER | Edit distance |
|---|---|---:|---:|
{deep}

D0, D1 and D2 are separate historical configurations on the same first scan,
not repeated measurements under one setting. D1b is synthetic only; D3 was not
run. None contributes to the OpenAI aggregate.

## Boundaries

Both strings are NFC-normalized and counted in Unicode code points. Visible ASCII
space, Khojki separators, punctuation and Gujarati digits are retained. No
independent manual boxes exist, so detection recall/precision/IoU and manual-box
CER were not measured. Mechanical edit types are not causal stage attribution;
that remains T13. This evaluation is offline and makes no model calls.
"""


def evaluate_run(truth, run: RunContext, project_root, include_deepseek=False):
    manifest = {"stage": "evaluation", "status": "running", "run_id": run.run_id, "api_calls": 0,
                "policy_version": POLICY_VERSION, "truth_path": str(truth.resolve()), "files": {}}
    atomic_json(run.directory / "manifest.json", manifest)
    try:
        truth_manifest, truth_records, lines = _main_lines(truth)
        summary = summarize(lines)
        appendix = deepseek_appendix(project_root, truth_records[0]) if include_deepseek else []
        alignments = run.directory / "alignments"
        alignments.mkdir()
        compact_lines = []
        for line in lines:
            alignment = line.pop("alignment")
            path = alignments / f"{line['line_id']}.json"
            atomic_json(path, {"policy_version": POLICY_VERSION, "line_id": line["line_id"], "alignment": alignment})
            line["alignment_file"] = str(path.relative_to(run.directory))
            compact_lines.append(line)
        (run.directory / "lines.jsonl").write_text(''.join(canonical_json(line) + "\n" for line in compact_lines), encoding="utf-8")
        atomic_json(run.directory / "summary.json", summary)
        atomic_json(run.directory / "confusion.json", {
            "substitution_confusions": summary["substitution_confusions"],
            "inserted_codepoints": summary["inserted_codepoints"],
            "deleted_codepoints": summary["deleted_codepoints"],
        })
        atomic_json(run.directory / "deepseek-appendix.json", {"included_in_main_metrics": False, "cases": appendix})
        (run.directory / "report.md").write_text(render_report(summary, compact_lines, appendix), encoding="utf-8")
        source_files = [truth, truth.with_suffix(".manifest.json"), _archive(truth) / "manifest.json"]
        guard_path = project_root / "data/annotations/confirmations/t11-source-guard.json"
        if guard_path.exists():
            guard = parse_json(guard_path.read_bytes())
            guarded = [project_root / name for name in guard["files"]]
            if any(sha(path.read_bytes()) != guard["files"][str(path.relative_to(project_root))] for path in guarded):
                raise ValueError("A guarded T11 prediction, cache, selection or budget source changed")
            source_files.extend([guard_path, *guarded])
        source_files = list(dict.fromkeys(path.resolve() for path in source_files))
        manifest.update({"status": "completed", "truth_version": truth_manifest["truth_version"],
            "selection_id": truth_manifest["selection_id"], "include_historical_deepseek": include_deepseek,
            "detection_comparison": "not_performed_no_independent_manual_boxes",
            "source_hashes": {str(path): sha(path.read_bytes()) for path in source_files},
            "files": {str(path.relative_to(run.directory)): sha(path.read_bytes()) for path in run.directory.rglob("*")
                      if path.is_file() and path.name not in ("manifest.json", "run.log")}})
        atomic_json(run.directory / "manifest.json", manifest)
        verify_evaluation(run.directory)
        return manifest, summary
    except Exception:
        manifest["status"] = "failed"
        atomic_json(run.directory / "manifest.json", manifest)
        raise


def verify_evaluation(directory):
    manifest = parse_json((directory / "manifest.json").read_bytes())
    if manifest.get("stage") != "evaluation" or manifest.get("status") != "completed" or manifest.get("api_calls") != 0:
        raise ValueError("Not a completed offline evaluation")
    for name, digest in manifest["files"].items():
        if sha((directory / name).read_bytes()) != digest:
            raise ValueError("Evaluation artifact hash mismatch")
    for name, digest in manifest["source_hashes"].items():
        if sha(source_path(name).read_bytes()) != digest:
            raise ValueError("Evaluation source hash mismatch")
    truth = source_path(manifest["truth_path"])
    _, _, recomputed = _main_lines(truth)
    expected = summarize(recomputed)
    if parse_json((directory / "summary.json").read_bytes()) != expected:
        raise ValueError("Evaluation summary does not recompute from frozen sources")
    saved = [parse_json(line) for line in (directory / "lines.jsonl").read_bytes().splitlines()]
    if len(saved) != len(recomputed) or [r["line_id"] for r in saved] != [r["line_id"] for r in recomputed]:
        raise ValueError("Evaluation line set mismatch")
    for record, original in zip(saved, recomputed):
        alignment = parse_json((directory / record["alignment_file"]).read_bytes())["alignment"]
        if alignment != original.pop("alignment") or record != {**original, "alignment_file": record["alignment_file"]}:
            raise ValueError("Evaluation line/alignment does not recompute")
    return manifest, expected, saved
