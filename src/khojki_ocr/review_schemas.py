"""Offline review contracts. T09 has no Ground Truth confirmation operation."""

from typing import Literal

from pydantic import Field

from .schemas import StrictModel, UncertainSpan

REVIEW_VERSION = "review-1.0"


class ReviewEntry(StrictModel):
    line_id: str
    evaluation_order: int
    pdf_page: int
    detection_reading_order: int
    image_path: str
    image_sha256: str
    prediction_state: Literal["candidate_available", "recognition_failed", "result_missing", "not_run"]
    recognition_status: str | None = None
    requested_model: str | None = None
    returned_model: str | None = None
    machine_text: str | None = None
    nfc_text: str | None = None
    codepoints: list[dict] = Field(default_factory=list)
    uncertain_spans: list[UncertainSpan] = Field(default_factory=list)
    unicode_report: dict | None = None
    prediction_sha256: str | None = None
    snapshot_path: str | None = None
    source_file_sha256: str | None = None
    warnings: list[str] = Field(default_factory=list)
    review_status: Literal["pending", "draft"] = "pending"
    latest_draft: dict | None = None
    base_revision: int = 0
    ground_truth_confirmed: Literal[False] = False


class DraftEdit(StrictModel):
    line_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    prediction_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_revision: int = Field(ge=0)
    human_text: str = Field(max_length=10000)
    notes: str = Field(default="", max_length=4000)


class BlankTemplateRow(StrictModel):
    line_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    prediction_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    base_revision: int = Field(ge=0)
    human_text: Literal[None]
    notes: Literal[""]


class SavedDraftEdit(DraftEdit):
    unicode_report: dict


class DraftRevision(StrictModel):
    schema_version: Literal["review-draft-1.0"] = "review-draft-1.0"
    selection_id: str
    selection_sha256: str
    revision: int = Field(ge=1)
    base_revision: int = Field(ge=0)
    previous_revision_sha256: str | None
    bundle_manifest_sha256: str
    reviewer: str = Field(min_length=1, max_length=128)
    created_at: str
    review_status: Literal["draft"] = "draft"
    ground_truth_confirmed: Literal[False] = False
    edits: list[SavedDraftEdit]
