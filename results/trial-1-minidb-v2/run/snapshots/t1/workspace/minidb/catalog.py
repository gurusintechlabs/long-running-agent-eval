"""Tables and the database catalog (in-memory storage)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from minidb.protocol import ConstraintError, SQLNameError
from minidb.values import value_key

Row = tuple


@dataclass
class Column:
    name: str
    type: str  # INTEGER, REAL, TEXT, BOOLEAN
    not_null: bool = False
    unique: bool = False
    primary_key: bool = False
    default: Any = None


class Table:
    """A table: its schema and its rows (tuples, in insertion order).

    For every UNIQUE (or PRIMARY KEY) column, ``unique_keys`` holds the keys of the non-NULL
    values currently stored, so constraint checks do not need to scan the table.
    """

    def __init__(self, name: str, columns: list[Column]) -> None:
        self.name = name
        self.columns = columns
        self.index = {c.name: i for i, c in enumerate(columns)}
        self.rows: list[Row] = []
        self.unique_keys: dict[int, set] = {
            i: set() for i, c in enumerate(columns) if c.unique or c.primary_key}

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    def column_index(self, name: str) -> int:
        try:
            return self.index[name]
        except KeyError:
            raise SQLNameError(f"no such column: {name} in table {self.name}") from None

    def _violation(self, i: int, value: Any) -> ConstraintError:
        col = self.columns[i]
        kind = "PRIMARY KEY" if col.primary_key else "UNIQUE"
        return ConstraintError(f"{kind} constraint violated: duplicate value {value!r} in "
                               f"{self.name}.{col.name}")

    def insert_rows(self, new_rows: list[Row]) -> None:
        """Append rows after checking UNIQUE constraints; all or nothing."""
        added: dict[int, set] = {}
        for i, keys in self.unique_keys.items():
            fresh: set = set()
            for row in new_rows:
                v = row[i]
                if v is None:
                    continue
                k = value_key(v)
                if k in keys or k in fresh:
                    raise self._violation(i, v)
                fresh.add(k)
            added[i] = fresh
        for i, fresh in added.items():
            self.unique_keys[i] |= fresh
        self.rows.extend(new_rows)

    def update_rows(self, changes: list[tuple[int, Row]]) -> None:
        """Replace rows (by position) after checking UNIQUE constraints; all or nothing."""
        new_keys: dict[int, set] = {}
        for i, keys in self.unique_keys.items():
            if all(self.rows[pos][i] == new[i] and type(self.rows[pos][i]) is type(new[i])
                   for pos, new in changes):
                continue
            remaining = set(keys)
            for pos, _ in changes:
                old = self.rows[pos][i]
                if old is not None:
                    remaining.discard(value_key(old))
            for _, new in changes:
                v = new[i]
                if v is None:
                    continue
                k = value_key(v)
                if k in remaining:
                    raise self._violation(i, v)
                remaining.add(k)
            new_keys[i] = remaining
        self.unique_keys.update(new_keys)
        for pos, new in changes:
            self.rows[pos] = new

    def delete_rows(self, positions: set[int]) -> None:
        if not positions:
            return
        for i, keys in self.unique_keys.items():
            for pos in positions:
                v = self.rows[pos][i]
                if v is not None:
                    keys.discard(value_key(v))
        self.rows = [r for pos, r in enumerate(self.rows) if pos not in positions]


class Database:
    def __init__(self) -> None:
        self.tables: dict[str, Table] = {}

    def get_table(self, name: str) -> Table:
        table = self.tables.get(name)
        if table is None:
            raise SQLNameError(f"no such table: {name}")
        return table

    def find_table(self, name: str) -> Optional[Table]:
        return self.tables.get(name)

    def add_table(self, table: Table) -> None:
        if table.name in self.tables:
            raise SQLNameError(f"table already exists: {table.name}")
        self.tables[table.name] = table

    def drop_table(self, name: str) -> None:
        self.get_table(name)
        del self.tables[name]
