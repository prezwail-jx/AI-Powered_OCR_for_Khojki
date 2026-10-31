import json

import pytest
import unicodedata2 as ucd

from khojki_ocr.cli import main
from khojki_ocr.unicode_rules import (
    UNICODE_VERSION, character_table, describe_text, normalize_text, script_of,
    transcription_rules, validate_text,
)


def test_official_repertoire_and_names():
    table = character_table()
    assert UNICODE_VERSION == ucd.unidata_version == "17.0.0"
    assert len(table) == 75
    assert len([c for c in table if c >= 0x11200]) == 65
    assert table[0x11208]["name"] == "KHOJKI LETTER KA"
    assert table[0x1120A]["name"] == "KHOJKI LETTER GA"
    assert table[0x11241]["name"] == "KHOJKI VOWEL SIGN VOCALIC R"
    assert 0x11212 not in table
    assert {c for c in table if c < 0x11200} == set(range(0xAE6, 0xAF0))
    for cp, record in table.items():
        assert ucd.name(chr(cp)) == record["name"]
        assert ucd.category(chr(cp)) == record["category"]
        assert ucd.combining(chr(cp)) == record["combining_class"]
        assert script_of(cp) == record["script"]


def test_legitimate_line_and_punctuation_are_preserved():
    text = "\U00011208\U0001122C \U0001123A\u0AE7\U00011239."
    result = validate_text(text)
    assert result["valid"] and not result["needs_review"]
    assert result["raw_text"] == result["nfc_text"] == text
    assert result["characters"][3]["codepoint"] == "U+1123A"
    assert describe_text("\U0001120A")[0]["index"] == 0


@pytest.mark.parametrize("char,code", [
    ("\U00011212", "unassigned"), ("\U0001124F", "unassigned"),
    ("\U000112F0", "foreign_script"), ("\u0966", "foreign_script"),
    ("a", "foreign_script"), ("\u0A95", "foreign_script"),
    ("\u200D", "control_or_invisible"), ("\u200C", "control_or_invisible"),
    ("\uFE0F", "control_or_invisible"), ("\uFEFF", "control_or_invisible"),
    ("\t", "control_or_invisible"), ("\n", "control_or_invisible"),
    ("\uFFFD", "replacement_character"), ("\ud800", "invalid_scalar"),
    ("0", "not_allowed"), ("\u00A0", "not_allowed"),
    ("\u25CC", "not_allowed"), ("\u0301", "not_allowed"),
])
def test_invalid_scalars_and_scripts_are_not_silently_fixed(char, code):
    text = "\U00011208" + char
    result = validate_text(text)
    assert not result["valid"]
    problem = next(item for item in result["issues"] if item["code"] == code)
    assert problem["index"] == 1
    assert problem["text"] == char
    assert result["raw_text"] == text


@pytest.mark.parametrize("rule", transcription_rules()["atomic_sequences"])
def test_all_official_atomic_recommendations(rule):
    sequence = "".join(chr(int(cp, 16)) for cp in rule["sequence"])
    text = "\U00011208\U0001123A" + sequence
    result = validate_text(text)
    assert not result["valid"]
    problem = next(item for item in result["issues"] if item["code"] == "non_atomic_sequence")
    assert problem["index"] == 2
    assert problem["recommended_codepoint"] == f"U+{rule['recommended']}"
    assert result["raw_text"] == text
    # These visual decompositions do NOT compose automatically with NFC.
    assert normalize_text(sequence)["nfc_text"] == sequence


def test_normalization_tracks_changes_and_does_not_invent_visual_composition():
    text = "\U00011208\U00011235\U00011236"
    result = normalize_text(text)
    assert result["changed"]
    assert result["raw_text"] == text
    assert result["nfc_text"] == "\U00011208\U00011236\U00011235"
    assert result["changes"]
    assert not normalize_text(result["nfc_text"])["changed"]
    assert normalize_text("e\u0301")["nfc_text"] == "é"
    assert not validate_text("e\u0301")["valid"]


def test_isolated_mark_is_review_warning_not_guessed_grammar():
    result = validate_text("\U00011241")
    assert result["valid"] and result["needs_review"]
    assert result["issues"][0]["severity"] == "warning"
    assert not validate_text("")["valid"]
    assert not validate_text("   ")["valid"]


def test_unicode_cli_delimiter_and_raw_preservation(tmp_path, capsys):
    path = tmp_path / "line.txt"
    original = "\U00011208\U0001122C\r\n"
    path.write_bytes(original.encode("utf-8"))
    assert main(["unicode-check", "--text-file", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["source_file_text"] == original
    assert result["raw_text"] == original[:-2]
    assert result["terminal_file_delimiter"] == "\r\n"
    path.write_text("\U00011208\n\U00011208\n", encoding="utf-8")
    report = tmp_path / "reports/result.json"
    assert main(["unicode-check", "--text-file", str(path), "--output", str(report)]) == 1
    assert any(i["code"] == "control_or_invisible" for i in json.loads(report.read_text())["issues"])
    path.write_bytes(b"\xff")
    assert main(["unicode-check", "--text-file", str(path)]) == 2
