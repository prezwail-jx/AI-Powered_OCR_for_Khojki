import json

import pymupdf
import pytest

from khojki_ocr.cli import main
from khojki_ocr.config import load_config, parse_pages
from khojki_ocr.runtime import RunContext, redact


@pytest.mark.parametrize("value", ["0", "3-1", "1,,2", "one", "-1", "1-2-3", "1-100001"])
def test_invalid_pages(value):
    with pytest.raises(ValueError):
        parse_pages(value)


def test_pages_preserve_order_and_deduplicate():
    assert parse_pages("3,1-3, 5") == [3, 1, 2, 5]


def test_config_overrides_and_rejects_unknown_fields(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("dpi: 350\npages: '2-3'\n", encoding="utf-8")
    assert load_config(path, {"dpi": 400}).dpi == 400
    assert load_config(path).pages == "2-3"
    path.write_text("api_key: should-not-be-accepted\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)


def test_provider_config_is_customizable():
    config = load_config(overrides={"openai": {"model": "gpt-6.1-sol", "base_url": "https://api.openai.com/v1",
                                               "timeout_seconds": 90, "max_output_tokens": 2048}})
    assert config.openai.timeout_seconds == 90
    assert config.openai.max_output_tokens == 2048


def test_secret_url_is_rejected():
    with pytest.raises(ValueError):
        load_config(overrides={"openai": {"model": "test", "base_url": "https://user:secret@example.com"}})


def test_redacts_formatted_and_environment_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "custom-private-value")
    run = RunContext(tmp_path)
    run.error(ValueError("custom-private-value Bearer abc123 api_key=another-private-value sk-example"))
    for path in run.directory.iterdir():
        text = path.read_text(encoding="utf-8")
        for secret in ("custom-private-value", "abc123", "another-private-value", "sk-example"):
            assert secret not in text
    assert "[REDACTED]" in redact("custom-private-value")


def test_prepare_without_keys_and_failed_run_record(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    pdf = tmp_path / "sample.pdf"
    with pymupdf.open() as document:
        document.new_page()
        document.new_page()
        document.save(pdf)
    output = tmp_path / "runs"
    args = ["prepare", "--pdf", str(pdf), "--pages", "1-2", "--output-dir", str(output), "--dpi", "400"]
    assert main(args) == 0
    manifest = json.loads(next(output.glob("*/manifest.json")).read_text())
    assert manifest["selected_pages"] == [1, 2]
    assert manifest["api_calls"] == 0
    assert manifest["ocr_performed"] is False
    assert manifest["config"]["dpi"] == 400
    assert main(args + ["--pages", "3"]) == 1
    assert len(list(output.iterdir())) == 2
    assert json.loads(next(output.glob("*/error.json")).read_text())["status"] == "failed"


def test_invalid_config_does_not_leak_secret(tmp_path, capsys):
    path = tmp_path / "invalid.yaml"
    path.write_text("unexpected: sk-private-example\n", encoding="utf-8")
    assert main(["prepare", "--config", str(path)]) == 2
    assert "sk-private-example" not in capsys.readouterr().err
