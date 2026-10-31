import openai
import pytest
from pathlib import Path

from khojki_ocr.evaluation import align, evaluate_pair, evaluate_run, summarize, verify_evaluation
from khojki_ocr.ground_truth import freeze_truth
from khojki_ocr.runtime import RunContext
from test_ground_truth import ready
from test_review import references, source


def test_codepoint_cer_operations_and_empty_policy():
    result = evaluate_pair("𑈀𑈁𑈂", "𑈀𑈃𑈂𑈄")
    assert (result["substitutions"], result["deletions"], result["insertions"]) == (1, 0, 1)
    assert result["distance"] == 2 and result["cer"]["decimal"] == "0.666666666667"
    empty = evaluate_pair("𑈀 ૧", "")
    assert empty["deletions"] == empty["reference_length"] == 3
    assert empty["cer"]["decimal"] == "1.000000000000"
    over_one = evaluate_pair("𑈀", "𑈀𑈁𑈂")
    assert over_one["insertions"] == 2 and over_one["cer"]["decimal"] == "2.000000000000"
    with pytest.raises(ValueError, match="nonempty"):
        evaluate_pair("", "𑈀")


def test_nfc_is_applied_without_trimming_counted_characters():
    result = evaluate_pair("A\u030a 𑊱", "Å 𑊱")
    assert result["exact_match"] and result["reference_nfc_changed"]
    assert result["reference_length"] == 3
    deletion = evaluate_pair("𑈀 𑈁", "𑈀𑈁")
    assert deletion["deletions"] == 1
    assert next(op for op in deletion["alignment"] if op["operation"] == "deletion")["reference"]["codepoint"] == "U+0020"


def test_alignment_tie_break_is_deterministic():
    first = align("aa", "a")
    assert first == align("aa", "a")
    assert [op["operation"] for op in first["alignment"]] == ["deletion", "match"]


def test_summary_uses_micro_and_macro_denominators():
    lines = []
    for reference, hypothesis in (("ab", "a"), ("c", "")):
        row = evaluate_pair(reference, hypothesis)
        row["recognition_status"] = "needs_review"
        lines.append(row)
    summary = summarize(lines)
    assert summary["micro_cer"] == {"numerator": 2, "denominator": 3, "decimal": "0.666666666667"}
    assert summary["macro_cer"]["decimal"] == "0.750000000000"
    assert summary["deleted_codepoints"] == [{"codepoint": "U+0062", "count": 1}, {"codepoint": "U+0063", "count": 1}]


def test_frozen_evaluation_is_offline_recomputable_and_tamper_evident(ready, monkeypatch):
    source, bundle, confirmation, _, truth = ready
    freeze_truth(source["selection"], bundle, confirmation, truth, "truth-v1", confirm=True)
    monkeypatch.setattr(openai, "OpenAI", lambda *args, **kwargs: pytest.fail("Evaluation must be offline"))
    before = {path: path.read_bytes() for path in truth.parent.rglob("*") if path.is_file()}
    run = RunContext(source["outputs"])
    manifest, summary = evaluate_run(truth, run, source["outputs"].parent, include_deepseek=False)
    assert manifest["api_calls"] == 0 and summary["line_count"] == 3
    assert summary["exact_line_count"] == 2 and summary["insertions"] == 1
    assert (run.directory / "confusion.json").is_file()
    _, verified, rows = verify_evaluation(run.directory)
    assert verified == summary and rows[0]["insertions"] == 1
    assert all(path.read_bytes() == value for path, value in before.items())
    saved = (run.directory / "summary.json").read_bytes()
    (run.directory / "summary.json").write_bytes(saved + b" ")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_evaluation(run.directory)


def test_summary_rejects_empty_evaluation():
    with pytest.raises(ValueError, match="at least one"):
        summarize([])


def test_repository_frozen_truth_has_declared_single_insertion():
    root = Path(__file__).resolve().parents[1]
    from khojki_ocr.evaluation import _main_lines

    _, _, lines = _main_lines(root / "data/annotations/ground_truth.jsonl")
    summary = summarize(lines)
    assert summary["micro_cer"] == {"numerator": 1, "denominator": 253, "decimal": "0.003952569170"}
    assert summary["exact_line_count"] == 9 and summary["insertions"] == 1
    changed = [line for line in lines if not line["exact_match"]]
    assert len(changed) == 1 and changed[0]["line_id"] == "p0017-l015-e38c91e25be6"
    edits = [op for op in changed[0]["alignment"] if op["operation"] != "match"]
    assert len(edits) == 1 and edits[0]["operation"] == "insertion"
    assert edits[0]["hypothesis"]["codepoint"] == "U+11235"
