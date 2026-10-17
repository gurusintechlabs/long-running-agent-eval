"""Tables, indexes and the database catalog (in-memory storage).

A table stores its rows in a dict ``rowid -> row``. Rowids only ever increase and an UPDATE
replaces a row under the same rowid, so iterating the dict gives table order (insertion order,
updated rows in place, deleted rows gone).
"""
from __future__ import annotations

import bisect
import itertools
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from minidb.protocol import ConstraintError, SQLNameError
from minidb.values import value_key

Row = tuple

# Batches at least this large rebuild an index's sorted key list instead of inserting each new
# key into it.
_BULK = 64

_creation_order = itertools.count()


@dataclass
class Column:
    name: str
    type: str  # INTEGER, REAL, TEXT, BOOLEAN
    not_null: bool = False
    unique: bool = False
    primary_key: bool = False
    default: Any = None


class Index:
    """An ordered index on one column: equality and range lookups returning rowids in table
    order. NULLs are not indexed (they never match a lookup). All non-NULL values of a column
    have comparable types, so the raw values serve as keys."""

    def __init__(self, name: str, table: "Table", column: int, unique: bool = False,
                 implicit: bool = False) -> None:
        self.name = name
        self.table = table
        self.column = column
        self.unique = unique
        self.implicit = implicit
        self.seq = next(_creation_order)  # creation order, across the whole database
        self.rids: dict[Any, list[int]] = {}  # key -> rowids, ascending
        self.keys: list[Any] = []             # distinct keys, ascending
        self._keys_dirty = False

    @property
    def column_name(self) -> str:
        return self.table.columns[self.column].name

    def add(self, key: Any, rid: int, bulk: bool = False) -> None:
        if key is None:
            return
        lst = self.rids.get(key)
        if lst is None:
            self.rids[key] = [rid]
            if bulk or self._keys_dirty:
                self._keys_dirty = True
            else:
                bisect.insort(self.keys, key)
        elif lst[-1] < rid:
            lst.append(rid)
        else:
            bisect.insort(lst, rid)

    def remove(self, key: Any, rid: int) -> None:
        if key is None:
            return
        lst = self.rids[key]
        lst.remove(rid)
        if not lst:
            self._drop_key(key)

    def remove_many(self, entries: Iterable[tuple[Any, int]]) -> None:
        by_key: dict[Any, set[int]] = {}
        for key, rid in entries:
            if key is not None:
                by_key.setdefault(key, set()).add(rid)
        for key, gone in by_key.items():
            remaining = [r for r in self.rids[key] if r not in gone]
            if remaining:
                self.rids[key] = remaining
            else:
                self._drop_key(key)

    def add_many(self, entries: Iterable[tuple[Any, int]]) -> None:
        by_key: dict[Any, list[int]] = {}
        for key, rid in entries:
            if key is not None:
                by_key.setdefault(key, []).append(rid)
        for key, new in by_key.items():
            lst = self.rids.get(key)
            if lst is None:
                self.rids[key] = sorted(new)
                self._keys_dirty = True
            else:
                lst.extend(new)
                lst.sort()

    def _drop_key(self, key: Any) -> None:
        del self.rids[key]
        if not self._keys_dirty:
            del self.keys[bisect.bisect_left(self.keys, key)]

    def sorted_keys(self) -> list[Any]:
        if self._keys_dirty:
            self.keys = sorted(self.rids)
            self._keys_dirty = False
        return self.keys

    def lookup(self, lo: Any, lo_incl: bool, hi: Any, hi_incl: bool) -> list[int]:
        """Rowids (in table order) of the rows whose key is within the bounds; a bound of None
        is open."""
        if lo is not None and hi is not None and lo == hi:
            if not (lo_incl and hi_incl):
                return []
            return list(self.rids.get(lo, ()))
        keys = self.sorted_keys()
        i = 0 if lo is None else (bisect.bisect_left(keys, lo) if lo_incl
                                  else bisect.bisect_right(keys, lo))
        j = len(keys) if hi is None else (bisect.bisect_right(keys, hi) if hi_incl
                                          else bisect.bisect_left(keys, hi))
        if i >= j:
            return []
        if j - i == 1:
            return list(self.rids[keys[i]])
        out: list[int] = []
        for key in keys[i:j]:
            out.extend(self.rids[key])
        out.sort()
        return out

    def has_values(self) -> bool:
        return bool(self.rids)


