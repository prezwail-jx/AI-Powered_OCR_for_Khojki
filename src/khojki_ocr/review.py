"""Offline review bundles and append-only human DRAFT revisions. No inference."""

import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock
from PIL import Image

from .review_html import render_html
from .review_schemas import BlankTemplateRow, DraftEdit, DraftRevision, REVIEW_VERSION, ReviewEntry, SavedDraftEdit
from .schemas import OCRPayload, RecognitionResult
from .storage import atomic_json, canonical_json, content_hash
from .unicode_rules import UNICODE_VERSION, asset_bytes, validate_text

DEFAULT_REFERENCES = Path("outputs/references-v1")
DEFAULT_REVIEWS = Path("data/annotations/reviews")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Review artifact path escapes its directory")
    return path


def parse_json(value):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate review JSON field")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("Non-finite review JSON constant")

    return json.loads(value, object_pairs_hook=pairs, parse_constant=constant)


def prediction_hash(result: RecognitionResult):
    # Runtime cost/cache-hit/elapsed fields are NOT machine prediction identity.
    # A pilot and a later cached batch retain the same review binding.
    return content_hash({"version": "prediction-1.0", "provider": result.provider,
                         "requested_model": result.requested_model, "returned_model": result.returned_model,
                         "cache_key": result.cache_key, "raw_response_text": result.raw_response_text,
                         "candidate": result.candidate.model_dump(mode="json") if result.candidate else None})


def journal_directory(root, selection_id):
    if not isinstance(selection_id, str) or not ID.fullmatch(selection_id):
        raise ValueError("Invalid selection identifier")
    return root / selection_id


def read_journal(root: Path, selection_id: str, selection_sha256: str):
    directory = journal_directory(root, selection_id)
    previous = None
    revisions, drafts = [], {}
    for index, path in enumerate(sorted(directory.glob("revision-*.json")), 1):
        data = path.read_bytes()
        revision = DraftRevision.model_validate(parse_json(data))
        if (path.name != f"revision-{index:06}.json" or revision.revision != index or revision.base_revision != index - 1
                or revision.previous_revision_sha256 != previous or revision.selection_id != selection_id
                or revision.selection_sha256 != selection_sha256 or not revision.edits):
            raise ValueError("Review journal integrity, sequence or selection mismatch")
        for edit in revision.edits:
            if edit.base_revision != index - 1:
                raise ValueError("Review edit revision mismatch")
            drafts[edit.line_id] = {**edit.model_dump(mode="json"), "reviewer": revision.reviewer,
                                    "revision": revision.revision, "created_at": revision.created_at}
        revisions.append(revision)
        previous = sha(data)
    return len(revisions), previous, drafts


def _selection(path):
    data = path.read_bytes()
    selection = parse_json(data)
    journal_directory(Path("."), selection["selection_id"])
    records = selection["lines"]
    if not records or len(records) != selection["line_count"] or len({r["line_id"] for r in records}) != len(records):
        raise ValueError("Selection count/identity mismatch")
    for record in records:
        if not isinstance(record["line_id"], str) or not ID.fullmatch(record["line_id"]) or record["crop_review_status"] != "user_confirmed_complete":
            raise ValueError("Invalid or unapproved review sample")
    return selection, data


def _recognition_sources(directory, selection, selection_sha256):
    manifest_path = directory / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = parse_json(manifest_bytes)
    if manifest.get("stage") != "recognition" or manifest.get("dry_run") is not False:
        raise ValueError("Review requires an executed recognition run, not dry-run/diagnosis")
    if manifest["selection_sha256"] != selection_sha256:
        raise ValueError("Recognition run does not match frozen selection")
    selected = {r["line_id"]: r for r in selection["lines"]}
    requests, results = {}, {}
    for request in manifest["requests"]:
        line_id = request["line_id"]
        if request["provider"] != "openai":
            raise ValueError("Review accepts active OpenAI-only runs, not DeepSeek results")
        if line_id not in selected or line_id in requests:
            raise ValueError("Unknown or duplicate line in recognition requests")
        identity = request["request_identity"]
        targets = [image for image in identity["images"] if image["label"] == "TARGET LINE"]
        if (content_hash(identity) != request["cache_key"] or identity["provider"] != "openai"
                or identity["settings"]["model"] != "gpt-6.1-sol" or len(targets) != 1
                or targets[0]["sha256"] != selected[line_id]["image_sha256"]):
            raise ValueError("Request identity/target image mismatch")
        requests[line_id] = request
    for record in manifest["results"]:
        line_id = record["line_id"]
        if record["provider"] != "openai" or line_id not in requests or line_id in results:
            raise ValueError("Unknown, duplicate or inactive-provider result")
        path = inside(directory, record["file"])
        if not path.is_file():
            results[line_id] = (None, None, "missing_declared_result")
            continue
        raw = path.read_bytes()
        result = RecognitionResult.model_validate(parse_json(raw))
        if (result.line_id != line_id or result.provider != "openai" or result.requested_model != "gpt-6.1-sol"
                or result.cache_key != requests[line_id]["cache_key"] or result.status != record["status"]):
            raise ValueError("Result does not match recognition manifest/request")
        if result.status in ("succeeded", "needs_review"):
            if result.candidate is None or not result.candidate.text.strip():
                raise ValueError("Successful source has no nonempty candidate")
            # Validate consistency without repairing/trimming model JSON.
            payload = OCRPayload.model_validate(parse_json(result.raw_response_text))
            if payload != result.candidate:
                raise ValueError("Raw response and extracted candidate disagree")
        results[line_id] = (result, raw, str(path))
    return manifest, manifest_bytes, requests, results


