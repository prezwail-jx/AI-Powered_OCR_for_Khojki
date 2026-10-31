import hashlib
import json

import pytest
from PIL import Image

from khojki_ocr import reference
from khojki_ocr.unicode_rules import asset_bytes, character_table


def test_bundled_assets_match_source_hashes():
    source = json.loads(asset_bytes("unicode", "sources.json"))
    names = {"NotoSansKhojki-Regular.ttf", "NotoSansGujarati.ttf", "Khojki-OFL.txt", "Gujarati-OFL.txt", "SerifKhojki-OFL.txt"}
    for name in names:
        assert hashlib.sha256(asset_bytes("fonts", name)).hexdigest() == source["sources"][name]["sha256"]
    assert hashlib.sha256(asset_bytes("fonts", reference.SERIF)).hexdigest() == source["serif_font_extraction"]["sha256"]
    for name in ("Scripts.txt", "Unicode-LICENSE.txt"):
        assert hashlib.sha256(asset_bytes("unicode", name)).hexdigest() == source["sources"][name]["sha256"]


def test_complete_font_coverage_and_missing_font_rejection():
    required = {cp for cp, item in character_table().items() if item["script"] == "Khojki"}
    assert not required - reference.font_cmap(reference.SERIF)
    assert required - reference.font_cmap(reference.SANS) == {0x11241}
    with pytest.raises(ValueError, match="U\\+11241"):
        reference.shape_text("\U00011208\U00011241", reference.SANS)
    infos, _ = reference.shape_text("\U00011208\U00011241")
    assert all(info.codepoint != 0 for info in infos)


def test_missing_selected_glyph_fails_before_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(reference, "font_cmap", lambda name: frozenset())
    target = tmp_path / "incomplete"
    with pytest.raises(ValueError, match="Incomplete"):
        reference.build_reference(target)
    assert not target.exists()


def test_reference_generation_matches_codepoints_and_no_clipping(tmp_path, monkeypatch):
    # Network must not be required for ordinary reference generation.
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: pytest.fail("Unexpected network access"))
    target = tmp_path / "references"
    manifest = reference.build_reference(target)
    assert len(manifest["sheets"]) == 8
    assert manifest["fonts"][reference.SERIF]["missing_codepoints"] == []
    assert manifest["fonts"][reference.SANS]["used_for_rendering"] is False
    seen = set()
    combos = []
    for sheet in manifest["sheets"]:
        path = target / sheet["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sheet["sha256"]
        with Image.open(path) as image:
            for cell in sheet["cells"]:
                assert cell["codepoints"] == [f"U+{ord(c):04X}" for c in cell["text"]]
                assert cell["names"] == [character_table()[ord(c)]["name"] for c in cell["text"]]
                x, y, w, h = cell["box"]
                assert x >= 0 and y >= 0 and x+w <= image.width and y+h <= image.height
                if sheet["file"].startswith("matrix-"):
                    combos.append(cell["text"])
                else:
                    seen.update(ord(c) for c in cell["text"])
    assert seen == set(character_table())
    assert len(combos) == 36 * 15
    assert "\U00011208\U00011241" in combos
    assert "\u25cc" not in "".join(combos)
    # Existing results must never be silently overwritten.
    with pytest.raises(ValueError, match="already exists"):
        reference.build_reference(target)
