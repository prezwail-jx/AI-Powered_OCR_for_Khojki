"""Explicit network preparation; normal CLI commands use bundled data offline.

Run from any directory using the project .venv interpreter. Downloaded files are
cached; use --fetch to re-download and verify against the existing source hashes.
"""

import argparse
import hashlib
import json
import io
import zipfile
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src/khojki_ocr/assets"
VERSION = "17.0.0"
COMMIT = "8b0a1d0f5983c89bc2b93f1b5fb55f9e252744b5"
UCD = f"https://www.unicode.org/Public/{VERSION}/ucd/"
FONTS = f"https://raw.githubusercontent.com/google/fonts/{COMMIT}/ofl/"
SOURCES = {
    "UnicodeData.txt": UCD + "UnicodeData.txt",
    "Scripts.txt": UCD + "Scripts.txt",
    "Unicode-LICENSE.txt": "https://www.unicode.org/license.txt",
    "NotoSansKhojki-Regular.ttf": FONTS + "notosanskhojki/NotoSansKhojki-Regular.ttf",
    "Khojki-OFL.txt": FONTS + "notosanskhojki/OFL.txt",
    "NotoSansGujarati.ttf": FONTS + "notosansgujarati/NotoSansGujarati%5Bwdth%2Cwght%5D.ttf",
    "Gujarati-OFL.txt": FONTS + "notosansgujarati/OFL.txt",
    "NotoSerifKhojki-v2.005.zip": "https://github.com/notofonts/khojki/releases/download/NotoSerifKhojki-v2.005/NotoSerifKhojki-v2.005.zip",
    "SerifKhojki-OFL.txt": "https://raw.githubusercontent.com/notofonts/khojki/02e25bf94664812076be4fa7dd1d688641e4bf8a/OFL.txt",
}


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="Re-download and verify cached sources")
    args = parser.parse_args()
    cache = ROOT / ".cache/unicode-17.0.0"
    cache.mkdir(parents=True, exist_ok=True)
    unicode_dir = ASSETS / "unicode"
    font_dir = ASSETS / "fonts"
    unicode_dir.mkdir(parents=True, exist_ok=True)
    font_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = unicode_dir / "sources.json"
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"sources": {}}
    manifest = {"unicode_version": VERSION, "font_repository_commit": COMMIT,
                "rules_source": "https://www.unicode.org/versions/Unicode17.0.0/core-spec/chapter-15/#G113410",
                "sources": {}}
    payloads = {}
    for name, url in SOURCES.items():
        path = cache / name
        if args.fetch or not path.exists():
            with urlopen(url, timeout=60) as response:
                data = response.read()
        else:
            data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        expected = previous["sources"].get(name, {}).get("sha256")
        if expected and digest != expected:
            raise ValueError(f"Source hash mismatch: {name}; review upstream changes before updating")
        path.write_bytes(data)
        manifest["sources"][name] = {"url": url, "sha256": digest, "bytes": len(data)}
        payloads[name] = data
        if name.endswith(".ttf") or name.endswith("OFL.txt"):
            (font_dir / name).write_bytes(data)
        print(name, digest)
    with zipfile.ZipFile(io.BytesIO(payloads["NotoSerifKhojki-v2.005.zip"])) as archive:
        candidates = [name for name in archive.namelist() if name.endswith("/NotoSerifKhojki-Regular.ttf")]
        print("Serif candidates:", candidates)
        chosen = next((name for name in candidates if "/full/ttf/" in name), None)
        if chosen is None:
            raise ValueError("Expected full/ttf/NotoSerifKhojki-Regular.ttf in pinned release")
        font_bytes = archive.read(chosen)
        (font_dir / "NotoSerifKhojki-Regular.ttf").write_bytes(font_bytes)
        manifest["serif_font_extraction"] = {"archive": "NotoSerifKhojki-v2.005.zip", "member": chosen,
                                              "sha256": hashlib.sha256(font_bytes).hexdigest()}
    records = []
    for line in payloads["UnicodeData.txt"].decode("utf-8").splitlines():
        fields = line.split(";")
        cp = int(fields[0], 16)
        if 0x11200 <= cp <= 0x1124F or 0x0AE6 <= cp <= 0x0AEF:
            records.append({"codepoint": fields[0], "name": fields[1], "category": fields[2],
                            "combining_class": int(fields[3]), "decomposition": fields[5],
                            "script": "Khojki" if cp >= 0x11200 else "Gujarati"})
    dump(unicode_dir / "characters.json", {"unicode_version": VERSION, "characters": records})
    (unicode_dir / "Scripts.txt").write_bytes(payloads["Scripts.txt"])
    (unicode_dir / "Unicode-LICENSE.txt").write_bytes(payloads["Unicode-LICENSE.txt"])
    dump(manifest_path, manifest)
    print(f"Generated {len(records)} character records")


if __name__ == "__main__":
    main()
