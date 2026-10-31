import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import openai
import pytest
from PIL import Image

from khojki_ocr.config import load_config
from khojki_ocr.deepseek_diagnosis import (
    BASELINE_OUTPUT, SYNTHETIC_TEXT, TARGET_ONLY_PROMPT, build_case,
    diagnostic_metrics, edit_distance, run_case,
)
from khojki_ocr.providers.deepseek import DeepSeekAdapter
from khojki_ocr.recognition import prepare_requests
from khojki_ocr.runtime import RunContext
from khojki_ocr.schemas import ProviderResponse, TokenUsage
from khojki_ocr.unicode_rules import asset_bytes, validate_text

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def inputs(tmp_path):
    cfg = load_config(ROOT / "configs/smoke.yaml")
    records = []
    for index, value in enumerate((180, 170)):
        buffer = io.BytesIO()
        Image.new("L", (64, 32), value).save(buffer, format="PNG")
        path = tmp_path / f"target-{index}.png"
        path.write_bytes(buffer.getvalue())
        records.append({"line_id": f"line-{index}", "image_path": path.name,
                        "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "crop_review_status": "user_confirmed_complete", "ground_truth": None})
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({"line_count": 2, "lines": records}))
    references = tmp_path / "references"
    references.mkdir()
    sheets = []
    for index, name in enumerate(cfg.recognition.reference_files):
        path = references / name
        Image.new("RGB", (64, 32), (100 + index, 100, 100)).save(path)
        sheets.append({"file": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    (references / "manifest.json").write_text(json.dumps({"unicode_version": "17.0.0",
        "policy_sha256": hashlib.sha256(asset_bytes("unicode", "transcription_rules.json")).hexdigest(),
        "characters_sha256": hashlib.sha256(asset_bytes("unicode", "characters.json")).hexdigest(), "sheets": sheets}))
    cfg.recognition.reference_dir = references
    cfg.recognition.cache_dir = tmp_path / "cache"
    cfg.recognition.ledger_path = tmp_path / "ledger.json"
    return cfg, selection


def test_variants_isolate_payloads_and_do_not_modify_main_config(tmp_path, inputs):
    cfg, selection = inputs
    original = cfg.model_dump(mode="json")
    baseline = prepare_requests(selection, cfg, "deepseek", 1)[0]
    cases = {name: build_case(name, cfg, selection, tmp_path / name) for name in ("D1", "D1b", "D2", "D3")}
    assert [len(cases[name].request.images) for name in cases] == [1, 1, 2, 9]
    assert cases["D1"].request.system_prompt == cases["D1b"].request.system_prompt == TARGET_ONLY_PROMPT
    assert cases["D2"].request.system_prompt == cases["D3"].request.system_prompt == baseline.system_prompt
    assert cases["D3"].request.images == (*baseline.images[1:], baseline.images[0])
    assert cases["D2"].request.images[1].label.startswith("REFERENCE CHART: marks.png ")
    assert cfg.model_dump(mode="json") == original
    assert len({baseline.cache_key, *(case.request.cache_key for case in cases.values())}) == 5
    assert cases["D1"].metadata["confound"]


def test_synthetic_oracle_is_rendered_not_sent_as_text_and_is_deterministic(tmp_path, inputs):
    cfg, selection = inputs
    first = build_case("D1b", cfg, selection, tmp_path / "one")
    second = build_case("D1b", cfg, selection, tmp_path / "two")
    assert first.request.images[0].sha256 == second.request.images[0].sha256
    assert first.expected == SYNTHETIC_TEXT and validate_text(SYNTHETIC_TEXT)["valid"]
    assert SYNTHETIC_TEXT not in json.dumps(DeepSeekAdapter().build_payload(first.request), ensure_ascii=False)
    assert first.request.images[0].label == "TARGET LINE"
    oracle = json.loads((tmp_path / "one/synthetic-oracle.json").read_text())
    assert oracle["expected_text"] == SYNTHETIC_TEXT
    assert all(record["ground_truth"] is None for record in json.loads(selection.read_text())["lines"])


def test_structural_metrics_are_not_real_scan_accuracy():
    baseline = diagnostic_metrics(BASELINE_OUTPUT)
    assert baseline["signs_only"] and baseline["chart_like_run"]
    assert baseline["khojki_base_letters"] == 0 and baseline["shared_chart_sequence_length"] == 15
    assert "synthetic_cer" not in baseline
    actual = diagnostic_metrics(SYNTHETIC_TEXT + " ૨", unverified_control="\U00011208")
    assert actual["khojki_base_letters"] == 4 and actual["base_letter_ratio"] < .5
    assert not actual["signs_only"] and actual["ends_with_gujarati_digit"]
    assert actual["unverified_openai_agreement"]["not_ground_truth"]
    assert "cer" not in actual


def test_synthetic_metrics_use_exact_known_codepoints_only():
    exact = diagnostic_metrics(SYNTHETIC_TEXT, SYNTHETIC_TEXT)
    assert exact["synthetic_exact_match"] and exact["synthetic_cer"] == 0
    altered = "\U0001120A" + SYNTHETIC_TEXT[1:]
    error = diagnostic_metrics(altered, SYNTHETIC_TEXT)
    assert error["synthetic_edit_distance"] == 1
    assert error["synthetic_cer"] == pytest.approx(1 / len(SYNTHETIC_TEXT))
    assert diagnostic_metrics(None, SYNTHETIC_TEXT)["synthetic_cer"] is None
    assert edit_distance("abc", "axc") == 1


def test_dry_run_does_not_create_sdk_or_budget(tmp_path, inputs, monkeypatch):
    cfg, selection = inputs
    monkeypatch.setattr(openai, "OpenAI", lambda *a, **kw: pytest.fail("No SDK client in dry-run"))
    run = RunContext(tmp_path / "runs")
    manifest = run_case("D1b", cfg, selection, run, dry_run=True)
    assert manifest["api_calls"] == 0 and manifest["status"] == "prepared_not_executed"
    assert not cfg.recognition.ledger_path.exists()
    assert not cfg.recognition.cache_dir.exists()
    assert (run.directory / "synthetic-target.png").exists()


def test_mocked_diagnostic_exact_match_and_cache_without_second_call(tmp_path, inputs):
    cfg, selection = inputs
    before = selection.read_bytes()

    class Fake(DeepSeekAdapter):
        calls = 0

        def __init__(self):
            super().__init__(SimpleNamespace())

        def send(self, req):
            self.calls += 1
            return ProviderResponse(state="completed", raw_text=json.dumps({"text": SYNTHETIC_TEXT, "uncertain_spans": [], "unreadable": False}),
                                    returned_model="deepseek-flash", usage=TokenUsage(input_tokens=100, output_tokens=20))

    adapter = Fake()
    first_run = RunContext(tmp_path / "runs")
    first = run_case("D1b", cfg, selection, first_run, dry_run=False, adapter=adapter)
    assert first["api_calls"] == 1 and first["status"] == "completed"
    assert json.loads((first_run.directory / "metrics.json").read_text())["synthetic_cer"] == 0
    second = run_case("D1b", cfg, selection, RunContext(tmp_path / "runs"), dry_run=False, adapter=adapter)
    assert second["cache_hit"] and second["api_calls"] == 0 and adapter.calls == 1
    assert selection.read_bytes() == before


def test_timeout_pauses_with_one_held_reservation(tmp_path, inputs):
    cfg, selection = inputs

    class TimeoutAdapter(DeepSeekAdapter):
        def __init__(self):
            super().__init__(SimpleNamespace())

        def send(self, req):
            raise TimeoutError("mock timeout")

    run = RunContext(tmp_path / "runs")
    manifest = run_case("D1", cfg, selection, run, dry_run=False, adapter=TimeoutAdapter())
    assert manifest["status"] == "paused" and manifest["api_calls"] == 1
    assert manifest["budget"]["unknown_or_reserved_attempts"] == 1
    cfg.recognition.max_attempts = 2
    with pytest.raises(ValueError, match="max_attempts"):
        run_case("D1", cfg, selection, RunContext(tmp_path / "runs"))