def _copy_png(source, destination, expected, expected_size=None):
    data = source.read_bytes()
    if sha(data) != expected:
        raise ValueError("Review image hash mismatch")
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "PNG" or (expected_size is not None and image.size != expected_size):
            raise ValueError("Review image format/dimensions mismatch")
        image.verify()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)


def _copy_references(source, bundle):
    raw = (source / "manifest.json").read_bytes()
    manifest = parse_json(raw)
    if (manifest["unicode_version"] != UNICODE_VERSION
            or manifest["policy_sha256"] != sha(asset_bytes("unicode", "transcription_rules.json"))
            or manifest["characters_sha256"] != sha(asset_bytes("unicode", "characters.json"))):
        raise ValueError("Reference Unicode data/policy mismatch")
    destination = bundle / "assets/references"
    destination.mkdir(parents=True, exist_ok=False)
    names = []
    for record in manifest["sheets"]:
        name = record["file"]
        if Path(name).name != name or not name.endswith(".png") or name in names:
            raise ValueError("Invalid or duplicate reference name")
        _copy_png(inside(source, name), destination / name, record["sha256"])
        names.append(name)
    (destination / "manifest.json").write_bytes(raw)
    licenses = bundle / "assets/licenses"
    licenses.mkdir()
    for name in ("SerifKhojki-OFL.txt", "Gujarati-OFL.txt"):
        (licenses / name).write_bytes(asset_bytes("fonts", name))
    (licenses / "Unicode-LICENSE.txt").write_bytes(asset_bytes("unicode", "Unicode-LICENSE.txt"))
    return names


