"""Query execution: name resolution, expression compilation, SELECT and set operations.

Expressions are compiled once per statement into closures ``f(env) -> value``. Name resolution
happens at compile time, so unknown or ambiguous names fail before any row is read. An ``Env``
holds the current row (a tuple with one entry per FROM source; ``None`` for a NULL-extended
LEFT JOIN side), the enclosing query's env (correlated subqueries), and aggregate values.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from minidb import functions
from minidb import nodes as n
from minidb.protocol import SQLNameError, SQLRuntimeError, SQLSyntaxError, SQLTypeError
from minidb.storage import Database
from minidb.values import (
    arith,
    check_int,
    check_real,
    compare,
    compare_op,
    concat,
    family,
    hash_key,
    is_number,
    kind,
    like,
    negate,
    truth,
    type_name,
)

AGGREGATES = frozenset({"count", "sum", "avg", "min", "max"})

Fn = Callable[["Env"], Any]


class Env:
    __slots__ = ("row", "outer", "aggs")

    def __init__(self, row: tuple, outer: Env | None = None, aggs: list | None = None) -> None:
        self.row, self.outer, self.aggs = row, outer, aggs


@dataclass
class Source:
    exposed: str
    name: str | None               # table name (None for a derived table)
    columns: list[str]
    table: str | None = None       # set for base tables
    query: Any = None              # PreparedQuery of a derived table


class Scope:
    """The table references of one query, linked to the enclosing query's scope."""

    def __init__(self, sources: list[Source], outer: Scope | None = None,
                 level: int | None = None) -> None:
        self.sources, self.outer = sources, outer
        self.level = level if level is not None else (outer.level + 1 if outer else 0)
        self.restrict: set | None = None   # grouping columns while compiling grouped items

    def resolve(self, ref: n.ColumnRef) -> tuple[int, int, int, Scope]:
        """``(depth, source index, column index, scope)`` for a column reference."""
        level, depth = self, 0
        label = f"{ref.table}.{ref.name}" if ref.table else ref.name
        while level is not None:
            if ref.table is not None:
                srcs = [i for i, s in enumerate(level.sources) if s.exposed == ref.table]
                if srcs:
                    cols = [i for i, c in enumerate(level.sources[srcs[0]].columns) if c == ref.name]
                    if len(cols) > 1:
                        raise SQLNameError(f"column reference {label} is ambiguous")
                    if cols:
                        return depth, srcs[0], cols[0], level
            else:
                found = [(si, ci) for si, s in enumerate(level.sources)
                         for ci, c in enumerate(s.columns) if c == ref.name]
                if len(found) > 1:
                    raise SQLNameError(f"column reference {label} is ambiguous")
                if found:
                    return depth, found[0][0], found[0][1], level
            level, depth = level.outer, depth + 1
        raise SQLNameError(f"no such column: {label}")


def accessor(depth: int, si: int, ci: int) -> Fn:
    if depth == 0:
        def get0(env: Env) -> Any:
            r = env.row[si]
            return None if r is None else r[ci]
        return get0

    def get(env: Env) -> Any:
        for _ in range(depth):
            env = env.outer
        r = env.row[si]
        return None if r is None else r[ci]
    return get


def contains_aggregate(e: Any) -> bool:
    """True if ``e`` has an aggregate of its own query (not counting subqueries)."""
    if isinstance(e, n.Func):
        return e.name in AGGREGATES or any(contains_aggregate(a) for a in e.args)
    if isinstance(e, (n.Literal, n.ColumnRef, n.Star, n.ScalarSubquery, n.Exists)) or e is None:
        return False
    if isinstance(e, n.InSubquery):
        return contains_aggregate(e.operand)
    if isinstance(e, n.Unary):
        return contains_aggregate(e.operand)
    if isinstance(e, n.Binary):
        return contains_aggregate(e.left) or contains_aggregate(e.right)
    if isinstance(e, n.IsNull):
        return contains_aggregate(e.operand)
    if isinstance(e, n.Between):
        return any(contains_aggregate(x) for x in (e.operand, e.low, e.high))
    if isinstance(e, n.InList):
        return contains_aggregate(e.operand) or any(contains_aggregate(x) for x in e.items)
    if isinstance(e, n.Like):
        return contains_aggregate(e.operand) or contains_aggregate(e.pattern)
    if isinstance(e, n.Case):
        parts = [e.operand, e.else_] + [x for pair in e.whens for x in pair]
        return any(contains_aggregate(x) for x in parts)
    if isinstance(e, n.Cast):
        return contains_aggregate(e.expr)
    return False


