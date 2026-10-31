"""Explicit human-confirmation freezing; never inference or automatic labeling."""

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal

from filelock import FileLock
from pydantic import Field, model_validator

from .review import inside, parse_json, verify_bundle
from .schemas import StrictModel
from .storage import atomic_json
from .unicode_rules import UNICODE_VERSION, validate_text


def sha(data):
    return hashlib.sha256(data).hexdigest()


class ConfirmedLine(StrictModel):
    line_id: str
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prediction_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    human_text: str = Field(min_length=1, max_length=10000)
    confirmed: bool

    @model_validator(mode="after")
    def explicitly_confirmed(self):
        if not self.confirmed or not self.human_text.strip():
            raise ValueError("Every truth line must have explicit human confirmation and nonempty text")
        return self


class HumanConfirmation(StrictModel):
    stage: Literal["explicit_human_confirmation"]
    selection_id: str
    selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer: str = Field(min_length=1, max_length=128)
    recorded_at: str
    annotation_duration_seconds: float | None = Field(default=None, ge=0)
    method: Literal["model_assisted_user_visual_review"]
    statements: list[str] = Field(min_length=1)
    lines: list[ConfirmedLine] = Field(min_length=1)

    @model_validator(mode="after")
    def provenance(self):
        if not self.reviewer.strip() or any(not s.strip() for s in self.statements):
            raise ValueError("Reviewer and confirmation statements must be nonblank")
        if datetime.fromisoformat(self.recorded_at.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("Confirmation record time requires a timezone")
        return self


def edit_trace(before, after):
    return [{"operation": tag, "raw_start": i, "raw_end": j, "truth_start": k, "truth_end": l,
             "removed": before[i:j], "inserted": after[k:l],
             "removed_codepoints": [f"U+{ord(c):04X}" for c in before[i:j]],
             "inserted_codepoints": [f"U+{ord(c):04X}" for c in after[k:l]]}
            for tag, i, j, k, l in SequenceMatcher(None, before, after, autojunk=False).get_opcodes() if tag != "equal"]


def freeze_truth(selection_path, bundle, confirmation_path, output, version, *, confirm=False):
    if not confirm:
        raise ValueError("Explicit --confirm is required to freeze human truth")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}", version):
        raise ValueError("Invalid truth version")
    manifest, manifest_sha, entries = verify_bundle(bundle)
    selection_bytes = selection_path.read_bytes()
    if sha(selection_bytes) != manifest["selection_sha256"]:
        raise ValueError("Selection does not match review bundle")
    approval_bytes = confirmation_path.read_bytes()
    approval = HumanConfirmation.model_validate(parse_json(approval_bytes))
    if (approval.selection_id != manifest["selection_id"] or approval.selection_sha256 != manifest["selection_sha256"]
            or approval.review_manifest_sha256 != manifest_sha):
        raise ValueError("Human confirmation selection/review binding mismatch")
    by_id = {line.line_id: line for line in approval.lines}
    if len(by_id) != len(approval.lines) or set(by_id) != {e.line_id for e in entries}:
        raise ValueError("Human confirmation must cover every selected line exactly once")
    materials = {"selection.json": selection_bytes, "confirmation.json": approval_bytes,
                 "source-review-manifest.json": (bundle / "manifest.json").read_bytes()}
    records = []
    for entry in sorted(entries, key=lambda e: e.evaluation_order):
        line = by_id[entry.line_id]
        if (entry.prediction_state != "candidate_available" or entry.machine_text is None or not entry.snapshot_path
                or line.image_sha256 != entry.image_sha256 or line.prediction_sha256 != entry.prediction_sha256):
            raise ValueError("Human confirmation image/prediction identity mismatch or missing candidate")
        report = validate_text(line.human_text)
        if not report["valid"]:
            raise ValueError("Confirmed truth contains invalid Unicode; resolve before freezing")
        source_bytes = inside(bundle, entry.snapshot_path).read_bytes()
        if sha(source_bytes) != entry.source_file_sha256:
            raise ValueError("Source prediction changed during freeze")
        source_name = f"predictions/{entry.line_id}.json"
        materials[source_name] = source_bytes
        records.append({"schema_version": "ground-truth-1.0", "truth_version": version,
            "selection_id": manifest["selection_id"], "selection_sha256": manifest["selection_sha256"],
            "line_id": entry.line_id, "evaluation_order": entry.evaluation_order, "pdf_page": entry.pdf_page,
            "detection_reading_order": entry.detection_reading_order, "image_sha256": entry.image_sha256,
            "prediction_sha256": entry.prediction_sha256, "source_prediction_file": source_name,
            "source_prediction_sha256": entry.source_file_sha256, "machine_text": entry.machine_text,
            "text": line.human_text, "nfc_text": report["nfc_text"], "text_sha256": sha(line.human_text.encode("utf-8")),
            "codepoints": [f"U+{ord(c):04X}" for c in line.human_text], "unicode_report": report,
            "confirmed": True, "ground_truth_status": "confirmed", "reviewer": approval.reviewer,
            "confirmation_recorded_at": approval.recorded_at, "annotation_method": approval.method,
            "human_edits": edit_trace(entry.machine_text, line.human_text)})
    truth_bytes = ''.join(json.dumps(r, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n" for r in records).encode("utf-8")
    materials["ground_truth.jsonl"] = truth_bytes
    output.parent.mkdir(parents=True, exist_ok=True)
    pointer_path = output.with_suffix(".manifest.json")
    archive = output.parent / "versions" / version
    with FileLock(str(output) + ".freeze.lock", timeout=10):
        if output.exists() or pointer_path.exists() or archive.exists():
            raise ValueError("Truth/version already exists; never overwrite frozen truth")
        with tempfile.TemporaryDirectory(prefix=".truth-", dir=output.parent) as staging:
            stage = Path(staging) / "version"
            stage.mkdir()
            for name, data in materials.items():
                path = stage / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            frozen = {"stage": "frozen_ground_truth", "status": "completed", "truth_version": version,
                "selection_id": manifest["selection_id"], "selection_sha256": manifest["selection_sha256"],
                "unicode_version": UNICODE_VERSION, "line_count": len(records), "api_calls": 0,
                "frozen_at": datetime.now(timezone.utc).isoformat(), "reviewer": approval.reviewer,
                "annotation_method": approval.method, "annotation_duration_seconds": approval.annotation_duration_seconds,
                "modified_line_count": sum(bool(r["human_edits"]) for r in records),
                "ground_truth_file": "ground_truth.jsonl", "files": {name: sha(data) for name, data in materials.items()},
                "note": "Explicit user-confirmed model-assisted reference, not blind expert transcription. Freeze time is not annotation duration. Future corrections require a new version and reevaluation."}
            atomic_json(stage / "manifest.json", frozen)
            archive.parent.mkdir(parents=True, exist_ok=True)
            os.rename(stage, archive)
            pending = Path(staging) / "ground_truth.jsonl"
            pending.write_bytes(truth_bytes)
            os.replace(pending, output)
            atomic_json(pointer_path, {"stage": "active_ground_truth", "truth_version": version,
                "selection_id": manifest["selection_id"], "line_count": len(records),
                "archive": str(archive.relative_to(output.parent)), "archive_manifest_sha256": sha((archive / "manifest.json").read_bytes()),
                "ground_truth_sha256": sha(truth_bytes)})
    return verify_truth(output)


def verify_truth(output):
    pointer = parse_json(output.with_suffix(".manifest.json").read_bytes())
    if pointer.get("stage") != "active_ground_truth":
        raise ValueError("Not an active frozen truth pointer")
    archive = inside(output.parent, pointer["archive"])
    raw = (archive / "manifest.json").read_bytes()
    if sha(raw) != pointer["archive_manifest_sha256"]:
        raise ValueError("Truth archive manifest hash mismatch")
    manifest = parse_json(raw)
    if manifest.get("stage") != "frozen_ground_truth" or manifest.get("status") != "completed":
        raise ValueError("Not a completed frozen truth version")
    if not {"ground_truth.jsonl", "confirmation.json", "selection.json", "source-review-manifest.json"}.issubset(manifest["files"]):
        raise ValueError("Truth source declarations missing")
    for name, digest in manifest["files"].items():
        if sha(inside(archive, name).read_bytes()) != digest:
            raise ValueError("Truth archive file hash mismatch")
    data = output.read_bytes()
    if sha(data) != pointer["ground_truth_sha256"] or data != (archive / "ground_truth.jsonl").read_bytes():
        raise ValueError("Active truth file hash mismatch")
    records = [parse_json(line) for line in data.splitlines()]
    selection = parse_json((archive / "selection.json").read_bytes())
    if (manifest["truth_version"] != pointer["truth_version"] or manifest["selection_id"] != pointer["selection_id"]
            or selection["selection_id"] != manifest["selection_id"]
            or sha((archive / "selection.json").read_bytes()) != manifest["selection_sha256"]
            or len(records) != selection["line_count"] or len(records) != manifest["line_count"] or len(records) != pointer["line_count"]
            or [r["line_id"] for r in records] != [r["line_id"] for r in selection["lines"]]):
        raise ValueError("Truth version/count/selection mismatch")
    for record in records:
        if (record["confirmed"] is not True or record["truth_version"] != manifest["truth_version"]
                or sha(record["text"].encode("utf-8")) != record["text_sha256"]
                or not validate_text(record["text"])["valid"]):
            raise ValueError("Truth confirmation/text invalid")
    return manifest, records
