"""The minidb engine: executes one SQL statement at a time for ``minidb.protocol``.

``Engine.execute(sql)`` parses the statement and dispatches it. Every statement is atomic: DML
computes and validates all its changes before applying any of them, and DDL validates first.
"""
from __future__ import annotations

from typing import Any

from minidb import nodes as n
from minidb.executor import Env, Executor, Source
from minidb.parser import parse
from minidb.protocol import ConstraintError, SQLNameError, SQLSyntaxError
from minidb.storage import Column, Database, Table
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
        self.db.tables[s.name] = Table(s.name, cols)
        return {}

    def _x_DropTable(self, s: n.DropTable) -> dict:
        if s.if_exists and s.name not in self.db.tables:
            return {}
        self._table(s.name)
        del self.db.tables[s.name]
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

    def _check_final_state(self, table: Table, changes: dict[int, list | None],
                           new_rows: list[list]) -> None:
        for ci, c in enumerate(table.columns):
            if not c.unique:
                continue
            final = (changes.get(rid, row) for rid, row in table.rows.items())
            values = [r[ci] for r in final if r is not None] + [r[ci] for r in new_rows]
            self._check_unique_values(c.name, values)

    def _apply(self, table: Table, changes: dict[int, list | None], new_rows: list[list]) -> None:
        """Apply validated changes: ``changes`` maps rowid -> new row (None = delete)."""
        for rid, new in changes.items():
            if new is None:
                del table.rows[rid]
            else:
                table.rows[rid] = new
        for row in new_rows:
            table.rows[self.db.new_rowid()] = row

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
        new_rows = []
        for values in source:
            new_rows.append(self._store(table, [c.default for c in table.columns], values, positions))
        self._check_final_state(table, {}, new_rows)
        self._apply(table, {}, new_rows)
        return {"rowcount": len(new_rows)}

    def _target_source(self, table: Table) -> list[Source]:
        return [Source(table.name, table.name, [c.name for c in table.columns])]

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
            values = [f(env) for f in fns]
            changes[rid] = self._store(table, list(row), values, targets)
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