def build_review(selection_path: Path, recognition_run: Path, run, references_dir=Path("outputs/references-v1"), reviews_dir=DEFAULT_REVIEWS):
    bundle = run.directory
    manifest_path = bundle / "manifest.json"
    manifest = {"schema_version": REVIEW_VERSION, "stage": "offline_review", "status": "running", "api_calls": 0,
                "ground_truth_written": False, "run_id": run.run_id}
    atomic_json(manifest_path, manifest)
    try:
        selection, selection_bytes = _selection(selection_path)
        selection_sha = sha(selection_bytes)
        source, source_bytes, requests, results = _recognition_sources(recognition_run, selection, selection_sha)
        head, head_sha, drafts = read_journal(reviews_dir, selection["selection_id"], selection_sha)
        snapshots = bundle / "snapshots"
        snapshots.mkdir()
        (snapshots / "selection.json").write_bytes(selection_bytes)
        (snapshots / "recognition-manifest.json").write_bytes(source_bytes)
        manifest.update({"selection_id": selection["selection_id"], "selection_sha256": selection_sha,
                         "recognition_manifest_sha256": sha(source_bytes), "source_recognition_run": str(recognition_run.resolve()),
                         "review_head": head, "review_head_sha256": head_sha, "reviews_dir": str(reviews_dir.resolve()),
                         "unicode_version": UNICODE_VERSION, "entries": "entries.jsonl",
                         "editable_files": ["review-template.jsonl"]})
        entries = []
        template = []
        for record in selection["lines"]:
            line_id = record["line_id"]
            image_path = f"assets/crops/{line_id}.png"
            x0, y0, x1, y1 = record["crop_box"]
            _copy_png(inside(selection_path.parent, record["image_path"]), bundle / image_path,
                      record["image_sha256"], (x1 - x0, y1 - y0))
            entry = ReviewEntry(line_id=line_id, evaluation_order=record["evaluation_order"], pdf_page=record["pdf_page"],
                                detection_reading_order=record["detection_reading_order"], image_path=image_path,
                                image_sha256=record["image_sha256"], prediction_state="not_run", base_revision=head)
            if line_id in results:
                result, raw, source_path = results[line_id]
                if result is None:
                    entry.prediction_state = "result_missing"
                    entry.warnings.append(source_path)
                else:
                    entry.snapshot_path = f"snapshots/{line_id}.json"
                    (bundle / entry.snapshot_path).write_bytes(raw)
                    entry.source_file_sha256 = sha(raw)
                    entry.prediction_sha256 = prediction_hash(result)
                    entry.recognition_status = result.status
                    entry.requested_model, entry.returned_model = result.requested_model, result.returned_model
                    entry.warnings.extend(result.warnings)
                    entry.prediction_state = "candidate_available" if result.status in ("succeeded", "needs_review") else "recognition_failed"
                    if result.candidate is not None:
                        entry.machine_text = result.candidate.text
                        entry.uncertain_spans = result.candidate.uncertain_spans
                        entry.unicode_report = validate_text(entry.machine_text)
                        entry.nfc_text = entry.unicode_report["nfc_text"]
                        entry.codepoints = entry.unicode_report["characters"]
                        computed = [item["codepoint"] for item in entry.codepoints]
                        if computed != result.codepoints:
                            entry.warnings.append("reported_codepoints_mismatch; display recomputed from raw text")
                        if result.status == "succeeded" and (entry.unicode_report["needs_review"] or entry.uncertain_spans or result.candidate.unreadable):
                            entry.warnings.append("source_success_does_not_establish_validity_or_accuracy")
            elif line_id in requests:
                request = requests[line_id]
                if request.get("status") == "not_executed" and request.get("not_executed_reason"):
                    entry.warnings.append("Not executed: " + request["not_executed_reason"])
                else:
                    entry.prediction_state = "result_missing"
                    entry.warnings.append("Request was prepared but no result record exists; dispatch status cannot be assumed")
            if line_id in drafts:
                if drafts[line_id]["prediction_sha256"] == entry.prediction_sha256:
                    entry.review_status, entry.latest_draft = "draft", drafts[line_id]
                else:
                    entry.warnings.append("Existing draft belongs to another prediction; history preserved")
            entries.append(entry)
            template.append({"line_id": line_id, "prediction_sha256": entry.prediction_sha256,
                             "base_revision": head, "human_text": None, "notes": ""})
        names = _copy_references(references_dir, bundle)
        (bundle / "entries.jsonl").write_text(''.join(canonical_json(entry.model_dump(mode="json")) + "\n" for entry in entries), encoding="utf-8")
        (bundle / "review-template.jsonl").write_text(''.join(canonical_json(row) + "\n" for row in template), encoding="utf-8")
        (bundle / "index.html").write_text(render_html(entries, selection["selection_id"], names), encoding="utf-8")
        files = {str(path.relative_to(bundle)): sha(path.read_bytes()) for path in bundle.rglob("*") if path.is_file()
                 and path.name not in ("manifest.json", "run.log", "review-template.jsonl")}
        # Include nested source/reference manifests, excluding ONLY the root manifest.
        for path in (snapshots / "selection.json", snapshots / "recognition-manifest.json", bundle / "assets/references/manifest.json"):
            files[str(path.relative_to(bundle))] = sha(path.read_bytes())
        manifest.update({"status": "completed", "line_count": len(entries),
                         "candidate_count": sum(e.prediction_state == "candidate_available" for e in entries),
                         "not_run_count": sum(e.prediction_state == "not_run" for e in entries), "files": files,
                         "note": "Immutable facts are hashed. review-template.jsonl is intentionally editable. Human status is pending/draft only."})
        atomic_json(manifest_path, manifest)
        run.log(f"Offline review created: {len(entries)} selected rows, {manifest['candidate_count']} candidates; no inference")
        return manifest
    except Exception:
        manifest["status"] = "failed"
        atomic_json(manifest_path, manifest)
        raise