def _not3(v: Any) -> Any:
    return None if v is None else not v


def _and3(a: Any, b: Any) -> Any:
    if a is False or b is False:
        return False
    return None if a is None or b is None else True


def _in_values(x: Any, values) -> Any:
    saw_null = False
    for v in values:
        c = compare_op("=", x, v)
        if c is True:
            return True
        if c is None:
            saw_null = True
    return None if saw_null else False


def output_name(e: Any) -> str:
    if isinstance(e, (n.ColumnRef, n.Func)):
        return e.name
    if isinstance(e, n.Exists):
        return "exists"
    if isinstance(e, n.Case):
        return "case"
    if isinstance(e, n.Cast):
        return "cast"
    return "?column?"


# ------------------------------------------------------------------ aggregates


@dataclass
class AggSpec:
    name: str
    arg: Fn | None
    distinct: bool


def distinct_values(vals: list) -> list:
    seen, out = set(), []
    for v in vals:
        k = hash_key(v)
        if k not in seen:
            seen.add(k)
            out.append(v)
    return out


def aggregate_values(name: str, vals: list) -> Any:
    """Aggregate ``vals`` (non-NULL inputs in input order)."""
    if name == "count":
        return len(vals)
    if name in ("sum", "avg"):
        for v in vals:
            if not is_number(v):
                raise SQLTypeError(f"{name.upper()} needs numbers, got {type_name(v)}")
        if not vals:
            return None
        if all(isinstance(v, int) for v in vals):
            total = sum(vals)
            return check_int(total) if name == "sum" else total / len(vals)
        acc = 0.0
        for v in vals:
            acc += v
        check_real(acc)
        return acc if name == "sum" else check_real(acc / len(vals))
    best = None
    for v in vals:
        if best is None:
            best = v
            continue
        c = compare(v, best)
        if (c < 0 and name == "min") or (c > 0 and name == "max"):
            best = v
    return best


def compute_aggregate(a: AggSpec, rows: list, outer: Env | None) -> Any:
    if a.arg is None:  # COUNT(*)
        return len(rows)
    vals = [v for v in (a.arg(Env(r, outer)) for r in rows) if v is not None]
    if a.distinct:
        vals = distinct_values(vals)
    return aggregate_values(a.name, vals)


# ------------------------------------------------------------------ compiler


