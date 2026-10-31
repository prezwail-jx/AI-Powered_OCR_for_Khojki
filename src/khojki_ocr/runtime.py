"""Run directories and redacted diagnostics. No API requests are made here."""

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def redact(text: str) -> str:
    secrets = [value for name, value in os.environ.items()
               if any(word in name.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")) and value]
    for value in sorted(secrets, key=len, reverse=True):
        text = text.replace(value, "[REDACTED]")
    # Providers can echo only a masked prefix/suffix, which no longer matches
    # the full environment value. Suppress the entire reported key token too.
    text = re.sub(r"(?i)(incorrect\s+api\s+key\s+provided:\s*)\S+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(bearer\s+)\S+", r"\1[REDACTED]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[REDACTED]", text)
    text = re.sub(r"(?i)((?:api[_-]?key|token|secret|password)\s*[=:]\s*)[^\s,;]+", r"\1[REDACTED]", text)
    return text


def write_json(path: Path, payload: Any) -> None:
    path.write_text(redact(json.dumps(payload, ensure_ascii=False, indent=2)) + "\n", encoding="utf-8")


class RunContext:
    def __init__(self, output_dir: Path):
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12]
        self.directory = output_dir / self.run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.log_path = self.directory / "run.log"

    def log(self, message: str) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} {redact(message)}\n")

    def error(self, exc: Exception) -> None:
        self.log(f"ERROR {type(exc).__name__}: {exc}")
        write_json(self.directory / "error.json", {"run_id": self.run_id, "status": "failed",
                                                  "error_type": type(exc).__name__, "message": str(exc)})
