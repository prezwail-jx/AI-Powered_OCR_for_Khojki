"""Offline reference charts, shaped with HarfBuzz and rasterized by FreeType."""

import hashlib
import io
import json
import math
import textwrap
from functools import lru_cache
from pathlib import Path

import freetype
import uharfbuzz as hb
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont, __version__ as pillow_version

from .unicode_rules import UNICODE_VERSION, asset_bytes, character_table

SANS = "NotoSansKhojki-Regular.ttf"
SERIF = "NotoSerifKhojki-Regular.ttf"
GUJARATI = "NotoSansGujarati.ttf"
DOT = "\u25cc"


@lru_cache
def font_cmap(name: str) -> frozenset[int]:
    with TTFont(io.BytesIO(asset_bytes("fonts", name))) as font:
        return frozenset(cp for cp, glyph in font.getBestCmap().items() if glyph != ".notdef")


def shape_text(text: str, name: str = SERIF, size: int = 58):
    missing = sorted({ord(c) for c in text} - font_cmap(name))
    if missing:
        raise ValueError(f"Missing glyphs in {name}: " + ", ".join(f"U+{cp:04X}" for cp in missing))
    font = hb.Font(hb.Face(asset_bytes("fonts", name)))
    hb.ot_font_set_funcs(font)
    font.scale = (size * 64, size * 64)
    buffer = hb.Buffer()
    buffer.add_str(text)
    buffer.guess_segment_properties()
    buffer.direction = "ltr"
    buffer.script = "Gujr" if name == GUJARATI else "Khoj"
    buffer.language = "und"
    hb.shape(font, buffer)
    if any(info.codepoint == 0 for info in buffer.glyph_infos):
        raise ValueError(f"Shaping produced .notdef in {name}")
    return buffer.glyph_infos, buffer.glyph_positions


def render_glyph(text: str, name: str = SERIF, size: int = 58) -> Image.Image:
    infos, positions = shape_text(text, name, size)
    face = freetype.Face(io.BytesIO(asset_bytes("fonts", name)))
    face.set_pixel_sizes(0, size)
    fragments = []
    pen_x = pen_y = 0.0
    for info, pos in zip(infos, positions):
        face.load_glyph(info.codepoint, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_NORMAL)
        glyph = face.glyph
        bitmap = glyph.bitmap
        if bitmap.width and bitmap.rows:
            if bitmap.pixel_mode != freetype.FT_PIXEL_MODE_GRAY:
                raise ValueError("Expected grayscale FreeType bitmap")
            stride = abs(bitmap.pitch)
            rows = [bytes(bitmap.buffer)[r * stride:r * stride + bitmap.width] for r in range(bitmap.rows)]
            if bitmap.pitch < 0:
                rows.reverse()
            mask = Image.frombytes("L", (bitmap.width, bitmap.rows), b"".join(rows))
            x = round(pen_x + pos.x_offset / 64) + glyph.bitmap_left
            y = -round(pen_y + pos.y_offset / 64) - glyph.bitmap_top
            fragments.append((x, y, mask))
        pen_x += pos.x_advance / 64
        pen_y += pos.y_advance / 64
    if not fragments:
        raise ValueError("Reference glyph rendered empty")
    left = min(x for x, _, _ in fragments)
    top = min(y for _, y, _ in fragments)
    right = max(x + image.width for x, _, image in fragments)
    bottom = max(y + image.height for _, y, image in fragments)
    canvas = Image.new("RGB", (right - left + 12, bottom - top + 12), "white")
    for x, y, mask in fragments:
        canvas.paste("black", (x - left + 6, y - top + 6), mask)
    return canvas


def reference_groups() -> dict[str, list[int]]:
    table = character_table()
    vowels = list(range(0x11200, 0x11208)) + [0x11240]
    consonants = [cp for cp, item in table.items() if item["script"] == "Khojki"
                  and item["category"] == "Lo" and cp not in vowels]
    return {"vowels": vowels, "consonants": consonants,
            "marks": [cp for cp, item in table.items() if item["script"] == "Khojki" and item["category"].startswith("M")],
            "punctuation": [cp for cp, item in table.items() if item["script"] == "Khojki" and item["category"] == "Po"],
            "digits": list(range(0x0AE6, 0x0AF0))}


