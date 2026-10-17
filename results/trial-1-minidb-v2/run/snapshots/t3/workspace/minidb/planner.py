"""Query plans: a bound SELECT (``SelectPlan``) or set operation (``CompoundPlan``).

A plan is built (all name and syntax checks) before any row is read. ``plan.columns`` are the
output names and ``plan.run()`` returns the output rows as tuples. A plan that is a subquery
reads the envs of its enclosing queries from the statement's ``Runtime``.
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Union

from minidb import nodes as n
from minidb import values as v
from minidb.access import EquiJoin, TableAccess, equi_join
from minidb.catalog import Index
from minidb.compiler import (
    AggregateSpec,
    ExprCompiler,
    Fn,
    QueryContext,
    Scope,
    as_predicate,
    contains_aggregate,
)
from minidb.protocol import SQLNameError, SQLSyntaxError, SQLTypeError

Plan = Union["SelectPlan", "CompoundPlan"]

# A sort key: (getter of the key from a result entry, descending, NULLs first)
SortKey = tuple[Callable[[Any], Any], bool, bool]


def build_query(query: n.Query, ctx: QueryContext) -> Plan:
    if isinstance(query, n.Compound):
        return CompoundPlan(query, ctx)
    return SelectPlan(query, ctx)


def sort_entries(entries: list, keys: list[SortKey]) -> list:
    """Stable multi-key sort, NULLs placed first or last per key. Two non-NULL values of
    incomparable types under one key are a TypeError, whatever the sort would compare."""
    if not keys or len(entries) < 2:
        return entries
    for get, _, _ in keys:
        classes = {v.value_class(x) for x in map(get, entries) if x is not None}
        if len(classes) > 1:
            raise SQLTypeError("ORDER BY compares values of incomparable types: "
                               + ", ".join(sorted(classes)))
    entries = list(entries)
    for get, desc, nulls_first in reversed(keys):
        # NULL's key must be "larger" in the sort's own direction when it goes at the end of
        # an ascending sort or the start of a descending one.
        null_key = (1,) if nulls_first == desc else (-1,)
        entries.sort(key=lambda e, get=get, null_key=null_key: _sort_key(get(e), null_key),
                     reverse=desc)
    return entries


def _sort_key(x: Any, null_key: tuple) -> tuple:
    return null_key if x is None else (0, x)


def apply_limit(entries: list, limit: Optional[int], offset: Optional[int]) -> list:
    if offset:
        entries = entries[offset:]
    if limit is not None:
        entries = entries[:limit]
    return entries


def output_position(item: n.OrderItem, columns: list[str]) -> Optional[int]:
    """The output column an ORDER BY item refers to (by position or bare name), or None."""
    e = item.expr
    if item.bare and isinstance(e, n.Literal) and type(e.value) is int:
        if not 1 <= e.value <= len(columns):
            raise SQLSyntaxError(f"ORDER BY position {e.value} is not in the select list")
        return e.value - 1
    if item.bare and isinstance(e, n.ColumnRef) and e.table is None:
        matches = [i for i, c in enumerate(columns) if c == e.name]
        if len(matches) > 1:
            raise SQLNameError(f"ORDER BY {e.name} is ambiguous")
        if matches:
            return matches[0]
    return None


def _dedupe(rows: list[tuple]) -> list[tuple]:
    seen: set = set()
    unique = []
    for row in rows:
        k = row_key(row)
        if k not in seen:
            seen.add(k)
            unique.append(row)
    return unique


def row_key(row: tuple) -> tuple:
    return tuple(v.value_key(x) for x in row)


class _Source:
    """The rows of one table reference: a stored table, or a derived table's query."""

    def __init__(self, name: str, table: Any = None, plan: Optional[Plan] = None,
                 correlated: bool = False) -> None:
        self.name = name  # for plans: the table's name, or a derived table's alias
        self.table = table
        self.plan = plan
        self.correlated = correlated
        self._cache: Optional[list[tuple]] = None

    def rows(self) -> list[tuple]:
        if self.table is not None:
            return list(self.table.rows.values())
        if self._cache is not None:
            return self._cache
        rows = self.plan.run()
        if not self.correlated:
            self._cache = rows
        return rows


