"""Read-only T15 acceptance checks over frozen results and delivery archives."""

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

import pymupdf

from khojki_ocr.delivery import (T12, T13, TRUTH, digest, inside, measured_metrics,
                                offline, read, scan_bytes)
from khojki_ocr.error_analysis import verify_error_analysis
from khojki_ocr.evaluation import verify_evaluation
from khojki_ocr.ground_truth import verify_truth
from khojki_ocr.schemas import RecognitionResult
from khojki_ocr.storage import atomic_json
from khojki_ocr.unicode_rules import validate_text


def check(root, packages, output):
    if output.exists():
        raise ValueError("Acceptance record already exists; choose a new output")
    with offline():
        truth_manifest, truth = verify_truth(root / TRUTH)
        _, evaluation, evaluated_lines = verify_evaluation(root / T12)
        _, analysis, cases = verify_error_analysis(root, root / T13)
        batch = root / "outputs/20261030T210414Z-23bc6581d98c"
        batch_manifest = read(batch / "manifest.json")
        for name, expected in batch_manifest["exports"]["files"].items():
            if digest(inside(batch, name)) != expected:
                raise ValueError("Original OCR export hash mismatch")
        for row in truth:
            result = RecognitionResult.model_validate(read(root / "data/annotations/versions/ground-truth-v1" / row["source_prediction_file"]))
            text = result.candidate.text
            exported = (batch / "transcriptions" / f"openai-{row['line_id']}.txt").read_bytes().decode("utf-8", errors="strict")
            if (exported != text or result.codepoints != [f"U+{ord(ch):04X}" for ch in text]
                    or not validate_text(text)["valid"] or not validate_text(row["text"])["valid"]):
                raise ValueError("UTF-8, Unicode or original prediction export mismatch")
        baseline = read(root / "reports/t14-source-baseline.json")
        for name, expected in baseline["files"].items():
            if digest(root / name) != expected:
                raise ValueError("Protected evidence baseline mismatch")
        package_record = read(packages / "packages.json")
        inspected = {}
        for kind, record in package_record["packages"].items():
            path = inside(packages, record["file"])
            if digest(path) != record["sha256"] or path.stat().st_size != record["bytes"]:
                raise ValueError("Delivery zip digest or size mismatch")
            with zipfile.ZipFile(path) as archive:
                index_name = "code-index.json" if kind == "code" else "evidence-index.json"
                index = json.loads(archive.read(index_name))
                names = archive.namelist()
                if len(set(names)) != len(names) or set(names) != set(index["files"]) | {index_name}:
                    raise ValueError("Delivery archive has duplicate or undeclared entries")
                if len(index["files"]) != record["file_count"]:
                    raise ValueError("Delivery file count mismatch")
                for name, expected in index["files"].items():
                    inside(root, name)
                    data = archive.read(name)
                    if hashlib.sha256(data).hexdigest() != expected:
                        raise ValueError("Delivery zip-entry hash mismatch")
                    if Path(name).name == ".env" or (name.endswith(".pdf") and name != "reports/reflection.pdf"):
                        raise ValueError("Input PDF or private environment present in zip")
                    scan_bytes(name, data)
                if kind == "code" and any(name.startswith(("data/", "outputs/", ".cache/")) for name in names):
                    raise ValueError("Private scan evidence present in code package")
                inspected[kind] = {"sha256": record["sha256"], "files": len(index["files"]), "verified": True}
        logs = [path for path in (root / "outputs").rglob("*")
                if path.is_file() and path.name in ("run.log", "error.json")]
        for path in logs:
            scan_bytes(str(path.relative_to(root)), path.read_bytes())
        with pymupdf.open(root / "reports/reflection.pdf") as pdf:
            if len(pdf) != 1:
                raise ValueError("Reflection is not one page")
            extracted = " ".join(pdf[0].get_text().split())
            expected = (root / "reports/reflection.md").read_text().replace("**", "")
            expected = re.sub(r"(?m)^#{1,3} ", "", expected)
            if extracted != " ".join(expected.split()):
                raise ValueError("Reflection PDF lost source text")
        clean = read(root / "reports/t14-clean-replay.json")
        if not (clean["core_outputs_byte_identical"] and clean["original_workspace_reads_blocked"]
                and clean["network_blocked"] and clean["image_replay"]["selected_crop_hashes_and_geometry_match"]):
            raise ValueError("Clean replay evidence is incomplete")
        metrics = measured_metrics(root)
        if float(metrics["accounted_usd"]) > 15:
            raise ValueError("Historical accounted budget exceeds cap")
        report = {"stage": "t15_local_acceptance", "status": "technical_checks_passed", "api_calls": 0,
                  "new_cost_usd": "0", "truth_version": truth_manifest["truth_version"],
                  "line_count": len(truth), "utf8_unicode_exports_verified": len(truth),
                  "evaluation": evaluation, "attribution": analysis, "case_count": len(cases),
                  "metrics": metrics, "protected_sources_unchanged": len(baseline["files"]),
                  "archives": inspected, "historical_logs_scanned": len(logs),
                  "reflection_pages": 1, "clean_replay_verified": True,
                  "python": sys.version, "isolated_venv": sys.prefix != sys.base_prefix,
                  "source_records": {str(name): digest(root / name) for name in
                                     (TRUTH, T12 / "manifest.json", T13 / "manifest.json", Path(".cache/api-budget.json"))},
                  "github_submission_completed": False,
                  "note": "Technical acceptance is distinct from user sign-off and GitHub publication."}
        atomic_json(output, report)
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--packages", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = check(args.root.resolve(), args.packages.resolve(), args.output)
    print(json.dumps({"status": result["status"], "line_count": result["line_count"],
                      "protected_sources_unchanged": result["protected_sources_unchanged"],
                      "historical_logs_scanned": result["historical_logs_scanned"], "api_calls": 0,
                      "verification_file": str(args.output)}, indent=2))