class Compiler:
    """Compiles expressions against a scope. ``ctx`` is 'row' (no aggregates), 'group' (grouped
    query output: aggregates allowed, bare columns must be grouping columns) or 'agg' (inside
    an aggregate's argument)."""

    def __init__(self, executor: Executor, scope: Scope) -> None:
        self.ex, self.scope = executor, scope
        self.aggs: list[AggSpec] = []

    def compile(self, e: Any, ctx: str = "row") -> Fn:
        m = getattr(self, "_c_" + type(e).__name__, None)
        if m is None:
            raise SQLSyntaxError(f"unsupported expression {type(e).__name__}")
        return m(e, ctx)

    def _c_Literal(self, e: n.Literal, ctx: str) -> Fn:
        v = e.value
        return lambda env: v

    def _c_Star(self, e: n.Star, ctx: str) -> Fn:
        raise SQLSyntaxError("* is only allowed in the select list")

    def _c_ColumnRef(self, e: n.ColumnRef, ctx: str) -> Fn:
        depth, si, ci, scope = self.scope.resolve(e)
        self.ex.resolved_levels.append(scope.level)
        if scope.restrict is not None and (si, ci) not in scope.restrict:
            raise SQLSyntaxError(f"column {e.name} must appear in GROUP BY or in an aggregate")
        return accessor(depth, si, ci)

    def _c_Unary(self, e: n.Unary, ctx: str) -> Fn:
        f = self.compile(e.operand, ctx)
        if e.op == "-":
            return lambda env: negate(f(env))
        if e.op == "+":
            def plus(env):
                v = f(env)
                if v is not None and not is_number(v):
                    raise SQLTypeError(f"cannot apply unary + to {type_name(v)}")
                return v
            return plus
        return lambda env: _not3(truth(f(env), "NOT operand"))

    def _c_Binary(self, e: n.Binary, ctx: str) -> Fn:
        lf, rf, op = self.compile(e.left, ctx), self.compile(e.right, ctx), e.op
        if op == "AND":
            def and_(env):
                a = truth(lf(env), "AND operand")
                if a is False:
                    return False
                return _and3(a, truth(rf(env), "AND operand"))
            return and_
        if op == "OR":
            def or_(env):
                a = truth(lf(env), "OR operand")
                if a is True:
                    return True
                b = truth(rf(env), "OR operand")
                if b is True:
                    return True
                return None if a is None or b is None else False
            return or_
        if op == "||":
            return lambda env: concat(lf(env), rf(env))
        if op in ("+", "-", "*", "/", "%"):
            return lambda env: arith(op, lf(env), rf(env))
        return lambda env: compare_op(op, lf(env), rf(env))

    def _c_IsNull(self, e: n.IsNull, ctx: str) -> Fn:
        f, neg = self.compile(e.operand, ctx), e.negated
        return lambda env: (f(env) is None) != neg

    def _c_Between(self, e: n.Between, ctx: str) -> Fn:
        f, lo, hi = (self.compile(x, ctx) for x in (e.operand, e.low, e.high))
        neg = e.negated

        def between(env):
            x, a, b = f(env), lo(env), hi(env)
            r = _and3(compare_op(">=", x, a), compare_op("<=", x, b))
            return _not3(r) if neg else r
        return between

    def _c_InList(self, e: n.InList, ctx: str) -> Fn:
        f, items, neg = self.compile(e.operand, ctx), [self.compile(x, ctx) for x in e.items], e.negated

        def in_list(env):
            x = f(env)
            r = _in_values(x, [g(env) for g in items])
            return _not3(r) if neg else r
        return in_list

    def _c_Like(self, e: n.Like, ctx: str) -> Fn:
        f, p, neg = self.compile(e.operand, ctx), self.compile(e.pattern, ctx), e.negated

        def like_(env):
            r = like(f(env), p(env))
            return _not3(r) if neg else r
        return like_

    # -- subqueries

    def _subquery(self, query: Any, ncols: int | None) -> Callable[[Env], list]:
        """Rows of a subquery for an env; uncorrelated ones are run once, when first needed."""
        sub, correlated = self.ex.prepare_sub(query, self.scope)
        if ncols is not None and len(sub.columns) != ncols:
            raise SQLSyntaxError("subquery must return exactly one column")
        if correlated:
            return sub.run
        cache: list = []

        def once(env: Env) -> list:
            if not cache:
                cache.append(sub.run(env))
            return cache[0]
        return once

    def _c_InSubquery(self, e: n.InSubquery, ctx: str) -> Fn:
        f, neg = self.compile(e.operand, ctx), e.negated
        rows = self._subquery(e.query, 1)

        def in_sub(env):
            x = f(env)
            r = _in_values(x, (row[0] for row in rows(env)))
            return _not3(r) if neg else r
        return in_sub

    def _c_ScalarSubquery(self, e: n.ScalarSubquery, ctx: str) -> Fn:
        rows = self._subquery(e.query, 1)

        def scalar(env):
            rs = rows(env)
            if len(rs) > 1:
                raise SQLRuntimeError("scalar subquery returned more than one row")
            return rs[0][0] if rs else None
        return scalar

    def _c_Exists(self, e: n.Exists, ctx: str) -> Fn:
        rows = self._subquery(e.query, None)
        return lambda env: bool(rows(env))

    # -- CASE / CAST / functions

    def _c_Case(self, e: n.Case, ctx: str) -> Fn:
        operand = self.compile(e.operand, ctx) if e.operand is not None else None
        whens = [(self.compile(c, ctx), self.compile(r, ctx)) for c, r in e.whens]
        else_ = self.compile(e.else_, ctx) if e.else_ is not None else None

        def case(env):
            if operand is None:
                for cond, res in whens:
                    if truth(cond(env), "CASE condition") is True:
                        return res(env)
            else:
                x = operand(env)
                for val, res in whens:
                    if compare_op("=", x, val(env)) is True:
                        return res(env)
            return else_(env) if else_ is not None else None
        return case

    def _c_Cast(self, e: n.Cast, ctx: str) -> Fn:
        f, ty = self.compile(e.expr, ctx), e.type
        return lambda env: functions.cast(f(env), ty)

    def _c_Func(self, e: n.Func, ctx: str) -> Fn:
        name = e.name
        if name in AGGREGATES:
            if ctx != "group":
                raise SQLSyntaxError(f"aggregate {name.upper()} is not allowed here")
            if not e.star and len(e.args) != 1:
                raise SQLSyntaxError(f"{name.upper()} takes exactly one argument")
            saved, self.scope.restrict = self.scope.restrict, None
            try:
                arg = None if e.star else self.compile(e.args[0], "agg")
            finally:
                self.scope.restrict = saved
            slot = len(self.aggs)
            self.aggs.append(AggSpec(name, arg, e.distinct))
            return lambda env: env.aggs[slot]
        spec = functions.SCALARS.get(name)
        if spec is None:
            raise SQLNameError(f"no such function: {name}")
        lo, hi, impl = spec
        if len(e.args) < lo or (hi is not None and len(e.args) > hi):
            raise SQLSyntaxError(f"wrong number of arguments to {name.upper()}")
        args = [self.compile(a, ctx) for a in e.args]
        if name == "coalesce":
            def coalesce(env):
                for g in args:
                    v = g(env)
                    if v is not None:
                        return v
                return None
            return coalesce
        if name in functions.NULL_AWARE:
            return lambda env: impl(*[g(env) for g in args])

        def call(env):
            vals = [g(env) for g in args]
            if any(v is None for v in vals):
                return None
            return impl(*vals)
        return call


