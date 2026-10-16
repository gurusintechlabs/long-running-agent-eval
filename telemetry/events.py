"""Append-only JSONL event writer with the common envelope (docs/spec.md §6.1)."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]
REDACTED = "[REDACTED]"


def redact(obj: Any) -> Any:
    """Return a copy of ``obj`` with token-like strings replaced."""
    if isinstance(obj, str):
        for pat in _SECRET_PATTERNS:
            obj = pat.sub(REDACTED, obj)
        return obj
    if isinstance(obj, dict):
        return {k: redact(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    return obj


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class EventWriter:
    """One file per (run, source). Append-only, fsync'd per line, thread-safe, monotonic ``seq``."""

    def __init__(self, path: Path | str, run_id: str, source: str):
        self.path = Path(path)
        self.run_id = run_id
        self.source = source
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seq = self._next_seq()
        self._fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)

    def _next_seq(self) -> int:
        if not self.path.exists():
            return 0
        last = None
        with open(self.path, "rb") as fh:
            for line in fh:
                if line.strip():
                    last = line
        if last is None:
            return 0
        try:
            return int(json.loads(last)["seq"]) + 1
        except (ValueError, KeyError, TypeError):
            return 0

    def emit(self, type: str, payload: dict | None = None, ts: str | None = None) -> dict:
        with self._lock:
            event = {
                "ts": ts or utc_now_iso(),
                "mono_ns": time.monotonic_ns(),
                "run_id": self.run_id,
                "source": self.source,
                "type": type,
                "seq": self._seq,
                "payload": redact(payload or {}),
            }
            line = json.dumps(event, default=str, separators=(",", ":")) + "\n"
            os.write(self._fd, line.encode())
            os.fsync(self._fd)
            self._seq += 1
            return event

    def close(self) -> None:
        with self._lock:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None

    def __enter__(self) -> EventWriter:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
