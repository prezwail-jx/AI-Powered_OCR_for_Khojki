"""Offline input preparation CLI. OCR is implemented in subsequent tasks."""

import argparse
import json
import sys
from pathlib import Path

import pymupdf

from .config import load_config, parse_pages
from .runtime import RunContext, redact, write_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="khojki-ocr", description="Khojki OCR pipeline")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Validate PDF and save an offline run manifest (no OCR/API calls)")
    prepare.add_argument("--config", type=Path, help="YAML configuration; paths relative to working directory")
    prepare.add_argument("--pdf", type=Path)
    prepare.add_argument("--pages", help="1-based pages, e.g. 8,10-11 (default: 1)")
    prepare.add_argument("--output-dir", type=Path)
    prepare.add_argument("--dpi", type=int)
    preprocessing = commands.add_parser("preprocess", help="Render and preprocess full PDF pages offline (no OCR/API calls)")
    preprocessing.add_argument("--config", type=Path)
    preprocessing.add_argument("--pdf", type=Path)
    preprocessing.add_argument("--pages", help="1-based pages, e.g. 8,16")
    preprocessing.add_argument("--output-dir", type=Path)
    preprocessing.add_argument("--dpi", type=int)
    preprocessing.add_argument("--angle", type=float, help="Manual OpenCV correction angle in degrees, positive counterclockwise")
    detect = commands.add_parser("detect-lines", help="Detect text lines from a T04 run offline")
    detect.add_argument("--input-run", type=Path, required=True)
    detect.add_argument("--config", type=Path)
    detect.add_argument("--pages", help="Subset of pages available in the input run; default: all")
    detect.add_argument("--output-dir", type=Path)
    recognize = commands.add_parser("recognize", help="Prepare or explicitly execute independent visual transcription")
    recognize.add_argument("--selection", type=Path, default=Path("data/evaluation/selection.json"))
    recognize.add_argument("--provider", choices=("openai", "deepseek", "both"), required=True)
    recognize.add_argument("--limit", type=int, default=1, help="Selected lines, not provider calls (default: 1)")
    recognize.add_argument("--config", type=Path)
    recognize.add_argument("--output-dir", type=Path)
    mode = recognize.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Offline request preparation; no credentials or paid calls")
    mode.add_argument("--execute", action="store_true", help="Actual paid requests; verify pricing and T08 approval first")
    mode.add_argument("--cache-only", action="store_true", help="Read verified caches only; never create API clients or retry missing results")
    recognize.add_argument("--require-first-cache-hit", action="store_true", help="Guard a one-attempt OpenAI batch: stop before any call unless the first result is cached")
    check = commands.add_parser("unicode-check", help="Check a single UTF-8 transcription line offline")
    check.add_argument("--text-file", type=Path, required=True, help="Single-line UTF-8 file; one terminal line ending is treated as a file delimiter")
    check.add_argument("--output", type=Path, help="Optional JSON report; defaults to stdout")
    reference = commands.add_parser("build-reference", help="Generate bundled Unicode/font reference charts offline")
    reference.add_argument("--output-dir", type=Path, default=Path("outputs/references"), help="New directory (existing directories are not overwritten)")
    review = commands.add_parser("build-review", help="Build a read-only offline HTML/JSONL review bundle; no API calls")
    review.add_argument("--selection", type=Path, default=Path("data/evaluation/selection.json"))
    review.add_argument("--recognition-run", type=Path, required=True)
    review.add_argument("--references-dir", type=Path, default=Path("outputs/references-v1"))
    review.add_argument("--reviews-dir", type=Path, default=Path("data/annotations/reviews"))
    review.add_argument("--output-dir", type=Path, default=Path("outputs"))
    imports = commands.add_parser("review-import", help="Import human edits as versioned DRAFTS, never confirmed Ground Truth")
    imports.add_argument("--bundle", type=Path, required=True)
    imports.add_argument("--edits", type=Path, required=True)
    imports.add_argument("--reviewer", required=True)
    imports.add_argument("--reviews-dir", type=Path, default=Path("data/annotations/reviews"))
    freeze = commands.add_parser("freeze-truth", help="Freeze explicitly human-confirmed transcription; no model calls")
    freeze.add_argument("--selection", type=Path, required=True)
    freeze.add_argument("--bundle", type=Path, required=True)
    freeze.add_argument("--confirmation", type=Path, required=True)
    freeze.add_argument("--output", type=Path, default=Path("data/annotations/ground_truth.jsonl"))
    freeze.add_argument("--version", required=True)
    freeze.add_argument("--confirm", action="store_true", required=True, help="Explicitly authorize freezing the supplied human confirmations")
    verify = commands.add_parser("verify-truth", help="Verify the frozen truth and provenance hashes offline")
    verify.add_argument("--truth", type=Path, default=Path("data/annotations/ground_truth.jsonl"))
    evaluate = commands.add_parser("evaluate", help="Compute offline codepoint CER from frozen truth and original predictions")
    evaluate.add_argument("--truth", type=Path, default=Path("data/annotations/ground_truth.jsonl"))
    evaluate.add_argument("--output-dir", type=Path, default=Path("outputs"))
    evaluate.add_argument("--include-historical-deepseek", action="store_true")
    verify_eval = commands.add_parser("verify-evaluation", help="Recompute and verify an offline evaluation run")
    verify_eval.add_argument("--evaluation", type=Path, required=True)
    challenge = commands.add_parser("build-challenge-set", help="Freeze two offline qualitative manuscript crops")
    challenge.add_argument("--selection", type=Path, default=Path("data/challenges/t13/selection.json"))
    challenge.add_argument("--output", type=Path, default=Path("data/challenges/t13/frozen"))
    errors = commands.add_parser("analyze-errors", help="Build evidence-bound offline T13 error analysis")
    errors.add_argument("--attributions", type=Path, default=Path("data/annotations/error-attribution-v1.json"))
    errors.add_argument("--challenge", type=Path, default=Path("data/challenges/t13/frozen/manifest.json"))
    errors.add_argument("--evaluation", type=Path, default=Path("outputs/20261030T230213Z-afd44e1b89db"))
    errors.add_argument("--output-dir", type=Path, default=Path("outputs"))
    verify_errors = commands.add_parser("verify-error-analysis", help="Verify and recompute a T13 error analysis")
    verify_errors.add_argument("--analysis", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in ("evaluate", "verify-evaluation"):
        return evaluation_command(args)
    if args.command in ("build-challenge-set", "analyze-errors", "verify-error-analysis"):
        return error_analysis_command(args)
    if args.command in ("freeze-truth", "verify-truth"):
        return truth_command(args)
    if args.command in ("build-review", "review-import"):
        return review_command(args)
    if args.command not in ("prepare", "preprocess", "detect-lines", "recognize"):
        return unicode_command(args)
    try:
        config = load_config(args.config, {key: getattr(args, key, None) for key in ("pdf", "pages", "output_dir", "dpi")})
        if args.command == "preprocess" and args.angle is not None:
            from .config import PreprocessConfig

            config.preprocess = PreprocessConfig.model_validate({**config.preprocess.model_dump(), "angle_override": args.angle})
    except Exception:
        # Avoid exposing raw YAML, paths or validation input that may contain secrets.
        print("Configuration error: check YAML fields, pages, DPI and provider settings.", file=sys.stderr)
        return 2

    run = None
    try:
        run = RunContext(config.output_dir)
        if args.command == "recognize":
            from .recognition import recognize_run

            manifest = recognize_run(args.selection, config, args.provider, args.limit, args.dry_run, run,
                                     cache_only=args.cache_only, require_first_cache_hit=args.require_first_cache_hit)
            print(redact(f"Recognition {'dry-run' if args.dry_run else 'run'}: {manifest['status']}; API calls={manifest['api_calls']}. Manifest: {run.directory / 'manifest.json'}"))
            return 1 if manifest["status"] == "completed_with_errors" else 0
        if args.command == "detect-lines":
            from .line_detection import detect_run

            manifest = detect_run(args.input_run, config, run, args.pages)
            print(redact(f"Detected {sum(p['line_count'] for p in manifest['pages'])} line candidates. Manifest: {run.directory / 'manifest.json'}"))
            return 0
        if args.command == "preprocess":
            from .preprocess import preprocess_pdf

            manifest = preprocess_pdf(config, run)
            run.log("Page preprocessing completed; no OCR or API calls")
            print(redact(f"Preprocessed {len(manifest['pages'])} page(s). Manifest: {run.directory / 'manifest.json'}"))
            return 0
        run.log("Preparing PDF inputs offline; no OCR or API calls")
        with pymupdf.open(config.pdf) as document:
            if not document.is_pdf or document.needs_pass or document.page_count == 0:
                raise ValueError("Input must be a readable, nonempty, unencrypted PDF")
            pages = parse_pages(config.pages)
            if max(pages) > document.page_count:
                raise ValueError(f"Requested page exceeds PDF page count ({document.page_count})")
            manifest = {"run_id": run.run_id, "status": "prepared", "stage": "input_validation",
                        "ocr_performed": False, "api_calls": 0, "pdf_page_count": document.page_count,
                        "selected_pages": pages, "config": config.model_dump(mode="json")}
        write_json(run.directory / "manifest.json", manifest)
        run.log("Input validation completed")
        print(redact(f"Prepared {len(pages)} page(s). Manifest: {run.directory / 'manifest.json'}"))
        return 0
    except Exception as exc:
        if run is not None:
            run.error(exc)
        operation = {"detect-lines": "Line detection", "preprocess": "Page preprocessing", "recognize": "Recognition"}.get(args.command, "Input preparation")
        print(redact(f"{operation} failed: {exc}"), file=sys.stderr)
        return 1


def evaluation_command(args) -> int:
    from .evaluation import evaluate_run, verify_evaluation

    try:
        if args.command == "evaluate":
            run = RunContext(args.output_dir)
            _, summary = evaluate_run(args.truth, run, Path.cwd(), args.include_historical_deepseek)
            print(f"Evaluation: micro CER={summary['micro_cer']['decimal']}; {summary['exact_line_count']}/{summary['line_count']} exact; API calls=0. {run.directory / 'manifest.json'}")
        else:
            manifest, summary, _ = verify_evaluation(args.evaluation)
            print(f"Evaluation verified: {manifest['truth_version']}; micro CER={summary['micro_cer']['decimal']}; API calls=0")
        return 0
    except Exception:
        print("Evaluation failed: check frozen truth, source predictions, policy, hashes and complete line coverage. Raw input omitted.", file=sys.stderr)
        return 1


def error_analysis_command(args) -> int:
    from .error_analysis import analyze_run, freeze_challenge_set, verify_error_analysis

    try:
        root = Path.cwd()
        if args.command == "build-challenge-set":
            manifest = freeze_challenge_set(root, args.selection, args.output)
            print(f"Challenge set frozen: {manifest['line_count']} qualitative manuscript lines; API calls=0. {args.output / 'manifest.json'}")
        elif args.command == "analyze-errors":
            run = RunContext(args.output_dir)
            _, summary = analyze_run(root, args.attributions, args.challenge, args.evaluation, run)
            print(f"Error analysis: {summary['main_error_count']} main error, {summary['qualitative_detection_cases']} detection cases, {summary['qualitative_manuscript_cases']} manuscript cases; API calls=0. {run.directory / 'manifest.json'}")
        else:
            _, summary, _ = verify_error_analysis(root, args.analysis)
            print(f"Error analysis verified: {summary['main_error_count']} main error; main CER unchanged; API calls=0")
        return 0
    except Exception:
        print("Error analysis failed: check evidence hashes, frozen T12 result, qualitative challenge scope and source bindings.", file=sys.stderr)
        return 1


def truth_command(args) -> int:
    from .ground_truth import freeze_truth, verify_truth

    try:
        manifest, records = (freeze_truth(args.selection, args.bundle, args.confirmation, args.output, args.version,
                                        confirm=args.confirm) if args.command == "freeze-truth" else verify_truth(args.truth))
        print(f"Frozen truth verified: {manifest['truth_version']}; {len(records)} lines; {manifest['modified_line_count']} human-edited lines; API calls=0")
        return 0
    except Exception:
        print("Truth operation failed: check explicit confirmation, source bindings, Unicode, hashes and existing version. Raw input omitted.", file=sys.stderr)
        return 1


def review_command(args) -> int:
    from pydantic import ValidationError
    from .review import build_review, import_drafts

    run = None
    try:
        if args.command == "build-review":
            run = RunContext(args.output_dir)
            manifest = build_review(args.selection, args.recognition_run, run, args.references_dir, args.reviews_dir)
            print(redact(f"Review bundle: {run.directory / 'index.html'}; {manifest['candidate_count']}/{manifest['line_count']} candidates; no API calls"))
        else:
            path, revision = import_drafts(args.bundle, args.edits, args.reviewer, args.reviews_dir)
            print(redact(f"Saved DRAFT revision {revision.revision}: {path}. Rebuild review to view it; Ground Truth is NOT confirmed."))
        return 0
    except ValidationError:
        if run is not None:
            run.log("Review schema validation failed; raw input omitted")
        print("Review schema validation failed: check fields, types and offsets.", file=sys.stderr)
        return 2
    except Exception as exc:
        if run is not None:
            run.error(exc)
        print(redact(f"Review operation failed: {exc}"), file=sys.stderr)
        return 1


def unicode_command(args) -> int:
    try:
        if args.command == "build-reference":
            from .reference import build_reference

            manifest = build_reference(args.output_dir)
            print(redact(f"Generated {len(manifest['sheets'])} reference sheets in {args.output_dir}"))
            return 0
        from .unicode_rules import validate_text

        # Keep original file content, including a removed file delimiter, in the report.
        with args.text_file.open(encoding="utf-8", newline="") as handle:
            file_text = handle.read()
        delimiter = "\r\n" if file_text.endswith("\r\n") else "\n" if file_text.endswith("\n") else ""
        text = file_text[:-len(delimiter)] if delimiter else file_text
        report = validate_text(text)
        report.update({"source_file_text": file_text, "terminal_file_delimiter": delimiter})
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            # Preserve transcription text exactly; this is data, not diagnostics.
            args.output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        else:
            print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0 if report["valid"] else 1
    except Exception as exc:
        print(redact(f"Unicode operation failed: {exc}"), file=sys.stderr)
        return 2