class _Join:
    """How a later table reference is joined: by probing an index or a hash table with the
    key of its equi-join conjunct, or (without one) by testing every pair."""

    def __init__(self, kind: str, pred: Optional[Callable[[tuple], bool]], source: _Source,
                 width: int, equi: Optional[EquiJoin]) -> None:
        self.kind = kind
        self.pred = pred
        self.source = source
        self.nulls = (None,) * width
        self.equi = equi
        self.index: Optional[Index] = None
        if equi is not None and source.table is not None:
            self.index = source.table.first_index(equi.right_column)
        if equi is None:
            self.label = f"SCAN {source.name}"
        elif self.index is not None:
            col = source.table.columns[equi.right_column].name
            self.label = (f"SEARCH {source.table.name} USING INDEX {self.index.name} "
                          f"({col} = ?)")
        else:
            col = source.plan.columns[equi.right_column] if source.table is None else \
                source.table.columns[equi.right_column].name
            self.label = f"HASH JOIN {source.name} ({col})"

    def join(self, rows: list[tuple]) -> list[tuple]:
        if self.equi is not None:
            return self._probe(rows)
        pred, left_join, nulls = self.pred, self.kind == "LEFT", self.nulls
        right = self.source.rows()
        joined = []
        for left in rows:
            matched = False
            for r in right:
                combined = left + r
                if pred is None or pred(combined):
                    joined.append(combined)
                    matched = True
            if left_join and not matched:
                joined.append(left + nulls)
        return joined

    def _probe(self, rows: list[tuple]) -> list[tuple]:
        li, ri = self.equi.left_index, self.equi.right_column
        left_classes = {v.value_class(x) for x in (r[li] for r in rows) if x is not None}
        if self.index is not None:
            table = self.source.table
            index, stored = self.index, table.rows
            right_classes = ({v.column_class(table.columns[ri].type)} if index.has_values()
                             else set())

            def partners(key: Any) -> list[tuple]:
                return [stored[rid] for rid in index.rids.get(key, ())]
        else:
            buckets: dict[Any, list[tuple]] = {}
            for r in self.source.rows():
                x = r[ri]
                if x is not None:
                    buckets.setdefault(v.value_key(x), []).append(r)
            right_classes = {v.value_class(rs[0][ri]) for rs in buckets.values()}

            def partners(key: Any) -> list[tuple]:
                return buckets.get(v.value_key(key), [])
        if left_classes and right_classes and len(left_classes | right_classes) > 1:
            raise SQLTypeError("ON compares incomparable types: "
                               + ", ".join(sorted(left_classes | right_classes)))
        pred = None if self.equi.only_conjunct else self.pred
        left_join, nulls = self.kind == "LEFT", self.nulls
        joined = []
        for left in rows:
            key = left[li]
            matched = False
            if key is not None:
                for r in partners(key):
                    combined = left + r
                    if pred is None or pred(combined):
                        joined.append(combined)
                        matched = True
            if left_join and not matched:
                joined.append(left + nulls)
        return joined


