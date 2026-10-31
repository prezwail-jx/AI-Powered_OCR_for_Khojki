import copy
import hashlib
import json
from pathlib import Path

import openai
import pytest
from PIL import Image

from khojki_ocr.cli import main
from khojki_ocr.config import ProviderConfig
from khojki_ocr.providers.base import ImageInput, PreparedRequest
from khojki_ocr.review import build_review, import_drafts, prediction_hash, read_journal, sha, verify_bundle
from khojki_ocr.review_html import escaped, word_context
from khojki_ocr.runtime import RunContext
from khojki_ocr.schemas import OCRPayload, RecognitionResult
from khojki_ocr.storage import canonical_json, content_hash
from khojki_ocr.unicode_rules import validate_text

TEXT = "\U00011224\U0001122D\U0001121C\U00011230\U0001123A ૨"


@pytest.fixture(scope="module")
def references(tmp_path_factory):
    from khojki_ocr.reference import build_reference

    path = tmp_path_factory.mktemp("review-references") / "references"
    build_reference(path)
    return path


@pytest.fixture
def source(tmp_path):
    selection_dir = tmp_path / "selection"
    selection_dir.mkdir()
    rows = []
    for i in range(3):
        path = selection_dir / f"row-{i + 1}.png"
        Image.new("L", (120, 40), 180 + i).save(path)
        rows.append({"line_id": f"row-{i + 1}", "evaluation_order": i + 1, "pdf_page": 17,
                     "detection_reading_order": i + 6, "image_path": path.name, "image_sha256": sha(path.read_bytes()),
                     "crop_box": [10, 20, 130, 60], "crop_review_status": "user_confirmed_complete", "ground_truth": None})
    selection = selection_dir / "selection.json"
    selection.write_text(json.dumps({"selection_id": "test-selection-v1", "line_count": 3, "lines": rows}), encoding="utf-8")
    target = ImageInput.read(selection_dir / rows[0]["image_path"], "TARGET LINE", rows[0]["image_sha256"])
    request = PreparedRequest("row-1", "openai", ProviderConfig(model="gpt-6.1-sol", base_url="https://api.openai.com/v1"), (target,))
    payload = OCRPayload(text=TEXT, uncertain_spans=[{"start": 1, "end": 2, "alternatives": ["\U0001122E"], "reason": "I vs II"}], unreadable=False)
    report = validate_text(TEXT)
    result = RecognitionResult(line_id="row-1", provider="openai", requested_model="gpt-6.1-sol", returned_model="gpt-6.1-sol",
                               cache_key=request.cache_key, status="needs_review", candidate=payload,
                               raw_response_text=json.dumps(payload.model_dump(), ensure_ascii=True), unicode_report=report,
                               codepoints=[item["codepoint"] for item in report["characters"]])
    run = tmp_path / "recognized"
    run.mkdir()
    path = run / "row-1.json"
    path.write_text(canonical_json(result.model_dump(mode="json")), encoding="utf-8")
    manifest = {"stage": "recognition", "dry_run": False, "status": "completed", "selection_sha256": sha(selection.read_bytes()),
                "requests": [{"line_id": "row-1", "provider": "openai", "cache_key": request.cache_key, "request_identity": request.identity()}],
                "results": [{"line_id": "row-1", "provider": "openai", "status": result.status, "file": path.name}]}
    (run / "manifest.json").write_text(canonical_json(manifest))
    return {"selection": selection, "run": run, "result_path": path, "result": result, "manifest": manifest,
            "journal": tmp_path / "human-reviews", "outputs": tmp_path / "outputs"}


def bundle(source, references):
    run = RunContext(source["outputs"])
    manifest = build_review(source["selection"], source["run"], run, references, source["journal"])
    return run.directory, manifest


def rewrite_result(source, result):
    source["result_path"].write_text(canonical_json(result.model_dump(mode="json")))
    source["manifest"]["results"][0]["status"] = result.status
    (source["run"] / "manifest.json").write_text(canonical_json(source["manifest"]))


def edit_template(path, text, **changes):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0].update({"human_text": text, **changes})
    path.write_text(''.join(canonical_json(row) + "\n" for row in rows))


