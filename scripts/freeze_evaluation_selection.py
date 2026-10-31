"""Freeze the ten page-17 crops explicitly approved by the user (not Ground Truth)."""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ORDERS = [6, 7, 9, 10, 11, 12, 13, 14, 15, 16]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, default=ROOT / "outputs/20261030T154139Z-8f9c0c0bcbcb")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/evaluation")
    args = parser.parse_args()
    source = args.source_run.resolve()
    output = args.output_dir.resolve()
    if output.exists():
        raise ValueError("Selection output already exists; do not silently overwrite a frozen selection")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if manifest["stage"] != "line_detection" or manifest["status"] != "completed":
        raise ValueError("Expected a completed detection run")
    page = source / "pages/page-0017"
    records = [json.loads(line) for line in (page / "lines.jsonl").read_text(encoding="utf-8").splitlines()]
    by_order = {record["reading_order"]: record for record in records}
    preprocessed = Path(manifest["input_run"])
    metadata = json.loads((preprocessed / "pages/page-0017/metadata.json").read_text(encoding="utf-8"))
    if metadata["dpi"] != 300:
        raise ValueError("The approved selection is from the 300-DPI run")
    selected = []
    for index, order in enumerate(ORDERS, 1):
        record = by_order[order]
        crop = (page / record["crop_path"]).resolve()
        if not crop.is_relative_to(page.resolve()) or digest(crop) != record["crop_sha256"]:
            raise ValueError(f"Crop path/hash mismatch for order {order}")
        if record["page_number"] != 17 or record["classification"] != "body" or not record["has_trailing_number_candidate"]:
            raise ValueError(f"Selection provenance mismatch for order {order}")
        with Image.open(crop) as image:
            x0, y0, x1, y1 = record["crop_box"]
            if image.mode != "L" or image.size != (x1 - x0, y1 - y0):
                raise ValueError(f"Crop dimensions/mode mismatch for order {order}")
            image.verify()
        selected.append({"evaluation_order": index, "line_id": record["line_id"], "pdf_page": 17,
                         "detection_reading_order": order, "trailing_number_value_for_reference": index + 1,
                         "image_path": f"crops/{crop.name}", "image_sha256": record["crop_sha256"],
                         "source_crop_path": str(crop.relative_to(ROOT)),
                         "content_box": record["content_box"], "crop_box": record["crop_box"],
                         "page_coordinates": record["page_coordinates"], "original_detection_flags": record["flags"],
                         "crop_review_status": "user_confirmed_complete", "ground_truth_status": "pending",
                         "ground_truth": None})
    selection = {
        "selection_version": "1.0", "selection_id": "page17-ten-lines-v1", "dpi": 300,
        "source_detection_run": str(source.relative_to(ROOT)),
        "source_manifest_sha256": digest(source / "manifest.json"),
        "source_lines_sha256": digest(page / "lines.jsonl"), "pdf_sha256": manifest["pdf_sha256"],
        "pdf_filename": "sample_khojki_script_vatiations.pdf", "pdf_page": 17,
        "selected_reading_orders": ORDERS, "include_trailing_numbers": True,
        "confirmed_by": "user", "confirmation": "这 10 行裁剪都完整，可以使用。", "line_count": 10,
        "evaluation_scope": "Selected-line OCR/CER after manual transcription; not full-page detection recall",
        "detection_annotations": "not_performed", "ground_truth_confirmed": False,
        "notes": ["Crop completeness is approved; Unicode transcription is not yet available.",
                  "Order 8 is an ornament and intentionally excluded.",
                  "Page 9 is retained as a qualitative false-positive example, not a main evaluation page.",
                  "Results on this selected clear subset must not be presented as full-collection accuracy."],
        "lines": selected,
    }
    output.mkdir(parents=True, exist_ok=False)
    (output / "crops").mkdir()
    for record in selected:
        (output / record["image_path"]).write_bytes((ROOT / record["source_crop_path"]).read_bytes())
    (output / "selection.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Frozen {len(selected)} approved crops: {output / 'selection.json'}")
    print("Ground Truth remains pending; no detection recall or CER computed.")


if __name__ == "__main__":
    main()
