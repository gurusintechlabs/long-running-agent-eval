"""Statement execution: binds a parsed statement against the catalog, then runs it.

Every statement is fully checked (names, syntax rules that need the schema) before any row is
processed, and changes the database only after all of its rows have been processed and every
constraint has been checked, so a failing statement has no effect.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from minidb import nodes as n
from minidb import values as v
from minidb.catalog import Column, Database, Table
from minidb.compiler import (
    AggregateSpec,
    ExprCompiler,
    Fn,
    Scope,
    as_predicate,
    contains_aggregate,
)
from minidb.protocol import ConstraintError, SQLNameError, SQLSyntaxError, SQLTypeError


class Executor:
    def __init__(self, db: Database) -> None:
        self.db = db

    def execute(self, stmt: n.Statement) -> dict:
        method = getattr(self, "exec_" + type(stmt).__name__)
        return method(stmt)

    # ------------------------------------------------------------ DDL

    def exec_CreateTable(self, stmt: n.CreateTable) -> dict:
        if self.db.find_table(stmt.name) is not None:
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
        self.db.drop_table(stmt.name)
        return {}

    # ------------------------------------------------------------ DML

    def exec_Insert(self, stmt: n.Insert) -> dict:
        table = self.db.get_table(stmt.table)
        if stmt.columns is None:
            targets = list(range(len(table.columns)))
        else:
            targets = [table.column_index(c) for c in stmt.columns]
        compiler = ExprCompiler(Scope(), "VALUES")
        compiled_rows = []
        for values in stmt.rows:
            if len(values) != len(targets):
                raise SQLSyntaxError(f"INSERT has {len(values)} values but {len(targets)} "
                                     "columns")
            compiled_rows.append([compiler.compile(e) for e in values])
        template = [c.default for c in table.columns]
        new_rows = []
        for fns in compiled_rows:
            vals = [f(()) for f in fns]
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
        compiler = ExprCompiler(scope, "UPDATE")
        set_fns = [compiler.compile(e) for _, e in stmt.assignments]
        where = (as_predicate(compiler.compile(stmt.where), "WHERE")
                 if stmt.where is not None else None)
        changes = []
        for pos, old in enumerate(table.rows):
            if where is not None and not where(old):
                continue
            vals = [f(old) for f in set_fns]
            row = list(old)
            for idx, val in zip(targets, vals):
                col = table.columns[idx]
                row[idx] = v.coerce_to_column(val, col.type, col.name)
            _check_not_null(table, row)
            changes.append((pos, tuple(row)))
        table.update_rows(changes)
        return {"rowcount": len(changes)}

    def exec_Delete(self, stmt: n.Delete) -> dict:
        table = self.db.get_table(stmt.table)
        if stmt.where is None:
            positions = set(range(len(table.rows)))
        else:
            compiler = ExprCompiler(self._table_scope(table), "DELETE")
            where = as_predicate(compiler.compile(stmt.where), "WHERE")
            positions = {pos for pos, row in enumerate(table.rows) if where(row)}
        table.delete_rows(positions)
        return {"rowcount": len(positions)}

    # ------------------------------------------------------------ SELECT

    def exec_Select(self, stmt: n.Select) -> dict:
        columns, rows = SelectPlan(self.db, stmt).run()
        return {"columns": columns, "rows": rows}


def _check_not_null(table: Table, row: list) -> None:
    for col, val in zip(table.columns, row):
        if val is None and col.not_null:
            raise ConstraintError(f"NOT NULL constraint violated: {table.name}.{col.name}")


class SelectPlan:
    """A bound SELECT statement, ready to run."""

    def __init__(self, db: Database, stmt: n.Select) -> None:
        self.stmt = stmt
        self.scope = Scope()
        self.tables: list[Table] = []
        self.joins: list[tuple[str, Optional[Callable[[tuple], bool]]]] = []
        self.where: Optional[Callable[[tuple], bool]] = None
        self._bind_from(db)

        grouped = bool(stmt.group_by) or stmt.having is not None or any(
            isinstance(item, n.SelectItem) and contains_aggregate(item.expr)
            for item in stmt.items) or any(
            contains_aggregate(o.expr) for o in stmt.order_by)
        self.grouped = grouped
        self.aggregates: list[AggregateSpec] = []
        self.group_indices: list[int] = []
        if grouped:
            self.group_indices = [self.scope.resolve(ref) for ref in stmt.group_by]
            self.compiler = ExprCompiler(self.scope, "the select list",
                                         aggregates=self.aggregates,
                                         grouping=set(self.group_indices))
        else:
            self.compiler = ExprCompiler(self.scope, "the select list")

        self.columns: list[str] = []
        self.item_fns: list[Fn] = []
        self._bind_items()
        self.having = None
        if stmt.having is not None:
            self.compiler.clause = "HAVING"
            self.having = as_predicate(self.compiler.compile(stmt.having), "HAVING")
        self.compiler.clause = "ORDER BY"
        # each sort key: (output column index or None, expression or None, descending)
        self.sort_keys: list[tuple[Optional[int], Optional[Fn], bool]] = []
        self._bind_order_by()

    # ------------------------------------------------------------ binding

    def _bind_from(self, db: Database) -> None:
        clause = self.stmt.from_
        if clause is None:
            return
        refs = [clause.first] + [j.table for j in clause.joins]
        for ref in refs:
            table = db.get_table(ref.name)
            self.scope.add(ref.exposed, table.column_names)
            self.tables.append(table)
        for k, join in enumerate(clause.joins, start=2):
            pred = None
            if join.on is not None:
                on = ExprCompiler(self.scope, "ON", visible=k)
                pred = as_predicate(on.compile(join.on), "ON")
            self.joins.append((join.kind, pred))
        if self.stmt.where is not None:
            where = ExprCompiler(self.scope, "WHERE")
            self.where = as_predicate(where.compile(self.stmt.where), "WHERE")

    def _bind_items(self) -> None:
        for item in self.stmt.items:
            if isinstance(item, n.Star):
                if self.stmt.from_ is None:
                    raise SQLSyntaxError("SELECT * requires FROM")
                if self.grouped:
                    raise SQLSyntaxError("* is not allowed in a grouped query")
                sources = (self.scope.sources if item.table is None
                           else [self.scope.source(item.table)])
                for src in sources:
                    for i, name in enumerate(src.columns):
                        idx = src.offset + i
                        self.columns.append(name)
                        self.item_fns.append(lambda env, idx=idx: env[idx])
                continue
            self.item_fns.append(self.compiler.compile(item.expr))
            self.columns.append(item.alias or _output_name(item.expr))

    def _bind_order_by(self) -> None:
        for item in self.stmt.order_by:
            e = item.expr
            if item.bare and isinstance(e, n.Literal) and type(e.value) is int:
                if not 1 <= e.value <= len(self.columns):
                    raise SQLSyntaxError(f"ORDER BY position {e.value} is not in the select "
                                         "list")
                self.sort_keys.append((e.value - 1, None, item.desc))
                continue
            if item.bare and isinstance(e, n.ColumnRef) and e.table is None:
                matches = [i for i, c in enumerate(self.columns) if c == e.name]
                if len(matches) > 1:
                    raise SQLNameError(f"ORDER BY {e.name} is ambiguous")
                if matches:
                    self.sort_keys.append((matches[0], None, item.desc))
                    continue
            if self.stmt.distinct:
                raise SQLSyntaxError("with SELECT DISTINCT, ORDER BY items must be output "
                                     "columns")
            self.sort_keys.append((None, self.compiler.compile(e), item.desc))

    # ------------------------------------------------------------ execution

    def _source_rows(self) -> list[tuple]:
        if not self.tables:
            return [()]
        rows = [tuple(r) for r in self.tables[0].rows]
        for table, (kind, pred) in zip(self.tables[1:], self.joins):
            right = table.rows
            nulls = (None,) * len(table.columns)
            joined = []
            for left in rows:
                matched = False
                for r in right:
                    combined = left + r
                    if pred is None or pred(combined):
                        joined.append(combined)
                        matched = True
                if kind == "LEFT" and not matched:
                    joined.append(left + nulls)
            rows = joined
        return rows

    def run(self) -> tuple[list[str], list[list[Any]]]:
        rows = self._source_rows()
        if self.where is not None:
            where = self.where
            rows = [r for r in rows if where(r)]
        results: list[tuple[tuple, list]] = []  # (output row, expression sort keys)
        item_fns = self.item_fns
        key_fns = [fn for _, fn, _ in self.sort_keys if fn is not None]
        if self.grouped:
            envs = self._group_envs(rows)
        else:
            envs = rows
        for env in envs:
            out = tuple(f(env) for f in item_fns)
            results.append((out, [f(env) for f in key_fns]))
        if self.stmt.distinct:
            seen: set = set()
            unique = []
            for res in results:
                k = tuple(v.value_key(x) for x in res[0])
                if k not in seen:
                    seen.add(k)
                    unique.append(res)
            results = unique
        if self.sort_keys and len(results) > 1:
            results = self._sort(results)
        offset = self.stmt.offset or 0
        if offset:
            results = results[offset:]
        if self.stmt.limit is not None:
            results = results[:self.stmt.limit]
        return list(self.columns), [list(out) for out, _ in results]

    def _group_envs(self, rows: list[tuple]) -> list[tuple]:
        groups: dict[tuple, list[tuple]] = {}
        if self.group_indices:
            idxs = self.group_indices
            for r in rows:
                groups.setdefault(tuple(v.value_key(r[i]) for i in idxs), []).append(r)
        else:
            groups[()] = rows
        width = self.scope.width
        envs = []
        for members in groups.values():
            rep = members[0] if members else (None,) * width
            env = rep + tuple(a.compute(members) for a in self.aggregates)
            if self.having is None or self.having(env):
                envs.append(env)
        return envs

    def _sort(self, results: list[tuple[tuple, list]]) -> list[tuple[tuple, list]]:
        expr_pos = 0
        getters = []
        for out_idx, fn, desc in self.sort_keys:
            if fn is None:
                getters.append((lambda res, i=out_idx: res[0][i], desc))
            else:
                getters.append((lambda res, i=expr_pos: res[1][i], desc))
                expr_pos += 1
        for get, _ in getters:
            classes = {v.value_class(x) for x in map(get, results) if x is not None}
            if len(classes) > 1:
                raise SQLTypeError("ORDER BY compares values of incomparable types: "
                                   + ", ".join(sorted(classes)))
        results = list(results)
        for get, desc in reversed(getters):
            results.sort(key=lambda res, get=get: _sort_key(get(res)), reverse=desc)
        return results


def _sort_key(x: Any) -> tuple:
    return (0,) if x is None else (1, x)


def _output_name(e: n.Expr) -> str:
    if isinstance(e, n.ColumnRef):
        return e.name
    if isinstance(e, n.FuncCall):
        return e.name
    return "?column?"