class Table:
    """A table: its schema, its rows (``rowid -> row``) and its indexes.

    ``unique_keys`` holds, for every column that must be unique (a UNIQUE or PRIMARY KEY
    constraint, or a unique index), the keys of its non-NULL values, so constraint checks do
    not scan the table.
    """

    def __init__(self, name: str, columns: list[Column]) -> None:
        self.name = name
        self.columns = columns
        self.index = {c.name: i for i, c in enumerate(columns)}
        self.rows: dict[int, Row] = {}
        self.next_rid = 0
        self.indexes: list[Index] = []  # in creation order
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

    def first_index(self, column: int) -> Optional[Index]:
        """The column's index created first, if any."""
        for idx in self.indexes:
            if idx.column == column:
                return idx
        return None

    # ------------------------------------------------------------ indexes

    def add_index(self, index: Index) -> None:
        """Build ``index`` over the current rows. A unique index on a column that has
        duplicates is a ConstraintError (and nothing changes)."""
        col = index.column
        if index.unique and col not in self.unique_keys:
            keys: set = set()
            for row in self.rows.values():
                val = row[col]
                if val is None:
                    continue
                k = value_key(val)
                if k in keys:
                    raise self._violation(col, val)
                keys.add(k)
            self.unique_keys[col] = keys
        for rid, row in self.rows.items():
            index.add(row[col], rid, bulk=True)
        self.indexes.append(index)

    def remove_index(self, index: Index) -> None:
        self.indexes.remove(index)
        col = index.column
        still_unique = (self.columns[col].unique or self.columns[col].primary_key
                        or any(i.unique and i.column == col for i in self.indexes))
        if not still_unique:
            self.unique_keys.pop(col, None)

    # ------------------------------------------------------------ changes

    def _violation(self, i: int, value: Any) -> ConstraintError:
        col = self.columns[i]
        kind = "PRIMARY KEY" if col.primary_key else "UNIQUE"
        return ConstraintError(f"{kind} constraint violated: duplicate value {value!r} in "
                               f"{self.name}.{col.name}")

    def insert_rows(self, new_rows: list[Row]) -> None:
        """Append rows after checking unique columns; all or nothing."""
        added: dict[int, set] = {}
        for i, keys in self.unique_keys.items():
            fresh: set = set()
            for row in new_rows:
                val = row[i]
                if val is None:
                    continue
                k = value_key(val)
                if k in keys or k in fresh:
                    raise self._violation(i, val)
                fresh.add(k)
            added[i] = fresh
        for i, fresh in added.items():
            self.unique_keys[i] |= fresh
        bulk = len(new_rows) >= _BULK
        rid = self.next_rid
        for row in new_rows:
            self.rows[rid] = row
            for index in self.indexes:
                index.add(row[index.column], rid, bulk)
            rid += 1
        self.next_rid = rid

    def update_rows(self, changes: list[tuple[int, Row]]) -> None:
        """Replace rows (by rowid) after checking unique columns; all or nothing."""
        rows = self.rows
        for i, keys in self.unique_keys.items():
            changed = [(rows[rid][i], new[i]) for rid, new in changes if rows[rid][i] != new[i]]
            if not changed:
                continue
            old_keys = {value_key(old) for old, _ in changed if old is not None}
            seen: set = set()
            for _, val in changed:
                if val is None:
                    continue
                k = value_key(val)
                if (k in keys and k not in old_keys) or k in seen:
                    raise self._violation(i, val)
                seen.add(k)
        for i, keys in self.unique_keys.items():
            for rid, new in changes:
                old = rows[rid][i]
                if old != new[i] and old is not None:
                    keys.discard(value_key(old))
            for rid, new in changes:
                if new[i] is not None:
                    keys.add(value_key(new[i]))
        for index in self.indexes:
            col = index.column
            moved = [(rows[rid][col], new[col], rid) for rid, new in changes
                     if rows[rid][col] != new[col]]
            if len(moved) < _BULK:
                for old, val, rid in moved:
                    index.remove(old, rid)
                    index.add(val, rid)
            else:
                index.remove_many((old, rid) for old, _, rid in moved)
                index.add_many((val, rid) for _, val, rid in moved)
        for rid, new in changes:
            rows[rid] = new

    def delete_rows(self, rids: list[int]) -> None:
        if not rids:
            return
        rows = self.rows
        for i, keys in self.unique_keys.items():
            for rid in rids:
                val = rows[rid][i]
                if val is not None:
                    keys.discard(value_key(val))
        for index in self.indexes:
            col = index.column
            if len(rids) == 1:
                index.remove(rows[rids[0]][col], rids[0])
            else:
                index.remove_many((rows[rid][col], rid) for rid in rids)
        for rid in rids:
            del rows[rid]


class Database:
    def __init__(self) -> None:
        self.tables: dict[str, Table] = {}
        self.indexes: dict[str, Index] = {}

    def get_table(self, name: str) -> Table:
        table = self.tables.get(name)
        if table is None:
            raise SQLNameError(f"no such table: {name}")
        return table

    def find_table(self, name: str) -> Optional[Table]:
        return self.tables.get(name)

    def add_table(self, table: Table) -> None:
        """Add a table and its implicit indexes (one per PRIMARY KEY / UNIQUE column)."""
        if table.name in self.tables:
            raise SQLNameError(f"table already exists: {table.name}")
        implicit = [Index(f"{table.name}_{c.name}_key", table, i, unique=True, implicit=True)
                    for i, c in enumerate(table.columns) if c.unique or c.primary_key]
        for index in implicit:
            if index.name in self.indexes:
                raise SQLNameError(f"index already exists: {index.name} (needed for the "
                                   f"implicit index of {table.name}.{index.column_name})")
        self.tables[table.name] = table
        for index in implicit:
            table.add_index(index)
            self.indexes[index.name] = index

    def drop_table(self, name: str) -> None:
        table = self.get_table(name)
        for index in table.indexes:
            del self.indexes[index.name]
        del self.tables[name]

    def add_index(self, index: Index) -> None:
        if index.name in self.indexes:
            raise SQLNameError(f"index already exists: {index.name}")
        index.table.add_index(index)
        self.indexes[index.name] = index

    def drop_index(self, name: str) -> None:
        index = self.indexes.get(name)
        if index is None:
            raise SQLNameError(f"no such index: {name}")
        if index.implicit:
            raise ConstraintError(f"index {name} belongs to a PRIMARY KEY or UNIQUE constraint "
                                  "and cannot be dropped")
        index.table.remove_index(index)
        del self.indexes[name]
