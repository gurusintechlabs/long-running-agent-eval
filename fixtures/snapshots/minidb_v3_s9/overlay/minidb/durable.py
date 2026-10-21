"""Durable storage for ``python -m minidb --db PATH``: a snapshot file plus a write-ahead log.

* ``PATH`` holds a JSON snapshot of the whole database (written atomically: temp file + rename)
  together with the sequence number of the last log record it contains.
* ``PATH-wal`` is an append-only log. Every committed unit (a statement outside a transaction, or
  a whole transaction at COMMIT) is ONE line ``{"seq": n, "ops": [...]}`` written with a single
  ``write`` before the statement is answered. A line without its final newline, or that does not
  parse, is a torn write from a crash: it and everything after it are discarded on recovery, so
  a unit is either completely present or completely absent.
* When the log grows large, the database is checkpointed into a new snapshot and the log is
  truncated; records already contained in the snapshot (``seq <= snapshot seq``) are skipped.

Log operations: ``["i", table, rowid, row]`` insert, ``["u", table, rowid, row]`` update,
``["d", table, rowid]`` delete, ``["s", sql]`` a DDL statement, replayed by executing it.
"""
from __future__ import annotations

import datetime
import json
import os
from typing import Any

from minidb.storage import Column, Database, Index, Table, View
from minidb.values import Vector

FORMAT = "minidb-v2"
CHECKPOINT_RECORDS = 20_000
CHECKPOINT_BYTES = 8 << 20


class NotADatabase(Exception):
    pass


# ------------------------------------------------------------------ snapshot <-> Database

def encode_value(v: Any) -> Any:
    """JSON form of a stored value: DATEs and VECTORs are tagged so they never come back as TEXT."""
    if isinstance(v, datetime.date):
        return {"date": v.isoformat()}
    if isinstance(v, Vector):
        return {"vector": list(v)}
    return v


def decode_value(v: Any) -> Any:
    if isinstance(v, dict):
        if "vector" in v:
            return Vector(float(x) for x in v["vector"])
        return datetime.date.fromisoformat(v["date"])
    return v


def to_snapshot(db: Database, seq: int) -> dict:
    return {
        "format": FORMAT, "seq": seq, "next_rowid": db.next_rowid,
        "next_index_seq": db.next_index_seq,
        "tables": [{"name": t.name,
                    "columns": [{"name": c.name, "type": c.type, "primary_key": c.primary_key,
                                 "not_null": c.not_null, "unique": c.unique,
                                 "default": encode_value(c.default)} for c in t.columns],
                    "rows": [[rid, *(encode_value(v) for v in row)] for rid, row in t.rows.items()]}
                   for t in db.tables.values()],
        "indexes": [{"name": ix.name, "table": ix.table, "column": ix.column, "unique": ix.unique,
                     "seq": ix.seq, "implicit": ix.implicit}
                    for ix in sorted(db.indexes.values(), key=lambda i: i.seq)],
        "views": [{"name": v.name, "sql": v.sql, "columns": v.columns} for v in db.views.values()],
    }


def from_snapshot(data: Any, parse_query=None) -> tuple[Database, int]:
    if not (isinstance(data, dict) and data.get("format") == FORMAT):
        raise NotADatabase("not a minidb database")
    db = Database(next_rowid=int(data["next_rowid"]), next_index_seq=int(data["next_index_seq"]))
    for t in data["tables"]:
        cols = [Column(c["name"], c["type"], bool(c["primary_key"]), bool(c["not_null"]),
                       bool(c["unique"]), decode_value(c["default"])) for c in t["columns"]]
        table = Table(t["name"], cols)
        for row in t["rows"]:
            table.rows[int(row[0])] = [decode_value(v) for v in row[1:]]
        db.tables[table.name] = table
    for d in data["indexes"]:
        db.indexes[d["name"]] = Index(d["name"], d["table"], d["column"], bool(d["unique"]),
                                      int(d["seq"]), bool(d["implicit"]))
    for d in data.get("views", []):
        db.views[d["name"]] = View(d["name"], d["sql"], parse_query(d["sql"]), d["columns"])
    return db, int(data["seq"])


def build_indexes(db: Database) -> None:
    for ix in db.indexes.values():
        ix.build(db.tables[ix.table])


# ------------------------------------------------------------------ files

class Store:
    def __init__(self, path: str, *, read_only: bool = False) -> None:
        self.path = os.path.abspath(path)
        self.read_only = read_only      # read the files, never create, repair or append to them
        self.wal_path = self.path + "-wal"
        self.seq = 0
        self.wal_records = 0
        self.wal_bytes = 0
        self.fd: int | None = None

    def open(self) -> tuple[dict | None, list[list]]:
        """Read the snapshot and the valid log records after it; create the files if needed."""
        snapshot = None
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as fh:
                    snapshot = json.load(fh)
            except (ValueError, UnicodeDecodeError) as exc:
                raise NotADatabase(f"{self.path} is not a minidb database") from exc
            if not (isinstance(snapshot, dict) and snapshot.get("format") == FORMAT):
                raise NotADatabase(f"{self.path} is not a minidb database")
            self.seq = int(snapshot["seq"])
        elif not self.read_only:
            self._write_snapshot(to_snapshot(Database(), 0))
        records: list[list] = []
        good = 0
        if os.path.exists(self.wal_path):
            with open(self.wal_path, "rb") as fh:
                data = fh.read()
            pos = 0
            while pos < len(data):
                end = data.find(b"\n", pos)
                if end < 0:
                    break
                try:
                    rec = json.loads(data[pos:end])
                    seq, ops = int(rec["seq"]), rec["ops"]
                    if not isinstance(ops, list):
                        raise ValueError("bad ops")
                except (ValueError, KeyError, TypeError):
                    break
                if seq > self.seq:
                    records.append(ops)
                    self.seq = seq
                    self.wal_records += len(ops)
                pos = good = end + 1
            if good < len(data) and not self.read_only:
                with open(self.wal_path, "r+b") as fh:
                    fh.truncate(good)
        self.wal_bytes = good
        if not self.read_only:
            self.fd = os.open(self.wal_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        return snapshot, records

    def append(self, ops: list) -> None:
        """Make one unit durable: a single line, written completely before returning."""
        self.seq += 1
        line = (json.dumps({"seq": self.seq, "ops": ops}, ensure_ascii=False,
                           separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        view = memoryview(line)
        while view:
            written = os.write(self.fd, view)
            view = view[written:]
        self.wal_records += len(ops)
        self.wal_bytes += len(line)

    def wants_checkpoint(self) -> bool:
        return self.wal_records > CHECKPOINT_RECORDS or self.wal_bytes > CHECKPOINT_BYTES

    def checkpoint(self, db: Database) -> None:
        self._write_snapshot(to_snapshot(db, self.seq))
        os.ftruncate(self.fd, 0)
        self.wal_records = self.wal_bytes = 0

    def _write_snapshot(self, data: dict) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        os.replace(tmp, self.path)
