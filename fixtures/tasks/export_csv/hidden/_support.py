"""Shared helpers for the black-box /export acceptance tests (no app imports).

Environment (set by the scorer):
  LRAE_APP_URL  base URL of the running app, e.g. http://127.0.0.1:54321
  LRAE_APP_DB   path of the app's SQLite file; used only to register test users and to read
                the audit_log table
Every test uses its own user (API key ``hk-NN``, user id 100+NN), listed in scorer.yaml.
The app is expected to run with a limit of 5 successful exports per user per window.
"""
from __future__ import annotations

import csv
import io
import os
import sqlite3

import httpx

BASE_URL = os.environ["LRAE_APP_URL"].rstrip("/")
DB_PATH = os.environ["LRAE_APP_DB"]
RATE_LIMIT = 5
HEADER = ["id", "title", "slug", "description", "quantity", "created_at"]
AUDIT_ACTION = "export.csv"


def client() -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, timeout=10.0)


def _db() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, timeout=10.0)


class User:
    def __init__(self, n: int) -> None:
        self.n = n
        self.uid = 100 + n
        self.headers = {"X-API-Key": f"hk-{n:02d}"}
        with _db() as conn:  # the seed only creates users 1 and 2
            conn.execute(
                "INSERT OR IGNORE INTO users (id, name, email) VALUES (?, ?, ?)",
                (self.uid, f"Hidden {n}", f"hk-{n:02d}@example.test"),
            )

    def add_items(self, c: httpx.Client, count: int, prefix: str = "item") -> None:
        for i in range(count):
            r = c.post("/items", json={"title": f"{prefix} {i:03d}"}, headers=self.headers)
            assert r.status_code == 201, r.text

    def export(self, c: httpx.Client, **params) -> httpx.Response:
        return c.get("/export", params=params or None, headers=self.headers)

    def audit_count(self) -> int:
        return audit_count(self.uid)


def audit_count(user_id: int | None = None) -> int:
    sql, args = "SELECT COUNT(*) FROM audit_log WHERE action = ?", [AUDIT_ACTION]
    if user_id is not None:
        sql += " AND user_id = ?"
        args.append(user_id)
    with _db() as conn:
        return conn.execute(sql, args).fetchone()[0]


def parse_csv(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text, newline="")))
