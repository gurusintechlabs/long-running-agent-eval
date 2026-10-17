"""Tables, indexes and the database catalog (in-memory storage).

A table stores its rows in a dict ``rowid -> row``. Rowids only ever increase and an UPDATE
replaces a row under the same rowid, so table order (insertion order, updated rows in place,
deleted rows gone) is rowid order. Every change is recorded in the database's journal
(``minidb.journal``) for ROLLBACK, statement atomicity and the durable log.
"""
from __future__ import annotations

import bisect
import itertools
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from minidb.journal import Journal
from minidb.names import Ident
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

    def __post_init__(self) -> None:
        self.name = Ident(self.name)


class Index:
    """An ordered index on one column: equality and range lookups returning rowids in table
    order. NULLs are not indexed (they never match a lookup). All non-NULL values of a column
    have comparable types, so the raw values serve as keys."""

    def __init__(self, name: str, table: "Table", column: int, unique: bool = False,
                 implicit: bool = False) -> None:
        self.name = Ident(name)
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

    Table order is rowid order. Iterating ``rows`` gives it, except right after a ROLLBACK
    re-inserted deleted rows under their old rowids: then ``_order_dirty`` is set and the next
    scan restores the order (a scan is linear anyway, and so is sorting nearly sorted keys).
    Always read rows in order through ``scan`` / ``scan_items``.

    ``unique_keys`` holds, for every column that must be unique (a UNIQUE or PRIMARY KEY
    constraint, or a unique index), the keys of its non-NULL values, so constraint checks do
    not scan the table.

    Every change is recorded in ``journal`` (if set): how to undo it, and a redo operation.
    """

    def __init__(self, name: str, columns: list[Column]) -> None:
        self.name = Ident(name)
        self.columns = columns
        self.index = {c.name: i for i, c in enumerate(columns)}
        self.rows: dict[int, Row] = {}
        self._order_dirty = False
        self.next_rid = 0
        self.indexes: list[Index] = []  # in creation order
        self.unique_keys: dict[int, set] = {
            i: set() for i, c in enumerate(columns) if c.unique or c.primary_key}
        self.journal: Optional[Journal] = None

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    def column_index(self, name: str) -> int:
        try:
            return self.index[Ident(name)]
        except KeyError:
            raise SQLNameError(f"no such column: {name} in table {self.name}") from None

    def first_index(self, column: int) -> Optional[Index]:
        """The column's index created first, if any."""
        found = [idx for idx in self.indexes if idx.column == column]
        return min(found, key=lambda idx: idx.seq) if found else None

    def _log(self, undo: Callable[[], None], redo: Optional[list]) -> None:
        if self.journal is not None:
            self.journal.record(undo, redo)

    # ------------------------------------------------------------ reading

    def _ensure_order(self) -> None:
        if self._order_dirty:
            self.rows = dict(sorted(self.rows.items()))
            self._order_dirty = False

    def scan(self) -> list[Row]:
        """All rows, in table order."""
        self._ensure_order()
        return list(self.rows.values())

    def scan_items(self) -> list[tuple[int, Row]]:
        """All (rowid, row) pairs, in table order."""
        self._ensure_order()
        return list(self.rows.items())

    # ------------------------------------------------------------ indexes

    def add_index(self, index: Index) -> None:
        """Build ``index`` over the current rows. A unique index on a column that has
        duplicates is a ConstraintError (and nothing changes)."""
        col = index.column
        created_keys = False
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
            created_keys = True
        for rid, row in self.scan_items():
            index.add(row[col], rid, bulk=True)
        self.indexes.append(index)

        def undo() -> None:
            self.indexes.remove(index)
            if created_keys:
                del self.unique_keys[col]
        self._log(undo, None)  # the redo operation is recorded by the Database

    def remove_index(self, index: Index) -> None:
        position = self.indexes.index(index)
        del self.indexes[position]
        col = index.column
        still_unique = (self.columns[col].unique or self.columns[col].primary_key
                        or any(i.unique and i.column == col for i in self.indexes))
        dropped_keys = None if still_unique else self.unique_keys.pop(col, None)

        def undo() -> None:
            self.indexes.insert(position, index)
            if dropped_keys is not None:
                self.unique_keys[col] = dropped_keys
        self._log(undo, None)

    # ------------------------------------------------------------ row changes

    def _violation(self, i: int, value: Any) -> ConstraintError:
        col = self.columns[i]
        kind = "PRIMARY KEY" if col.primary_key else "UNIQUE"
        return ConstraintError(f"{kind} constraint violated: duplicate value {value!r} in "
                               f"{self.name}.{col.name}")

    def insert_rows(self, new_rows: list[Row]) -> None:
        """Append rows after checking unique columns; all or nothing."""
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
        start = self.next_rid
        rid_rows = list(zip(range(start, start + len(new_rows)), new_rows))
        self._apply_insert(rid_rows)
        rids = [rid for rid, _ in rid_rows]
        self._log(lambda: self._apply_delete(rids),
                  ["insert", self.name, [[rid, list(row)] for rid, row in rid_rows]])

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
        old_rows = [(rid, rows[rid]) for rid, _ in changes]
        self._apply_update(changes)
        self._log(lambda: self._apply_update(old_rows),
                  ["update", self.name, [[rid, list(row)] for rid, row in changes]])

    def delete_rows(self, rids: list[int]) -> None:
        if not rids:
            return
        old_rows = [(rid, self.rows[rid]) for rid in rids]
        self._apply_delete(rids)

        self._log(lambda: self._apply_insert(old_rows), ["delete", self.name, list(rids)])

    # The _apply_* methods change rows, unique keys and indexes without checking constraints
    # or journaling: they serve the checked methods above, undo, and replay from the log.

    def _apply_insert(self, rid_rows: list[tuple[int, Row]]) -> None:
        for i, keys in self.unique_keys.items():
            for _, row in rid_rows:
                if row[i] is not None:
                    keys.add(value_key(row[i]))
        bulk = len(rid_rows) >= _BULK
        rows, indexes = self.rows, self.indexes
        for rid, row in rid_rows:
            rows[rid] = row
            for index in indexes:
                index.add(row[index.column], rid, bulk)
            if rid >= self.next_rid:
                self.next_rid = rid + 1
            else:  # an old rowid put back (undo of a DELETE): it went to the end of the dict
                self._order_dirty = True

    def _apply_update(self, changes: list[tuple[int, Row]]) -> None:
        rows = self.rows
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

    def _apply_delete(self, rids: list[int]) -> None:
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

    # ------------------------------------------------------------ schema changes

    def _schema_state(self) -> tuple:
        return (self.columns, self.index, self.rows, self._order_dirty, self.unique_keys,
                list(self.indexes), [(idx, idx.column) for idx in self.indexes])

    def _restore_schema_state(self, state: tuple) -> None:
        (self.columns, self.index, self.rows, self._order_dirty, self.unique_keys,
         self.indexes, columns) = state
        for idx, col in columns:
            idx.column = col

    def add_column(self, column: Column) -> None:
        """Append a column; existing rows get its default. (Checks are the caller's.)"""
        state = self._schema_state()
        self.columns = self.columns + [column]
        self.index = {c.name: i for i, c in enumerate(self.columns)}
        default = column.default
        self.rows = {rid: row + (default,) for rid, row in self.scan_items()}
        self._order_dirty = False
        self._log(lambda: self._restore_schema_state(state),
                  ["add_column", self.name, column_spec(column)])

    def drop_column(self, position: int, dropped_indexes: list[Index]) -> None:
        """Remove a column and its values; ``dropped_indexes`` (all indexes on it) must
        already be gone from the database's index namespace. (Checks are the caller's.)"""
        state = self._schema_state()
        name = self.columns[position].name
        self.columns = self.columns[:position] + self.columns[position + 1:]
        self.index = {c.name: i for i, c in enumerate(self.columns)}
        self.rows = {rid: row[:position] + row[position + 1:]
                     for rid, row in self.scan_items()}
        self._order_dirty = False
        self.indexes = [idx for idx in self.indexes if idx not in dropped_indexes]
        for idx in self.indexes:
            if idx.column > position:
                idx.column -= 1
        self.unique_keys = {(i - 1 if i > position else i): keys
                            for i, keys in self.unique_keys.items() if i != position}
        self._log(lambda: self._restore_schema_state(state),
                  ["drop_column", self.name, name])


