"""The audit log of admin actions (stage 5): ``DIR/audit.log``, one JSON object per line,
``{"ts": "<UTC ISO 8601>", "actor": "<key id>", "action", "target"}``. Entries name keys by id, never
by secret. ``latest(n)`` reads the newest entries first.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

AUDIT_FILE = "audit.log"
ACTIONS = ("key.create", "key.revoke", "collection.create", "collection.delete", "collection.index",
           "snapshot.restore")


class AuditLog:
    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / AUDIT_FILE
        self.lock = threading.Lock()

    def record(self, actor: str, action: str, target: str) -> None:
        assert action in ACTIONS
        entry = {"ts": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                 "actor": actor, "action": action, "target": target}
        line = (json.dumps(entry, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")
        with self.lock:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            try:
                os.write(fd, line)
            finally:
                os.close(fd)

    def latest(self, n: int) -> list[dict]:
        with self.lock:
            try:
                lines = self.path.read_bytes().splitlines()
            except FileNotFoundError:
                return []
        out = []
        for raw in reversed(lines):
            try:
                out.append(json.loads(raw))
            except ValueError:
                continue              # a torn last line after a crash
            if len(out) >= n:
                break
        return out
