"""Strict model-output contract and provider-neutral response records."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "ocr-1.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class UncertainSpan(StrictModel):
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    alternatives: list[str]
    reason: str


class OCRPayload(StrictModel):
    text: str = Field(max_length=10000)
    uncertain_spans: list[UncertainSpan]
    unreadable: bool

    @model_validator(mode="after")
    def valid_spans(self):
        for span in self.uncertain_spans:
            if not 0 <= span.start < span.end <= len(self.text):
                raise ValueError("Uncertainty spans must index raw text in Unicode code points")
        return self


class TokenUsage(StrictModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def check_subsets(self):
        if ((self.cached_input_tokens is not None and self.cached_input_tokens > self.input_tokens)
                or (self.reasoning_tokens is not None and self.reasoning_tokens > self.output_tokens)):
            raise ValueError("Usage detail cannot exceed its total")
        return self


class ProviderResponse(StrictModel):
    state: Literal["completed", "refused", "truncated", "schema_error", "transport_error"]
    raw_text: str = ""
    returned_model: str | None = None
    request_id: str | None = None
    usage: TokenUsage | None = None
    usage_warning: bool = False
    billing_metadata: dict = Field(default_factory=dict)


class RecognitionResult(StrictModel):
    line_id: str
    provider: Literal["openai", "deepseek"]
    requested_model: str
    returned_model: str | None = None
    cache_key: str
    status: Literal["succeeded", "needs_review", "refused", "empty_output", "truncated", "schema_error",
                    "timeout", "rate_limited", "transport_error", "budget_blocked", "authentication_error",
                    "request_error", "model_unavailable", "cache_error"]
    raw_response_text: str = ""
    candidate: OCRPayload | None = None
    codepoints: list[str] = Field(default_factory=list)
    unicode_report: dict | None = None
    usage: TokenUsage | None = None
    request_id: str | None = None
    elapsed_seconds: float = Field(default=0.0, ge=0)
    cache_hit: bool = False
    attempts: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    cost: dict = Field(default_factory=dict)
    billing_metadata: dict = Field(default_factory=dict)