def column_spec(column: Column) -> list:
    """A column as a JSON-serializable list (for the log and snapshots)."""
    return [column.name, column.type, column.not_null, column.unique, column.primary_key,
            column.default]


def column_from_spec(spec: list) -> Column:
    name, type_, not_null, unique, primary_key, default = spec
    return Column(name, type_, not_null=not_null, unique=unique, primary_key=primary_key,
                  default=default)


@dataclass
class View:
    """A named query: ``sql`` is its text (what is stored), ``query`` its parsed form."""
    name: str
    columns: Optional[list[str]]  # renamed output columns, if given
    sql: str
    query: Any

    def __post_init__(self) -> None:
        self.name = Ident(self.name)
        if self.columns is not None:
            self.columns = [Ident(c) for c in self.columns]


class Database:
    """The catalog: tables and views (one namespace), and indexes (their own namespace)."""

    def __init__(self) -> None:
        self.tables: dict[str, Table] = {}
        self.views: dict[str, View] = {}
        self.indexes: dict[str, Index] = {}
        self.journal = Journal()

    def relation_exists(self, name: str) -> bool:
        name = Ident(name)
        return name in self.tables or name in self.views

    def get_table(self, name: str) -> Table:
        name = Ident(name)
        table = self.tables.get(name)
        if table is None:
            if name in self.views:
                raise SQLNameError(f"{name} is a view, not a table")
            raise SQLNameError(f"no such table: {name}")
        return table

    def find_table(self, name: str) -> Optional[Table]:
        return self.tables.get(Ident(name))

    def add_table(self, table: Table) -> None:
        """Add a table and its implicit indexes (one per PRIMARY KEY / UNIQUE column)."""
        if self.relation_exists(table.name):
            raise SQLNameError(f"a table or view named {table.name} already exists")
        # named from the defined spellings (CR-4), e.g. Users_Id_key
        implicit = [Index(f"{table.name}_{c.name}_key", table, i, unique=True, implicit=True)
                    for i, c in enumerate(table.columns) if c.unique or c.primary_key]
        for index in implicit:
            if index.name in self.indexes:
                raise SQLNameError(f"index already exists: {index.name} (needed for the "
                                   f"implicit index of {table.name}.{index.column_name})")
        table.journal = self.journal
        self.tables[table.name] = table
        for index in implicit:
            table.indexes.append(index)  # the table is empty: nothing to build
            self.indexes[index.name] = index

        def undo() -> None:
            del self.tables[table.name]
            for index in implicit:
                del self.indexes[index.name]
        self.journal.record(undo, ["create_table", table.name,
                                   [column_spec(c) for c in table.columns]])

    def drop_table(self, name: str) -> None:
        table = self.get_table(name)
        name = table.name
        indexes = list(table.indexes)
        for index in indexes:
            del self.indexes[index.name]
        del self.tables[name]

        def undo() -> None:
            self.tables[name] = table
            for index in indexes:
                self.indexes[index.name] = index
        self.journal.record(undo, ["drop_table", name])

    def add_view(self, view: View) -> None:
        if self.relation_exists(view.name):
            raise SQLNameError(f"a table or view named {view.name} already exists")
        self.views[view.name] = view
        self.journal.record(lambda: self.views.pop(view.name),
                            ["create_view", view.name, view.columns, view.sql])

    def drop_view(self, name: str) -> None:
        name = Ident(name)
        view = self.views.get(name)
        if view is None:
            if name in self.tables:
                raise SQLNameError(f"{name} is a table, not a view")
            raise SQLNameError(f"no such view: {name}")
        del self.views[name]
        self.journal.record(lambda: self.views.__setitem__(name, view), ["drop_view", name])

    def add_index(self, index: Index) -> None:
        if index.name in self.indexes:
            raise SQLNameError(f"index already exists: {index.name}")
        index.table.add_index(index)
        self.indexes[index.name] = index
        self.journal.record(lambda: self.indexes.pop(index.name),
                            ["create_index", index.name, index.table.name, index.column_name,
                             index.unique])

    def drop_index(self, name: str) -> None:
        name = Ident(name)
        index = self.indexes.get(name)
        if index is None:
            raise SQLNameError(f"no such index: {name}")
        if index.implicit:
            raise ConstraintError(f"index {name} belongs to a PRIMARY KEY or UNIQUE constraint "
                                  "and cannot be dropped")
        index.table.remove_index(index)
        del self.indexes[name]
        self.journal.record(lambda: self.indexes.__setitem__(name, index), ["drop_index", name])

    def drop_column(self, table: Table, position: int) -> None:
        """Remove a column with every index on it. (Checks are the caller's.)"""
        dropped = [idx for idx in table.indexes if idx.column == position]
        for idx in dropped:
            del self.indexes[idx.name]
        table.drop_column(position, dropped)

        def undo() -> None:
            for idx in dropped:
                self.indexes[idx.name] = idx
        self.journal.record(undo, None)  # the table records the redo operation

    # ------------------------------------------------------------ replay

    def apply_redo(self, op: list) -> None:
        """Re-apply a logged operation (recovery after a restart)."""
        kind = op[0]
        if kind in ("insert", "update", "delete", "add_column", "drop_column"):
            op = [kind, Ident(op[1]), *op[2:]]
        if kind == "insert":
            self.tables[op[1]]._apply_insert([(rid, tuple(row)) for rid, row in op[2]])
        elif kind == "update":
            self.tables[op[1]]._apply_update([(rid, tuple(row)) for rid, row in op[2]])
        elif kind == "delete":
            self.tables[op[1]]._apply_delete(op[2])
        elif kind == "create_table":
            self.add_table(Table(op[1], [column_from_spec(c) for c in op[2]]))
        elif kind == "drop_table":
            self.drop_table(op[1])
        elif kind == "create_index":
            _, name, table, column, unique = op
            t = self.get_table(table)
            self.add_index(Index(name, t, t.column_index(column), unique=unique))
        elif kind == "drop_index":
            self.drop_index(op[1])
        elif kind == "add_column":
            self.tables[op[1]].add_column(column_from_spec(op[2]))
        elif kind == "create_view":
            self.add_view(view_from_spec(op[1:]))
        elif kind == "drop_view":
            self.drop_view(op[1])
        elif kind == "drop_column":
            t = self.tables[op[1]]
            self.drop_column(t, t.column_index(op[2]))
        else:
            raise ValueError(f"unknown log operation {kind!r}")


def view_from_spec(spec: list) -> View:
    """A view from its stored form ``[name, columns, sql]``."""
    from minidb.parser import Parser  # (the parser does not import the catalog)
    from minidb.lexer import tokenize
    name, columns, sql = spec
    parser = Parser(tokenize(sql), sql)
    query = parser.parse_query()
    parser.expect_end()
    return View(name, columns, sql, query)  # (View makes the names Idents)
