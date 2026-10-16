"""The minidb engine: executes one SQL statement at a time for ``minidb.protocol``.

``Engine.execute(sql)`` parses the statement and dispatches it. Every statement is atomic: DML
computes and validates all its changes before applying any of them, DDL validates first, and a
transaction keeps a full copy of the database taken at BEGIN.
"""
from __future__ import annotations

import copy
from typing import Any

from minidb import nodes as n
from minidb import storage
from minidb.executor import Env, Executor, Source
from minidb.parser import parse
from minidb.protocol import ConstraintError, SQLNameError, SQLSyntaxError, TransactionError
from minidb.storage import Column, Database, Index, Table, View
from minidb.values import coerce, hash_key, truth


def _parse_view(sql: str) -> n.Select:
    stmt = parse(sql)
    if not isinstance(stmt, n.Select):
        raise ValueError("view definition is not a SELECT")
    return stmt


class Engine:
    """One database session; state lives as long as the process."""

    def __init__(self) -> None:
        self.db = Database()
        self.tx_backup: Database | None = None

    # ------------------------------------------------------------ dispatch

    def execute(self, sql: str) -> dict:
        stmt = parse(sql)
        handler = getattr(self, "_x_" + type(stmt).__name__)
        return handler(stmt)

    @property
    def ex(self) -> Executor:
        return Executor(self.db)

    def _table(self, name: str) -> Table:
        if name in self.db.tables:
            return self.db.tables[name]
        if name in self.db.views:
            raise SQLNameError(f"{name} is a view, not a table")
        raise SQLNameError(f"no such table: {name}")

    # ------------------------------------------------------------ queries

    def _x_Select(self, s: n.Select) -> dict:
        return self.ex.query(s)

    def _x_Explain(self, s: n.Explain) -> dict:
        return self.ex.explain(s.query)

    # ------------------------------------------------------------ DDL

    def _column(self, d: n.ColumnDef) -> Column:
        default = coerce(d.default, d.type, d.name) if d.has_default else None
        return Column.from_def(d, default)

    def _x_CreateTable(self, s: n.CreateTable) -> dict:
        if self.db.relation_exists(s.name):
            raise SQLNameError(f"{s.name} already exists")
        names = [c.name for c in s.columns]
        if len(set(names)) != len(names):
            raise SQLNameError(f"duplicate column name in table {s.name}")
        if sum(c.primary_key for c in s.columns) > 1:
            raise SQLSyntaxError("a table can have only one PRIMARY KEY column")
        cols = [self._column(c) for c in s.columns]
        self.db.tables[s.name] = Table(s.name, cols)
        return {}

    def _x_DropTable(self, s: n.DropTable) -> dict:
        self._table(s.name)
        del self.db.tables[s.name]
        for name in [i.name for i in self.db.indexes.values() if i.table == s.name]:
            del self.db.indexes[name]
        return {}

    def _x_CreateIndex(self, s: n.CreateIndex) -> dict:
        if s.name in self.db.indexes:
            raise SQLNameError(f"index {s.name} already exists")
        table = self._table(s.table)
        ci = table.col_index(s.column)
        if ci is None:
            raise SQLNameError(f"no column {s.column} in table {s.table}")
        if s.unique:
            self._check_unique_values(s.column, [r[ci] for r in table.rows.values()])
        ix = Index(s.name, s.table, s.column, s.unique, self.db.next_index_seq)
        ix.build(table)
        self.db.next_index_seq += 1
        self.db.indexes[s.name] = ix
        return {}

    def _x_DropIndex(self, s: n.DropIndex) -> dict:
        if s.name not in self.db.indexes:
            raise SQLNameError(f"no such index: {s.name}")
        del self.db.indexes[s.name]
        return {}

    def _x_CreateView(self, s: n.CreateView) -> dict:
        if self.db.relation_exists(s.name):
            raise SQLNameError(f"{s.name} already exists")
        self.ex.prepare(s.query)  # validates every name now
        self.db.views[s.name] = View(s.name, s.sql, s.query)
        return {}

    def _x_DropView(self, s: n.DropView) -> dict:
        if s.name not in self.db.views:
            if s.name in self.db.tables:
                raise SQLNameError(f"{s.name} is a table, not a view")
            raise SQLNameError(f"no such view: {s.name}")
        del self.db.views[s.name]
        return {}

    def _x_AlterAddColumn(self, s: n.AlterAddColumn) -> dict:
        table = self._table(s.table)
        if table.col_index(s.column.name) is not None:
            raise SQLNameError(f"column {s.column.name} already exists in {s.table}")
        col = self._column(s.column)
        if col.not_null and col.default is None and table.rows:
            raise ConstraintError(f"cannot add NOT NULL column {col.name} without a default "
                                  "to a table that has rows")
        table.columns.append(col)
        for row in table.rows.values():
            row.append(col.default)
        return {}

    # ------------------------------------------------------------ DML

    def _unique_columns(self, table: Table) -> list[int]:
        cols = {i for i, c in enumerate(table.columns) if c.unique}
        for ix in self.db.table_indexes(table.name):
            if ix.unique:
                cols.add(table.col_index(ix.column))
        return sorted(cols)

    @staticmethod
    def _check_unique_values(column: str, values) -> None:
        seen = set()
        for v in values:
            if v is None:
                continue
            k = hash_key(v)
            if k in seen:
                raise ConstraintError(f"UNIQUE constraint failed: duplicate value {v!r} in {column}")
            seen.add(k)

    def _check_row(self, table: Table, row: list) -> None:
        for c, v in zip(table.columns, row, strict=True):
            if v is None and c.not_null:
                raise ConstraintError(f"NOT NULL constraint failed: {table.name}.{c.name}")

    def _apply(self, table: Table, changes: dict[int, list | None], new_rows: list[list]) -> None:
        """Apply validated changes: ``changes`` maps rowid -> new row (None = delete)."""
        indexes = [(ix, table.col_index(ix.column)) for ix in self.db.table_indexes(table.name)]
        for rid, new in changes.items():
            old = table.rows[rid]
            for ix, ci in indexes:
                ix.remove(old[ci], rid)
            if new is None:
                del table.rows[rid]
            else:
                table.rows[rid] = new
                for ix, ci in indexes:
                    ix.add(new[ci], rid)
        for row in new_rows:
            rid = self.db.new_rowid()
            table.rows[rid] = row
            for ix, ci in indexes:
                ix.add(row[ci], rid)

    def _check_final_state(self, table: Table, changes: dict[int, list | None],
                           new_rows: list[list]) -> None:
        for ci in self._unique_columns(table):
            final = (changes.get(rid, row) for rid, row in table.rows.items())
            values = [r[ci] for r in final if r is not None] + [r[ci] for r in new_rows]
            self._check_unique_values(table.columns[ci].name, values)

    def _x_Insert(self, s: n.Insert) -> dict:
        table = self._table(s.table)
        if s.columns is None:
            positions = list(range(len(table.columns)))
        else:
            positions = []
            for name in s.columns:
                ci = table.col_index(name)
                if ci is None:
                    raise SQLNameError(f"no column {name} in table {s.table}")
                positions.append(ci)
        for vals in s.rows:
            if len(vals) != len(positions):
                raise SQLSyntaxError(f"expected {len(positions)} values, got {len(vals)}")
        comp = self.ex.compiler([])
        compiled = [[comp.compile(e) for e in vals] for vals in s.rows]
        env = Env(())
        new_rows = []
        for fns in compiled:
            row = [c.default for c in table.columns]
            for ci, f in zip(positions, fns, strict=True):
                c = table.columns[ci]
                row[ci] = coerce(f(env), c.type, c.name)
            self._check_row(table, row)
            new_rows.append(row)
        self._check_final_state(table, {}, new_rows)
        self._apply(table, {}, new_rows)
        return {"rowcount": len(new_rows)}

    def _target_source(self, table: Table) -> list[Source]:
        return [Source(table.name, table.name, [c.name for c in table.columns], table=table.name)]

    def _x_Update(self, s: n.Update) -> dict:
        table = self._table(s.table)
        targets = []
        for name, _ in s.assignments:
            ci = table.col_index(name)
            if ci is None:
                raise SQLNameError(f"no column {name} in table {s.table}")
            targets.append(ci)
        comp = self.ex.compiler(self._target_source(table))
        fns = [comp.compile(e) for _, e in s.assignments]
        where = comp.compile(s.where) if s.where is not None else None
        changes: dict[int, list | None] = {}
        for rid, row in table.rows.items():
            env = Env((row,))
            if where is not None and truth(where(env), "WHERE condition") is not True:
                continue
            new = list(row)
            for ci, f in zip(targets, fns, strict=True):
                c = table.columns[ci]
                new[ci] = coerce(f(env), c.type, c.name)
            self._check_row(table, new)
            changes[rid] = new
        self._check_final_state(table, changes, [])
        self._apply(table, changes, [])
        return {"rowcount": len(changes)}

    def _x_Delete(self, s: n.Delete) -> dict:
        table = self._table(s.table)
        comp = self.ex.compiler(self._target_source(table))
        where = comp.compile(s.where) if s.where is not None else None
        doomed = [rid for rid, row in table.rows.items()
                  if where is None or truth(where(Env((row,))), "WHERE condition") is True]
        self._apply(table, dict.fromkeys(doomed), [])
        return {"rowcount": len(doomed)}

    # ------------------------------------------------------------ transactions

    def _x_Begin(self, s: n.Begin) -> dict:
        if self.tx_backup is not None:
            raise TransactionError("a transaction is already open")
        self.tx_backup = copy.deepcopy(self.db)
        return {}

    def _x_Commit(self, s: n.Commit) -> dict:
        if self.tx_backup is None:
            raise TransactionError("no transaction is open")
        self.tx_backup = None
        return {}

    def _x_Rollback(self, s: n.Rollback) -> dict:
        if self.tx_backup is None:
            raise TransactionError("no transaction is open")
        self.db, self.tx_backup = self.tx_backup, None
        return {}

    # ------------------------------------------------------------ persistence

    def _x_Save(self, s: n.Save) -> dict:
        if self.tx_backup is not None:
            raise TransactionError("SAVE is not allowed inside a transaction")
        storage.save(self.db, s.path)
        return {}

    def _x_Load(self, s: n.Load) -> dict:
        if self.tx_backup is not None:
            raise TransactionError("LOAD is not allowed inside a transaction")
        self.db = storage.load(s.path, _parse_view)
        return {}


def run_sql(engine: Engine, script: str) -> list[Any]:
    """Convenience for tests: execute every statement of ``script``; return results/errors."""
    from minidb.protocol import DBError, split_statements
    out: list[Any] = []
    for stmt in split_statements(script):
        try:
            out.append(engine.execute(stmt))
        except DBError as exc:
            out.append(exc)
    return out
