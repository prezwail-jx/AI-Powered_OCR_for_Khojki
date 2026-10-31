"""Integrity-checked response cache with per-request locks and atomic writes."""

import json
import re
from pathlib import Path

from filelock import FileLock

from .schemas import RecognitionResult
from .storage import atomic_json, content_hash

CACHEABLE = {"succeeded", "needs_review"}


class CacheError(ValueError):
    pass


class ResponseCache:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key):
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise CacheError("Invalid cache key")
        return self.directory / f"{key}.json"

    def lock(self, key):
        return FileLock(str(self._path(key)) + ".lock", timeout=180)

    def get(self, key):
        path = self._path(key)
        if not path.exists():
            return None
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            if envelope["version"] != 1 or content_hash(envelope["result"]) != envelope["result_sha256"]:
                raise ValueError("Cache integrity mismatch")
            result = RecognitionResult.model_validate(envelope["result"])
            if result.cache_key != key or result.status not in CACHEABLE or result.candidate is None:
                raise ValueError("Cache identity/state mismatch")
            return result
        except (KeyError, TypeError, ValueError) as exc:
            raise CacheError("Corrupt cache entry; review/remove explicitly before retrying") from exc

    def put(self, result: RecognitionResult):
        if result.status not in CACHEABLE or result.candidate is None:
            return
        value = result.model_dump(mode="json")
        atomic_json(self._path(result.cache_key), {"version": 1, "result": value, "result_sha256": content_hash(value)})
