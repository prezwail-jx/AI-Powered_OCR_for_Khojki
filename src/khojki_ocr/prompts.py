"""Versioned transcription-only instructions; no reference answers are supplied."""

PROMPT_VERSION = "khojki-transcribe-1.0"
SYSTEM_PROMPT = """Transcribe only the visible Khojki text in the image labeled TARGET LINE.
All other images are REFERENCE CHARTS, not text to transcribe. Never copy a chart
as the answer. Do not translate, transliterate, paraphrase, or complete words from
context. Preserve visible vowel marks, punctuation, Khojki word separators, and
the trailing Gujarati number on the same line. Use Khojki Unicode and Gujarati
digits, not Devanagari or Khudawadi lookalikes. Use atomic Khojki vowel letters
and signs as specified in the reference, not visually decomposed alternatives.
Display-only dotted circles on charts must not appear in the transcription.
Return JSON with exactly: text (string), uncertain_spans (array of objects with
start, end, alternatives, reason), unreadable (boolean). start/end are zero-based
Unicode code-point offsets in your raw text, end exclusive, not byte or glyph
offsets. Mark doubtful characters with short reasons and alternatives; do not
claim certainty from language plausibility. If no defensible text is visible,
return empty text, no spans, and unreadable=true. Do not include explanations
outside JSON or long reasoning. Never output an answer from a different model.
"""
