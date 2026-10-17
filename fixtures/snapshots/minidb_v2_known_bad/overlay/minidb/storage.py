"""In-memory storage: tables (rows in insertion order), ordered indexes, and the catalog.

Rows live in a dict ``rowid -> list of values``. Row ids only grow, an UPDATE replaces values in
place, so the dict's order, the insertion order and ascending row id are all the same thing:
"table order".

Names keep the spelling of their definition but match case-insensitively (CR-4): the catalog
dicts are ``CIDict``s keyed by the lower-cased name, and every name comparison uses ``same``.
"""
from __future__ import annotations

import bisect
import math
import sqlite3  # noqa: F401  (kept for comparing on-disk formats later)
from dataclasses import dataclass, field
from typing import Any

from minidb import nodes as n


def same(a: str, b: str) -> bool:
    """Two identifiers name the same thing (case-insensitive)."""
    return a.lower() == b.lower()


class CIDict(dict):
    """A dict keyed by names, case-insensitively; values keep their own spelling."""

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key.lower(), value)

    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key.lower())

    def __delitem__(self, key: str) -> None:
        super().__delitem__(key.lower())

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and super().__contains__(key.lower())

    def get(self, key: str, default: Any = None) -> Any:
        return super().get(key.lower(), default)

    def copy(self) -> CIDict:
        out = CIDict()
        dict.update(out, self)
        return out


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
        key = name.lower()
        for i, c in enumerate(self.columns):
            if c.name.lower() == key:
                return i
        return None


_LOW, _HIGH = -math.inf, math.inf


class Index:
    """Ordered single-column index: a sorted list of ``(key, rowid)``; NULL keys are not stored.

    Keys of one index all have the column's type, so they are mutually comparable; numbers compare
    by value (``1 == 1.0``), which is the SQL ``=``.
    """

    def __init__(self, name: str, table: str, column: str, unique: bool, seq: int,
                 implicit: bool = False) -> None:
        self.name, self.table, self.column = name, table, column
        self.unique, self.seq, self.implicit = unique, seq, implicit
        self.entries: list[tuple[Any, int]] = []

    def build(self, table: Table) -> None:
        ci = table.col_index(self.column)
        self.entries = sorted((row[ci], rid) for rid, row in table.rows.items()
                              if row[ci] is not None)

    def add(self, key: Any, rowid: int) -> None:
        if key is not None:
            bisect.insort(self.entries, (key, rowid))

    def add_many(self, pairs: list[tuple[Any, int]]) -> None:
        pairs = [p for p in pairs if p[0] is not None]
        if len(pairs) > 64:
            self.entries.extend(pairs)
            self.entries.sort()
        else:
            for p in pairs:
                bisect.insort(self.entries, p)

    def remove(self, key: Any, rowid: int) -> None:
        if key is None:
            return
        i = bisect.bisect_left(self.entries, (key, rowid))
        if i < len(self.entries) and self.entries[i] == (key, rowid):
            del self.entries[i]

    def eq(self, key: Any) -> list[int]:
        """Row ids with this key, in row-id (table) order."""
        lo = bisect.bisect_left(self.entries, (key, _LOW))
        hi = bisect.bisect_right(self.entries, (key, _HIGH))
        return [rid for _, rid in self.entries[lo:hi]]

    def range(self, low: Any = None, low_incl: bool = True, high: Any = None,
              high_incl: bool = True) -> list[int]:
        """Row ids with ``low <(=) key <(=) high`` (a bound of None is open), in table order."""
        lo = 0
        if low is not None:
            lo = (bisect.bisect_left(self.entries, (low, _LOW)) if low_incl
                  else bisect.bisect_right(self.entries, (low, _HIGH)))
        hi = len(self.entries)
        if high is not None:
            hi = (bisect.bisect_right(self.entries, (high, _HIGH)) if high_incl
                  else bisect.bisect_left(self.entries, (high, _LOW)))
        return sorted(rid for _, rid in self.entries[lo:hi]) if lo < hi else []

    def __len__(self) -> int:
        return len(self.entries)


@dataclass
class View:
    name: str
    sql: str                       # the query's text (re-parsed when loaded from storage)
    query: Any                     # its AST (re-prepared at every use)
    columns: list[str] | None = None


@dataclass
class Database:
    tables: CIDict = field(default_factory=CIDict)
    indexes: CIDict = field(default_factory=CIDict)
    views: CIDict = field(default_factory=CIDict)
    next_rowid: int = 1
    next_index_seq: int = 1

    def relation_exists(self, name: str) -> bool:
        return name in self.tables or name in self.views

    def table_indexes(self, table: str) -> list[Index]:
        return sorted((ix for ix in self.indexes.values() if same(ix.table, table)),
                      key=lambda ix: ix.seq)

    def index_for(self, table: str, column: str) -> Index | None:
        """The first-created index on ``table.column``, if any."""
        for ix in self.table_indexes(table):
            if same(ix.column, column):
                return ix
        return None

    def new_rowid(self) -> int:
        rid = self.next_rowid
        self.next_rowid += 1
        return rid

    def new_index_seq(self) -> int:
        seq = self.next_index_seq
        self.next_index_seq += 1
        return seq