# ------------------------------------------------------------------ sorting


def sort_rows(out: list, desc: list[bool]) -> None:
    """Stable sort of ``(values, keys)`` pairs by ``keys``. NULL is the smallest value."""
    for i in range(len(desc)):
        fams = set()
        for _, keys in out:
            v = keys[i]
            if v is not None:
                fams.add(family(v))
        if len(fams) > 1:
            raise SQLTypeError("ORDER BY compares values of incomparable types")
    for i in reversed(range(len(desc))):
        out.sort(key=lambda item: (0, 0) if item[1][i] is None else (1, item[1][i]),
                 reverse=desc[i])


def apply_limit(rows: list, limit: int | None, offset: int) -> list:
    end = None if limit is None else offset + limit
    return rows[offset:end]


# ------------------------------------------------------------------ SELECT


class PreparedSelect:
    def __init__(self, ex: Executor, q: n.Select, outer: Scope | None,
                 level: int | None = None) -> None:
        self.ex, self.q = ex, q
        db = ex.db
        self.sources: list[Source] = []
        self.scope = Scope(self.sources, outer, level)
        refs = ([q.from_] + [j.table for j in q.joins]) if q.from_ else []
        for ref in refs:
            if ref.query is not None:
                # a derived table sees the enclosing queries, not its sibling references
                sub = ex.prepare(ref.query, outer, level=self.scope.level + 1)
                src = Source(ref.exposed, None, list(sub.columns), query=sub)
            elif ref.name in db.tables:
                t = db.tables[ref.name]
                src = Source(ref.exposed, ref.name, [c.name for c in t.columns], table=ref.name)
            else:
                raise SQLNameError(f"no such table: {ref.name}")
            if any(s.exposed == src.exposed for s in self.sources):
                raise SQLNameError(f"table name {src.exposed} specified more than once")
            self.sources.append(src)
        comp = Compiler(ex, self.scope)

        self.joins = []
        for j, join in enumerate(q.joins):
            on = None
            if join.on is not None:
                on_scope = Scope(self.sources[:j + 2], outer, self.scope.level)
                on = Compiler(ex, on_scope).compile(join.on)
            self.joins.append((join.kind, on))
        self.where = comp.compile(q.where) if q.where is not None else None

        self.grouped = bool(q.group_by) or q.having is not None or any(
            contains_aggregate(it.expr) for it in q.items) or any(
            contains_aggregate(o.expr) for o in q.order_by)
        self.group_keys: list[Fn] = []
        if self.grouped:
            group_cols = set()
            for ref in q.group_by:
                depth, si, ci, _ = self.scope.resolve(ref)
                if depth != 0:
                    raise SQLNameError(f"GROUP BY column {ref.name} is not in FROM")
                group_cols.add((si, ci))
                self.group_keys.append(accessor(0, si, ci))
            self.scope.restrict = group_cols
        ctx = "group" if self.grouped else "row"

        # select list
        self.columns: list[str] = []
        self.items: list[Fn] = []
        for it in q.items:
            if isinstance(it.expr, n.Star):
                if self.grouped:
                    raise SQLSyntaxError("* is not allowed in a grouped query")
                if it.expr.table is not None and not any(
                        s.exposed == it.expr.table for s in self.sources):
                    raise SQLNameError(f"no such table: {it.expr.table}")
                for si, src in enumerate(self.sources):
                    if it.expr.table is None or src.exposed == it.expr.table:
                        for ci, cname in enumerate(src.columns):
                            self.columns.append(cname)
                            self.items.append(accessor(0, si, ci))
                continue
            self.items.append(comp.compile(it.expr, ctx))
            self.columns.append(it.alias or output_name(it.expr))
        self.having = comp.compile(q.having, ctx) if q.having is not None else None

        # ORDER BY: ('out', index) or ('expr', fn)
        self.order: list[tuple[str, Any, bool]] = []
        for o in q.order_by:
            e = o.expr
            if isinstance(e, n.Literal) and kind(e.value) == "int":
                if not 1 <= e.value <= len(self.columns):
                    raise SQLSyntaxError(f"ORDER BY position {e.value} is out of range")
                self.order.append(("out", e.value - 1, o.desc))
                continue
            if isinstance(e, n.ColumnRef) and e.table is None and e.name in self.columns:
                if self.columns.count(e.name) > 1:
                    raise SQLNameError(f"ORDER BY {e.name} is ambiguous")
                self.order.append(("out", self.columns.index(e.name), o.desc))
                continue
            if q.distinct:
                raise SQLSyntaxError("with DISTINCT, ORDER BY must refer to output columns")
            self.order.append(("expr", comp.compile(e, ctx), o.desc))
        self.scope.restrict = None
        self.aggs = comp.aggs

    # -------------------------------------------------------------- execution

    def _source_rows(self, i: int, outer: Env | None) -> list:
        src = self.sources[i]
        if src.query is not None:
            return src.query.run(outer)
        return list(self.ex.db.tables[src.table].rows.values())

    def run(self, outer: Env | None = None) -> list[list]:
        if not self.sources:
            rows = [()]
        else:
            rows = [(r,) for r in self._source_rows(0, outer)]
            for j, (kind_, on) in enumerate(self.joins):
                right = self._source_rows(j + 1, outer)
                joined = []
                for left in rows:
                    matched = False
                    for rr in right:
                        combo = left + (rr,)
                        if on is None or truth(on(Env(combo, outer)), "ON condition") is True:
                            joined.append(combo)
                            matched = True
                    if kind_ == "left" and not matched:
                        joined.append(left + (None,))
                rows = joined
        if self.where is not None:
            where = self.where
            rows = [r for r in rows if truth(where(Env(r, outer)), "WHERE condition") is True]

        out: list[tuple[list, list]] = []
        if self.grouped:
            groups: dict[tuple, list] = {}
            if self.group_keys:
                for r in rows:
                    env = Env(r, outer)
                    key = tuple(hash_key(g(env)) for g in self.group_keys)
                    groups.setdefault(key, []).append(r)
            else:
                groups[()] = rows
            null_row = tuple(None for _ in self.sources)
            for grows in groups.values():
                aggs = [compute_aggregate(a, grows, outer) for a in self.aggs]
                env = Env(grows[0] if grows else null_row, outer, aggs)
                if self.having is not None and truth(self.having(env), "HAVING condition") is not True:
                    continue
                out.append(self._project(env))
        else:
            for r in rows:
                out.append(self._project(Env(r, outer)))

        if self.q.distinct:
            seen, unique = set(), []
            for vals, keys in out:
                k = tuple(hash_key(v) for v in vals)
                if k not in seen:
                    seen.add(k)
                    unique.append((vals, keys))
            out = unique
        if self.order:
            sort_rows(out, [d for _, _, d in self.order])
        return apply_limit([vals for vals, _ in out], self.q.limit, self.q.offset)

    def _project(self, env: Env) -> tuple[list, list]:
        vals = [f(env) for f in self.items]
        keys = [vals[x] if how == "out" else x(env) for how, x, _ in self.order]
        return vals, keys


