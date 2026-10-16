"""Query execution: name resolution, expression compilation, the SELECT pipeline.

Expressions are compiled once per statement into closures ``f(env) -> value``. Name resolution
happens at compile time, so unknown or ambiguous names fail before any row is read. An ``Env``
holds the current row (a tuple with one entry per FROM source; ``None`` for a NULL-extended
LEFT JOIN side) and the aggregate values of the current group.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from minidb import nodes as n
from minidb.protocol import SQLNameError, SQLSyntaxError, SQLTypeError
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
SCALARS = {"lower": (1, 1), "upper": (1, 1), "length": (1, 1), "abs": (1, 1),
           "coalesce": (1, None), "typeof": (1, 1)}

Fn = Callable[["Env"], Any]


class Env:
    __slots__ = ("row", "aggs")

    def __init__(self, row: tuple, aggs: list | None = None) -> None:
        self.row, self.aggs = row, aggs


@dataclass
class Source:
    exposed: str
    name: str
    columns: list[str]


class Scope:
    def __init__(self, sources: list[Source]) -> None:
        self.sources = sources

    def resolve(self, ref: n.ColumnRef) -> tuple[int, int]:
        """``(source index, column index)`` for a column reference."""
        label = f"{ref.table}.{ref.name}" if ref.table else ref.name
        if ref.table is not None:
            srcs = [i for i, s in enumerate(self.sources) if s.exposed == ref.table]
            if not srcs:
                raise SQLNameError(f"no such table: {ref.table}")
            cols = [i for i, c in enumerate(self.sources[srcs[0]].columns) if c == ref.name]
            if not cols:
                raise SQLNameError(f"no column {label}")
            return srcs[0], cols[0]
        found = [(si, ci) for si, s in enumerate(self.sources)
                 for ci, c in enumerate(s.columns) if c == ref.name]
        if len(found) > 1:
            raise SQLNameError(f"column reference {label} is ambiguous")
        if not found:
            raise SQLNameError(f"no such column: {label}")
        return found[0]


def accessor(si: int, ci: int) -> Fn:
    def get(env: Env) -> Any:
        r = env.row[si]
        return None if r is None else r[ci]
    return get


def contains_aggregate(e: Any) -> bool:
    if isinstance(e, n.Func):
        return e.name in AGGREGATES or any(contains_aggregate(a) for a in e.args)
    if isinstance(e, (n.Literal, n.ColumnRef, n.Star)) or e is None:
        return False
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


def _in_values(x: Any, values: list) -> Any:
    saw_null = False
    for v in values:
        c = compare_op("=", x, v)
        if c is True:
            return True
        if c is None:
            saw_null = True
    return None if saw_null else False


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


def compute_aggregate(a: AggSpec, rows: list) -> Any:
    if a.arg is None:  # COUNT(*)
        return len(rows)
    vals = [v for v in (a.arg(Env(r)) for r in rows) if v is not None]
    if a.distinct:
        vals = distinct_values(vals)
    return aggregate_values(a.name, vals)


# ------------------------------------------------------------------ scalar functions


def _text_fn(name: str, v: Any) -> Any:
    if kind(v) != "text":
        raise SQLTypeError(f"{name.upper()} needs TEXT, got {type_name(v)}")
    return v.lower() if name == "lower" else v.upper() if name == "upper" else len(v)


def _abs(v: Any) -> Any:
    if not is_number(v):
        raise SQLTypeError(f"ABS needs a number, got {type_name(v)}")
    return check_int(abs(v)) if isinstance(v, int) else abs(v)


# ------------------------------------------------------------------ compiler


class Compiler:
    """Compiles expressions against a scope. ``ctx`` is 'row' (no aggregates), 'group' (grouped
    query output: aggregates allowed, bare columns must be grouping columns) or 'agg' (inside
    an aggregate's argument)."""

    def __init__(self, scope: Scope, group_cols: set | None = None) -> None:
        self.scope = scope
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
        si, ci = self.scope.resolve(e)
        if ctx == "group" and (si, ci) not in (self.group_cols or set()):
            raise SQLSyntaxError(f"column {e.name} must appear in GROUP BY or in an aggregate")
        return accessor(si, ci)

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
        if name == "typeof":
            return lambda env: type_name(g(env))
        if name == "abs":
            return lambda env: None if (v := g(env)) is None else _abs(v)
        return lambda env: None if (v := g(env)) is None else _text_fn(name, v)


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


# ------------------------------------------------------------------ SELECT


class PreparedSelect:
    def __init__(self, ex: Executor, q: n.Select) -> None:
        self.ex, self.q = ex, q
        db = ex.db
        self.sources: list[Source] = []
        refs = ([q.from_] + [j.table for j in q.joins]) if q.from_ else []
        for ref in refs:
            if ref.name not in db.tables:
                raise SQLNameError(f"no such table: {ref.name}")
            t = db.tables[ref.name]
            src = Source(ref.exposed, ref.name, [c.name for c in t.columns])
            if any(s.exposed == src.exposed for s in self.sources):
                raise SQLNameError(f"table name {src.exposed} specified more than once")
            self.sources.append(src)
        self.scope = Scope(self.sources)
        comp = Compiler(self.scope)

        self.joins = []
        for j, join in enumerate(q.joins):
            on = None
            if join.on is not None:
                on = Compiler(Scope(self.sources[:j + 2])).compile(join.on)
            self.joins.append((join.kind, on))
        self.where = comp.compile(q.where) if q.where is not None else None

        self.grouped = bool(q.group_by) or q.having is not None or any(
            contains_aggregate(it.expr) for it in q.items) or any(
            contains_aggregate(o.expr) for o in q.order_by)
        self.group_keys: list[Fn] = []
        if self.grouped:
            group_cols = set()
            for ref in q.group_by:
                si, ci = self.scope.resolve(ref)
                group_cols.add((si, ci))
                self.group_keys.append(accessor(si, ci))
            comp = Compiler(self.scope, group_cols)
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
                            self.items.append(accessor(si, ci))
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

    # -------------------------------------------------------------- execution

    def _source_rows(self, i: int) -> list:
        return list(self.ex.db.tables[self.sources[i].name].rows.values())

    def run(self) -> list[list]:
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
                        if on is None or truth(on(Env(combo)), "ON condition") is True:
                            joined.append(combo)
                            matched = True
                    if kind_ == "left" and not matched:
                        joined.append(left + (None,))
                rows = joined
        if self.where is not None:
            rows = [r for r in rows if truth(self.where(Env(r)), "WHERE condition") is True]

        out: list[tuple[list, list]] = []
        if self.grouped:
            groups: dict[tuple, list] = {}
            if self.group_keys:
                for r in rows:
                    env = Env(r)
                    key = tuple(hash_key(g(env)) for g in self.group_keys)
                    groups.setdefault(key, []).append(r)
            else:
                groups[()] = rows
            null_row = tuple(None for _ in self.sources)
            for grows in groups.values():
                aggs = [compute_aggregate(a, grows) for a in self.aggs]
                env = Env(grows[0] if grows else null_row, aggs)
                if self.having is not None and truth(self.having(env), "HAVING condition") is not True:
                    continue
                out.append(self._project(env))
        else:
            for r in rows:
                out.append(self._project(Env(r)))

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

    def prepare(self, q: n.Select) -> PreparedSelect:
        return PreparedSelect(self, q)

    def query(self, q: n.Select) -> dict:
        p = self.prepare(q)
        return {"columns": p.columns, "rows": p.run()}

    def compiler(self, sources: list[Source]) -> Compiler:
        return Compiler(Scope(sources))
