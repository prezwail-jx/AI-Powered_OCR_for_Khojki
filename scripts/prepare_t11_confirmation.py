"""Record the specific final user decision: restore v1 and accept l015 option B.

Requires the explicit decision flag. This is a recorded conversation approval,
not an inference-based or automatic truth-labeling command.
"""

import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from khojki_ocr.ground_truth import HumanConfirmation
from khojki_ocr.review import verify_bundle
from khojki_ocr.storage import atomic_json

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "outputs/20261030T211104Z-ac77dcd92108"
SELECTION = ROOT / "data/evaluation/selection.json"
LINE = "p0017-l015-e38c91e25be6"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accept-original-v1-with-l015-deletion", action="store_true", required=True)
    args = parser.parse_args()
    manifest, manifest_sha, entries = verify_bundle(BUNDLE)
    assert manifest["selection_id"] == "page17-ten-lines-v1" and len(entries) == 10
    assert hashlib.sha256(SELECTION.read_bytes()).hexdigest() == manifest["selection_sha256"]
    rows = []
    for entry in entries:
        text = entry.machine_text
        assert text is not None and entry.prediction_state == "candidate_available"
        if entry.line_id == LINE:
            assert text[21] == "\U00011235" and text.count("\U00011235") == 1
            text = text[:21] + text[22:]
            comparison = ROOT / "outputs/20261030T221931Z-f5afa6843c01/proposed-not-confirmed.txt"
            assert text.encode("utf-8") == comparison.read_bytes()
        rows.append({"line_id": entry.line_id, "image_sha256": entry.image_sha256,
            "prediction_sha256": entry.prediction_sha256, "human_text": text, "confirmed": True})
    approval = HumanConfirmation.model_validate({"stage": "explicit_human_confirmation",
        "selection_id": manifest["selection_id"], "selection_sha256": manifest["selection_sha256"],
        "review_manifest_sha256": manifest_sha, "reviewer": "user_in_conversation",
        "recorded_at": datetime.now(timezone.utc).isoformat(), "annotation_duration_seconds": None,
        "method": "model_assisted_user_visual_review", "statements": [
            "B：其他 9 行也已逐字符核对正确，只剩 l015 的疑点。",
            "用户最终选择：确认，采用 B 并冻结 v1。",
            "最终确认的具体范围：恢复原版 v1 十行（使用 line15，不使用 line18）；接受对照页 B 的整行文本作为 line15 最终人工转录，仅删除 U+11235，其余字符保持不变（包括第四组 II）；结合已确认的其他九行冻结真值。",
            "模型辅助用户视觉核对，非独立盲转录。人工核对起止时间、姓名及耗时未提供；recorded_at 仅为确认入档时间。"
        ], "lines": rows})
    folder = ROOT / "data/annotations/confirmations"
    target, guard_path = folder / "page17-ten-lines-v1-final.json", folder / "t11-source-guard.json"
    if target.exists() or guard_path.exists():
        raise ValueError("Final decision already recorded; never overwrite")
    guarded = [SELECTION, ROOT / "data/evaluation/v2/selection.json", ROOT / ".cache/api-budget.json",
               ROOT / "outputs/20261030T220010Z-5f33329394a2/results/openai-p0017-l018-3fac6e9e7454.json"]
    guarded += sorted((ROOT / ".cache/recognition").glob("*.json"))
    guarded += sorted((ROOT / "outputs/20261030T210414Z-23bc6581d98c/results").glob("*.json"))
    atomic_json(guard_path, {"stage": "pre_truth_freeze_guard", "api_calls": 0,
        "files": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in guarded}})
    atomic_json(target, approval.model_dump(mode="json"))
    print(f"Recorded explicit final confirmation: {target}; {len(rows)} lines, one proposed deletion accepted.")
    print("No API calls, no source prediction changes; freezing requires the separate freeze-truth --confirm command.")


if __name__ == "__main__":
    main()
