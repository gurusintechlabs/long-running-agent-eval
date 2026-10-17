"""Query plans: a bound SELECT (``SelectPlan``) or set operation (``CompoundPlan``).

A plan is built (all name and syntax checks) before any row is read. ``plan.columns`` are the
output names and ``plan.run()`` returns the output rows as tuples. A plan that is a subquery
reads the envs of its enclosing queries from the statement's ``Runtime``.
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Union

from minidb import nodes as n
from minidb import values as v
from minidb.access import EquiJoin, TableAccess, conjuncts, equi_join
from minidb.catalog import Index
from minidb.compiler import (
    AggregateSpec,
    ExprCompiler,
    WindowCollector,
    Fn,
    QueryContext,
    Scope,
    as_predicate,
    contains_aggregate,
)
from minidb.protocol import SQLNameError, SQLRuntimeError, SQLSyntaxError, SQLTypeError
from minidb.sorting import SortKey, row_key, sort_entries

Plan = Union["SelectPlan", "CompoundPlan", "WithPlan"]

MAX_RECURSIVE_ROWS = 100_000

def build_query(query: n.Query, ctx: QueryContext) -> Plan:
    if isinstance(query, n.Compound):
        return CompoundPlan(query, ctx)
    if isinstance(query, n.With):
        return WithPlan(query, ctx)
    return SelectPlan(query, ctx)


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


class _Source:
    """The rows of one table reference: a stored table, the query of a derived table or a
    view, or a WITH name."""

    def __init__(self, name: str, columns: list[str], table: Any = None,
                 plan: Optional[Plan] = None, correlated: bool = False, cte: Any = None) -> None:
        self.name = name  # for plans: the table / view / WITH name, or a derived table's alias
        self.columns = columns
        self.table = table
        self.plan = plan
        self.correlated = correlated
        self.cte = cte
        self._cache: Optional[list[tuple]] = None

    def rows(self) -> list[tuple]:
        if self.table is not None:
            return self.table.scan()
        if self.cte is not None:
            return self.cte.rows()
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
            self.label = f"HASH JOIN {source.name} ({source.columns[equi.right_column]})"

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
        self.probe: Optional[tuple[int, Fn]] = None  # see _bind_correlated_probe
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
        # window functions: allowed in the select list and ORDER BY only
        self.windows = WindowCollector()
        self.compiler.windows = self.windows
        self._bind_items()
        self.having = None
        if stmt.having is not None:
            self.compiler.clause = "HAVING"
            self.compiler.windows = None
            self.having = as_predicate(self.compiler.compile(stmt.having), "HAVING")
            self.compiler.windows = self.windows
        self.compiler.clause = "ORDER BY"
        # each sort key: (output column index or None, expression or None, the ORDER BY item)
        self.sort_keys: list[tuple[Optional[int], Optional[Fn], n.OrderItem]] = []
        self._bind_order_by()
        # window values follow the row (and, in a grouped query, the aggregates)
        self.windows.base[0] = self.scope.width + (len(self.aggregates) if self.grouped else 0)

    # ------------------------------------------------------------ binding

    def _bind_from(self) -> None:
        clause = self.stmt.from_
        if clause is None:
            return
        refs = [clause.first] + [j.table for j in clause.joins]
        for ref in refs:
            source = self._source(ref)
            self.scope.add(ref.exposed, source.columns)
            self.sources.append(source)
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
            self._bind_correlated_probe()

    def _source(self, ref: n.TableRef) -> _Source:
        """A FROM item: a derived table, a WITH name (which hides tables and views), a table
        or a view."""
        ctx = self.ctx
        if ref.query is not None:
            sub = ctx.derived()
            plan = build_query(ref.query, sub)
            ctx.absorb(sub)
            return _Source(ref.exposed, list(plan.columns), plan=plan, correlated=sub.correlated)
        cte = ctx.ctes.get(ref.name)
        if cte is not None:
            if cte.correlated:  # its rows depend on rows of queries enclosing its WITH
                ctx.min_ref = min(ctx.min_ref, cte.min_ref)
            return _Source(cte.name, list(cte.columns), cte=cte)
        table = ctx.db.find_table(ref.name)
        if table is not None:
            return _Source(table.name, table.column_names, table=table)
        view = ctx.db.views.get(ref.name)
        if view is None:
            raise SQLNameError(f"no such table: {ref.name}")
        plan, columns = plan_view(view, ctx)
        return _Source(view.name, columns, plan=plan)

    def _bind_correlated_probe(self) -> None:
        """A correlated subquery whose WHERE starts with ``col = outer_col`` (a column of its
        only table, compared with a column of an enclosing query) is re-run for every outer
        row; scanning the whole table each time would be quadratic. When the outer value is
        non-NULL and comparable with the column, the rows whose ``col`` holds another value
        make that leftmost conjunct FALSE, so AND evaluates nothing else on them: skipping them
        changes neither the result nor the errors. Rows where ``col`` is NULL make it NULL, and
        the rest of WHERE is still evaluated on them, so they stay. EXPLAIN still says SCAN:
        exactly the same rows are evaluated against the rest of the condition."""
        if self.joins or self.access.index is not None:
            return
        parts = conjuncts(self.stmt.where)
        first = parts[0] if parts else None
        if not (isinstance(first, n.Binary) and first.op == "="
                and isinstance(first.left, n.ColumnRef) and isinstance(first.right, n.ColumnRef)):
            return
        for inner, outer in ((first.left, first.right), (first.right, first.left)):
            found = self.scope.lookup(inner)
            if found is not None and self.scope.lookup(outer) is None:
                outer_fn = ExprCompiler(self.scope, "WHERE", self.ctx).compile(outer)
                self.probe = (found[1], outer_fn)
                return

    def _probe_rows(self) -> Optional[list[tuple]]:
        """The rows to evaluate through the correlated probe, or None for a full scan."""
        column, outer_fn = self.probe
        value = outer_fn(())  # reads the enclosing query's row only
        table = self.sources[0].table
        if value is None or v.value_class(value) != v.column_class(table.columns[column].type):
            return None
        buckets, nulls = self.ctx.runtime.column_hash(table, column)
        rids = buckets.get(v.value_key(value), [])
        if nulls:
            rids = sorted(rids + nulls)
        stored = table.rows
        return [stored[r] for r in rids]

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
            if item.alias is not None:
                self.columns.append(item.alias)
            elif isinstance(item.expr, n.ColumnRef):
                self.columns.append(self.compiler.defined_name(item.expr))
            else:
                self.columns.append(output_name(item.expr))

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
        if self.access is not None and self.probe is not None:
            rows = self._probe_rows()
            if rows is not None:
                return rows
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
        if self.windows.specs:
            values = [spec.compute(envs) for spec in self.windows.specs]
            envs = [env + tuple(col[i] for col in values) for i, env in enumerate(envs)]
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
    if isinstance(e, (n.FuncCall, n.WindowCall)):
        return e.name
    if isinstance(e, n.Case):
        return "case"
    if isinstance(e, n.Cast):
        return "cast"
    if isinstance(e, n.Exists):
        return "exists"
    return "?column?"


# ---------------------------------------------------------------- views

def plan_view(view: Any, ctx: QueryContext) -> tuple[Plan, list[str]]:
    """Plan a view's query for one use. It is planned afresh every time (so it sees the
    current schema) and in a context of its own: it sees neither the enclosing queries nor
    their WITH names."""
    runtime = ctx.runtime
    if view.name in runtime.expanding_views:
        raise SQLNameError(f"view {view.name} refers to itself")
    runtime.expanding_views.add(view.name)
    try:
        plan = build_query(view.query, QueryContext(ctx.db, runtime, ctx.depth))
    finally:
        runtime.expanding_views.discard(view.name)
    columns = list(plan.columns)
    if view.columns is not None:
        if len(view.columns) != len(columns):
            raise SQLSyntaxError(f"view {view.name} names {len(view.columns)} columns but its "
                                 f"query returns {len(columns)}")
        columns = list(view.columns)
    return plan, columns


def check_column_names(names: Optional[list[str]], what: str) -> None:
    if names is not None:
        seen: set[str] = set()
        for name in names:
            if name in seen:
                raise SQLNameError(f"column {name} named twice in {what}")
            seen.add(name)


# ---------------------------------------------------------------- WITH

class WithPlan:
    """``WITH name AS (query), ... body``. Each name's rows are computed when first needed and
    shared by all its references; a name that does not depend on rows of enclosing queries is
    computed at most once per statement."""

    def __init__(self, node: n.With, ctx: QueryContext) -> None:
        self.ctx = ctx
        self.stack_height = 0  # height of the outer-row stack when this query runs
        names = [c.name for c in node.ctes]
        for i, name in enumerate(names):
            if name in names[:i]:
                raise SQLNameError(f"WITH name {name} defined twice")
        visible = dict(ctx.ctes)
        self.ctes: list[CteDef] = []
        for cte in node.ctes:
            definition = CteDef(cte, self, node.recursive, visible, ctx)
            self.ctes.append(definition)
            visible = {**visible, cte.name: definition}
        body_ctx = ctx.derived(visible)
        self.body = build_query(node.body, body_ctx)
        ctx.absorb(body_ctx)
        self.columns = list(self.body.columns)

    def run(self) -> list[tuple]:
        self.stack_height = len(self.ctx.runtime.outer_rows)
        for cte in self.ctes:
            if cte.correlated:
                cte.cache = None
        return self.body.run()

    def explain(self) -> list[str]:
        return self.body.explain()


class _WorkingSet:
    """What a recursive name stands for inside its own step: the previous round's rows."""

    correlated = False

    def __init__(self, name: str, columns: list[str], depth: int) -> None:
        self.name = name
        self.columns = columns
        self.min_ref = depth
        self.current: list[tuple] = []

    def rows(self) -> list[tuple]:
        return self.current


