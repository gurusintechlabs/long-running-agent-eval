"""In-memory storage: tables (rows in insertion order), ordered indexes, views, and the catalog.

Rows live in a dict ``rowid -> list of values``. Row ids only grow, an UPDATE replaces values in
place, so the dict's order, the insertion order and ascending row id are all the same thing:
"table order".
"""
from __future__ import annotations

import bisect
import json
import math
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any

from minidb import nodes as n
from minidb.protocol import SQLIOError
from minidb.values import kind

FORMAT = "minidb"
VERSION = 1


@dataclass
class Column:
    name: str
    type: str
    primary_key: bool = False
    not_null: bool = False
    unique: bool = False
    default: Any = None

    @classmethod
    def from_def(cls, d: n.ColumnDef, default: Any) -> Column:
        return cls(d.name, d.type, d.primary_key, d.not_null, d.unique, default)


@dataclass
class Table:
    name: str
    columns: list[Column]
    rows: dict[int, list] = field(default_factory=dict)

    def col_index(self, name: str) -> int | None:
        for i, c in enumerate(self.columns):
            if c.name == name:
                return i
        return None


class Index:
    """Ordered single-column index: a sorted list of ``(key, rowid)``; NULL keys are not stored."""

    def __init__(self, name: str, table: str, column: str, unique: bool, seq: int) -> None:
        self.name, self.table, self.column, self.unique, self.seq = name, table, column, unique, seq
        self.entries: list[tuple[Any, int]] = []

    def build(self, table: Table) -> None:
        ci = table.col_index(self.column)
        self.entries = sorted((row[ci], rid) for rid, row in table.rows.items()
                              if row[ci] is not None)

    def add(self, key: Any, rowid: int) -> None:
        if key is not None:
            bisect.insort(self.entries, (key, rowid))

    def remove(self, key: Any, rowid: int) -> None:
        if key is None:
            return
        i = bisect.bisect_left(self.entries, (key, rowid))
        if i < len(self.entries) and self.entries[i] == (key, rowid):
            del self.entries[i]

    def lookup(self, low: Any = None, low_incl: bool = True, high: Any = None,
               high_incl: bool = True) -> list[int]:
        """Row ids with ``low <(=) key <(=) high`` (a bound of None is open), in key order."""
        lo = 0
        if low is not None:
            lo = (bisect.bisect_left(self.entries, (low, -math.inf)) if low_incl
                  else bisect.bisect_right(self.entries, (low, math.inf)))
        hi = len(self.entries)
        if high is not None:
            hi = (bisect.bisect_right(self.entries, (high, math.inf)) if high_incl
                  else bisect.bisect_left(self.entries, (high, -math.inf)))
        return [rid for _, rid in self.entries[lo:hi]]


@dataclass
class View:
    name: str
    sql: str
    query: n.Select


@dataclass
class Database:
    tables: dict[str, Table] = field(default_factory=dict)
    views: dict[str, View] = field(default_factory=dict)
    indexes: dict[str, Index] = field(default_factory=dict)
    next_rowid: int = 1
    next_index_seq: int = 1

    def relation_exists(self, name: str) -> bool:
        return name in self.tables or name in self.views

    def table_indexes(self, table: str) -> list[Index]:
        return sorted((ix for ix in self.indexes.values() if ix.table == table),
                      key=lambda ix: ix.seq)

    def index_for(self, table: str, column: str) -> Index | None:
        for ix in self.table_indexes(table):
            if ix.column == column:
                return ix
        return None

    def new_rowid(self) -> int:
        rid = self.next_rowid
        self.next_rowid += 1
        return rid


# ------------------------------------------------------------------ persistence

def to_json(db: Database) -> dict:
    return {
        "format": FORMAT, "version": VERSION, "next_rowid": db.next_rowid,
        "next_index_seq": db.next_index_seq,
        "tables": [{"name": t.name,
                    "columns": [{"name": c.name, "type": c.type, "primary_key": c.primary_key,
                                 "not_null": c.not_null, "unique": c.unique, "default": c.default}
                                for c in t.columns],
                    "rows": [[rid, *row] for rid, row in t.rows.items()]}
                   for t in db.tables.values()],
        "indexes": [{"name": ix.name, "table": ix.table, "column": ix.column, "unique": ix.unique,
                     "seq": ix.seq} for ix in sorted(db.indexes.values(), key=lambda i: i.seq)],
        "views": [{"name": v.name, "sql": v.sql} for v in db.views.values()],
    }


def save(db: Database, path: str) -> None:
    data = json.dumps(to_json(db), ensure_ascii=False, allow_nan=False)
    target = os.path.abspath(path)
    try:
        fd, tmp = tempfile.mkstemp(prefix=".minidb-", dir=os.path.dirname(target))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
            os.replace(tmp, target)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    except OSError as exc:
        raise SQLIOError(f"cannot write {path}: {exc.strerror or exc}") from None


_VALUE_KINDS = {"INTEGER": "int", "REAL": "real", "TEXT": "text", "BOOLEAN": "bool"}


def _check(cond: bool, what: str) -> None:
    if not cond:
        raise ValueError(what)


def from_json(data: Any, parse_view) -> Database:
    """Rebuild a Database; raises ValueError/KeyError/TypeError on anything malformed."""
    _check(isinstance(data, dict) and data.get("format") == FORMAT
           and data.get("version") == VERSION, "not a minidb database file")
    db = Database(next_rowid=int(data["next_rowid"]), next_index_seq=int(data["next_index_seq"]))
    for t in data["tables"]:
        cols = []
        for c in t["columns"]:
            _check(c["type"] in _VALUE_KINDS, "bad column type")
            cols.append(Column(str(c["name"]), c["type"], bool(c["primary_key"]),
                               bool(c["not_null"]), bool(c["unique"]), c["default"]))
        table = Table(str(t["name"]), cols)
        for row in t["rows"]:
            _check(isinstance(row, list) and len(row) == len(cols) + 1, "bad row")
            rid, values = int(row[0]), row[1:]
            for c, v in zip(cols, values, strict=True):
                _check(v is None or kind(v) == _VALUE_KINDS[c.type], "bad value")
            table.rows[rid] = values
        _check(list(table.rows) == sorted(table.rows), "rows out of order")
        db.tables[table.name] = table
    for d in data["indexes"]:
        table = db.tables[d["table"]]
        _check(table.col_index(d["column"]) is not None, "bad index column")
        ix = Index(str(d["name"]), table.name, d["column"], bool(d["unique"]), int(d["seq"]))
        ix.build(table)
        db.indexes[ix.name] = ix
    for d in data["views"]:
        db.views[str(d["name"])] = View(str(d["name"]), d["sql"], parse_view(d["sql"]))
    return db


def load(path: str, parse_view) -> Database:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return from_json(data, parse_view)
    except OSError as exc:
        raise SQLIOError(f"cannot read {path}: {exc.strerror or exc}") from None
    except Exception as exc:  # noqa: BLE001 - anything malformed is "not a database"
        raise SQLIOError(f"{path} is not a valid minidb database ({type(exc).__name__})") from None
