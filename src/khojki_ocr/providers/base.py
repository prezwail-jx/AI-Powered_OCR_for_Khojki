"""Immutable verified inputs and explicit, non-logging transport helpers."""

import base64
import hashlib
import io
import os
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from ..config import ProviderConfig
from ..prompts import PROMPT_VERSION, SYSTEM_PROMPT
from ..schemas import OCRPayload, SCHEMA_VERSION, TokenUsage
from ..storage import content_hash
from ..unicode_rules import UNICODE_VERSION, asset_bytes


@dataclass(frozen=True)
class ImageInput:
    label: str
    data: bytes = field(repr=False)
    sha256: str
    width: int
    height: int

    @classmethod
    def read(cls, path: Path, label: str, expected: str):
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected:
            raise ValueError(f"Image hash mismatch: {label}")
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG":
                raise ValueError("Only verified PNG inputs are supported")
            width, height = image.size
            image.verify()
        return cls(label, data, digest, width, height)

    def data_url(self):
        return "data:image/png;base64," + base64.b64encode(self.data).decode("ascii")

    def summary(self):
        return {"label": self.label, "sha256": self.sha256, "width": self.width, "height": self.height, "bytes": len(self.data)}


@dataclass(frozen=True)
class PreparedRequest:
    line_id: str
    provider: str
    settings: ProviderConfig
    images: tuple[ImageInput, ...] = field(repr=False)
    system_prompt: str = SYSTEM_PROMPT

    def identity(self):
        return {"provider": self.provider, "protocol": "responses" if self.provider == "openai" else "chat.completions",
                "settings": self.settings.model_dump(mode="json", exclude={"pricing"}),
                "images": [image.summary() for image in self.images], "prompt": self.system_prompt,
                "prompt_version": PROMPT_VERSION, "schema_version": SCHEMA_VERSION,
                "schema": OCRPayload.model_json_schema(), "unicode_version": UNICODE_VERSION,
                "policy_sha256": hashlib.sha256(asset_bytes("unicode", "transcription_rules.json")).hexdigest(),
                "characters_sha256": hashlib.sha256(asset_bytes("unicode", "characters.json")).hexdigest(),
                "adapter_version": "1.1", "deepseek_thinking": "disabled" if self.provider == "deepseek" else None}

    @property
    def cache_key(self):
        return content_hash(self.identity())


class Adapter:
    provider = ""
    key_variable = ""

    def __init__(self, client=None):
        self.client = client
        self._injected = client is not None
        self._connection = None

    def preflight(self, request):
        if self._injected:
            return
        key = os.environ.get(self.key_variable)
        if not key or key.startswith("replace-with-"):
            raise ValueError(f"Missing {self.key_variable}; configure it locally")
        connection = (request.settings.base_url, request.settings.timeout_seconds, hashlib.sha256(key.encode()).hexdigest())
        if self.client is None or self._connection != connection:
            from openai import OpenAI

            self.close()
            self.client = OpenAI(api_key=key, base_url=request.settings.base_url,
                                 timeout=request.settings.timeout_seconds, max_retries=0)
            self._connection = connection

    def close(self):
        if not self._injected and self.client is not None:
            if hasattr(self.client, "close"):
                self.client.close()
            self.client = None


def response_dict(response):
    return response.model_dump(mode="json") if hasattr(response, "model_dump") else response


def parse_usage(raw, provider):
    if not isinstance(raw, dict):
        return None, True
    try:
        if provider == "openai":
            usage = TokenUsage(input_tokens=raw["input_tokens"], output_tokens=raw["output_tokens"],
                               cached_input_tokens=(raw.get("input_tokens_details") or {}).get("cached_tokens"),
                               reasoning_tokens=(raw.get("output_tokens_details") or {}).get("reasoning_tokens"))
        else:
            usage = TokenUsage(input_tokens=raw["prompt_tokens"], output_tokens=raw["completion_tokens"],
                               cached_input_tokens=(raw.get("prompt_tokens_details") or {}).get("cached_tokens", raw.get("prompt_cache_hit_tokens")),
                               reasoning_tokens=(raw.get("completion_tokens_details") or {}).get("reasoning_tokens"))
        return usage, False
    except (KeyError, TypeError, ValueError, AttributeError):
        return None, True
