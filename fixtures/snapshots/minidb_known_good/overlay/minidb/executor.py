"""Query execution: name resolution, expression compilation, SELECT pipeline, index plans.

Expressions are compiled once per statement into closures ``f(env) -> value``. Name resolution
happens at compile time, so unknown or ambiguous names fail before any row is read. An ``Env``
holds the current row (a tuple with one entry per FROM source; ``None`` for a NULL-extended
LEFT JOIN side), the enclosing query's env (correlated subqueries), and aggregate values.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cmp_to_key
from typing import Any, Callable

from minidb import nodes as n
from minidb.protocol import SQLNameError, SQLRuntimeError, SQLSyntaxError, SQLTypeError
from minidb.storage import Database
from minidb.values import (
    arith,
    check_int,
    compare,
    compare_op,
    concat,
    hash_key,
    is_number,
    kind,
    like,
    negate,
    sort_compare,
    truth,
    type_name,
)

AGGREGATES = frozenset({"count", "sum", "avg", "min", "max"})
SCALARS = {"lower": (1, 1), "upper": (1, 1), "length": (1, 1), "abs": (1, 1),
           "coalesce": (1, None)}
_RANGE_FLIP = {"<": ">", "<=": ">=", ">": "<", ">=": "<=", "=": "="}

Fn = Callable[["Env"], Any]


class Env:
    __slots__ = ("row", "outer", "aggs")

    def __init__(self, row: tuple, outer: Env | None = None, aggs: list | None = None) -> None:
        self.row, self.outer, self.aggs = row, outer, aggs


@dataclass
class Source:
    exposed: str
    name: str                      # table or view name
    columns: list[str]
    table: str | None = None       # set for base tables
    view: PreparedSelect | None = None


class Scope:
    def __init__(self, sources: list[Source], outer: Scope | None = None) -> None:
        self.sources, self.outer = sources, outer

    def resolve(self, ref: n.ColumnRef) -> tuple[int, int, int]:
        """``(depth, source index, column index)`` for a column reference."""
        level, depth = self, 0
        label = f"{ref.table}.{ref.name}" if ref.table else ref.name
        while level is not None:
            if ref.table is not None:
                srcs = [i for i, s in enumerate(level.sources) if s.exposed == ref.table]
                if srcs:
                    cols = [i for i, c in enumerate(level.sources[srcs[0]].columns) if c == ref.name]
                    if not cols:
                        raise SQLNameError(f"no column {label}")
                    if len(cols) > 1:
                        raise SQLNameError(f"column reference {label} is ambiguous")
                    return depth, srcs[0], cols[0]
            else:
                found = [(si, ci) for si, s in enumerate(level.sources)
                         for ci, c in enumerate(s.columns) if c == ref.name]
                if len(found) > 1:
                    raise SQLNameError(f"column reference {label} is ambiguous")
                if found:
                    return depth, found[0][0], found[0][1]
            level, depth = level.outer, depth + 1
        raise SQLNameError(f"no such column: {label}")


def accessor(depth: int, si: int, ci: int) -> Fn:
    def get(env: Env) -> Any:
        for _ in range(depth):
            env = env.outer
        r = env.row[si]
        return None if r is None else r[ci]
    return get


def flatten_and(e: Any) -> list:
    if isinstance(e, n.Binary) and e.op == "AND":
        return flatten_and(e.left) + flatten_and(e.right)
    return [e]


def literal_value(e: Any) -> tuple[bool, Any]:
    """(True, value) if ``e`` is a non-NULL literal (numbers may carry a unary minus)."""
    if isinstance(e, n.Literal) and e.value is not None:
        return True, e.value
    if (isinstance(e, n.Unary) and e.op == "-" and isinstance(e.operand, n.Literal)
            and is_number(e.operand.value)):
        return True, -e.operand.value
    return False, None


def contains_aggregate(e: Any) -> bool:
    if isinstance(e, n.Func):
        return e.name in AGGREGATES or any(contains_aggregate(a) for a in e.args)
    if isinstance(e, (n.ScalarSubquery, n.Exists, n.Literal, n.ColumnRef, n.Star)) or e is None:
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


@dataclass
class AggSpec:
    name: str
    arg: Fn | None
    distinct: bool


def compute_aggregate(a: AggSpec, rows: list, outer: Env | None) -> Any:
    if a.arg is None:  # COUNT(*)
        return len(rows)
    vals = [v for v in (a.arg(Env(r, outer)) for r in rows) if v is not None]
    if a.name == "count":
        return len({hash_key(v) for v in vals}) if a.distinct else len(vals)
    if a.name in ("sum", "avg"):
        for v in vals:
            if not is_number(v):
                raise SQLTypeError(f"{a.name.upper()} needs numbers, got {type_name(v)}")
        if not vals:
            return None
        total = sum(vals)
        if a.name == "avg":
            return total / len(vals)
        return check_int(total) if all(isinstance(v, int) for v in vals) else float(total)
    best = None
    for v in vals:
        if kind(v) not in ("int", "real", "text", "bool"):
            raise SQLTypeError(f"{a.name.upper()} cannot order {type_name(v)}")
        if best is None:
            best = v
        else:
            c = compare(v, best)
            if (c < 0 and a.name == "min") or (c > 0 and a.name == "max"):
                best = v
    return best


# ------------------------------------------------------------------ compiler


class Compiler:
    """Compiles expressions against a scope. ``ctx`` is 'row' (no aggregates), 'group' (grouped
    query output: aggregates allowed, bare columns must be grouping columns) or 'agg' (inside
    an aggregate's argument)."""

    def __init__(self, executor: Executor, scope: Scope, group_cols: set | None = None) -> None:
        self.ex, self.scope = executor, scope
        self.group_cols = group_cols
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
        depth, si, ci = self.scope.resolve(e)
        if ctx == "group" and depth == 0 and (si, ci) not in (self.group_cols or set()):
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
            x = f(env)
            r = _and3(compare_op(">=", x, lo(env)), compare_op("<=", x, hi(env)))
            return _not3(r) if neg else r
        return between

    def _c_InList(self, e: n.InList, ctx: str) -> Fn:
        f, items, neg = self.compile(e.operand, ctx), [self.compile(x, ctx) for x in e.items], e.negated

        def in_list(env):
            x = f(env)
            r = _in_values(x, (g(env) for g in items))
            return _not3(r) if neg else r
        return in_list

    def _c_InSubquery(self, e: n.InSubquery, ctx: str) -> Fn:
        f, neg = self.compile(e.operand, ctx), e.negated
        sub = self.ex.prepare(e.query, self.scope)
        if len(sub.columns) != 1:
            raise SQLSyntaxError("IN subquery must return exactly one column")

        def in_sub(env):
            x = f(env)
            r = _in_values(x, (row[0] for row in sub.run(env)))
            return _not3(r) if neg else r
        return in_sub

    def _c_Like(self, e: n.Like, ctx: str) -> Fn:
        f, p, neg = self.compile(e.operand, ctx), self.compile(e.pattern, ctx), e.negated

        def like_(env):
            r = like(f(env), p(env))
            return _not3(r) if neg else r
        return like_

    def _c_ScalarSubquery(self, e: n.ScalarSubquery, ctx: str) -> Fn:
        sub = self.ex.prepare(e.query, self.scope)
        if len(sub.columns) != 1:
            raise SQLSyntaxError("scalar subquery must return exactly one column")

        def scalar(env):
            rows = sub.run(env)
            if len(rows) > 1:
                raise SQLRuntimeError("scalar subquery returned more than one row")
            return rows[0][0] if rows else None
        return scalar

    def _c_Exists(self, e: n.Exists, ctx: str) -> Fn:
        sub = self.ex.prepare(e.query, self.scope)
        return lambda env: bool(sub.run(env))

    def _c_Func(self, e: n.Func, ctx: str) -> Fn:
        name = e.name
        if name in AGGREGATES:
            if ctx != "group":
                raise SQLSyntaxError(f"aggregate {name.upper()} is not allowed here")
            if not e.star and len(e.args) != 1:
                raise SQLSyntaxError(f"{name.upper()} takes exactly one argument")
            arg = None if e.star else self.compile(e.args[0], "agg")
            slot = len(self.aggs)
            self.aggs.append(AggSpec(name, arg, e.distinct))
            return lambda env: env.aggs[slot]
        if name not in SCALARS:
            raise SQLNameError(f"no such function: {name}")
        lo, hi = SCALARS[name]
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
        g = args[0]

        def scalar_fn(env):
            v = g(env)
            if v is None:
                return None
            if name == "abs":
                if not is_number(v):
                    raise SQLTypeError(f"ABS needs a number, got {type_name(v)}")
                return check_int(abs(v)) if isinstance(v, int) else abs(v)
            if kind(v) != "text":
                raise SQLTypeError(f"{name.upper()} needs TEXT, got {type_name(v)}")
            return v.lower() if name == "lower" else v.upper() if name == "upper" else len(v)
        return scalar_fn


# ------------------------------------------------------------------ SELECT


@dataclass
class IndexPlan:
    index: str
    column: str
    op: str        # '=', '<', '<=', '>', '>=', 'between'
    values: tuple

    @property
    def label(self) -> str:
        return f"({self.column} = ?)" if self.op == "=" else f"({self.column} RANGE)"


class PreparedSelect:
    def __init__(self, ex: Executor, q: n.Select, outer: Scope | None) -> None:
        self.ex, self.q = ex, q
        db = ex.db
        self.sources: list[Source] = []
        refs = ([q.from_] + [j.table for j in q.joins]) if q.from_ else []
        for ref in refs:
            if ref.name in db.tables:
                t = db.tables[ref.name]
                src = Source(ref.exposed, ref.name, [c.name for c in t.columns], table=ref.name)
            elif ref.name in db.views:
                view = ex.prepare(db.views[ref.name].query, None)
                src = Source(ref.exposed, ref.name, list(view.columns), view=view)
            else:
                raise SQLNameError(f"no such table: {ref.name}")
            if any(s.exposed == src.exposed for s in self.sources):
                raise SQLNameError(f"table name {src.exposed} specified more than once")
            self.sources.append(src)
        self.scope = Scope(self.sources, outer)
        comp = Compiler(ex, self.scope)

        self.joins = []
        for j, join in enumerate(q.joins):
            on = None
            if join.on is not None:
                on = Compiler(ex, Scope(self.sources[:j + 2], outer)).compile(join.on)
            self.joins.append((join.kind, on))
        self.where = comp.compile(q.where) if q.where is not None else None

        self.grouped = bool(q.group_by) or q.having is not None or any(
            contains_aggregate(it.expr) for it in q.items) or any(
            contains_aggregate(o.expr) for o in q.order_by)
        self.group_keys: list[Fn] = []
        if self.grouped:
            group_cols = set()
            for ref in q.group_by:
                depth, si, ci = self.scope.resolve(ref)
                if depth != 0:
                    raise SQLSyntaxError(f"GROUP BY column {ref.name} is not in FROM")
                group_cols.add((si, ci))
                self.group_keys.append(accessor(0, si, ci))
            comp = Compiler(ex, self.scope, group_cols)
        ctx = "group" if self.grouped else "row"

        # select list
        self.columns: list[str] = []
        self.items: list[Fn] = []
        for it in q.items:
            if isinstance(it.expr, n.Star):
                if self.grouped:
                    raise SQLSyntaxError("* is not allowed in a grouped query")
                for si, src in enumerate(self.sources):
                    if it.expr.table is None or src.exposed == it.expr.table:
                        for ci, cname in enumerate(src.columns):
                            self.columns.append(cname)
                            self.items.append(accessor(0, si, ci))
                if it.expr.table is not None and not any(
                        s.exposed == it.expr.table for s in self.sources):
                    raise SQLNameError(f"no such table: {it.expr.table}")
                continue
            self.items.append(comp.compile(it.expr, ctx))
            if it.alias:
                self.columns.append(it.alias)
            elif isinstance(it.expr, (n.ColumnRef, n.Func)):
                self.columns.append(it.expr.name)
            else:
                self.columns.append("?column?")
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
        self.aggs = comp.aggs
        self.plan = self._choose_index()

    # -------------------------------------------------------------- plan

    def _choose_index(self) -> IndexPlan | None:
        if self.q.where is None or not self.sources or self.sources[0].table is None:
            return None
        table = self.sources[0].table
        eq = rng = None
        for c in flatten_and(self.q.where):
            m = self._usable(c)
            if m is None:
                continue
            col, op, values = m
            ix = self.ex.db.index_for(table, col)
            if ix is None:
                continue
            if op == "=" and eq is None:
                eq = IndexPlan(ix.name, col, op, values)
            elif op != "=" and rng is None:
                rng = IndexPlan(ix.name, col, op, values)
        return eq or rng

    def _first_source_column(self, e: Any) -> str | None:
        if not isinstance(e, n.ColumnRef):
            return None
        try:
            depth, si, ci = self.scope.resolve(e)
        except SQLNameError:
            return None
        return self.sources[0].columns[ci] if depth == 0 and si == 0 else None

    def _usable(self, c: Any):
        if isinstance(c, n.Binary) and c.op in _RANGE_FLIP:
            col = self._first_source_column(c.left)
            ok, v = literal_value(c.right)
            if col is not None and ok:
                return col, c.op, (v,)
            col = self._first_source_column(c.right)
            ok, v = literal_value(c.left)
            if col is not None and ok:
                return col, _RANGE_FLIP[c.op], (v,)
        if isinstance(c, n.Between) and not c.negated:
            col = self._first_source_column(c.operand)
            ok1, lo = literal_value(c.low)
            ok2, hi = literal_value(c.high)
            if col is not None and ok1 and ok2:
                return col, "between", (lo, hi)
        return None

    def explain(self) -> list[list[str]]:
        rows = []
        for i, s in enumerate(self.sources):
            if i == 0 and self.plan is not None:
                rows.append([f"SEARCH {s.name} USING INDEX {self.plan.index} {self.plan.label}"])
            else:
                rows.append([f"SCAN {s.name}"])
        return rows

    # -------------------------------------------------------------- execution

    def _source_rows(self, i: int) -> list:
        src = self.sources[i]
        if src.view is not None:
            return [list(r) for r in src.view.run(None)]
        table = self.ex.db.tables[src.table]
        if i == 0 and self.plan is not None:
            rowids = self._index_lookup(table)
            if rowids is not None:
                return [table.rows[r] for r in sorted(rowids)]
        return list(table.rows.values())

    def _index_lookup(self, table) -> list[int] | None:
        p = self.plan
        ix = self.ex.db.indexes[p.index]
        col_type = table.columns[table.col_index(p.column)].type
        want = {"INTEGER": ("int", "real"), "REAL": ("int", "real"), "TEXT": ("text",),
                "BOOLEAN": ("bool",)}[col_type]
        if any(kind(v) not in want for v in p.values):
            return None  # let the full scan raise the type error
        v = p.values[0]
        if p.op == "=":
            return ix.lookup(v, True, v, True)
        if p.op == "between":
            return ix.lookup(p.values[0], True, p.values[1], True)
        if p.op in ("<", "<="):
            return ix.lookup(None, True, v, p.op == "<=")
        return ix.lookup(v, p.op == ">=", None, True)

    def run(self, outer: Env | None = None) -> list[list]:
        if not self.sources:
            rows = [()]
        else:
            rows = [(r,) for r in self._source_rows(0)]
            for j, (kind_, on) in enumerate(self.joins):
                right = self._source_rows(j + 1)
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
            rows = [r for r in rows if truth(self.where(Env(r, outer)), "WHERE condition") is True]

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
            desc = [d for _, _, d in self.order]

            def cmp(a, b):
                for x, y, d in zip(a[1], b[1], desc, strict=True):
                    c = sort_compare(x, y)
                    if c:
                        return -c if d else c
                return 0
            out.sort(key=cmp_to_key(cmp))
        result = [vals for vals, _ in out]
        end = None if self.q.limit is None else self.q.offset + self.q.limit
        return result[self.q.offset:end]

    def _project(self, env: Env) -> tuple[list, list]:
        vals = [f(env) for f in self.items]
        keys = [vals[x] if how == "out" else x(env) for how, x, _ in self.order]
        return vals, keys


class Executor:
    def __init__(self, db: Database) -> None:
        self.db = db

    def prepare(self, q: n.Select, outer: Scope | None = None) -> PreparedSelect:
        return PreparedSelect(self, q, outer)

    def query(self, q: n.Select) -> dict:
        p = self.prepare(q)
        return {"columns": p.columns, "rows": p.run(None)}

    def explain(self, q: n.Select) -> dict:
        return {"columns": ["plan"], "rows": self.prepare(q).explain()}

    def compiler(self, sources: list[Source]) -> Compiler:
        return Compiler(self, Scope(sources))