def test_bundle_has_one_candidate_and_missing_rows_not_implicitly_empty(source, references, monkeypatch):
    monkeypatch.setattr(openai, "OpenAI", lambda *a, **kw: pytest.fail("Offline review must never construct a model client"))
    before = {path: path.read_bytes() for path in (source["selection"], source["result_path"])}
    path, manifest = bundle(source, references)
    verified, _, entries = verify_bundle(path)
    assert manifest["api_calls"] == 0 and verified["ground_truth_written"] is False
    assert manifest["line_count"] == 3 and manifest["candidate_count"] == 1 and manifest["not_run_count"] == 2
    assert entries[0].machine_text == TEXT and len(entries[0].uncertain_spans) == 1
    assert entries[0].review_status == "pending" and not entries[0].ground_truth_confirmed
    assert all(entry.machine_text is None and entry.prediction_state == "not_run" for entry in entries[1:])
    assert (path / entries[0].snapshot_path).read_bytes() == before[source["result_path"]]
    assert all(original.read_bytes() == data for original, data in before.items())
    assert not source["journal"].exists()
    html = (path / "index.html").read_text()
    assert f'<div class="candidate glyph">{escaped(TEXT)}</div>' in html
    assert "font/ttf;base64," in html and "<script" not in html
    assert "not image coordinates" in html


def test_explicitly_stopped_request_is_not_misreported_as_lost_result(source, references):
    manifest = source["manifest"]
    first = manifest["requests"][0]
    # Bind a genuine request identity to another approved crop.
    selection = json.loads(source["selection"].read_text())
    row = selection["lines"][1]
    identity = copy.deepcopy(first["request_identity"])
    identity["images"][0]["sha256"] = row["image_sha256"]
    manifest["requests"].append({"line_id": row["line_id"], "provider": "openai",
        "request_identity": identity, "cache_key": content_hash(identity),
        "status": "not_executed", "not_executed_reason": "timeout"})
    (source["run"] / "manifest.json").write_text(canonical_json(manifest))
    path, _ = bundle(source, references)
    _, _, entries = verify_bundle(path)
    assert entries[1].prediction_state == "not_run" and entries[1].machine_text is None
    assert entries[1].warnings == ["Not executed: timeout"]


def test_draft_import_is_versioned_pending_and_does_not_change_predictions(source, references):
    path, _ = bundle(source, references)
    source_bytes = source["result_path"].read_bytes()
    selection_bytes = source["selection"].read_bytes()
    template = path / "review-template.jsonl"
    edit_template(template, TEXT, notes="Checked visually, still a draft")
    # Editing only the template intentionally does NOT invalidate immutable facts.
    verify_bundle(path)
    first_path, first = import_drafts(path, template, "Reviewer A", source["journal"])
    assert first.review_status == "draft" and first.ground_truth_confirmed is False
    assert first.revision == 1 and first.edits[0].unicode_report["valid"]
    assert source["result_path"].read_bytes() == source_bytes and source["selection"].read_bytes() == selection_bytes
    with pytest.raises(ValueError, match="Stale"):
        import_drafts(path, template, "Reviewer A", source["journal"])
    newer, _ = bundle(source, references)
    _, _, entries = verify_bundle(newer)
    assert entries[0].review_status == "draft" and entries[0].machine_text == TEXT
    assert entries[0].recognition_status == "needs_review" and not entries[0].ground_truth_confirmed
    changed = TEXT.replace("\U0001122D", "\U0001122E")
    edit_template(newer / "review-template.jsonl", changed)
    _, second = import_drafts(newer, newer / "review-template.jsonl", "Reviewer B", source["journal"])
    assert second.revision == 2 and second.previous_revision_sha256 == sha(first_path.read_bytes())
    head, _, drafts = read_journal(source["journal"], "test-selection-v1", sha(selection_bytes))
    assert head == 2 and drafts["row-1"]["human_text"] == changed


@pytest.mark.parametrize("changes", [{"ground_truth_confirmed": True}, {"review_status": "confirmed"},
                                     {"prediction_sha256": "0" * 64}, {"base_revision": 99}])
def test_invalid_or_confirmation_edits_are_rejected(source, references, changes):
    path, _ = bundle(source, references)
    template = path / "review-template.jsonl"
    edit_template(template, TEXT, **changes)
    with pytest.raises(ValueError):
        import_drafts(path, template, "Reviewer", source["journal"])
    assert not list(source["journal"].glob("**/revision-*.json"))


def test_unicode_invalid_draft_is_saved_as_draft_not_ground_truth(source, references):
    path, _ = bundle(source, references)
    edit_template(path / "review-template.jsonl", "abc")
    _, revision = import_drafts(path, path / "review-template.jsonl", "Reviewer", source["journal"])
    assert revision.review_status == "draft" and revision.edits[0].unicode_report["valid"] is False
    refreshed, _ = bundle(source, references)
    assert "Draft has Unicode errors" in (refreshed / "index.html").read_text()
    assert not revision.ground_truth_confirmed