class PreparedSetOp:
    def __init__(self, ex: Executor, q: n.SetOp, outer: Scope | None, level: int | None) -> None:
        self.q = q
        self.left = ex.prepare(q.left, outer, level)
        self.right = ex.prepare(q.right, outer, level)
        if len(self.left.columns) != len(self.right.columns):
            raise SQLSyntaxError("set operation operands have different numbers of columns")
        self.columns = list(self.left.columns)
        self.order: list[tuple[int, bool]] = []
        for o in q.order_by:
            e = o.expr
            if isinstance(e, n.Literal) and kind(e.value) == "int":
                if not 1 <= e.value <= len(self.columns):
                    raise SQLSyntaxError(f"ORDER BY position {e.value} is out of range")
                self.order.append((e.value - 1, o.desc))
            elif isinstance(e, n.ColumnRef) and e.table is None and e.name in self.columns:
                if self.columns.count(e.name) > 1:
                    raise SQLNameError(f"ORDER BY {e.name} is ambiguous")
                self.order.append((self.columns.index(e.name), o.desc))
            else:
                raise SQLSyntaxError("ORDER BY of a set operation must name an output column")

    def run(self, outer: Env | None = None) -> list[list]:
        left, right = self.left.run(outer), self.right.run(outer)
        op = self.q.op
        if op == "union" and self.q.all:
            rows = left + right
        else:
            key = lambda row: tuple(hash_key(v) for v in row)  # noqa: E731
            seen: set = set()
            rows = []
            if op == "union":
                for row in left + right:
                    k = key(row)
                    if k not in seen:
                        seen.add(k)
                        rows.append(row)
            else:
                other = {key(row) for row in right}
                for row in left:
                    k = key(row)
                    if k not in seen and ((k in other) == (op == "intersect")):
                        rows.append(row)
                    seen.add(k)
        if self.order:
            out = [(row, [row[i] for i, _ in self.order]) for row in rows]
            sort_rows(out, [d for _, d in self.order])
            rows = [row for row, _ in out]
        return apply_limit(rows, self.q.limit, self.q.offset)


class Executor:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.resolved_levels: list[int] = []

    def prepare(self, q: Any, outer: Scope | None = None, level: int | None = None):
        if isinstance(q, n.SetOp):
            return PreparedSetOp(self, q, outer, level)
        return PreparedSelect(self, q, outer, level)

    def prepare_sub(self, q: Any, outer: Scope) -> tuple[Any, bool]:
        """Prepare a subquery; also report whether it refers to an enclosing query."""
        mark = len(self.resolved_levels)
        sub = self.prepare(q, outer)
        own = outer.level + 1
        correlated = any(lv < own for lv in self.resolved_levels[mark:])
        return sub, correlated

    def query(self, q: Any) -> dict:
        p = self.prepare(q)
        return {"columns": p.columns, "rows": p.run(None)}

    def compiler(self, sources: list[Source]) -> Compiler:
        return Compiler(self, Scope(sources))
