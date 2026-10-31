"""Bind explicit user confirmations to unchanged predictions in a replacement set.

This creates a checkpoint, not frozen Ground Truth or an automatic confirmation
of the newly added row. No model clients are constructed.
"""

import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from khojki_ocr.review import verify_bundle
from khojki_ocr.storage import atomic_json


def transfer(source_bundle, target_bundle, checkpoint, orders, output):
    source, _, old = verify_bundle(source_bundle)
    target, _, new = verify_bundle(target_bundle)
    text = checkpoint.read_text(encoding="utf-8")
    confirmation = "B：其他 9 行也已逐字符核对正确，只剩 l015 的疑点。"
    if confirmation not in text or source["selection_id"] not in text:
        raise ValueError("Explicit user confirmation/source selection is not in the checkpoint")
    if output.exists():
        raise ValueError("Confirmation checkpoint already exists; do not overwrite")
    approved = {e.line_id: e for e in old if e.detection_reading_order in orders}
    if len(approved) != len(orders) or len(approved) != 9 or 15 in orders:
        raise ValueError("Expected the nine explicitly confirmed original rows, excluding line15")
    if not set(approved).issubset({e.line_id for e in new}):
        raise ValueError("A previously confirmed row disappeared")
    rows = []
    for entry in new:
        prior = approved.get(entry.line_id)
        if prior is not None and (entry.image_sha256 != prior.image_sha256 or entry.prediction_sha256 != prior.prediction_sha256
                                  or entry.machine_text != prior.machine_text or entry.machine_text is None):
            raise ValueError("Cannot transfer confirmation to changed image/prediction/text")
        rows.append({"line_id": entry.line_id, "evaluation_order": entry.evaluation_order,
            "detection_reading_order": entry.detection_reading_order, "image_sha256": entry.image_sha256,
            "prediction_sha256": entry.prediction_sha256,
            "human_status": "user_reported_confirmed" if prior else "pending",
            "user_accepted_text": prior.machine_text if prior else None,
            "confirmation_source": "Explicit user statement in conversation, model-assisted visual review" if prior else None,
            "ground_truth_frozen": False})
    output.parent.mkdir(parents=True, exist_ok=True)
    snapshot = output.parent / "source-confirmation-checkpoint.md"
    if snapshot.exists():
        raise ValueError("Confirmation source snapshot already exists")
    snapshot.write_bytes(checkpoint.read_bytes())
    report = {"stage": "human_confirmation_transfer", "created_at": datetime.now(timezone.utc).isoformat(),
        "reviewer": "user_in_conversation", "review_duration": None, "ground_truth_frozen": False,
        "source_selection_id": source["selection_id"], "target_selection_id": target["selection_id"],
        "source_bundle": str(source_bundle), "target_bundle": str(target_bundle),
        "source_confirmation_quote": confirmation,
        "confirmation_snapshot": snapshot.name, "confirmation_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        "source_manifest_sha256": hashlib.sha256((source_bundle / "manifest.json").read_bytes()).hexdigest(),
        "target_manifest_sha256": hashlib.sha256((target_bundle / "manifest.json").read_bytes()).hexdigest(),
        "confirmed_count": len(approved), "pending_count": len(rows) - len(approved), "rows": rows,
        "note": "Nine unchanged user confirmations carried forward by line/image/prediction identity; replacement must be reviewed separately. Not a final Ground Truth file."}
    atomic_json(output, report)
    print(f"Transferred {len(approved)} confirmations, {report['pending_count']} pending; no Ground Truth freeze. {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-bundle", type=Path, required=True)
    parser.add_argument("--target-bundle", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--confirmed-orders", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    transfer(args.source_bundle, args.target_bundle, args.checkpoint,
             {int(n) for n in args.confirmed_orders.split(",")}, args.output)
