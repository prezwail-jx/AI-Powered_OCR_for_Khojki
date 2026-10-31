"""Allowlisted delivery export and network-blocked reviewer reproduction."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import socket
import sys
import zipfile
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from .error_analysis import analyze_run, verify_error_analysis
from .evaluation import DEEPSEEK_CASES, evaluate_run, verify_evaluation
from .ground_truth import verify_truth
from .relocation import relocated_sources, source_path
from .runtime import RunContext
from .storage import atomic_json

T12 = Path("outputs/20261030T230213Z-afd44e1b89db")
T13 = Path("outputs/20261030T233828Z-bdf49aab235d")
TRUTH = Path("data/annotations/ground_truth.jsonl")
ATTRIBUTION = Path("data/annotations/error-attribution-v1.json")
CHALLENGE = Path("data/challenges/t13/frozen/manifest.json")
PDF_NAME = "sample_khojki_script_vatiations.pdf"
PDF_SHA = "99f373777e13ad01ccc7ff1ae067cb80a3de2bc22d96df6c7ab0a558f8d11f23"


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inside(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Delivery path escapes its root")
    return path


def evidence_files(root):
    """Derive a finite allowlist from selected, already frozen provenance only."""
    files = {TRUTH, TRUTH.with_suffix(".manifest.json"), ATTRIBUTION, CHALLENGE,
             Path("data/challenges/t13/selection.json"), Path("data/annotations/confirmations/t11-source-guard.json")}
    files.update(Path(name) for name in read(root / "data/annotations/confirmations/t11-source-guard.json")["files"])
    archive = root / "data/annotations/versions/ground-truth-v1"
    files.add(archive.relative_to(root) / "manifest.json")
    files.update(archive.relative_to(root) / name for name in read(archive / "manifest.json")["files"])
    for directory in (T12, T13):
        manifest = read(root / directory / "manifest.json")
        files.add(directory / "manifest.json")
        files.update(directory / name for name in manifest["files"])
        for name in manifest["source_hashes"]:
            files.add(source_path(name).resolve().relative_to(root))
    for case in read(root / ATTRIBUTION)["cases"]:
        files.update(Path(item["path"]) for item in case["evidence"])
    challenge = read(root / CHALLENGE)
    files.add(Path(challenge["contact_sheet"]))
    for line in challenge["lines"]:
        files.update(Path(line[key]) for key in ("frozen_crop_path", "source_lines_path", "source_crop_path"))
    for directory, result in DEEPSEEK_CASES.values():
        files.update((Path(directory) / "manifest.json", Path(directory) / result))
    files.add(Path("outputs/20261030T192315Z-0737de969846/metrics.json"))
    for name in ("data/evaluation/selection.json", "data/evaluation/v2/selection.json"):
        selection = read(root / name)
        files.add(Path(name))
        files.update(Path(name).parent / row["image_path"] for row in selection["lines"])
    # Tests and cache request identities require the exact reference package.
    files.update(p.relative_to(root) for p in (root / "outputs/references-v1").glob("*") if p.is_file())
    files.add(Path("outputs/20261030T185807Z-806667a839b0/results/openai-p0017-l006-2dcc97e9dc05.json"))
    batch = Path("outputs/20261030T210414Z-23bc6581d98c")
    files.add(batch / "manifest.json")
    files.update(batch / name for name in read(root / batch / "manifest.json")["exports"]["files"])
    files.add(Path("outputs/20261030T154139Z-8f9c0c0bcbcb/manifest.json"))
    # Historical geometry and source crops needed by selection replacement tests.
    for name in ("outputs/20261030T154139Z-8f9c0c0bcbcb/pages/page-0017",
                 "outputs/20261030T154140Z-29d2de257bd5/pages/page-0009"):
        page = Path(name)
        files.update((page / "lines.jsonl", page / "lines-overlay.png"))
        files.update(page / row["crop_path"] for row in
                     (json.loads(line) for line in (root / page / "lines.jsonl").read_bytes().splitlines()))
    return sorted(files)


def code_files(root):
    files = {Path(name) for name in ("README.md", "pyproject.toml", "requirements-repro.txt", ".env.example",
                                    ".gitignore", "PRD.md", "plan.md", "task.md")}
    for folder in ("src/khojki_ocr", "tests", "scripts", "configs", "docs", "reports", "spec/feats"):
        files.update(path.relative_to(root) for path in (root / folder).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts
                     and path.suffix not in (".pyc", ".zip") and not path.name.startswith("t14-source-baseline"))
    return sorted(files)


def scan_bytes(name, data, secrets=()):
    __tracebackhide__ = True
    # Only report the path/rule, never matched material.
    if any(secret and secret.encode() in data for secret in secrets):
        raise ValueError(f"Credential match in {name}; content omitted")
    text = data.decode("utf-8", errors="ignore")
    if re.search(r"\bsk-[A-Za-z0-9_-]{20,}", text) or ("-----BEGIN " + "PRIVATE KEY-----") in text:
        raise ValueError(f"Credential pattern in {name}; content omitted")


def export_packages(root, destination):
    __tracebackhide__ = True
    root, destination = root.resolve(), destination.resolve()
    if destination.exists():
        raise ValueError("Delivery destination exists; never overwrite")
    secrets = [value for key, value in os.environ.items()
               if any(word in key.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")) and len(value) >= 12]
    env = root / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                value = line.split("=", 1)[1].strip().strip("\"'")
                if len(value) >= 12:
                    secrets.append(value)
    destination.mkdir(parents=True)
    indexes = {}
    for kind, names in (("code", code_files(root)), ("review-evidence", evidence_files(root))):
        hashes = {}
        package = destination / f"{kind}.zip"
        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in names:
                path = inside(root, name)
                if name.name == ".env" or (name.suffix == ".pdf" and name != Path("reports/reflection.pdf")):
                    raise ValueError("Private environment or input PDF is forbidden in delivery")
                data = path.read_bytes()
                scan_bytes(str(name), data, secrets)
                archive.writestr(name.as_posix(), data)
                hashes[name.as_posix()] = hashlib.sha256(data).hexdigest()
            prior_index = root / "evidence-index.json"
            original_root = read(prior_index)["original_root"] if prior_index.exists() else str(root)
            index = {"version": "t14-delivery-1.0", "kind": kind, "original_root": original_root,
                     "distribution": "private exercise review only" if kind == "review-evidence" else "code and textual results",
                     "files": hashes, "input_pdf_included": False}
            archive.writestr(f"{kind}-index.json" if kind == "code" else "evidence-index.json",
                             json.dumps(index, sort_keys=True, indent=2) + "\n")
        # Read back the actual zip entries and verify bytes, not just the source tree.
        with zipfile.ZipFile(package) as archive:
            for name, expected in hashes.items():
                data = archive.read(name)
                scan_bytes(name, data, secrets)
                if hashlib.sha256(data).hexdigest() != expected:
                    raise ValueError("Archive read-back hash mismatch")
        indexes[kind] = {"file": package.name, "sha256": digest(package), "file_count": len(hashes),
                         "bytes": package.stat().st_size}
    atomic_json(destination / "packages.json", {"packages": indexes, "api_calls": 0,
                                                "note": "Review evidence is not authorized for public redistribution."})
    return indexes


@contextmanager
def offline():
    from unittest.mock import patch

    def blocked(*args, **kwargs):
        raise RuntimeError("Network access is forbidden during offline reproduction")

    with patch.object(socket, "getaddrinfo", blocked), patch.object(socket, "create_connection", blocked), \
            patch.object(socket.socket, "connect", blocked), patch.object(socket.socket, "connect_ex", blocked):
        yield


def verify_index(root, name="evidence-index.json"):
    index = read(root / name)
    for relative, expected in index["files"].items():
        if digest(inside(root, relative)) != expected:
            raise ValueError("Delivery file hash mismatch")
    return index


@contextmanager
def forbid_original_reads(original_root, current_root):
    """Audit actual filesystem reads during relocated replay, not only path strings."""
    old = Path(original_root).resolve()
    active = old != current_root.resolve()

    def audit(event, args):
        if active and event in ("open", "os.listdir", "os.scandir") and args and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).resolve()
            if path.is_relative_to(old):
                raise RuntimeError("Access to original author workspace is forbidden")

    sys.addaudithook(audit)
    try:
        yield active
    finally:
        active = False


def reproduce(root, output, pdf=None):
    root, output = root.resolve(), output.resolve()
    if output.exists():
        raise ValueError("Reproduction output already exists")
    index = verify_index(root)
    verify_index(root, "code-index.json")
    output.mkdir(parents=True)
    with offline(), forbid_original_reads(index["original_root"], root) as original_blocked, \
            relocated_sources(index["original_root"], root):
        verify_truth(root / TRUTH)
        _, expected_eval, _ = verify_evaluation(root / T12)
        _, expected_analysis, _ = verify_error_analysis(root, root / T13)
        evaluated = RunContext(output)
        evaluate_run(root / TRUTH, evaluated, root, include_deepseek=True)
        analyzed = RunContext(output)
        analyze_run(root, root / ATTRIBUTION, root / CHALLENGE, root / T12, analyzed)
        for name in ("summary.json", "lines.jsonl", "confusion.json", "deepseek-appendix.json"):
            if (evaluated.directory / name).read_bytes() != (root / T12 / name).read_bytes():
                raise ValueError(f"Recomputed evaluation differs: {name}")
        for name in ("summary.json", "cases.jsonl"):
            if (analyzed.directory / name).read_bytes() != (root / T13 / name).read_bytes():
                raise ValueError(f"Recomputed error analysis differs: {name}")
        image_result = None
        if pdf is not None:
            from .config import load_config
            from .line_detection import detect_run
            from .preprocess import preprocess_pdf

            if digest(pdf) != PDF_SHA:
                raise ValueError("Reviewer PDF does not match the frozen source")
            config = load_config(root / "configs/default.yaml", {"pdf": pdf, "pages": "9,17", "dpi": 300})
            prepared = RunContext(output)
            preprocess_pdf(config, prepared)
            detected = RunContext(output)
            detection = detect_run(prepared.directory, config, detected)
            selection = read(root / "data/evaluation/selection.json")
            rows = {row["line_id"]: row for row in
                    (json.loads(line) for line in (detected.directory / "pages/page-0017/lines.jsonl").read_bytes().splitlines())}
            for selected in selection["lines"]:
                row = rows[selected["line_id"]]
                if any(row[key] != selected[key] for key in ("crop_box", "content_box", "page_coordinates")):
                    raise ValueError("Recomputed selected line geometry differs")
                if row["crop_sha256"] != selected["image_sha256"]:
                    raise ValueError("Recomputed crop differs from frozen selected crop")
            image_result = {"pages": [p["page_number"] for p in detection["pages"]],
                            "line_counts": [p["line_count"] for p in detection["pages"]],
                            "selected_crop_hashes_and_geometry_match": True}
    report = {"stage": "t14_clean_reproduction", "status": "completed", "api_calls": 0,
              "network_blocked": True, "source_fallback_allowed": False, "input_hashes_verified": True,
              "original_workspace_reads_blocked": original_blocked,
              "python": sys.version, "executable": sys.executable, "platform": platform.platform(),
              "dependencies": {dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions()},
              "evaluation_summary": expected_eval, "analysis_summary": expected_analysis,
              "core_outputs_byte_identical": True, "image_replay": image_result}
    atomic_json(output / "reproduction.json", report)
    # Check immutable delivery files again after all processing.
    verify_index(root)
    return report


def measured_metrics(root):
    truth = [json.loads(line) for line in (root / TRUTH).read_bytes().splitlines()]
    records = [read(root / "data/annotations/versions/ground-truth-v1" / row["source_prediction_file"]) for row in truth]
    records[0] = read(root / "outputs/20261030T185807Z-806667a839b0/results/openai-p0017-l006-2dcc97e9dc05.json")
    seconds = sum(row["elapsed_seconds"] for row in records)
    cost = sum(Decimal(row["cost"]["accounted_this_call_usd"]) for row in records)
    ledger = read(root / ".cache/api-budget.json")
    estimated = sum(Decimal(row["accounted_usd"]) for row in ledger["entries"] if row["state"] == "usage_estimate")
    unknown = sum(Decimal(row["accounted_usd"]) for row in ledger["entries"] if row["state"] != "usage_estimate")
    return {"main_lines": len(records), "main_serial_elapsed_seconds": seconds, "main_estimated_cost_usd": str(cost),
            "mean_seconds_per_line": seconds / len(records), "mean_usd_per_line": str(cost / len(records)),
            "all_usage_estimates_usd": str(estimated), "unknown_reserved_usd": str(unknown),
            "accounted_usd": str(estimated + unknown), "ledger_attempts": len(ledger["entries"])}


def render_reflection(markdown, pdf):
    import pymupdf

    # Markdown is restricted to plain English sections for reliable built-in fonts.
    text = markdown.read_text().replace("**", "")
    text = re.sub(r"(?m)^#{1,3} ", "", text)
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    remaining = page.insert_textbox(pymupdf.Rect(40, 36, 555, 806), text, fontsize=10,
                                    fontname="helv", lineheight=1.18)
    if remaining < 0:
        raise ValueError("Reflection exceeds one page at 10 pt; edit the content")
    document.save(pdf)
    document.close()
    with pymupdf.open(pdf) as rendered:
        if len(rendered) != 1:
            raise ValueError("Reflection must contain exactly one page")
        actual = " ".join(rendered[0].get_text().split())
        expected = " ".join(text.split())
        if actual != expected:
            raise ValueError("Reflection PDF lost text during rendering")
        rendered[0].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).save(pdf.with_name("reflection-preview.png"))
    return {"pages": 1, "font_size": 10, "remaining_height_points": remaining, "text_complete": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "reproduce", "metrics", "reflection", "baseline", "check-baseline"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pdf", type=Path)
    args = parser.parse_args(argv)
    if args.action in ("baseline", "check-baseline"):
        if args.action == "baseline":
            if args.output.exists():
                raise ValueError("Baseline already exists")
            names = evidence_files(args.root.resolve())
            result = {"stage": "t14_source_baseline", "files": {str(p): digest(args.root / p) for p in names}, "api_calls": 0}
            atomic_json(args.output, result)
        else:
            baseline = read(args.output)
            if any(digest(args.root / name) != value for name, value in baseline["files"].items()):
                raise ValueError("Protected source changed")
            result = {"source_files_unchanged": len(baseline["files"]), "api_calls": 0}
    elif args.action == "export":
        result = export_packages(args.root, args.output)
    elif args.action == "reproduce":
        result = reproduce(args.root, args.output, args.pdf)
    elif args.action == "metrics":
        result = measured_metrics(args.root)
        if args.output:
            atomic_json(args.output, result)
    else:
        result = render_reflection(args.root / "reports/reflection.md", args.root / "reports/reflection.pdf")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