def verify_bundle(bundle: Path):
    manifest_bytes = (bundle / "manifest.json").read_bytes()
    manifest = parse_json(manifest_bytes)
    if manifest.get("schema_version") != REVIEW_VERSION or manifest.get("stage") != "offline_review" or manifest.get("status") != "completed":
        raise ValueError("Not a completed supported review bundle")
    required = {"entries.jsonl", "snapshots/selection.json", "snapshots/recognition-manifest.json", "index.html"}
    if not required.issubset(manifest["files"]):
        raise ValueError("Review bundle is missing immutable file declarations")
    for name, expected in manifest["files"].items():
        if sha(inside(bundle, name).read_bytes()) != expected:
            raise ValueError("Review bundle immutable-file hash mismatch")
    selection, raw_selection = _selection(bundle / "snapshots/selection.json")
    if sha(raw_selection) != manifest["selection_sha256"] or selection["selection_id"] != manifest["selection_id"]:
        raise ValueError("Review bundle selection mismatch")
    entries = [ReviewEntry.model_validate(parse_json(line)) for line in inside(bundle, manifest["entries"]).read_text(encoding="utf-8").splitlines()]
    selected = {r["line_id"]: r for r in selection["lines"]}
    if len(entries) != len(selected) or {e.line_id for e in entries} != set(selected):
        raise ValueError("Review entries do not match frozen selection")
    for entry in entries:
        if entry.image_sha256 != selected[entry.line_id]["image_sha256"] or sha(inside(bundle, entry.image_path).read_bytes()) != entry.image_sha256:
            raise ValueError("Review entry image mismatch")
        if entry.snapshot_path is not None:
            data = inside(bundle, entry.snapshot_path).read_bytes()
            result = RecognitionResult.model_validate(parse_json(data))
            if (sha(data) != entry.source_file_sha256 or result.line_id != entry.line_id or result.provider != "openai"
                    or prediction_hash(result) != entry.prediction_sha256):
                raise ValueError("Prediction snapshot identity mismatch")
        elif entry.prediction_sha256 is not None:
            raise ValueError("Prediction hash has no frozen snapshot")
    return manifest, sha(manifest_bytes), entries


def import_drafts(bundle: Path, edits_path: Path, reviewer: str, reviews_dir=DEFAULT_REVIEWS):
    if not reviewer.strip() or len(reviewer) > 128:
        raise ValueError("Reviewer must be a nonblank name, at most 128 characters")
    manifest, manifest_sha, entries = verify_bundle(bundle)
    by_id = {entry.line_id: entry for entry in entries}
    edits = []
    seen = set()
    for line in edits_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = parse_json(line)
        if not isinstance(raw, dict):
            raise ValueError("Each draft line must be a JSON object")
        # Only untouched, schema-correct blank template rows may be skipped.
        if raw.get("human_text") is None:
            blank = BlankTemplateRow.model_validate(raw)
            if blank.line_id not in by_id:
                raise ValueError("Malformed blank draft row")
            entry = by_id[blank.line_id]
            if blank.prediction_sha256 != entry.prediction_sha256 or blank.base_revision != manifest["review_head"]:
                raise ValueError("Blank draft template has stale identity/revision")
            continue
        edit = DraftEdit.model_validate(raw)
        if edit.line_id in seen or edit.line_id not in by_id:
            raise ValueError("Unknown or duplicate edited line")
        seen.add(edit.line_id)
        source = by_id[edit.line_id]
        if not source.prediction_sha256 or edit.prediction_sha256 != source.prediction_sha256:
            raise ValueError("Draft does not match a frozen machine prediction")
        if edit.base_revision != manifest["review_head"]:
            raise ValueError("Draft base revision does not match bundle")
        edits.append(SavedDraftEdit(**edit.model_dump(), unicode_report=validate_text(edit.human_text)))
    if not edits:
        raise ValueError("No proposed human edits; no revision created")
    directory = journal_directory(reviews_dir, manifest["selection_id"])
    directory.mkdir(parents=True, exist_ok=True)
    with FileLock(str(directory / ".journal.lock"), timeout=10):
        head, previous, _ = read_journal(reviews_dir, manifest["selection_id"], manifest["selection_sha256"])
        if head != manifest["review_head"] or previous != manifest["review_head_sha256"]:
            raise ValueError("Stale review bundle; rebuild from latest revision before importing")
        revision = DraftRevision(selection_id=manifest["selection_id"], selection_sha256=manifest["selection_sha256"],
                                 revision=head + 1, base_revision=head, previous_revision_sha256=previous,
                                 bundle_manifest_sha256=manifest_sha, reviewer=reviewer.strip(),
                                 created_at=datetime.now(timezone.utc).isoformat(), edits=edits)
        path = directory / f"revision-{head + 1:06}.json"
        if path.exists():
            raise ValueError("Revision already exists; refusing overwrite")
        atomic_json(path, revision.model_dump(mode="json"))
    return path, revision