def _paste_center(canvas, glyph, box):
    x, y, width, height = box
    if glyph.width > width or glyph.height > height:
        raise ValueError("Glyph exceeds reference cell; enlarge cell instead of silently clipping")
    canvas.paste(glyph, (x + (width - glyph.width) // 2, y + (height - glyph.height) // 2))


def build_reference(output_dir: Path) -> dict:
    """Build into a new directory; never overwrite a prior reference run."""
    if output_dir.exists():
        raise ValueError("Reference output directory already exists; choose a new directory")
    groups = reference_groups()
    table = character_table()
    manifest = {"unicode_version": UNICODE_VERSION, "rendering": {"harfbuzz": hb.version_string(),
                "freetype": list(freetype.version()), "pillow": pillow_version},
                "note": "Synthetic glyph reference, not scanned-page Ground Truth. Matrix cells are character sequences, not extra encoded letters. Dotted circles are display-only.",
                "fonts": {}, "sheets": []}
    sources = json.loads(asset_bytes("unicode", "sources.json"))
    manifest["policy_sha256"] = hashlib.sha256(asset_bytes("unicode", "transcription_rules.json")).hexdigest()
    manifest["characters_sha256"] = hashlib.sha256(asset_bytes("unicode", "characters.json")).hexdigest()
    for name, required in [(SERIF, {cp for cp, item in table.items() if item["script"] == "Khojki"} | {0x25CC}),
                           (GUJARATI, set(groups["digits"])), (SANS, {cp for cp, item in table.items() if item["script"] == "Khojki"})]:
        missing = sorted(required - font_cmap(name))
        if missing and name != SANS:
            raise ValueError(f"Incomplete selected reference font: {name}")
        manifest["fonts"][name] = {"sha256": hashlib.sha256(asset_bytes("fonts", name)).hexdigest(),
                                    "missing_codepoints": [f"U+{cp:04X}" for cp in missing],
                                    "used_for_rendering": name != SANS}
    # Preflight every scalar and matrix sequence before creating output files.
    vowels = list(range(0x1122C, 0x11234)) + [0x11241]
    signs = [0x11234, 0x11235, 0x11236, 0x11237, 0x1123E]
    combos = [None] + vowels + signs
    for group, cps in groups.items():
        for cp in cps:
            shape_text((DOT if table[cp]["category"].startswith("M") else "") + chr(cp), GUJARATI if group == "digits" else SERIF)
    for cp in groups["consonants"]:
        for mark in combos:
            shape_text(chr(cp) + (chr(mark) if mark else ""))
    output_dir.mkdir(parents=True, exist_ok=False)
    label_font = ImageFont.load_default(size=16)
    small_font = ImageFont.load_default(size=13)
    for group, cps in groups.items():
        width, height, columns = 240, 230, 5
        canvas = Image.new("RGB", (width * columns, 90 + math.ceil(len(cps) / columns) * height), "white")
        draw = ImageDraw.Draw(canvas)
        draw.text((16, 12), f"Khojki Unicode {UNICODE_VERSION} / {group}", fill="black", font=label_font)
        draw.text((16, 38), "Modern font reference; historical forms may differ. Dotted circles are not transcription text.", fill="black", font=small_font)
        cells = []
        for index, cp in enumerate(cps):
            x, y = (index % columns) * width, 90 + (index // columns) * height
            char = chr(cp)
            display = (DOT if table[cp]["category"].startswith("M") else "") + char
            font_name = GUJARATI if group == "digits" else SERIF
            _paste_center(canvas, render_glyph(display, font_name), (x + 10, y + 10, width - 20, 110))
            draw.rectangle((x, y, x + width - 1, y + height - 1), outline="#bbbbbb")
            draw.text((x + 12, y + 126), f"U+{cp:04X}", fill="black", font=label_font)
            draw.multiline_text((x + 12, y + 155), "\n".join(textwrap.wrap(table[cp]["name"], 27)), fill="black", font=small_font)
            cells.append({"text": char, "display_text": display, "codepoints": [f"U+{cp:04X}"],
                          "names": [table[cp]["name"]], "box": [x, y, width, height]})
        filename = f"{group}.png"
        canvas.save(output_dir / filename)
        manifest["sheets"].append({"file": filename, "cells": cells})

    # Split 36 consonants over three sheets to keep the matrix legible for VLM input.
    for page, start in enumerate(range(0, len(groups["consonants"]), 12), 1):
        rows = groups["consonants"][start:start + 12]
        cw, ch, header = 145, 115, 150
        canvas = Image.new("RGB", (cw * len(combos), header + ch * len(rows)), "white")
        draw = ImageDraw.Draw(canvas)
        draw.text((12, 10), f"Khojki consonant x vowel/sign matrix {page} / Unicode {UNICODE_VERSION}", fill="black", font=label_font)
        draw.text((12, 35), "Combinations are rendered sequences, not a list of attested words. Each row starts with an unmodified consonant.", fill="black", font=small_font)
        for column, mark in enumerate(combos):
            title = "Inherent" if mark is None else f"U+{mark:04X}"
            draw.text((column * cw + 8, 65), title, fill="black", font=small_font)
            if mark:
                name = table[mark]["name"].replace("KHOJKI ", "")
                draw.multiline_text((column * cw + 8, 87), "\n".join(textwrap.wrap(name, 16)), fill="black", font=small_font)
        cells = []
        for row, cp in enumerate(rows):
            for column, mark in enumerate(combos):
                text = chr(cp) + (chr(mark) if mark else "")
                x, y = column * cw, header + row * ch
                _paste_center(canvas, render_glyph(text, size=48), (x + 5, y + 5, cw - 10, 75))
                draw.rectangle((x, y, x + cw - 1, y + ch - 1), outline="#bbbbbb")
                draw.text((x + 8, y + 84), f"{cp:05X}" + (f" + {mark:05X}" if mark else ""), fill="black", font=small_font)
                cells.append({"text": text, "codepoints": [f"U+{ord(c):04X}" for c in text],
                              "names": [table[ord(c)]["name"] for c in text], "box": [x, y, cw, ch]})
        filename = f"matrix-{page:02}.png"
        canvas.save(output_dir / filename)
        manifest["sheets"].append({"file": filename, "cells": cells})
    for sheet in manifest["sheets"]:
        sheet["sha256"] = hashlib.sha256((output_dir / sheet["file"]).read_bytes()).hexdigest()
    manifest["sources"] = sources
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
