"""Statement execution: binds a parsed statement against the catalog, then runs it.

Every statement is fully checked (names, syntax rules that need the schema) before any row is
processed, and changes the database only after all of its rows have been processed and every
constraint has been checked, so a failing statement has no effect.
"""
from __future__ import annotations

from typing import Any

from minidb import nodes as n
from minidb import values as v
from minidb.access import TableAccess
from minidb.catalog import Column, Database, Index, Table
from minidb.compiler import ExprCompiler, QueryContext, Runtime, Scope, as_predicate
from minidb.planner import build_query
from minidb.protocol import ConstraintError, SQLNameError, SQLSyntaxError


class Executor:
    def __init__(self, db: Database) -> None:
        self.db = db

    def execute(self, stmt: n.Statement) -> dict:
        method = getattr(self, "exec_" + type(stmt).__name__)
        return method(stmt)

    def _context(self) -> QueryContext:
        """A fresh top-level context: one per statement."""
        return QueryContext(self.db, Runtime())

    # ------------------------------------------------------------ DDL

    def exec_CreateTable(self, stmt: n.CreateTable) -> dict:
        if self.db.find_table(stmt.name) is not None:
            if stmt.if_not_exists:
                return {}
            raise SQLNameError(f"table already exists: {stmt.name}")
        columns: list[Column] = []
        seen: set[str] = set()
        for cd in stmt.columns:
            if cd.name in seen:
                raise SQLNameError(f"duplicate column name: {cd.name}")
            seen.add(cd.name)
            default = v.coerce_to_column(cd.default, cd.type, cd.name)
            columns.append(Column(cd.name, cd.type, not_null=cd.not_null or cd.primary_key,
                                  unique=cd.unique or cd.primary_key,
                                  primary_key=cd.primary_key, default=default))
        self.db.add_table(Table(stmt.name, columns))
        return {}

    def exec_DropTable(self, stmt: n.DropTable) -> dict:
        if stmt.if_exists and self.db.find_table(stmt.name) is None:
            return {}
        self.db.drop_table(stmt.name)
        return {}

    def exec_AlterAddColumn(self, stmt: n.AlterAddColumn) -> dict:
        table = self.db.get_table(stmt.table)
        cd = stmt.column
        if cd.name in table.index:
            raise SQLNameError(f"column {cd.name} already exists in table {table.name}")
        default = v.coerce_to_column(cd.default, cd.type, cd.name)
        if cd.not_null and default is None and table.rows:
            raise ConstraintError(f"cannot add NOT NULL column {cd.name} without a non-NULL "
                                  f"default to table {table.name}, which has rows")
        table.add_column(Column(cd.name, cd.type, not_null=cd.not_null, default=default))
        return {}

    def exec_AlterDropColumn(self, stmt: n.AlterDropColumn) -> dict:
        table = self.db.get_table(stmt.table)
        position = table.column_index(stmt.column)
        if table.columns[position].primary_key:
            raise ConstraintError(f"cannot drop the PRIMARY KEY column {stmt.column}")
        if len(table.columns) == 1:
            raise ConstraintError(f"cannot drop {stmt.column}, the only column of table "
                                  f"{table.name}")
        self.db.drop_column(table, position)
        return {}

    def exec_CreateIndex(self, stmt: n.CreateIndex) -> dict:
        if stmt.name in self.db.indexes:
            if stmt.if_not_exists:
                return {}
            raise SQLNameError(f"index already exists: {stmt.name}")
        table = self.db.get_table(stmt.table)
        column = table.column_index(stmt.column)
        self.db.add_index(Index(stmt.name, table, column, unique=stmt.unique))
        return {}

    def exec_DropIndex(self, stmt: n.DropIndex) -> dict:
        if stmt.if_exists and stmt.name not in self.db.indexes:
            return {}
        self.db.drop_index(stmt.name)
        return {}

    def exec_Explain(self, stmt: n.Explain) -> dict:
        plan = build_query(stmt.query, self._context())
        return {"columns": ["plan"], "rows": [[line] for line in plan.explain()]}

    # ------------------------------------------------------------ DML

    def exec_Insert(self, stmt: n.Insert) -> dict:
        table = self.db.get_table(stmt.table)
        if stmt.columns is None:
            targets = list(range(len(table.columns)))
        else:
            targets = [table.column_index(c) for c in stmt.columns]
        ctx = self._context()
        if stmt.query is not None:
            plan = build_query(stmt.query, ctx)
            if len(plan.columns) != len(targets):
                raise SQLSyntaxError(f"INSERT query returns {len(plan.columns)} columns but "
                                     f"{len(targets)} are being filled")
            value_rows: Any = plan.run()  # completely, before any row is stored
        else:
            compiler = ExprCompiler(Scope(), "VALUES", ctx)
            compiled_rows = []
            for values in stmt.rows:
                if len(values) != len(targets):
                    raise SQLSyntaxError(f"INSERT has {len(values)} values but "
                                         f"{len(targets)} columns")
                compiled_rows.append([compiler.compile(e) for e in values])
            # rows are evaluated one at a time, interleaved with their checks
            value_rows = ([f(()) for f in fns] for fns in compiled_rows)
        template = [c.default for c in table.columns]
        new_rows = []
        for vals in value_rows:
            row = list(template)
            for idx, val in zip(targets, vals):
                col = table.columns[idx]
                row[idx] = v.coerce_to_column(val, col.type, col.name)
            _check_not_null(table, row)
            new_rows.append(tuple(row))
        table.insert_rows(new_rows)
        return {"rowcount": len(new_rows)}

    def _table_scope(self, table: Table) -> Scope:
        scope = Scope()
        scope.add(table.name, table.column_names)
        return scope

    def exec_Update(self, stmt: n.Update) -> dict:
        table = self.db.get_table(stmt.table)
        scope = self._table_scope(table)
        targets = [table.column_index(name) for name, _ in stmt.assignments]
        compiler = ExprCompiler(scope, "UPDATE", self._context())
        set_fns = [compiler.compile(e) for _, e in stmt.assignments]
        where = (as_predicate(compiler.compile(stmt.where), "WHERE")
                 if stmt.where is not None else None)
        changes = []
        for rid, old in TableAccess(table, stmt.where, scope).items():
            if where is not None and not where(old):
                continue
            vals = [f(old) for f in set_fns]
            row = list(old)
            for idx, val in zip(targets, vals):
                col = table.columns[idx]
                row[idx] = v.coerce_to_column(val, col.type, col.name)
            _check_not_null(table, row)
            changes.append((rid, tuple(row)))
        table.update_rows(changes)
        return {"rowcount": len(changes)}

    def exec_Delete(self, stmt: n.Delete) -> dict:
        table = self.db.get_table(stmt.table)
        if stmt.where is None:
            rids = [rid for rid, _ in table.scan_items()]
        else:
            scope = self._table_scope(table)
            compiler = ExprCompiler(scope, "DELETE", self._context())
            where = as_predicate(compiler.compile(stmt.where), "WHERE")
            rids = [rid for rid, row in TableAccess(table, stmt.where, scope).items()
                    if where(row)]
        table.delete_rows(rids)
        return {"rowcount": len(rids)}

    # ------------------------------------------------------------ SELECT

    def _query(self, stmt: n.Query) -> dict:
        plan = build_query(stmt, self._context())
        return {"columns": list(plan.columns), "rows": [list(r) for r in plan.run()]}

    exec_Select = exec_Compound = _query


def _check_not_null(table: Table, row: list) -> None:
    for col, val in zip(table.columns, row):
        if val is None and col.not_null:
            raise ConstraintError(f"NOT NULL constraint violated: {table.name}.{col.name}")
