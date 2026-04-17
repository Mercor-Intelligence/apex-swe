"""TrajectoryWriter: append-only JSONL writer with schema validation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from common.schemas import validate_event

DEFAULT_MAX_CONTENT_BYTES = 16 * 1024
_TRUNCATION_SUFFIX = "...[truncated]"


class TrajectoryWriter:
    def __init__(self, path: Path | str, max_content_bytes: int = DEFAULT_MAX_CONTENT_BYTES):
        self.path = Path(path)
        self.max_content_bytes = max_content_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")

    def write(self, **event) -> None:
        if event.get("type") == "tool_result":
            content = event.get("content", "")
            if isinstance(content, str) and len(content) > self.max_content_bytes:
                keep = self.max_content_bytes - len(_TRUNCATION_SUFFIX)
                event["content"] = content[:keep] + _TRUNCATION_SUFFIX
        validate_event(event)
        self._fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        if self._fh and not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> "TrajectoryWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