def test_cache_hit_telemetry_changes_do_not_orphan_human_draft(source, references):
    path, _ = bundle(source, references)
    edit_template(path / "review-template.jsonl", TEXT)
    import_drafts(path, path / "review-template.jsonl", "Reviewer", source["journal"])
    changed = source["result"].model_copy(update={"cache_hit": True, "elapsed_seconds": 0.0, "cost": {"status": "cache_hit"}})
    assert prediction_hash(changed) == prediction_hash(source["result"])
    rewrite_result(source, changed)
    refreshed, _ = bundle(source, references)
    _, _, entries = verify_bundle(refreshed)
    assert entries[0].review_status == "draft"
    assert entries[0].source_file_sha256 != json.loads((path / "entries.jsonl").read_text().splitlines()[0])["source_file_sha256"]


def test_changed_prediction_preserves_old_revision_but_does_not_apply_it(source, references):
    path, _ = bundle(source, references)
    edit_template(path / "review-template.jsonl", TEXT)
    import_drafts(path, path / "review-template.jsonl", "Reviewer", source["journal"])
    payload = source["result"].candidate.model_copy(update={"text": TEXT.replace("\U0001122D", "\U0001122E")})
    changed = source["result"].model_copy(update={"candidate": payload, "raw_response_text": payload.model_dump_json()})
    rewrite_result(source, changed)
    refreshed, _ = bundle(source, references)
    _, _, entries = verify_bundle(refreshed)
    assert entries[0].review_status == "pending" and entries[0].latest_draft is None
    assert any("another prediction" in message for message in entries[0].warnings)
    assert len(list(source["journal"].glob("**/revision-*.json"))) == 1


@pytest.mark.parametrize("status", ["truncated", "schema_error", "authentication_error", "empty_output"])
def test_failed_recognition_never_promotes_to_success_even_with_human_draft(source, references, status):
    failed = source["result"].model_copy(update={"status": status, "candidate": None, "raw_response_text": "{}", "codepoints": [], "unicode_report": None})
    rewrite_result(source, failed)
    path, _ = bundle(source, references)
    _, _, entries = verify_bundle(path)
    assert entries[0].prediction_state == "recognition_failed" and entries[0].machine_text is None
    edit_template(path / "review-template.jsonl", TEXT)
    import_drafts(path, path / "review-template.jsonl", "Reviewer", source["journal"])
    refreshed, _ = bundle(source, references)
    _, _, entries = verify_bundle(refreshed)
    assert entries[0].recognition_status == status and entries[0].prediction_state == "recognition_failed"
    assert entries[0].review_status == "draft" and not entries[0].ground_truth_confirmed


@pytest.mark.parametrize("missing", ["file", "record"])
def test_prepared_but_missing_result_is_not_labeled_not_run(source, references, missing):
    if missing == "file":
        source["result_path"].unlink()
    else:
        source["manifest"]["results"] = []
        (source["run"] / "manifest.json").write_text(canonical_json(source["manifest"]))
    path, manifest = bundle(source, references)
    _, _, entries = verify_bundle(path)
    assert entries[0].prediction_state == "result_missing"
    assert manifest["not_run_count"] == 2


def test_same_builder_accepts_a_complete_cached_batch(source, references):
    selection = json.loads(source["selection"].read_text())
    for row in selection["lines"][1:]:
        target = ImageInput.read(source["selection"].parent / row["image_path"], "TARGET LINE", row["image_sha256"])
        request = PreparedRequest(row["line_id"], "openai", ProviderConfig(model="gpt-6.1-sol", base_url="https://api.openai.com/v1"), (target,))
        result = source["result"].model_copy(update={"line_id": row["line_id"], "cache_key": request.cache_key,
                                                     "cache_hit": True, "cost": {"status": "cache_hit"}})
        path = source["run"] / f"{row['line_id']}.json"
        path.write_text(canonical_json(result.model_dump(mode="json")))
        source["manifest"]["requests"].append({"line_id": row["line_id"], "provider": "openai", "cache_key": request.cache_key,
                                               "request_identity": request.identity()})
        source["manifest"]["results"].append({"line_id": row["line_id"], "provider": "openai", "status": result.status, "file": path.name})
    (source["run"] / "manifest.json").write_text(canonical_json(source["manifest"]))
    path, manifest = bundle(source, references)
    _, _, entries = verify_bundle(path)
    assert manifest["candidate_count"] == 3 and manifest["not_run_count"] == 0
    assert all(entry.prediction_state == "candidate_available" and entry.review_status == "pending" for entry in entries)
    assert all(not entry.ground_truth_confirmed for entry in entries)


