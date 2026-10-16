"""In-memory storage: tables (rows in insertion order) and the catalog.

Rows live in a dict ``rowid -> list of values``. Row ids only grow, an UPDATE replaces values in
place, so the dict's order, the insertion order and ascending row id are all the same thing:
"table order".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from minidb import nodes as n


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


@dataclass
class Database:
    tables: dict[str, Table] = field(default_factory=dict)
    next_rowid: int = 1

    def new_rowid(self) -> int:
        rid = self.next_rowid
        self.next_rowid += 1
        return rid
