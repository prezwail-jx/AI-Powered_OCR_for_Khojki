"""Validated, credential-free pipeline configuration."""

from pathlib import Path
from decimal import Decimal
from datetime import date
from typing import Any, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


def parse_pages(value: str) -> list[int]:
    """Parse 1-based inclusive pages such as '1,3-5', preserving order."""
    pages: list[int] = []
    for part in value.split(","):
        bounds = part.strip().split("-")
        if len(bounds) not in (1, 2) or not all(b.strip().isascii() and b.strip().isdigit() for b in bounds):
            raise ValueError("Pages must use positive numbers or ascending ranges, e.g. 1,3-5")
        start, end = int(bounds[0]), int(bounds[-1])
        if start < 1 or end < start or end > 100000:
            raise ValueError("Pages must be between 1 and 100000 with ascending ranges")
        pages.extend(range(start, end + 1))
    return list(dict.fromkeys(pages))


class PricingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    model: str = Field(min_length=1)
    input_per_million_usd: Decimal = Field(ge=0)
    output_per_million_usd: Decimal = Field(ge=0)
    source_url: str = Field(min_length=1)
    checked_on: date
    max_input_tokens: int = Field(gt=0, le=2000000, strict=True)
    input_bound_basis: str = Field(min_length=1)

    @field_validator("source_url")
    @classmethod
    def validate_source(cls, value: str) -> str:
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query:
            raise ValueError("Pricing source must be HTTPS without credentials/query")
        return value

    @field_validator("checked_on")
    @classmethod
    def validate_date(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("Pricing verification date cannot be in the future")
        return value


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: str = Field(min_length=1)
    base_url: str
    timeout_seconds: float = Field(default=60, gt=0, le=600)
    max_output_tokens: int = Field(default=4096, gt=0, le=131072)
    image_detail: str = Field(default="original", pattern="^(original|high|low|auto)$")
    openai_service_tier: Literal["default"] | None = None
    openai_cache_mode: Literal["explicit"] | None = None
    pricing: PricingConfig | None = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Base URL must be HTTPS without credentials, query or fragment")
        return value.rstrip("/")


class PreprocessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    deskew: bool = True
    max_skew_degrees: float = Field(default=5.0, gt=0, le=10)
    deskew_min_gain: float = Field(default=0.10, ge=0, le=1)
    deskew_min_angle: float = Field(default=0.15, ge=0, le=1)
    angle_override: float | None = Field(default=None, ge=-10, le=10)
    denoise: bool = False
    clahe_clip_limit: float = Field(default=2.0, gt=0, le=10)
    clahe_grid_size: int = Field(default=8, ge=2, le=32)
    adaptive_block_size: int = Field(default=51, ge=3, le=301)
    adaptive_c: float = Field(default=15, ge=0, le=50)
    max_page_pixels: int = Field(default=40000000, ge=1000, le=100000000)

    @field_validator("adaptive_block_size")
    @classmethod
    def validate_block_size(cls, value: int) -> int:
        if value % 2 == 0:
            raise ValueError("Adaptive threshold block size must be odd")
        return value


class LineDetectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    max_work_width: int = Field(default=1600, ge=400, le=2400)
    min_intensity_range: int = Field(default=16, ge=1, le=100)
    background_sigma_ratio: float = Field(default=0.015, gt=0, le=0.1)
    min_component_height_ratio: float = Field(default=0.004, gt=0, le=0.02)
    row_center_tolerance: float = Field(default=0.65, gt=0, le=1)
    gutter_min_char_heights: float = Field(default=3.0, ge=2, le=10)
    mark_recovery_margin: float = Field(default=0.55, ge=0, le=1)
    crop_padding_x: float = Field(default=0.25, ge=0, le=1)
    crop_padding_y: float = Field(default=0.20, ge=0, le=1)


class RecognitionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    reference_dir: Path = Path("outputs/references-v1")
    reference_files: list[str] = Field(default_factory=lambda: [
        "vowels.png", "consonants.png", "marks.png", "punctuation.png", "digits.png",
        "matrix-01.png", "matrix-02.png", "matrix-03.png"])
    cache_dir: Path = Path(".cache/recognition")
    ledger_path: Path = Path(".cache/api-budget.json")
    budget_usd: Decimal = Field(default=Decimal("15"), gt=0, le=15)
    max_attempts: int = Field(default=2, ge=1, le=3, strict=True)
    retry_base_seconds: float = Field(default=1.0, ge=0, le=30)
    max_retry_delay_seconds: float = Field(default=30.0, ge=0, le=120)

    @field_validator("reference_files")
    @classmethod
    def unique_references(cls, value):
        if not value or len(value) != len(set(value)):
            raise ValueError("Reference files must be nonempty and unique")
        if any(Path(name).name != name or not name.endswith(".png") for name in value):
            raise ValueError("Reference files must be PNG basenames")
        return value


class PipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pdf: Path = Path("sample_khojki_script_vatiations.pdf")
    pages: str = "1"
    output_dir: Path = Path("outputs")
    dpi: int = Field(default=300, ge=72, le=600, strict=True)
    preprocess: PreprocessConfig = Field(default_factory=PreprocessConfig)
    line_detection: LineDetectionConfig = Field(default_factory=LineDetectionConfig)
    recognition: RecognitionConfig = Field(default_factory=RecognitionConfig)
    openai: ProviderConfig = Field(default_factory=lambda: ProviderConfig(
        model="gpt-6.1-sol", base_url="https://api.openai.com/v1"))
    deepseek: ProviderConfig = Field(default_factory=lambda: ProviderConfig(
        model="deepseek-flash", base_url="https://api.deepseek.com"))

    @field_validator("pages")
    @classmethod
    def validate_pages(cls, value: str) -> str:
        parse_pages(value)
        return value


def load_config(path: Path | None = None, overrides: dict[str, Any] | None = None) -> PipelineConfig:
    data: dict[str, Any] = {}
    if path is not None:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if loaded is not None and not isinstance(loaded, dict):
            raise ValueError("Configuration must be a YAML mapping")
        data = loaded or {}
    data.update({key: value for key, value in (overrides or {}).items() if value is not None})
    return PipelineConfig.model_validate(data)