@pytest.mark.parametrize("kind", ["selection_hash", "target_hash", "provider", "duplicate", "raw_candidate_disagrees"])
def test_wrong_source_identity_is_rejected(source, references, kind):
    manifest = source["manifest"]
    if kind == "selection_hash":
        manifest["selection_sha256"] = "wrong"
    elif kind == "target_hash":
        manifest["requests"][0]["request_identity"]["images"][0]["sha256"] = "wrong"
        manifest["requests"][0]["cache_key"] = content_hash(manifest["requests"][0]["request_identity"])
    elif kind == "provider":
        manifest["requests"][0]["provider"] = "deepseek"
    elif kind == "duplicate":
        manifest["results"].append(copy.deepcopy(manifest["results"][0]))
    else:
        result = source["result"].model_copy(update={"raw_response_text": '{"text":"wrong","uncertain_spans":[],"unreadable":false}'})
        rewrite_result(source, result)
    (source["run"] / "manifest.json").write_text(canonical_json(manifest))
    run = RunContext(source["outputs"])
    with pytest.raises(ValueError):
        build_review(source["selection"], source["run"], run, references, source["journal"])
    assert json.loads((run.directory / "manifest.json").read_text())["status"] == "failed"


def test_html_escapes_text_notes_and_preserves_nfc_raw_positions(source, references):
    text = "\U00011208\U00011235\U00011236 <script>alert('x')</script>"
    payload = OCRPayload(text=text, uncertain_spans=[{"start": 1, "end": 2, "alternatives": ["\U0001122D"], "reason": '<img src=x onerror="alert(1)">'}], unreadable=False)
    result = source["result"].model_copy(update={"candidate": payload, "raw_response_text": payload.model_dump_json(),
                                               "codepoints": [f"U+{ord(c):04X}" for c in text]})
    rewrite_result(source, result)
    path, _ = bundle(source, references)
    _, _, entries = verify_bundle(path)
    assert entries[0].uncertain_spans[0].start == 1
    assert entries[0].codepoints[1]["codepoint"] == "U+11235"
    assert entries[0].nfc_text != entries[0].machine_text
    html = (path / "index.html").read_text()
    assert "<script>" not in html and '<img src=x' not in html
    assert "&lt;script&gt;" in html and "[1, 2)" in html
    assert f'<div class="candidate glyph">{escaped(text)}</div>' in html
    assert word_context(TEXT, 1, 2, "\U0001122E") == TEXT[:1] + "\U0001122E" + TEXT[2:4]


def test_snapshot_tampering_and_journal_head_changes_block_import(source, references):
    path, _ = bundle(source, references)
    edit_template(path / "review-template.jsonl", TEXT)
    revision_path, _ = import_drafts(path, path / "review-template.jsonl", "Reviewer", source["journal"])
    current, _ = bundle(source, references)
    edit_template(current / "review-template.jsonl", TEXT)
    data = json.loads(revision_path.read_text())
    data["reviewer"] = "Changed after bundle creation"
    revision_path.write_text(canonical_json(data))
    with pytest.raises(ValueError, match="Stale"):
        import_drafts(current, current / "review-template.jsonl", "Reviewer", source["journal"])
    _, _, entries = verify_bundle(current)
    (current / entries[0].snapshot_path).write_text("{}")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_bundle(current)


def test_blank_template_does_not_create_revision_and_cli_is_offline(source, references, capsys, monkeypatch):
    monkeypatch.setattr(openai, "OpenAI", lambda *a, **kw: pytest.fail("No SDK client"))
    assert main(["build-review", "--selection", str(source["selection"]), "--recognition-run", str(source["run"]),
                 "--references-dir", str(references), "--reviews-dir", str(source["journal"]), "--output-dir", str(source["outputs"])]) == 0
    path = next(source["outputs"].iterdir())
    assert "index.html" in capsys.readouterr().out
    assert main(["review-import", "--bundle", str(path), "--edits", str(path / "review-template.jsonl"),
                 "--reviewer", "Reviewer", "--reviews-dir", str(source["journal"])]) == 1
    assert not source["journal"].exists()
    edit_template(path / "review-template.jsonl", TEXT)
    assert main(["review-import", "--bundle", str(path), "--edits", str(path / "review-template.jsonl"),
                 "--reviewer", "Reviewer", "--reviews-dir", str(source["journal"])]) == 0
    assert "DRAFT" in capsys.readouterr().out
