"""Versioned Khojki transcription checks, not a linguistic correctness oracle."""

import json
from bisect import bisect_right
from difflib import SequenceMatcher
from functools import lru_cache
from importlib.resources import files

import unicodedata2 as ucd

UNICODE_VERSION = "17.0.0"


def asset_bytes(group: str, name: str) -> bytes:
    return files("khojki_ocr").joinpath("assets", group, name).read_bytes()


@lru_cache
def character_table() -> dict[int, dict]:
    payload = json.loads(asset_bytes("unicode", "characters.json"))
    if payload["unicode_version"] != UNICODE_VERSION or ucd.unidata_version != UNICODE_VERSION:
        raise RuntimeError("Unicode data/normalizer version mismatch")
    return {int(item["codepoint"], 16): item for item in payload["characters"]}


@lru_cache
def transcription_rules() -> dict:
    return json.loads(asset_bytes("unicode", "transcription_rules.json"))


@lru_cache
def _script_ranges():
    ranges = []
    for line in asset_bytes("unicode", "Scripts.txt").decode("utf-8").splitlines():
        fields = line.split("#", 1)[0].strip()
        if not fields:
            continue
        span, script = [value.strip() for value in fields.split(";")]
        bounds = span.split("..")
        ranges.append((int(bounds[0], 16), int(bounds[-1], 16), script))
    ranges.sort()
    return [r[0] for r in ranges], ranges


def script_of(codepoint: int) -> str:
    starts, ranges = _script_ranges()
    index = bisect_right(starts, codepoint) - 1
    return ranges[index][2] if index >= 0 and codepoint <= ranges[index][1] else "Unknown"


def describe_text(text: str) -> list[dict]:
    """Indices always count Unicode code points, not bytes or glyphs."""
    table = character_table()
    return [{"index": index, "character": char, "codepoint": f"U+{ord(char):04X}",
             "name": table.get(ord(char), {}).get("name", ucd.name(char, "UNASSIGNED OR CONTROL")),
             "category": ucd.category(char), "combining_class": ucd.combining(char),
             "script": script_of(ord(char))} for index, char in enumerate(text)]


def normalize_text(text: str) -> dict:
    character_table()  # Enforce pinned data and normalizer before transforming.
    nfc = ucd.normalize("NFC", text)
    changes = [{"raw_span": [i, j], "nfc_span": [a, b], "raw": text[i:j], "nfc": nfc[a:b]}
               for tag, i, j, a, b in SequenceMatcher(a=text, b=nfc, autojunk=False).get_opcodes()
               if tag != "equal"]
    return {"raw_text": text, "nfc_text": nfc, "changed": text != nfc, "changes": changes}


def validate_text(text: str) -> dict:
    """Check a single line, retaining invalid input and suggested fixes verbatim."""
    normalized = normalize_text(text)
    characters = describe_text(text)
    table = character_table()
    rules = transcription_rules()
    common = {int(cp, 16) for cp in rules["allowed_spaces"] + rules["allowed_common_punctuation"]}
    issues = []

    def issue(code, start, end, message, severity="error", **extra):
        issues.append({"code": code, "severity": severity, "index": start, "end_index": end,
                       "text": text[start:end], "codepoints": [f"U+{ord(c):04X}" for c in text[start:end]],
                       "message": message, **extra})

    if not text or not text.strip():
        issue("empty_line", 0, len(text), "A transcription line must not be empty or whitespace-only")
    for item in characters:
        cp, index, category = ord(item["character"]), item["index"], item["category"]
        if cp in table or cp in common:
            # Only a conservative isolated-mark check; not a full Khojki grammar.
            if cp in table and category.startswith("M"):
                prev = ord(text[index - 1]) if index else None
                if prev not in table or table[prev]["script"] != "Khojki" or table[prev]["category"] == "Po":
                    issue("isolated_mark", index, index + 1, "Combining mark has no adjacent Khojki base/mark", "warning")
            continue
        if category == "Cs":
            code, message = "invalid_scalar", "Surrogate code point cannot be encoded as UTF-8"
        elif cp == 0xFFFD:
            code, message = "replacement_character", "Replacement character indicates lost or undecoded text"
        elif category in ("Cc", "Cf") or cp == 0x034F or 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF:
            code, message = "control_or_invisible", "Control/format/invisible character requires manual review"
        elif category == "Cn":
            code, message = "unassigned", "Unassigned in Unicode 17.0.0"
        elif item["script"] not in ("Common", "Inherited", "Unknown", "Khojki"):
            code, message = "foreign_script", f"Unexpected {item['script']} character (only Gujarati digits are allowed)"
        else:
            code, message = "not_allowed", "Character is outside the project transcription whitelist"
        issue(code, index, index + 1, message, name=item["name"], script=item["script"])

    # Longest first avoids duplicate overlapping recommendations for LETTER AU.
    covered = set()
    for rule in sorted(rules["atomic_sequences"], key=lambda r: -len(r["sequence"])):
        sequence = "".join(chr(int(cp, 16)) for cp in rule["sequence"])
        start = text.find(sequence)
        while start != -1:
            end = start + len(sequence)
            if not covered.intersection(range(start, end)):
                recommended = int(rule["recommended"], 16)
                issue("non_atomic_sequence", start, end, "Use the atomic character from Unicode Table 15-4",
                      recommended_text=chr(recommended), recommended_codepoint=f"U+{recommended:04X}",
                      source=rules["source"])
                covered.update(range(start, end))
            start = text.find(sequence, start + 1)
    return {"unicode_version": UNICODE_VERSION, "rules_version": rules["rules_version"], **normalized,
            "characters": characters, "nfc_characters": describe_text(normalized["nfc_text"]),
            "issues": issues, "valid": not any(item["severity"] == "error" for item in issues),
            "needs_review": bool(issues), "index_unit": "zero-based Unicode code point in raw_text",
            "limitation": "Encoding validity does not establish transcription accuracy or linguistic correctness"}
