"""The default test suite must never reach a network service."""

import socket
import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def relocated_review_evidence(tmp_path):
    """A reviewer tree must not read provenance from the author's workspace."""
    from khojki_ocr.relocation import relocated_sources

    root = Path(__file__).resolve().parents[1]
    index = root / "evidence-index.json"
    if index.exists():
        original = json.loads(index.read_bytes())["original_root"]
        with relocated_sources(original, root, allowed_roots=(tmp_path,)):
            yield
    else:
        yield


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Network access is forbidden in offline tests; inject a mock transport")

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
