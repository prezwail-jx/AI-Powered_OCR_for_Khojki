"""Version a user-approved sample replacement without overwriting the old selection."""

import argparse
import copy
import hashlib
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_selection(base, output, remove_order, add_order, number, selection_id, reason, *, crop_confirmed, root=ROOT):
    if not crop_confirmed:
        raise ValueError("New crop requires explicit user confirmation")
    if output.exists():
        raise ValueError("Replacement selection already exists; never overwrite")
    prior = json.loads(base.read_text(encoding="utf-8"))
    orders = prior["selected_reading_orders"]
    if remove_order not in orders or add_order in orders or not reason.strip() or selection_id == prior["selection_id"]:
        raise ValueError("Invalid replacement or unchanged selection identity")
    source = root / prior["source_detection_run"]
    lines_file = source / f"pages/page-{prior['pdf_page']:04d}/lines.jsonl"
    if digest(source / "manifest.json") != prior["source_manifest_sha256"] or digest(lines_file) != prior["source_lines_sha256"]:
        raise ValueError("Original detection provenance changed")
    detected = [json.loads(line) for line in lines_file.read_text().splitlines()]
    matches = [r for r in detected if r["reading_order"] == add_order]
    if len(matches) != 1:
        raise ValueError("Replacement order is missing or ambiguous")
    record = matches[0]
    if record["page_number"] != prior["pdf_page"] or record["classification"] != "body" or not record["has_trailing_number_candidate"]:
        raise ValueError("Replacement is not an approved kind of numbered body line")
    source_crop = (lines_file.parent / record["crop_path"]).resolve()
    if not source_crop.is_relative_to(lines_file.parent.resolve()) or digest(source_crop) != record["crop_sha256"]:
        raise ValueError("Replacement crop hash/path mismatch")
    with Image.open(source_crop) as image:
        x0, y0, x1, y1 = record["crop_box"]
        if image.mode != "L" or image.size != (x1 - x0, y1 - y0):
            raise ValueError("Replacement crop dimensions/mode mismatch")
        image.verify()
    removed = next(r for r in prior["lines"] if r["detection_reading_order"] == remove_order)
    rows = [copy.deepcopy(r) for r in prior["lines"] if r is not removed]
    rows.append({"line_id": record["line_id"], "pdf_page": record["page_number"], "detection_reading_order": add_order,
                 "trailing_number_value_for_reference": number, "image_path": f"crops/{source_crop.name}",
                 "image_sha256": record["crop_sha256"], "source_crop_path": str(source_crop.relative_to(root)),
                 "content_box": record["content_box"], "crop_box": record["crop_box"],
                 "page_coordinates": record["page_coordinates"], "original_detection_flags": record["flags"],
                 "crop_review_status": "user_confirmed_complete", "ground_truth_status": "pending", "ground_truth": None})
    rows.sort(key=lambda r: r["detection_reading_order"])
    if len(rows) != prior["line_count"] or len({r["line_id"] for r in rows}) != len(rows):
        raise ValueError("Replacement changed sample count or duplicated identities")
    prior_by_id = {r["line_id"]: r for r in prior["lines"]}
    copies = []
    for index, row in enumerate(rows, 1):
        row["evaluation_order"] = index
        image = base.parent / prior_by_id[row["line_id"]]["image_path"] if row["line_id"] in prior_by_id else source_crop
        if digest(image) != row["image_sha256"]:
            raise ValueError("Retained/replacement crop changed")
        copies.append((row["image_path"], image.read_bytes()))
    selection = copy.deepcopy(prior)
    selection.update({"selection_version": "2.0", "selection_id": selection_id, "lines": rows,
        "selected_reading_orders": [r["detection_reading_order"] for r in rows], "confirmed_by": "user",
        "confirmation": "Nine retained crops previously confirmed; user separately confirmed replacement crop complete and authorized recognition.",
        "supersedes": {"selection_path": str(base.relative_to(root)), "selection_sha256": digest(base),
            "selection_id": prior["selection_id"], "removed_line_id": removed["line_id"],
            "added_line_id": record["line_id"], "reason": reason,
            "policy": "Post-inspection user-directed replacement; old uncertain result remains available, not counted as a proved error."},
        "ground_truth_confirmed": False})
    selection["notes"] = ["User-approved replacement after an unresolved mark in the original sample.",
        "Selection is conditional on manual review, not a random or whole-page accuracy sample.",
        "Original selection and predictions are retained for transparent reporting.",
        "No human confirmation is transferred to the new line; final Ground Truth remains unfrozen."]
    output.mkdir(parents=True, exist_ok=False)
    for name, data in copies:
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (output / "selection.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return selection


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-selection", type=Path, default=ROOT / "data/evaluation/selection.json")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--remove-order", type=int, required=True)
    parser.add_argument("--add-order", type=int, required=True)
    parser.add_argument("--trailing-number", type=int, required=True)
    parser.add_argument("--selection-id", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--crop-confirmed", action="store_true")
    args = parser.parse_args()
    result = replace_selection(args.base_selection.resolve(), args.output_dir.resolve(), args.remove_order, args.add_order,
        args.trailing_number, args.selection_id, args.reason, crop_confirmed=args.crop_confirmed)
    print(f"New selection: {args.output_dir / 'selection.json'}; {result['line_count']} rows; no model calls or Ground Truth freeze")
