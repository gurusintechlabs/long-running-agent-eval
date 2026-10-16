"""SQLite-backed store for users and items (stdlib sqlite3 only)."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from vendor.slugify_lite import slugify

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT,
    quantity INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE (owner_id, slug)
);
CREATE INDEX IF NOT EXISTS idx_items_owner ON items(owner_id);
"""

SEED_USERS = [
    (1, "Alice Example", "alice@example.com"),
    (2, "Bob Example", "bob@example.com"),
]

Row = Dict[str, Any]


class Store:
    """Thin data-access layer. One shared connection guarded by a lock."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # -- users -----------------------------------------------------------
    def seed_users(self) -> None:
        with self._lock:
            self.conn.executemany(
                "INSERT OR IGNORE INTO users (id, name, email) VALUES (?, ?, ?)",
                SEED_USERS,
            )
            self.conn.commit()

    def get_user(self, user_id: int) -> Optional[Row]:
        with self._lock:
            r = self.conn.execute(
                "SELECT id, name, email FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return {"id": r[0], "name": r[1], "email": r[2]} if r else None

    def create_user(self, name: str, email: str) -> Row:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO users (name, email) VALUES (?, ?)", (name, email)
            )
            self.conn.commit()
            return {"id": cur.lastrowid, "name": name, "email": email}

    # -- items -----------------------------------------------------------
    @staticmethod
    def _item_row(r: Tuple) -> Row:
        return {
            "id": r[0],
            "owner_id": r[1],
            "title": r[2],
            "slug": r[3],
            "description": r[4],
            "quantity": r[5],
            "created_at": r[6],
        }

    _ITEM_COLS = "id, owner_id, title, slug, description, quantity, created_at"

    def _unique_slug(self, owner_id: int, title: str) -> str:
        base = slugify(title) or "item"
        slug, n = base, 2
        while self.conn.execute(
            "SELECT 1 FROM items WHERE owner_id = ? AND slug = ?", (owner_id, slug)
        ).fetchone():
            slug = f"{base}-{n}"
            n += 1
        return slug

    def create_item(
        self,
        owner_id: int,
        title: str,
        description: Optional[str] = None,
        quantity: int = 1,
    ) -> Row:
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._lock:
            slug = self._unique_slug(owner_id, title)
            cur = self.conn.execute(
                "INSERT INTO items (owner_id, title, slug, description, quantity,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (owner_id, title, slug, description, quantity, created_at),
            )
            self.conn.commit()
            item_id = cur.lastrowid
        item = self.get_item(owner_id, item_id)
        assert item is not None
        return item

    def get_item(self, owner_id: int, item_id: int) -> Optional[Row]:
        with self._lock:
            r = self.conn.execute(
                f"SELECT {self._ITEM_COLS} FROM items WHERE id = ? AND owner_id = ?",
                (item_id, owner_id),
            ).fetchone()
        return self._item_row(r) if r else None

    def list_items(
        self, owner_id: int, limit: int = 20, offset: int = 0
    ) -> List[Row]:
        with self._lock:
            rows = self.conn.execute(
                f"SELECT {self._ITEM_COLS} FROM items WHERE owner_id = ?"
                " ORDER BY id ASC LIMIT ? OFFSET ?",
                (owner_id, limit, offset),
            ).fetchall()
        return [self._item_row(r) for r in rows]

    def count_items(self, owner_id: int) -> int:
        with self._lock:
            (n,) = self.conn.execute(
                "SELECT COUNT(*) FROM items WHERE owner_id = ?", (owner_id,)
            ).fetchone()
        return int(n)

    def delete_item(self, owner_id: int, item_id: int) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM items WHERE id = ? AND owner_id = ?", (item_id, owner_id)
            )
            self.conn.commit()
            return cur.rowcount > 0
