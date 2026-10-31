"""Read-only, script-free HTML. Model text is escaped and glyph runs stay intact."""

import base64
import html

from .unicode_rules import asset_bytes, describe_text


def escaped(value):
    text = str(value).encode("utf-8", errors="backslashreplace").decode("utf-8")
    return html.escape(text, quote=True)


def word_context(text, start, end, alternative=None):
    separators = " \U0001123A\U00011238\U00011239\U0001123B\U0001123C"
    left = start
    while left > 0 and text[left - 1] not in separators:
        left -= 1
    right = end
    while right < len(text) and text[right] not in separators:
        right += 1
    if alternative is None:
        return text[left:right]
    return text[left:start] + alternative + text[end:right]


def render_html(entries, selection_id, references):
    def glyph(value):
        return f'<span class="glyph">{escaped(value)}</span>'

    cards = []
    for entry in entries:
        title = f"Row {entry.evaluation_order} · PDF page {entry.pdf_page} · overlay {entry.detection_reading_order}"
        state = "Not yet recognized / 尚未识别" if entry.prediction_state == "not_run" else entry.prediction_state
        body = [f'<section id="{escaped(entry.line_id)}"><h2>{escaped(title)}</h2>',
                f'<p class="muted">{escaped(entry.line_id)}</p>',
                f'<p><span class="chip">Prediction: {escaped(state)}</span> <span class="chip pending">Human review: {escaped(entry.review_status)}</span></p>',
                f'<a href="{escaped(entry.image_path)}" target="_blank" rel="noopener"><img class="line-image" src="{escaped(entry.image_path)}" alt="Original crop: {escaped(title)}"></a>',
                '<p class="muted">Click the image for native resolution. No character-level image boxes are claimed.</p>']
        if entry.machine_text is None:
            body.append('<p class="notice">No extracted candidate. This is not an empty reference answer and is not Ground Truth.</p>')
        else:
            body.append(f'<h3>Original machine candidate — not Ground Truth</h3><div class="candidate glyph">{escaped(entry.machine_text)}</div>')
            if entry.nfc_text != entry.machine_text:
                body.append(f'<h3>NFC (original kept separately)</h3><div class="candidate glyph">{escaped(entry.nfc_text)}</div>')
                body.append('<p class="notice">Normalization changed text. All uncertainty offsets below still refer to the original raw text.</p>')
        body.append(f'<p>Recognition status: {escaped(entry.recognition_status or "not_run")} · Model: {escaped(entry.returned_model or "not returned")}</p>')
        if entry.warnings:
            body.append('<ul class="notice">' + ''.join(f'<li>{escaped(warning)}</li>' for warning in entry.warnings) + '</ul>')
        if entry.uncertain_spans and entry.machine_text is not None:
            rows = []
            for span in entry.uncertain_spans:
                alternatives = []
                for alternative in span.alternatives:
                    codes = " ".join(item["codepoint"] for item in describe_text(alternative))
                    alternatives.append(f'{glyph(word_context(entry.machine_text, span.start, span.end, alternative))}<br><code>{escaped(codes)}</code>')
                rows.append(f'<tr><td><code>[{span.start}, {span.end})</code></td><td>{glyph(word_context(entry.machine_text, span.start, span.end))}</td>'
                            f'<td>{"<hr>".join(alternatives) or "No alternative supplied"}</td><td>{escaped(span.reason)}</td></tr>')
            body.append('<h3>Model uncertainty — text offsets, not scan coordinates</h3><table><thead><tr><th>Raw span</th><th>Current word context</th><th>Model alternative context</th><th>Reason</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table>')
        elif entry.prediction_state == "candidate_available":
            body.append('<p>No model-declared uncertain span. The full line still requires human verification.</p>')
        if entry.codepoints:
            rows = []
            for item in entry.codepoints:
                index = item["index"]
                uncertain = any(span.start <= index < span.end for span in entry.uncertain_spans)
                display = ("\u25cc" if item["category"].startswith("M") else "") + item["character"]
                rows.append(f'<tr class="{"uncertain" if uncertain else ""}"><td>{index}</td><td>{glyph(display)}</td><td><code>{escaped(item["codepoint"])}</code></td>'
                            f'<td>{escaped(item["name"])}</td><td>{"Model uncertainty" if uncertain else ""}</td></tr>')
            body.append(f'<details><summary>Raw codepoints ({len(entry.codepoints)})</summary><p>Zero-based codepoint indices, not visible glyph counts. Dotted circles are display-only.</p>'
                        '<table><thead><tr><th>Index</th><th>Display</th><th>Codepoint</th><th>Official name</th><th>Flag</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></details>')
        if entry.unicode_report and entry.unicode_report["issues"]:
            body.append('<h3>Unicode issues</h3><ul>' + ''.join(f'<li>{escaped(issue["code"])} at [{issue["index"]}, {issue["end_index"]}): {escaped(issue["message"])}</li>' for issue in entry.unicode_report["issues"]) + '</ul>')
        if entry.latest_draft is not None:
            draft = entry.latest_draft
            body.append(f'<h3>Latest human draft — NOT confirmed Ground Truth</h3><div class="candidate glyph">{escaped(draft["human_text"])}</div>'
                        f'<p>Reviewer: {escaped(draft["reviewer"])} · revision {draft["revision"]} · {escaped(draft["notes"])}</p>')
            if not draft["unicode_report"]["valid"]:
                body.append('<p class="notice">Draft has Unicode errors. It remains a draft and cannot be treated as confirmed.</p>')
        if entry.snapshot_path:
            body.append(f'<p><a href="{escaped(entry.snapshot_path)}">Frozen machine-result snapshot</a> · machine prediction hash <code>{escaped(entry.prediction_sha256)}</code></p>')
        body.append('</section>')
        cards.append(''.join(body))

    fonts = []
    for family, name, ranges in [("KhojkiReview", "NotoSerifKhojki-Regular.ttf", "U+11200-1124F,U+25CC"),
                                  ("GujaratiReview", "NotoSansGujarati.ttf", "U+0A80-0AFF")]:
        encoded = base64.b64encode(asset_bytes("fonts", name)).decode("ascii")
        fonts.append(f"@font-face{{font-family:{family};src:url(data:font/ttf;base64,{encoded}) format('truetype');font-weight:400;unicode-range:{ranges};}}")
    navigation = ' '.join(f'<a href="#{escaped(entry.line_id)}">{entry.evaluation_order} (#{entry.detection_reading_order})</a>' for entry in entries)
    ref_links = ' · '.join(f'<a target="_blank" rel="noopener" href="assets/references/{escaped(name)}">{escaped(name)}</a>' for name in references)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' data: file:; font-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Khojki review — {escaped(selection_id)}</title><style>
{''.join(fonts)}
body{{font-family:system-ui,sans-serif;color:#202733;background:#f3f5f8;max-width:1200px;margin:32px auto;padding:0 20px;line-height:1.6}}
section,header{{background:white;padding:24px;border:1px solid #dce1e8;border-radius:12px;margin:22px 0}}h1,h2,h3{{line-height:1.3}}h2{{font-size:22px}}h3{{font-size:17px}}
.glyph{{font-family:KhojkiReview,GujaratiReview,sans-serif;font-size:30px;line-height:1.9}}.candidate{{padding:18px;background:#f7f8fa;white-space:pre-wrap;overflow-x:auto;overflow-wrap:anywhere}}
.line-image{{width:100%;height:auto;border:1px solid #dce1e8}}.muted{{font-size:13px;color:#596477}}.notice{{background:#fff5df;padding:12px;border-left:4px solid #d89000}}
.chip{{display:inline-block;padding:3px 10px;border-radius:6px;background:#edf1f7;margin:2px}}.pending{{background:#fff0ce}}
table{{border-collapse:collapse;width:100%;font-size:14px;margin:12px 0}}th,td{{border:1px solid #dce1e8;text-align:left;padding:8px;vertical-align:top}}th{{background:#f0f3f7}}
.uncertain{{background:#fff1ce}}code{{font-family:ui-monospace,monospace;font-size:12px;overflow-wrap:anywhere}}summary{{cursor:pointer;font-weight:600;margin-top:16px}}nav a{{display:inline-block;margin:3px;padding:4px 9px;background:#edf1f7}}a{{color:#2355a0}}
</style></head><body><header><h1>Khojki offline review</h1><p>Selection: <code>{escaped(selection_id)}</code> · {len(entries)} frozen rows</p>
<p class="notice">Read-only document / 此页只读。Review all text, not only flagged characters. Tell the assistant the row and edit, or fill human_text in review-template.jsonl and import it as a draft. No model answer or encoding-valid draft is automatically Ground Truth.</p>
<p>Positions are zero-based codepoint offsets in the raw model text, not image coordinates or glyph counts. Full candidate runs remain intact to preserve combining-mark shaping.</p>
<nav>{navigation}</nav><details><summary>Reference charts (modern glyphs, not scanned answers)</summary><p>{ref_links}</p><p>Embedded fonts are provided under the OFL; copies are in assets/licenses/. This page has no scripts, network requests or model API calls.</p></details>
<p><a href="review-template.jsonl">Editable draft template</a> · <a href="entries.jsonl">Frozen review entries</a> · <a href="manifest.json">Provenance manifest</a></p></header>{''.join(cards)}</body></html>'''
