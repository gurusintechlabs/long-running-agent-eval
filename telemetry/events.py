"""Append-only JSONL event writer with the common envelope (docs/spec.md §6.1)."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import UTC, datetime
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
# Claude Code stamps every telemetry record with account identifiers (observed live, CLI 1.0.126;
# CLI 2.1.301 added ``user.account_id``). They are never needed for any metric, so they are dropped
# on the way in: the listed keys, and every key in the ``user.`` / ``organization.`` namespaces, so
# an identifier added by a future CLI cannot slip through.
SENSITIVE_KEYS = frozenset({"user.email", "user.account_uuid", "user.id", "organization.id"})
SENSITIVE_PREFIXES = ("user.", "organization.")


def is_sensitive_key(key: Any) -> bool:
    return isinstance(key, str) and (key in SENSITIVE_KEYS or key.startswith(SENSITIVE_PREFIXES))


def redact(obj: Any) -> Any:
    """Return a copy of ``obj`` with token-like strings replaced."""
    if isinstance(obj, str):
        for pat in _SECRET_PATTERNS:
            obj = pat.sub(REDACTED, obj)
        return obj
    if isinstance(obj, dict):
        return {k: (REDACTED if is_sensitive_key(k) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    return obj


def scrub_otlp(doc: Any) -> Any:
    """Copy of an OTLP JSON document with sensitive attribute values replaced.

    OTLP attributes are ``{"key": ..., "value": {...}}`` pairs, which :func:`redact` cannot see.
    """
    if isinstance(doc, dict):
        if is_sensitive_key(doc.get("key")) and "value" in doc:
            return {**doc, "value": {"stringValue": REDACTED}}
        return {k: scrub_otlp(v) for k, v in doc.items()}
    if isinstance(doc, list):
        return [scrub_otlp(v) for v in doc]
    return doc


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


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