class CteDef:
    """One WITH name: its plan(s), output columns and (once computed) rows."""

    def __init__(self, cte: n.Cte, owner: WithPlan, recursive: bool, visible: dict,
                 ctx: QueryContext) -> None:
        self.name = cte.name
        self.owner = owner
        self.cache: Optional[list[tuple]] = None
        check_column_names(cte.columns, f"WITH name {cte.name}")
        self.step: Optional[Plan] = None
        if recursive and count_references(cte.query, cte.name):
            anchor, step, self.distinct = split_recursive(cte.query, cte.name)
            anchor_ctx = ctx.derived(visible)
            self.plan = build_query(anchor, anchor_ctx)
            columns = self._rename(cte, self.plan.columns)
            self.working = _WorkingSet(cte.name, columns, ctx.depth)
            step_ctx = ctx.derived({**visible, cte.name: self.working})
            self.step = build_query(step, step_ctx)
            if len(self.step.columns) != len(columns):
                raise SQLSyntaxError(f"the anchor and the step of {cte.name} have different "
                                     "numbers of columns")
            self.min_ref = min(anchor_ctx.min_ref, step_ctx.min_ref)
        else:
            query_ctx = ctx.derived(visible)
            self.plan = build_query(cte.query, query_ctx)
            columns = self._rename(cte, self.plan.columns)
            self.min_ref = query_ctx.min_ref
        self.columns = columns
        self.correlated = self.min_ref < ctx.depth
        ctx.absorb(self)

    @staticmethod
    def _rename(cte: n.Cte, columns: list[str]) -> list[str]:
        if cte.columns is None:
            return list(columns)
        if len(cte.columns) != len(columns):
            raise SQLSyntaxError(f"WITH name {cte.name} names {len(cte.columns)} columns but "
                                 f"its query returns {len(columns)}")
        return list(cte.columns)

    def rows(self) -> list[tuple]:
        if self.cache is not None:
            return self.cache
        # Run as part of the WITH query: with the outer-row stack as it was when that query
        # started, whatever subquery first needed these rows.
        stack = self.owner.ctx.runtime.outer_rows
        height = self.owner.stack_height
        saved = stack[height:]
        del stack[height:]
        try:
            rows = self.plan.run() if self.step is None else self._iterate()
        finally:
            stack[height:] = saved
        self.cache = rows
        return rows

    def _iterate(self) -> list[tuple]:
        """A recursive name: the anchor's rows, then the step's rows round after round, each
        round seeing only the previous round's rows, until a round adds nothing."""
        seen: set = set()

        def fresh(rows: list[tuple]) -> list[tuple]:
            if not self.distinct:
                return rows
            kept = []
            for row in rows:
                k = row_key(row)
                if k not in seen:
                    seen.add(k)
                    kept.append(row)
            return kept

        first = fresh(self.plan.run())
        result = list(first)
        working = first
        while working:
            if len(result) > MAX_RECURSIVE_ROWS:
                raise SQLRuntimeError(f"recursive query {self.name} produced more than "
                                      f"{MAX_RECURSIVE_ROWS} rows")
            self.working.current = working
            working = fresh(self.step.run())
            result.extend(working)
        if len(result) > MAX_RECURSIVE_ROWS:
            raise SQLRuntimeError(f"recursive query {self.name} produced more than "
                                  f"{MAX_RECURSIVE_ROWS} rows")
        return result


