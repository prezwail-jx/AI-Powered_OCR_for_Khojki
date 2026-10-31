import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from khojki_ocr.delivery import (code_files, export_packages, forbid_original_reads,
                                offline, scan_bytes, verify_index)
from khojki_ocr.relocation import relocated_sources, source_path

ROOT = Path(__file__).resolve().parents[1]


def test_relocation_never_falls_back_to_existing_original(tmp_path):
    original, reviewer = tmp_path / "old", tmp_path / "new"
    original.mkdir()
    reviewer.mkdir()
    (original / "record.json").write_text("original")
    with relocated_sources(original, reviewer):
        with pytest.raises(ValueError, match="missing"):
            source_path(original / "record.json")
        (reviewer / "record.json").write_text("copied")
        assert source_path(original / "record.json").read_text() == "copied"
        with pytest.raises(ValueError, match="escapes"):
            source_path(original / ".." / "outside.json")


def test_original_workspace_read_audit_and_network_block(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    path = old / "hidden"
    path.write_text("old only")
    with forbid_original_reads(old, new):
        with pytest.raises(RuntimeError, match="original author"):
            path.read_bytes()
    assert path.read_text() == "old only"
    import socket
    with offline(), pytest.raises(RuntimeError, match="Network access"):
        socket.create_connection(("example.com", 443))


def test_index_rejects_missing_changed_and_escaping_input(tmp_path):
    (tmp_path / "item").write_text("saved")
    expected = hashlib.sha256(b"saved").hexdigest()
    index = tmp_path / "evidence-index.json"
    index.write_text(json.dumps({"files": {"item": expected}}))
    assert verify_index(tmp_path)["files"] == {"item": expected}
    (tmp_path / "item").write_text("changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_index(tmp_path)
    index.write_text(json.dumps({"files": {"../outside": expected}}))
    with pytest.raises(ValueError, match="escapes"):
        verify_index(tmp_path)


def test_secret_scan_does_not_echo_matches():
    token = "sk-" + "A" * 30
    with pytest.raises(ValueError) as caught:
        scan_bytes("file.json", token.encode())
    assert token not in str(caught.value)
    with pytest.raises(ValueError, match="Credential match"):
        scan_bytes("file.json", b"test-private-value", secrets=("test-private-value",))


def test_export_allowlist_split_and_actual_archive_hashes(tmp_path):
    result = export_packages(ROOT, tmp_path / "delivery")
    assert result["code"]["file_count"] > 0 and result["review-evidence"]["file_count"] > 0
    with zipfile.ZipFile(tmp_path / "delivery/code.zip") as code:
        names = code.namelist()
        assert "README.md" in names and "reports/reflection.pdf" in names
        assert ".env" not in names and not any(name.startswith(("outputs/", ".cache/", "data/")) for name in names)
        assert not any(name.endswith(".pdf") and name != "reports/reflection.pdf" for name in names)
    with zipfile.ZipFile(tmp_path / "delivery/review-evidence.zip") as evidence:
        index = json.loads(evidence.read("evidence-index.json"))
        assert index["distribution"] == "private exercise review only"
        for name, expected in index["files"].items():
            assert hashlib.sha256(evidence.read(name)).hexdigest() == expected


def test_reflection_one_page_complete_and_readable_size():
    import pymupdf
    with pymupdf.open(ROOT / "reports/reflection.pdf") as document:
        assert len(document) == 1
        text = document[0].get_text()
        for heading in ("stage breakdown", "Experiments", "Encoding", "Bottleneck", "Scale", "AI was wrong"):
            assert heading in text
        for block in document[0].get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    assert span["size"] >= 10
                    assert pymupdf.Rect(span["bbox"]) in document[0].rect
