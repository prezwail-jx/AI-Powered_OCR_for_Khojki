"""Lossless machine-only batch exports, including failed/unexecuted rows."""

import hashlib
from pathlib import Path

from .schemas import RecognitionResult
from .storage import atomic_json, canonical_json
from .unicode_rules import validate_text


def export_results(directory: Path, manifest):
    files, rows = {}, []
    records = {(r["line_id"], r["provider"]): r for r in manifest["results"]}

    def save(name, text):
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()

    for request in manifest["requests"]:
        key = (request["line_id"], request["provider"])
        record = records.get(key)
        result = RecognitionResult.model_validate_json((directory / record["file"]).read_bytes()) if record else None
        if result and (result.line_id, result.provider, result.cache_key) != (*key, request["cache_key"]):
            raise ValueError("Batch export result/request mismatch")
        text = result.candidate.text if result and result.candidate is not None else None
        report = validate_text(text) if text is not None else None
        row = {"line_id": key[0], "provider": key[1], "cache_key": request["cache_key"],
               "status": result.status if result else "not_executed", "not_executed_reason": request.get("not_executed_reason"),
               "source_file": record["file"] if record else None,
               "source_sha256": hashlib.sha256((directory / record["file"]).read_bytes()).hexdigest() if record else None,
               "cache_hit": result.cache_hit if result else False, "machine_text": text,
               "nfc_text": report["nfc_text"] if report else None,
               "codepoints": report["characters"] if report else [], "unicode_report": report,
               "uncertain_spans": [s.model_dump() for s in result.candidate.uncertain_spans] if result and result.candidate else [],
               "warnings": result.warnings if result else [], "cost": result.cost if result else {"status": "not_called"},
               "human_status": "pending", "ground_truth": None, "ground_truth_confirmed": False}
        if text is not None:
            stem = f"transcriptions/{key[1]}-{key[0]}"
            row.update({"text_file": stem + ".txt", "nfc_file": stem + ".nfc.txt"})
            # No terminal newline or whitespace edits to the model candidate.
            save(row["text_file"], text)
            save(row["nfc_file"], report["nfc_text"])
        rows.append(row)
    save("predictions.jsonl", "".join(canonical_json(row) + "\n" for row in rows))
    atomic_json(directory / "cost-summary.json", {
        "api_calls": manifest["api_calls"], "cache_only": manifest["cache_only"],
        "budget_before": manifest.get("budget_before"), "budget_after": manifest.get("budget"),
        "note": "Local conservative usage estimates/reservations, not confirmed invoices; historical unknown charges remain held.",
        "attempts": [{"line_id": row["line_id"], "provider": row["provider"], "cost": row["cost"]} for row in rows]})
    files["cost-summary.json"] = hashlib.sha256((directory / "cost-summary.json").read_bytes()).hexdigest()
    return {"rows": len(rows), "predictions": "predictions.jsonl", "files": files}