class SelectPlan:
    """A bound SELECT."""

    def __init__(self, stmt: n.Select, ctx: QueryContext) -> None:
        self.stmt = stmt
        self.ctx = ctx
        self.scope = Scope()
        self.sources: list[_Source] = []
        self.access: Optional[TableAccess] = None  # for a first table reference that is a table
        self.joins: list[_Join] = []
        self.where: Optional[Callable[[tuple], bool]] = None
        self._bind_from()

        self.grouped = bool(stmt.group_by) or stmt.having is not None or any(
            isinstance(item, n.SelectItem) and contains_aggregate(item.expr)
            for item in stmt.items) or any(
            contains_aggregate(o.expr) for o in stmt.order_by)
        self.aggregates: list[AggregateSpec] = []
        self.group_indices: list[int] = []
        if self.grouped:
            self.group_indices = [self.scope.resolve(ref) for ref in stmt.group_by]
            self.compiler = ExprCompiler(self.scope, "the select list", ctx,
                                         aggregates=self.aggregates,
                                         grouping=set(self.group_indices))
        else:
            self.compiler = ExprCompiler(self.scope, "the select list", ctx)

        self.columns: list[str] = []
        self.item_fns: list[Fn] = []
        self._bind_items()
        self.having = None
        if stmt.having is not None:
            self.compiler.clause = "HAVING"
            self.having = as_predicate(self.compiler.compile(stmt.having), "HAVING")
        self.compiler.clause = "ORDER BY"
        # each sort key: (output column index or None, expression or None, the ORDER BY item)
        self.sort_keys: list[tuple[Optional[int], Optional[Fn], n.OrderItem]] = []
        self._bind_order_by()

    # ------------------------------------------------------------ binding

    def _bind_from(self) -> None:
        clause = self.stmt.from_
        if clause is None:
            return
        refs = [clause.first] + [j.table for j in clause.joins]
        for ref in refs:
            if ref.query is not None:
                sub = self.ctx.derived()
                plan = build_query(ref.query, sub)
                self.ctx.absorb(sub)
                self.scope.add(ref.exposed, plan.columns)
                self.sources.append(_Source(ref.exposed, plan=plan, correlated=sub.correlated))
            else:
                table = self.ctx.db.get_table(ref.name)
                self.scope.add(ref.exposed, table.column_names)
                self.sources.append(_Source(table.name, table=table))
        for k, join in enumerate(clause.joins, start=2):
            pred = None
            if join.on is not None:
                on = ExprCompiler(self.scope, "ON", self.ctx, visible=k)
                pred = as_predicate(on.compile(join.on), "ON")
            equi = equi_join(join.on, self.scope, k) if join.kind != "CROSS" else None
            self.joins.append(_Join(join.kind, pred, self.sources[k - 1],
                                    len(self.scope.sources[k - 1].columns), equi))
        if self.stmt.where is not None:
            where = ExprCompiler(self.scope, "WHERE", self.ctx)
            self.where = as_predicate(where.compile(self.stmt.where), "WHERE")
        first = self.sources[0]
        if first.table is not None:
            self.access = TableAccess(first.table, self.stmt.where, self.scope)

    def explain(self) -> list[str]:
        """One plan line per table reference of the FROM clause."""
        if not self.sources:
            return []
        first = self.access.label if self.access is not None else \
            f"SCAN {self.sources[0].name}"
        return [first] + [j.label for j in self.joins]

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
            self.columns.append(item.alias or output_name(item.expr))

    def _bind_order_by(self) -> None:
        for item in self.stmt.order_by:
            pos = output_position(item, self.columns)
            if pos is not None:
                self.sort_keys.append((pos, None, item))
                continue
            if self.stmt.distinct:
                raise SQLSyntaxError("with SELECT DISTINCT, ORDER BY items must be output "
                                     "columns")
            self.sort_keys.append((None, self.compiler.compile(item.expr), item))

    # ------------------------------------------------------------ execution

    def _source_rows(self) -> list[tuple]:
        if not self.sources:
            return [()]
        rows = self.access.rows() if self.access is not None else self.sources[0].rows()
        for join in self.joins:
            rows = join.join(rows)
        return rows

    def run(self) -> list[tuple]:
        rows = self._source_rows()
        if self.where is not None:
            where = self.where
            rows = [r for r in rows if where(r)]
        item_fns = self.item_fns
        key_fns = [fn for _, fn, _ in self.sort_keys if fn is not None]
        envs = self._group_envs(rows) if self.grouped else rows
        # entries: (output row, values of the expression sort keys)
        entries = [(tuple(f(env) for f in item_fns), [f(env) for f in key_fns])
                   for env in envs]
        if self.stmt.distinct:
            seen: set = set()
            unique = []
            for entry in entries:
                k = row_key(entry[0])
                if k not in seen:
                    seen.add(k)
                    unique.append(entry)
            entries = unique
        keys: list[SortKey] = []
        expr_pos = 0
        for out_idx, fn, item in self.sort_keys:
            if fn is None:
                keys.append((lambda e, i=out_idx: e[0][i], item.desc, item.nulls_first))
            else:
                keys.append((lambda e, i=expr_pos: e[1][i], item.desc, item.nulls_first))
                expr_pos += 1
        entries = sort_entries(entries, keys)
        entries = apply_limit(entries, self.stmt.limit, self.stmt.offset)
        return [out for out, _ in entries]

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


class CompoundPlan:
    """A set operation: UNION [ALL], INTERSECT, EXCEPT."""

    def __init__(self, node: n.Compound, ctx: QueryContext) -> None:
        self.node = node
        self.left = build_query(node.left, ctx)
        self.right = build_query(node.right, ctx)
        if len(self.left.columns) != len(self.right.columns):
            raise SQLSyntaxError(f"{node.op} operands have different numbers of columns "
                                 f"({len(self.left.columns)} and {len(self.right.columns)})")
        self.columns = list(self.left.columns)
        self.sort_keys: list[SortKey] = []
        for item in node.order_by:
            pos = output_position(item, self.columns)
            if pos is None:
                raise SQLSyntaxError(f"ORDER BY of {node.op} must name an output column or "
                                     "position")
            self.sort_keys.append((lambda row, i=pos: row[i], item.desc, item.nulls_first))

    def run(self) -> list[tuple]:
        left = self.left.run()
        right = self.right.run()
        op = self.node.op
        if op == "UNION":
            rows = left + right
            if not self.node.all:
                rows = _dedupe(rows)
        else:
            right_keys = {row_key(r) for r in right}
            keep = op == "INTERSECT"
            rows = _dedupe([r for r in left if (row_key(r) in right_keys) == keep])
        rows = sort_entries(rows, self.sort_keys)
        return apply_limit(rows, self.node.limit, self.node.offset)

    def explain(self) -> list[str]:
        return self.left.explain() + self.right.explain()


def output_name(e: n.Expr) -> str:
    if isinstance(e, n.ColumnRef):
        return e.name
    if isinstance(e, n.FuncCall):
        return e.name
    if isinstance(e, n.Case):
        return "case"
    if isinstance(e, n.Cast):
        return "cast"
    if isinstance(e, n.Exists):
        return "exists"
    return "?column?"
