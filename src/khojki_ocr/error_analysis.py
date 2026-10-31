"""Offline evidence-bound error attribution and qualitative challenge packaging."""

import hashlib
import shutil
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageOps
from pydantic import Field, model_validator

from .evaluation import verify_evaluation
from .review import parse_json
from .relocation import source_path
from .runtime import RunContext
from .schemas import RecognitionResult, StrictModel
from .storage import atomic_json, canonical_json

ANALYSIS_VERSION = "t13-error-analysis-1.0"
STAGES = ("line_detection", "character_recognition", "unicode_mapping", "unknown_or_mixed")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Evidence(StrictModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Edit(StrictModel):
    operation: Literal["substitution", "deletion", "insertion"]
    hypothesis_index: int = Field(ge=0)
    codepoint: str = Field(pattern=r"^U\+[0-9A-F]{4,6}$")


class AttributionCase(StrictModel):
    case_id: str = Field(min_length=1)
    scope: Literal["main_ocr_error", "qualitative_detection_case"]
    stage: Literal["line_detection", "character_recognition", "unicode_mapping", "unknown_or_mixed"]
    evidence_strength: Literal["supported", "qualitative", "insufficient"]
    included_in_main_cer: bool
    line_id: str
    summary: str = Field(min_length=1)
    support: list[str] = Field(min_length=1)
    excluded_stages: dict[str, str]
    edit: Edit | None
    character_pixel_box: list[int] | None
    evidence: list[Evidence] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent_scope(self):
        if not self.summary.strip() or any(not value.strip() for value in self.support):
            raise ValueError("Attribution summary and supporting reasons must be nonempty")
        if any(not value.strip() for value in self.excluded_stages.values()):
            raise ValueError("Excluded stages require nonempty reasons")
        if self.scope == "main_ocr_error" and not self.included_in_main_cer:
            raise ValueError("Main OCR errors must be included in main CER")
        if self.scope != "main_ocr_error" and self.included_in_main_cer:
            raise ValueError("Qualitative cases cannot enter main CER")
        if self.character_pixel_box is not None and len(self.character_pixel_box) != 4:
            raise ValueError("Character pixel box must have four coordinates")
        if any(stage not in STAGES for stage in self.excluded_stages):
            raise ValueError("Unknown excluded stage")
        return self


class AttributionBundle(StrictModel):
    attribution_version: str
    evaluation_run: str
    main_cer: dict
    annotation_method: str
    cases: list[AttributionCase]
    limits: list[str]

    @model_validator(mode="after")
    def unique_cases(self):
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("Duplicate attribution case")
        if sum(case.scope == "main_ocr_error" for case in self.cases) != 1:
            raise ValueError("Exactly one main OCR error is required for frozen T12")
        return self


def _inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Evidence path escapes project root")
    return path


def _jsonl_record(path, line_id):
    records = [parse_json(line) for line in path.read_bytes().splitlines()]
    matches = [record for record in records if record.get("line_id") == line_id]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one saved line record for {line_id}")
    return matches[0]


def freeze_challenge_set(root, selection_path, output_dir):
    root = root.resolve()
    selection_path = selection_path.resolve()
    output_dir = output_dir.resolve()
    if not output_dir.is_relative_to(root):
        raise ValueError("Frozen challenge set must stay inside the project root")
    if output_dir.exists():
        raise ValueError("Challenge set already exists; never overwrite a frozen set")
    selection = parse_json(selection_path.read_bytes())
    if (selection.get("scope") != "qualitative_manuscript_detection_only" or selection.get("api_calls") != 0
            or selection.get("recognition_performed") is not False or selection.get("ground_truth_available") is not False
            or selection.get("cer_available") is not False or len(selection.get("lines", [])) != 2):
        raise ValueError("Challenge selection must contain exactly two offline qualitative manuscript lines")
    if len({line["pdf_page"] for line in selection["lines"]}) != 2:
        raise ValueError("Manuscript challenges must come from two different pages")
    if (len({line["challenge_id"] for line in selection["lines"]}) != 2
            or any(line["challenge_id"] not in ("manuscript-01", "manuscript-02") for line in selection["lines"])):
        raise ValueError("Challenge identifiers must be unique manuscript-01 and manuscript-02")
    pending = output_dir.with_name(f".{output_dir.name}.pending")
    if pending.exists():
        raise ValueError("Pending challenge freeze already exists")
    try:
        pending.mkdir(parents=True)
        crops = pending / "crops"
        crops.mkdir()
        frozen = []
        images = []
        for line in selection["lines"]:
            if line["pdf_page"] not in range(1, 7):
                raise ValueError("Manuscript challenge page must be in the documented page 1-6 range")
            lines_path = _inside(root, line["source_lines_path"])
            crop_path = _inside(root, line["source_crop_path"])
            if sha(lines_path) != line["source_lines_sha256"] or sha(crop_path) != line["source_crop_sha256"]:
                raise ValueError("Challenge source hash mismatch")
            record = _jsonl_record(lines_path, line["line_id"])
            if (record["page_number"] != line["pdf_page"] or record["reading_order"] != line["reading_order"]
                    or record["classification"] != "body" or record["crop_sha256"] != line["source_crop_sha256"]):
                raise ValueError("Challenge line metadata mismatch")
            target = crops / f"{line['challenge_id']}.png"
            shutil.copyfile(crop_path, target)
            images.append((line["challenge_id"], Image.open(target).convert("RGB")))
            final_target = output_dir / "crops" / target.name
            frozen.append({**line, "frozen_crop_path": str(final_target.relative_to(root)), "frozen_crop_sha256": sha(target),
                           "detector_classification": record["classification"], "detector_flags": record["flags"],
                           "included_in_main_metrics": False})
        width, panel_height = 1200, 260
        sheet = Image.new("RGB", (width, panel_height * len(images)), "white")
        draw = ImageDraw.Draw(sheet)
        for index, (label, image) in enumerate(images):
            fitted = ImageOps.contain(image, (width - 30, panel_height - 35))
            y = index * panel_height
            sheet.paste(fitted, (15, y + 25))
            draw.text((15, y + 7), label, fill="black")
        sheet_path = pending / "contact-sheet.png"
        sheet.save(sheet_path, optimize=True)
        final_sheet = output_dir / sheet_path.name
        manifest = {"stage": "t13_manuscript_challenge_freeze", "version": selection["selection_version"],
                    "scope": selection["scope"], "status": "completed", "api_calls": 0, "line_count": 2,
                    "ground_truth_available": False, "recognition_performed": False, "cer_available": False,
                    "selection_path": str(selection_path), "selection_sha256": sha(selection_path), "lines": frozen,
                    "contact_sheet": str(final_sheet.relative_to(root)), "contact_sheet_sha256": sha(sheet_path)}
        atomic_json(pending / "manifest.json", manifest)
        pending.replace(output_dir)
        return manifest
    except Exception:
        shutil.rmtree(pending, ignore_errors=True)
        raise


def validate_challenge_set(root, manifest_path):
    manifest = parse_json(manifest_path.read_bytes())
    if (manifest.get("stage") != "t13_manuscript_challenge_freeze"
            or manifest.get("scope") != "qualitative_manuscript_detection_only"
            or manifest.get("status") != "completed" or manifest.get("api_calls") != 0 or manifest.get("line_count") != 2
            or len(manifest.get("lines", [])) != 2
            or manifest.get("ground_truth_available") is not False or manifest.get("recognition_performed") is not False
            or manifest.get("cer_available") is not False):
        raise ValueError("Invalid frozen qualitative challenge manifest")
    if sha(source_path(manifest["selection_path"])) != manifest["selection_sha256"]:
        raise ValueError("Challenge selection hash mismatch")
    selection = parse_json(source_path(manifest["selection_path"]).read_bytes())
    if len({line["pdf_page"] for line in manifest["lines"]}) != 2 or len(selection["lines"]) != 2:
        raise ValueError("Two distinct manuscript pages are required")
    for line, selected in zip(manifest["lines"], selection["lines"]):
        if (line["pdf_page"] not in range(1, 7) or line["included_in_main_metrics"] is not False
                or any(line.get(key) != value for key, value in selected.items())):
            raise ValueError("Frozen challenge line disagrees with qualitative selection")
        source_lines = _inside(root, line["source_lines_path"])
        source_crop = _inside(root, line["source_crop_path"])
        if sha(source_lines) != line["source_lines_sha256"] or sha(source_crop) != line["source_crop_sha256"]:
            raise ValueError("Manuscript challenge source hash mismatch")
        record = _jsonl_record(source_lines, line["line_id"])
        if (record["classification"] != "body" or record["page_number"] != line["pdf_page"]
                or record["reading_order"] != line["reading_order"] or record["flags"] != line["detector_flags"]):
            raise ValueError("Manuscript challenge source metadata mismatch")
        if (sha(_inside(root, line["frozen_crop_path"])) != line["frozen_crop_sha256"]
                or line["frozen_crop_sha256"] != line["source_crop_sha256"]):
            raise ValueError("Frozen challenge crop hash mismatch")
        if any(key in line for key in ("prediction", "reference", "cer")):
            raise ValueError("Qualitative manuscript line cannot contain recognition or CER fields")
    if sha(_inside(root, manifest["contact_sheet"])) != manifest["contact_sheet_sha256"]:
        raise ValueError("Challenge contact sheet hash mismatch")
    return manifest


def _analyze(root, attribution_path, challenge_path, evaluation_path):
    root = root.resolve()
    attribution_path = attribution_path.resolve()
    challenge_path = challenge_path.resolve()
    evaluation_path = evaluation_path.resolve()
    bundle = AttributionBundle.model_validate(parse_json(attribution_path.read_bytes()))
    challenge = validate_challenge_set(root, challenge_path)
    _, evaluation, evaluated_lines = verify_evaluation(evaluation_path)
    if (bundle.evaluation_run != str(evaluation_path.relative_to(root))
            or evaluation["micro_cer"] != bundle.main_cer or evaluation["distance"] != 1):
        raise ValueError("Attribution does not bind to the frozen T12 result")
    for case in bundle.cases:
        for evidence in case.evidence:
            if sha(_inside(root, evidence.path)) != evidence.sha256:
                raise ValueError(f"Evidence hash mismatch for {case.case_id}")
    main = next(case for case in bundle.cases if case.scope == "main_ocr_error")
    if (main.line_id != "p0017-l015-e38c91e25be6" or main.stage != "character_recognition"
            or main.character_pixel_box is not None or main.edit is None
            or main.edit.operation != "insertion" or main.edit.hypothesis_index != 21 or main.edit.codepoint != "U+11235"):
        raise ValueError("Frozen main attribution must remain the supported line15 U+11235 recognition insertion")
    alignment_path = _inside(root, next(e.path for e in main.evidence if "/alignments/" in e.path))
    edits = [op for op in parse_json(alignment_path.read_bytes())["alignment"] if op["operation"] != "match"]
    if (len(edits) != 1 or edits[0]["operation"] != "insertion" or edits[0]["hypothesis_index"] != 21
            or edits[0]["hypothesis"]["codepoint"] != "U+11235"):
        raise ValueError("T12 alignment no longer supports the declared attribution")
    prediction_path = _inside(root, next(e.path for e in main.evidence if "/predictions/" in e.path))
    prediction = RecognitionResult.model_validate(parse_json(prediction_path.read_bytes()))
    evaluated = next(line for line in evaluated_lines if line["line_id"] == main.line_id)
    truth_path = _inside(root, next(e.path for e in main.evidence if e.path.endswith("ground_truth.jsonl")))
    truth_line = _jsonl_record(truth_path, main.line_id)
    crop_path = _inside(root, next(e.path for e in main.evidence if e.path.endswith(".png")))
    if (prediction.line_id != main.line_id or prediction.candidate is None
            or prediction.candidate.text != evaluated["hypothesis_raw"]
            or truth_line["text"] != evaluated["reference_raw"]
            or sha(crop_path) != truth_line["image_sha256"]):
        raise ValueError("Main attribution prediction, truth and image bindings disagree")
    if not any(span.start == 21 and span.end == 22 for span in prediction.candidate.uncertain_spans):
        raise ValueError("Saved model uncertainty no longer supports line15 attribution")
    main_lines_path = _inside(root, next(e.path for e in main.evidence if "page-0017/lines.jsonl" in e.path))
    main_line = _jsonl_record(main_lines_path, main.line_id)
    if main_line["classification"] != "body" or main_line["flags"]:
        raise ValueError("Saved detector record no longer supports excluding line detection for line15")
    detection = [case for case in bundle.cases if case.scope == "qualitative_detection_case"]
    if len(detection) != 2 or any(case.stage != "line_detection" or case.included_in_main_cer for case in detection):
        raise ValueError("Exactly two qualitative page-9 detection cases are required")
    expected_detection = {
        "p0009-l010-9eee9db3825d": {"ambiguous_mark", "decoration_overlap", "few_text_anchors", "overlapping_line_content"},
        "p0009-l009-99b5a8f5d214": {"ambiguous_mark", "decoration_overlap", "overlapping_line_content", "possible_truncation"},
    }
    if {case.line_id for case in detection} != set(expected_detection):
        raise ValueError("Unexpected qualitative page-9 detection case set")
    for case in detection:
        lines_path = _inside(root, next(e.path for e in case.evidence if "page-0009/lines.jsonl" in e.path))
        if "20261030T154140Z-29d2de257bd5" not in str(lines_path):
            raise ValueError("Detection cases must use the approved 400 DPI source run")
        record = _jsonl_record(lines_path, case.line_id)
        if not expected_detection[case.line_id].issubset(record["flags"]):
            raise ValueError("Saved page-9 flags no longer support the qualitative detection case")
    counts = {stage: sum(case.stage == stage for case in bundle.cases if case.scope == "main_ocr_error") for stage in STAGES}
    summary = {"analysis_version": ANALYSIS_VERSION, "main_error_count": 1, "main_attribution_counts": counts,
               "qualitative_detection_cases": len(detection), "qualitative_manuscript_cases": challenge["line_count"],
               "unicode_mapping_observed": counts["unicode_mapping"], "detection_metrics_measured": False,
               "main_cer": evaluation["micro_cer"], "main_cer_changed": False, "api_calls": 0,
               "new_cost_usd": "0", "limitations": bundle.limits}
    cases = [case.model_dump(mode="json") for case in bundle.cases]
    cases.extend({"case_id": line["challenge_id"], "scope": "qualitative_manuscript_challenge",
                  "stage": "unknown_or_mixed", "included_in_main_cer": False, "line_id": line["line_id"],
                  "pdf_page": line["pdf_page"], "summary": line["selection_reason"],
                  "known_detection_limits": line["known_detection_limits"], "recognition_performed": False,
                  "ground_truth_available": False, "cer_available": False,
                  "crop_path": line["frozen_crop_path"], "crop_sha256": line["frozen_crop_sha256"]}
                 for line in challenge["lines"])
    return bundle, challenge, summary, cases


def render_report(summary, cases):
    detection = [case for case in cases if case["scope"] == "qualitative_detection_case"]
    manuscripts = [case for case in cases if case["scope"] == "qualitative_manuscript_challenge"]
    return f"""# T13 Evidence-Based Error Attribution

## Attribution policy

| Stage | Evidence required |
|---|---|
| `line_detection` | Missing/merged lines, clipped content or non-text/margin regions emitted as lines. |
| `character_recognition` | A visual character identity or presence decision disagrees with the confirmed reference. |
| `unicode_mapping` | Evidence supports the visual character identity but its scalar or encoding sequence is wrong. |
| `unknown_or_mixed` | Saved evidence cannot distinguish stages; no forced causal label. |

These labels describe the supported interpretation of saved evidence. Model
uncertainty explanations are supporting observations, not internal reasoning.

## Main OCR error

The frozen ten-line evaluation contains one error: line15 has an extra U+11235 at
hypothesis index 21. It is attributed to **character recognition**, not line
detection: the user-approved crop is complete, its detector record has no flags,
and the model itself marked `[21,22)` uncertain because a small lower mark was
indistinct. There is no evidence that the model identified a correct visible
character and merely encoded the wrong scalar, so this is not classified as a
Unicode-mapping error. Text offsets are not claimed as character pixel boxes.

Main attribution counts: line detection {summary['main_attribution_counts']['line_detection']},
character recognition {summary['main_attribution_counts']['character_recognition']}, Unicode
mapping {summary['main_attribution_counts']['unicode_mapping']}, unknown/mixed
{summary['main_attribution_counts']['unknown_or_mixed']}. One event is not a stable error distribution.

## Qualitative detection cases

- `{detection[0]['line_id']}`: {detection[0]['summary']}
- `{detection[1]['line_id']}`: {detection[1]['summary']}

Page 9 has no complete manual line-box annotation. These examples demonstrate
failure modes but do not provide precision, recall, IoU, false-positive rate or a
detection CER delta.

## Qualitative manuscript challenge

- `{manuscripts[0]['line_id']}` (page {manuscripts[0]['pdf_page']}): {manuscripts[0]['summary']}
- `{manuscripts[1]['line_id']}` (page {manuscripts[1]['pdf_page']}): {manuscripts[1]['summary']}

No recognition or human transcription was performed for these manuscript crops,
so no accuracy or CER is reported and they are excluded from the printed main set.
The page-1 left-boundary truncation was found during visual inspection despite
an empty detector flag list. The user explicitly accepted this as a qualitative
detection-failure example, revising the earlier complete-crop selection rule.

## Evidence figures

![Original line15 input crop; no character pixel boxes claimed](assets/line15.png)

![Page 9 detection overlay at 400 DPI; inspect candidates 9 and 10](assets/page9-overlay.png)

![Two manuscript challenge crops; qualitative only](assets/manuscript-contact-sheet.png)

`cases.jsonl` links the original hashed predictions, alignment, truth and detection
records. The main attribution is a supported human-reviewed judgment, not proof
of the model's internal reasoning or a controlled causal experiment. The main
reference remains model-assisted user review with selection and anchoring bias.

## Reproducibility and boundaries

The OpenAI main CER remains {summary['main_cer']['numerator']}/{summary['main_cer']['denominator']}
= {summary['main_cer']['decimal']}. Zero observed Unicode-mapping errors means only
that none was confirmed in this selected set; it does not remove the risk. All
evidence and challenge crops are hash-bound. T13 is offline, made zero API calls
and added USD 0 cost.
"""


def analyze_run(root, attribution_path, challenge_path, evaluation_path, run: RunContext):
    bundle, challenge, summary, cases = _analyze(root, attribution_path, challenge_path, evaluation_path)
    assets = run.directory / "assets"
    assets.mkdir()
    main = next(case for case in bundle.cases if case.scope == "main_ocr_error")
    detection = next(case for case in bundle.cases if case.scope == "qualitative_detection_case")
    images = {
        "line15.png": next(e.path for e in main.evidence if e.path.endswith(".png")),
        "page9-overlay.png": next(e.path for e in detection.evidence if e.path.endswith("lines-overlay.png")),
        "manuscript-contact-sheet.png": challenge["contact_sheet"],
    }
    for name, source in images.items():
        shutil.copyfile(_inside(root, source), assets / name)
    atomic_json(run.directory / "summary.json", summary)
    (run.directory / "cases.jsonl").write_text("".join(canonical_json(case) + "\n" for case in cases), encoding="utf-8")
    (run.directory / "report.md").write_text(render_report(summary, cases), encoding="utf-8")
    sources = [attribution_path, challenge_path, evaluation_path / "summary.json"]
    manifest = {"stage": "t13_error_analysis", "status": "completed", "analysis_version": ANALYSIS_VERSION,
                "run_id": run.run_id, "api_calls": 0, "attribution_path": str(attribution_path.resolve()),
                "challenge_path": str(challenge_path.resolve()), "evaluation_path": str(evaluation_path.resolve()),
                "source_hashes": {str(path.resolve()): sha(path.resolve()) for path in sources},
                "files": {str(path.relative_to(run.directory)): sha(path) for path in run.directory.rglob("*") if path.is_file()}}
    atomic_json(run.directory / "manifest.json", manifest)
    verify_error_analysis(root, run.directory)
    return manifest, summary


def verify_error_analysis(root, directory):
    manifest = parse_json((directory / "manifest.json").read_bytes())
    if manifest.get("status") != "completed" or manifest.get("stage") != "t13_error_analysis" or manifest.get("api_calls") != 0:
        raise ValueError("Not a completed offline T13 analysis")
    for name, digest in manifest["source_hashes"].items():
        if sha(source_path(name)) != digest:
            raise ValueError("T13 source hash mismatch")
    for name, digest in manifest["files"].items():
        if sha(directory / name) != digest:
            raise ValueError("T13 artifact hash mismatch")
    _, _, summary, cases = _analyze(root, source_path(manifest["attribution_path"]), source_path(manifest["challenge_path"]),
                                     source_path(str(Path(manifest["evaluation_path"]) / "manifest.json")).parent)
    if parse_json((directory / "summary.json").read_bytes()) != summary:
        raise ValueError("T13 summary does not recompute")
    saved_cases = [parse_json(line) for line in (directory / "cases.jsonl").read_bytes().splitlines()]
    if saved_cases != cases:
        raise ValueError("T13 cases do not recompute")
    return manifest, summary, cases
