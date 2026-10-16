"""Audit log stored in the same SQLite database as the rest of the data.

Every mutating action should call ``record``; ``list_entries`` is the read
accessor. Entries are append-only.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    user_id INTEGER,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
"""

_conn: Optional[sqlite3.Connection] = None
_lock = threading.RLock()


def init(conn: sqlite3.Connection) -> None:
    """Bind the audit module to a connection and create its table."""
    global _conn
    with _lock:
        _conn = conn
        conn.executescript(SCHEMA)
        conn.commit()


def _require_conn() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("audit.init() has not been called")
    return _conn


def record(user_id: Optional[int], action: str, detail: str = "") -> int:
    """Append an audit entry and return its id."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _lock:
        conn = _require_conn()
        cur = conn.execute(
            "INSERT INTO audit_log (ts, user_id, action, detail) VALUES (?, ?, ?, ?)",
            (ts, user_id, action, detail),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_entries(
    user_id: Optional[int] = None, limit: int = 100, offset: int = 0
) -> List[Dict[str, Any]]:
    """Return audit entries oldest-first, optionally filtered by user."""
    sql = "SELECT id, ts, user_id, action, detail FROM audit_log"
    args: list = []
    if user_id is not None:
        sql += " WHERE user_id = ?"
        args.append(user_id)
    sql += " ORDER BY id ASC LIMIT ? OFFSET ?"
    args.extend([limit, offset])
    with _lock:
        rows = _require_conn().execute(sql, args).fetchall()
    return [
        {"id": r[0], "ts": r[1], "user_id": r[2], "action": r[3], "detail": r[4]}
        for r in rows
    ]