def count_references(node: Any, name: str) -> int:
    """How many FROM items of ``node`` (at any depth) refer to the WITH name ``name``,
    leaving out those that a nested WITH of the same name hides."""
    if isinstance(node, n.TableRef):
        own = 1 if node.query is None and node.name == name else 0
        return own + (count_references(node.query, name) if node.query is not None else 0)
    if isinstance(node, n.With):
        total = 0
        for cte in node.ctes:
            if cte.name == name:
                if not node.recursive:
                    total += count_references(cte.query, name)
                return total  # the rest of this WITH sees the inner name
            total += count_references(cte.query, name)
        return total + count_references(node.body, name)
    if isinstance(node, (list, tuple)):
        return sum(count_references(x, name) for x in node)
    if hasattr(node, "__dataclass_fields__"):
        return sum(count_references(getattr(node, f), name) for f in node.__dataclass_fields__)
    return 0


def split_recursive(query: n.Query, name: str) -> tuple[n.Query, n.Select, bool]:
    """(anchor, step, UNION without ALL) of a self-referencing WITH RECURSIVE query, which
    must be ``anchor UNION [ALL] step``; any other form is a SyntaxError."""
    if not (isinstance(query, n.Compound) and query.op == "UNION"):
        raise SQLSyntaxError(f"recursive query {name} must have the form "
                             "anchor UNION [ALL] step")
    if query.order_by or query.limit is not None:
        raise SQLSyntaxError(f"the step of recursive query {name} cannot use ORDER BY or "
                             "LIMIT")
    anchor, step = query.left, query.right
    if count_references(anchor, name):
        raise SQLSyntaxError(f"the anchor of recursive query {name} cannot refer to it")
    if not isinstance(step, n.Select) or step.from_ is None:
        raise SQLSyntaxError(f"the step of recursive query {name} must be a SELECT from it")
    refs = [step.from_.first] + [j.table for j in step.from_.joins]
    direct = sum(1 for r in refs if r.query is None and r.name == name)
    if direct != 1 or count_references(step, name) != 1:
        raise SQLSyntaxError(f"the step of recursive query {name} must refer to it exactly "
                             "once, in its own FROM clause")
    if (step.group_by or step.having is not None or step.distinct or step.order_by
            or step.limit is not None or any(isinstance(i, n.SelectItem)
                                             and contains_aggregate(i.expr)
                                             for i in step.items)):
        raise SQLSyntaxError(f"the step of recursive query {name} cannot use aggregates, "
                             "GROUP BY, DISTINCT, ORDER BY or LIMIT")
    return anchor, step, not query.all
