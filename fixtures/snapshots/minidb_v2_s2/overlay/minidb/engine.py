"""The minidb engine: executes one SQL statement at a time for ``minidb.protocol``.

``Engine.execute(sql)`` parses the statement and dispatches it. Every statement is atomic: DML
computes and validates all its changes before applying any of them, and DDL validates first.
UNIQUE and PRIMARY KEY constraints are checked through the indexes that back them, so a
single-row statement costs O(log n), not O(n).
"""
from __future__ import annotations

from typing import Any

from minidb import nodes as n
from minidb.executor import Compiler, Env, Executor, Scope, Source
from minidb.parser import parse
from minidb.protocol import ConstraintError, SQLNameError, SQLSyntaxError
from minidb.storage import Column, Database, Index, Table
from minidb.values import coerce, hash_key, truth


class Engine:
    """One database session; state lives as long as the process."""

    def __init__(self) -> None:
        self.db = Database()

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
        raise SQLNameError(f"no such table: {name}")

    # ------------------------------------------------------------ queries

    def _x_Select(self, s: n.Select) -> dict:
        return self.ex.query(s)

    def _x_SetOp(self, s: n.SetOp) -> dict:
        return self.ex.query(s)

    def _x_Explain(self, s: n.Explain) -> dict:
        return self.ex.explain(s.query)

    # ------------------------------------------------------------ DDL

    def _column(self, d: n.ColumnDef) -> Column:
        default = coerce(d.default, d.type, d.name) if d.has_default else None
        return Column.from_def(d, default)

    def _x_CreateTable(self, s: n.CreateTable) -> dict:
        if s.name in self.db.tables:
            if s.if_not_exists:
                return {}
            raise SQLNameError(f"{s.name} already exists")
        names = [c.name for c in s.columns]
        if len(set(names)) != len(names):
            raise SQLNameError(f"duplicate column name in table {s.name}")
        cols = [self._column(c) for c in s.columns]
        implicit = [f"{s.name}_{c.name}_key" for c in cols if c.unique]
        for name in implicit:
            if name in self.db.indexes:
                raise SQLNameError(f"index {name} already exists")
        self.db.tables[s.name] = Table(s.name, cols)
        for c in cols:
            if c.unique:
                name = f"{s.name}_{c.name}_key"
                self.db.indexes[name] = Index(name, s.name, c.name, True, self.db.new_index_seq(),
                                              implicit=True)
        return {}

    def _x_DropTable(self, s: n.DropTable) -> dict:
        if s.if_exists and s.name not in self.db.tables:
            return {}
        self._table(s.name)
        del self.db.tables[s.name]
        for name in [i.name for i in self.db.indexes.values() if i.table == s.name]:
            del self.db.indexes[name]
        return {}

    def _x_CreateIndex(self, s: n.CreateIndex) -> dict:
        if s.name in self.db.indexes:
            if s.if_not_exists:
                return {}
            raise SQLNameError(f"index {s.name} already exists")
        table = self._table(s.table)
        ci = table.col_index(s.column)
        if ci is None:
            raise SQLNameError(f"no column {s.column} in table {s.table}")
        if s.unique:
            self._check_unique_values(s.column, [r[ci] for r in table.rows.values()])
        ix = Index(s.name, s.table, s.column, s.unique, self.db.new_index_seq())
        ix.build(table)
        self.db.indexes[s.name] = ix
        return {}

    def _x_DropIndex(self, s: n.DropIndex) -> dict:
        ix = self.db.indexes.get(s.name)
        if ix is None:
            if s.if_exists:
                return {}
            raise SQLNameError(f"no such index: {s.name}")
        if ix.implicit:
            raise ConstraintError(f"index {s.name} enforces a constraint of {ix.table}")
        del self.db.indexes[s.name]
        return {}

    # ------------------------------------------------------------ DML

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

    @staticmethod
    def _store(table: Table, row: list, values: list, positions: list[int]) -> list:
        """Type-check ``values`` into ``row`` at ``positions`` (in order), then NOT NULL checks."""
        for ci, v in zip(positions, values, strict=True):
            c = table.columns[ci]
            row[ci] = coerce(v, c.type, c.name)
        for c, v in zip(table.columns, row, strict=True):
            if v is None and c.not_null:
                raise ConstraintError(f"NOT NULL constraint failed: {table.name}.{c.name}")
        return row

    def _unique_columns(self, table: Table) -> list[tuple[int, Index]]:
        """(column index, an index on it) for every column that must hold unique values."""
        out: dict[int, Index] = {}
        for ix in self.db.table_indexes(table.name):
            ci = table.col_index(ix.column)
            if (ix.unique or table.columns[ci].unique) and ci not in out:
                out[ci] = ix
        return sorted(out.items())

    def _check_final_state(self, table: Table, changes: dict[int, list | None],
                           new_rows: list[list]) -> None:
        """UNIQUE / PRIMARY KEY against the state at the end of the statement."""
        for ci, ix in self._unique_columns(table):
            seen: set = set()
            pending = [(rid, row) for rid, row in changes.items() if row is not None]
            pending += [(None, row) for row in new_rows]
            for rid, row in pending:
                v = row[ci]
                if v is None:
                    continue
                k = hash_key(v)
                if k in seen:
                    raise ConstraintError(f"UNIQUE constraint failed: duplicate value {v!r} in "
                                          f"{table.name}.{table.columns[ci].name}")
                seen.add(k)
                for other in ix.eq(v):
                    if other != rid and other not in changes:
                        raise ConstraintError(f"UNIQUE constraint failed: duplicate value {v!r} in "
                                              f"{table.name}.{table.columns[ci].name}")

    def _apply(self, table: Table, changes: dict[int, list | None], new_rows: list[list]) -> None:
        """Apply validated changes: ``changes`` maps rowid -> new row (None = delete)."""
        indexes = [(ix, table.col_index(ix.column)) for ix in self.db.table_indexes(table.name)]
        rows = table.rows
        for rid, new in changes.items():
            old = rows[rid]
            for ix, ci in indexes:
                if new is None or new[ci] != old[ci] or type(new[ci]) is not type(old[ci]):
                    ix.remove(old[ci], rid)
                    if new is not None:
                        ix.add(new[ci], rid)
            if new is None:
                del rows[rid]
            else:
                rows[rid] = new
        added = []
        for row in new_rows:
            rid = self.db.new_rowid()
            rows[rid] = row
            added.append(rid)
        for ix, ci in indexes:
            ix.add_many([(rows[rid][ci], rid) for rid in added])

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
        if s.query is not None:
            prepared = self.ex.prepare(s.query)
            if len(prepared.columns) != len(positions):
                raise SQLSyntaxError(f"expected {len(positions)} columns, got {len(prepared.columns)}")
            source = prepared.run(None)
        else:
            for vals in s.rows:
                if len(vals) != len(positions):
                    raise SQLSyntaxError(f"expected {len(positions)} values, got {len(vals)}")
            comp = self.ex.compiler([])
            compiled = [[comp.compile(e) for e in vals] for vals in s.rows]
            env = Env(())
            source = ([f(env) for f in fns] for fns in compiled)
        defaults = [c.default for c in table.columns]
        new_rows = [self._store(table, list(defaults), values, positions) for values in source]
        self._check_final_state(table, {}, new_rows)
        self._apply(table, {}, new_rows)
        return {"rowcount": len(new_rows)}

    def _target_scope(self, table: Table) -> Scope:
        return Scope([Source(table.name, table.name, [c.name for c in table.columns],
                             table=table.name)])

    def _x_Update(self, s: n.Update) -> dict:
        table = self._table(s.table)
        targets = []
        for name, _ in s.assignments:
            ci = table.col_index(name)
            if ci is None:
                raise SQLNameError(f"no column {name} in table {s.table}")
            targets.append(ci)
        ex = self.ex
        scope = self._target_scope(table)
        comp = Compiler(ex, scope)
        fns = [comp.compile(e) for _, e in s.assignments]
        where = comp.compile(s.where) if s.where is not None else None
        changes: dict[int, list | None] = {}
        rows = table.rows
        for rid in ex.target_rowids(table.name, s.where, scope):
            row = rows[rid]
            env = Env((row,))
            if where is not None and truth(where(env), "WHERE condition") is not True:
                continue
            values = [f(env) for f in fns]
            changes[rid] = self._store(table, list(row), values, targets)
        self._check_final_state(table, changes, [])
        self._apply(table, changes, [])
        return {"rowcount": len(changes)}

    def _x_Delete(self, s: n.Delete) -> dict:
        table = self._table(s.table)
        ex = self.ex
        scope = self._target_scope(table)
        where = Compiler(ex, scope).compile(s.where) if s.where is not None else None
        rows = table.rows
        doomed = [rid for rid in ex.target_rowids(table.name, s.where, scope)
                  if where is None or truth(where(Env((rows[rid],))), "WHERE condition") is True]
        self._apply(table, dict.fromkeys(doomed), [])
        return {"rowcount": len(doomed)}


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
