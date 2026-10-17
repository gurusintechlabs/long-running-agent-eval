"""Expression binding and compilation.

An expression AST is checked against a ``Scope`` (all name and syntax checks happen here, before
any row is touched) and compiled into a Python closure ``fn(env) -> value``. ``env`` is a tuple:
the concatenated columns of the scope's sources (a joined row), followed, in grouped queries,
by the values of the query's aggregates.

Subqueries: every query level has a ``QueryContext``. A name that is not found in the current
scope is looked up in the enclosing queries (the ``Outer`` chain). At run time, while a subquery
runs, the env of each enclosing query is on the statement's ``Runtime.outer_rows`` stack, so a
reference ``d`` levels out reads ``outer_rows[-d]``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from minidb import nodes as n
from minidb import values as v
from minidb.functions import FUNCTION_NAMES, SCALAR_FUNCTIONS, cast
from minidb.protocol import SQLNameError, SQLRuntimeError, SQLSyntaxError, SQLTypeError

Fn = Callable[[tuple], Any]

AGGREGATES = frozenset({"count", "sum", "avg", "min", "max"})


# ---------------------------------------------------------------- scopes

@dataclass
class Source:
    """A table reference visible to expressions: its exposed name and its column names."""
    exposed: str
    columns: list[str]
    offset: int = 0


@dataclass
class Scope:
    sources: list[Source] = field(default_factory=list)

    @property
    def width(self) -> int:
        return sum(len(s.columns) for s in self.sources)

    def add(self, exposed: str, columns: list[str]) -> Source:
        if any(s.exposed == exposed for s in self.sources):
            raise SQLNameError(f"table name {exposed} specified more than once "
                               "(use an alias)")
        src = Source(exposed, list(columns), self.width)
        self.sources.append(src)
        return src

    def source(self, exposed: str) -> Source:
        for s in self.sources:
            if s.exposed == exposed:
                return s
        raise SQLNameError(f"no such table: {exposed}")

    def lookup(self, ref: n.ColumnRef) -> Optional[tuple[int, int]]:
        """(source position, row index) of the column ``ref`` in this scope, or None if no
        source here has it. An ambiguous match is a NameError."""
        if ref.table is not None:
            matches = [s for s in self.sources
                       if s.exposed == ref.table and ref.name in s.columns]
        else:
            matches = [s for s in self.sources if ref.name in s.columns]
            if len(matches) > 1:
                raise SQLNameError(f"column reference {ref.name} is ambiguous")
        if not matches:
            return None
        src = matches[0]
        if src.columns.count(ref.name) > 1:
            raise SQLNameError(f"column reference {_ref_text(ref)} is ambiguous "
                               f"({src.exposed} has several columns named {ref.name})")
        return self.sources.index(src), src.offset + src.columns.index(ref.name)

    def resolve(self, ref: n.ColumnRef) -> int:
        """Row index of the column ``ref``, which must be in this scope."""
        found = self.lookup(ref)
        if found is None:
            raise SQLNameError(f"no such column: {_ref_text(ref)}")
        return found[1]


def _ref_text(ref: n.ColumnRef) -> str:
    return f"{ref.table}.{ref.name}" if ref.table else ref.name


# ---------------------------------------------------------------- query contexts

class Runtime:
    """Per-statement evaluation state: the envs of the enclosing queries of the running
    subquery (innermost last)."""

    def __init__(self) -> None:
        self.outer_rows: list[tuple] = []
        self._column_hashes: dict[tuple[Any, int], tuple[dict, list[int]]] = {}

    def column_hash(self, table: Any, column: int) -> tuple[dict, list[int]]:
        """For a column of a stored table: value key -> rowids, and the rowids holding NULL
        (both in table order). Built at most once per statement: no table changes while a
        statement is running."""
        found = self._column_hashes.get((table, column))
        if found is None:
            buckets: dict = {}
            nulls: list[int] = []
            for rid, row in table.scan_items():
                x = row[column]
                if x is None:
                    nulls.append(rid)
                else:
                    buckets.setdefault(v.value_key(x), []).append(rid)
            found = (buckets, nulls)
            self._column_hashes[(table, column)] = found
        return found


@dataclass
class Outer:
    """An enclosing query as seen from a subquery: its scope, and the restrictions of the
    clause the subquery is written in (grouping columns, visible join sources)."""
    scope: Scope
    grouping: Optional[set[int]]
    visible: Optional[int]
    parent: Optional["Outer"]
    depth: int


class QueryContext:
    """Compilation context of one query level (depth 0 is the statement itself)."""

    def __init__(self, db: Any, runtime: Runtime, depth: int = 0,
                 outer: Optional[Outer] = None) -> None:
        self.db = db
        self.runtime = runtime
        self.depth = depth
        self.outer = outer
        self.min_ref = depth  # the outermost depth referenced from inside this query

    @property
    def correlated(self) -> bool:
        return self.min_ref < self.depth

    def derived(self) -> "QueryContext":
        """Context for a derived table: it sees the enclosing queries, not its siblings."""
        return QueryContext(self.db, self.runtime, self.depth, self.outer)

    def absorb(self, child: "QueryContext") -> None:
        self.min_ref = min(self.min_ref, child.min_ref)


def run_plan(plan: Any, runtime: Runtime, correlated: bool) -> Callable[[tuple], list]:
    """A function env -> rows of a subquery plan. An uncorrelated subquery runs at most once
    (the first time it is needed); a correlated one runs on every call."""
    stack = runtime.outer_rows
    cache: list[list] = []

    def rows(env: tuple) -> list:
        if cache:
            return cache[0]
        stack.append(env)
        try:
            result = plan.run()
        finally:
            stack.pop()
        if not correlated:
            cache.append(result)
        return result
    return rows


# ---------------------------------------------------------------- aggregates

@dataclass
class AggregateSpec:
    name: str
    distinct: bool
    star: bool
    arg: Optional[Fn]

    def compute(self, rows: list[tuple]) -> Any:
        if self.star:
            return len(rows)
        arg = self.arg
        vals = [x for x in (arg(r) for r in rows) if x is not None]
        if self.distinct:
            seen: set = set()
            unique = []
            for x in vals:
                k = v.value_key(x)
                if k not in seen:
                    seen.add(k)
                    unique.append(x)
            vals = unique
        name = self.name
        if name == "count":
            return len(vals)
        if name in ("sum", "avg"):
            if not vals:
                return None
            for x in vals:
                if not v.is_number(x):
                    raise SQLTypeError(f"{name.upper()} requires numbers, got "
                                       f"{v.type_name(x)}")
            if all(type(x) is int for x in vals):
                total: Any = sum(vals)
                if name == "sum":
                    return v.check_int(total)
                v.check_int(total)
                return v.check_real(total / len(vals))
            ftotal = 0.0
            for x in vals:
                ftotal += float(x)
            v.check_real(ftotal)
            return ftotal if name == "sum" else v.check_real(ftotal / len(vals))
        # min / max
        best = None
        for x in vals:
            if best is None:
                best = x
                continue
            v.check_comparable(best, x)
            if (x < best) if name == "min" else (x > best):
                best = x
        return best


def contains_aggregate(expr: n.Expr) -> bool:
    if isinstance(expr, n.FuncCall) and expr.name in AGGREGATES:
        return True
    return any(contains_aggregate(c) for c in children(expr))


def children(expr: n.Expr) -> list[n.Expr]:
    if isinstance(expr, (n.Unary, n.Not)):
        return [expr.operand]
    if isinstance(expr, n.Binary):
        return [expr.left, expr.right]
    if isinstance(expr, n.IsNull):
        return [expr.operand]
    if isinstance(expr, n.Between):
        return [expr.operand, expr.low, expr.high]
    if isinstance(expr, n.InList):
        return [expr.operand, *expr.items]
    if isinstance(expr, n.FuncCall):
        return list(expr.args)
    if isinstance(expr, n.Case):
        parts = [] if expr.operand is None else [expr.operand]
        for cond, result in expr.whens:
            parts += [cond, result]
        return parts + ([] if expr.else_ is None else [expr.else_])
    if isinstance(expr, n.Cast):
        return [expr.operand]
    if isinstance(expr, n.InSubquery):
        return [expr.operand]  # the subquery's own aggregates belong to the subquery
    return []


class InIndex:
    """``x IN (values)`` without scanning the values for every ``x``.

    Same result as comparing ``x`` with each value in order (stopping at the first TRUE): the
    comparison raises a TypeError if a value of an incomparable type comes before the first
    equal value, so the index keeps the position of the first value of each key and of each
    type class.
    """

    def __init__(self, items: list) -> None:
        self.empty = not items
        self.has_null = False
        self.first_key: dict = {}
        self.first_class: dict[str, int] = {}
        for i, item in enumerate(items):
            if item is None:
                self.has_null = True
                continue
            self.first_key.setdefault(v.value_key(item), i)
            self.first_class.setdefault(v.value_class(item), i)

    def lookup(self, x: Any) -> Any:
        if x is None:
            return False if self.empty else None
        cls = v.value_class(x)
        match = self.first_key.get(v.value_key(x))
        for other, i in self.first_class.items():
            if other != cls and (match is None or i < match):
                raise SQLTypeError(f"cannot compare {v.type_name(x)} with {other} in IN")
        if match is not None:
            return True
        return None if self.has_null else False


# ---------------------------------------------------------------- the compiler

def as_predicate(fn: Fn, what: str) -> Callable[[tuple], bool]:
    """Wrap a condition: TRUE keeps the row, FALSE/NULL drop it, anything else is an error."""
    def pred(env: tuple) -> bool:
        x = fn(env)
        if x is True:
            return True
        if x is None or x is False:
            return False
        raise SQLTypeError(f"{what} condition must be BOOLEAN, got {v.type_name(x)}")
    return pred


class ExprCompiler:
    """Compiles expressions of one clause.

    ``aggregates``: None if aggregates are not allowed in the clause (``clause`` names it in
    the error); else the list collecting the query's aggregates. ``grouping``: in a grouped
    query, the row indices of the grouping columns (the only columns allowed outside an
    aggregate). ``visible``: number of sources that may be referenced (for ON conditions).
    ``ctx``: the context of the query the clause belongs to.
    """

    def __init__(self, scope: Scope, clause: str, ctx: QueryContext, *,
                 aggregates: Optional[list[AggregateSpec]] = None,
                 grouping: Optional[set[int]] = None,
                 visible: Optional[int] = None) -> None:
        self.scope = scope
        self.clause = clause
        self.ctx = ctx
        self.aggregates = aggregates
        self.grouping = grouping
        self.visible = visible

    def compile(self, e: n.Expr) -> Fn:
        method = getattr(self, "_" + type(e).__name__)
        return method(e)

    def _Literal(self, e: n.Literal) -> Fn:
        val = e.value
        return lambda env: val

    def _ColumnRef(self, e: n.ColumnRef) -> Fn:
        scope, grouping, visible = self.scope, self.grouping, self.visible
        outer, depth = None, self.ctx.depth
        while True:
            found = scope.lookup(e)
            if found is not None:
                break
            outer = self.ctx.outer if outer is None else outer.parent
            if outer is None:
                raise SQLNameError(f"no such column: {_ref_text(e)}")
            scope, grouping, visible, depth = (outer.scope, outer.grouping, outer.visible,
                                               outer.depth)
        pos, idx = found
        if visible is not None and pos >= visible:
            raise SQLNameError(f"column {_ref_text(e)} cannot be referenced here (its table "
                               "is joined later)")
        if grouping is not None and idx not in grouping:
            raise SQLSyntaxError(f"column {_ref_text(e)} must appear in GROUP BY or be used "
                                 "in an aggregate")
        if outer is None:
            return lambda env: env[idx]
        self.ctx.min_ref = min(self.ctx.min_ref, depth)
        stack = self.ctx.runtime.outer_rows
        up = depth - self.ctx.depth  # negative: index from the top of the stack
        return lambda env: stack[up][idx]

    def _Unary(self, e: n.Unary) -> Fn:
        f = self.compile(e.operand)
        op = v.negate if e.op == "-" else v.plus

        def unary(env: tuple) -> Any:
            x = f(env)
            return None if x is None else op(x)
        return unary

    def _Not(self, e: n.Not) -> Fn:
        f = self.compile(e.operand)

        def not_(env: tuple) -> Any:
            x = f(env)
            if x is None:
                return None
            v.check_bool(x, "NOT")
            return not x
        return not_

    def _Binary(self, e: n.Binary) -> Fn:
        lf = self.compile(e.left)
        rf = self.compile(e.right)
        op = e.op
        if op == "AND":
            def and_(env: tuple) -> Any:
                a = lf(env)
                if a is False:
                    return False
                b = rf(env)
                v.check_bool(a, "AND")
                v.check_bool(b, "AND")
                if b is False:
                    return False
                if a is None or b is None:
                    return None
                return True
            return and_
        if op == "OR":
            def or_(env: tuple) -> Any:
                a = lf(env)
                if a is True:
                    return True
                b = rf(env)
                v.check_bool(a, "OR")
                v.check_bool(b, "OR")
                if b is True:
                    return True
                if a is None or b is None:
                    return None
                return False
            return or_
        fn = _BINARY_OPS[op]

        def binary(env: tuple) -> Any:
            a = lf(env)
            b = rf(env)
            if a is None or b is None:
                return None
            return fn(a, b)
        return binary

    def _IsNull(self, e: n.IsNull) -> Fn:
        f = self.compile(e.operand)
        negated = e.negated
        return lambda env: (f(env) is None) != negated

    def _Between(self, e: n.Between) -> Fn:
        xf, lf, hf = self.compile(e.operand), self.compile(e.low), self.compile(e.high)
        ge, le = v.COMPARISONS[">="], v.COMPARISONS["<="]
        negated = e.negated

        def between(env: tuple) -> Any:
            x, lo, hi = xf(env), lf(env), hf(env)
            first = None if x is None or lo is None else ge(x, lo)
            if first is False:
                result: Any = False
            else:
                second = None if x is None or hi is None else le(x, hi)
                if second is False:
                    result = False
                elif first is None or second is None:
                    result = None
                else:
                    result = True
            if negated and result is not None:
                return not result
            return result
        return between

    def _InList(self, e: n.InList) -> Fn:
        xf = self.compile(e.operand)
        item_fns = [self.compile(i) for i in e.items]
        eq = v.COMPARISONS["="]
        negated = e.negated

        def in_list(env: tuple) -> Any:
            x = xf(env)
            items = [f(env) for f in item_fns]
            result: Any = False
            for item in items:
                if x is None or item is None:
                    result = None
                elif eq(x, item):
                    result = True
                    break
            if negated and result is not None:
                return not result
            return result
        return in_list

    def _FuncCall(self, e: n.FuncCall) -> Fn:
        name = e.name
        if name in AGGREGATES:
            return self._aggregate(e)
        if name not in FUNCTION_NAMES:
            raise SQLNameError(f"no such function: {name}")
        if e.star or e.distinct:
            raise SQLSyntaxError(f"{name.upper()}() is not an aggregate function")
        args = [self.compile(a) for a in e.args]
        if name == "coalesce":
            if not args:
                raise SQLSyntaxError("COALESCE() requires at least one argument")

            def coalesce(env: tuple) -> Any:
                for f in args:
                    x = f(env)
                    if x is not None:
                        return x
                return None
            return coalesce
        lo, hi, impl, null_in_null_out = SCALAR_FUNCTIONS[name]
        if not lo <= len(args) <= hi:
            count = str(lo) if lo == hi else f"{lo} to {hi}"
            raise SQLSyntaxError(f"{name.upper()}() takes {count} argument(s), "
                                 f"got {len(args)}")
        if len(args) == 1:
            f = args[0]
            if not null_in_null_out:
                return lambda env: impl(f(env))

            def call1(env: tuple) -> Any:
                x = f(env)
                return None if x is None else impl(x)
            return call1

        def call(env: tuple) -> Any:
            xs = [f(env) for f in args]
            if null_in_null_out and None in xs:
                return None
            return impl(*xs)
        return call

    def _Case(self, e: n.Case) -> Fn:
        operand = None if e.operand is None else self.compile(e.operand)
        whens = [(self.compile(c), self.compile(r)) for c, r in e.whens]
        else_ = None if e.else_ is None else self.compile(e.else_)
        eq = v.COMPARISONS["="]

        def case(env: tuple) -> Any:
            if operand is None:
                for cond, result in whens:
                    x = cond(env)
                    if x is True:
                        return result(env)
                    v.check_bool(x, "CASE WHEN")
            else:
                subject = operand(env)
                for value, result in whens:
                    x = value(env)
                    if subject is not None and x is not None and eq(subject, x):
                        return result(env)
            return None if else_ is None else else_(env)
        return case

    def _Cast(self, e: n.Cast) -> Fn:
        f = self.compile(e.operand)
        target = e.type

        def cast_(env: tuple) -> Any:
            x = f(env)
            return None if x is None else cast(x, target)
        return cast_

    # ------------------------------------------------------------ subqueries

    def _plan(self, query: n.Query) -> tuple[Any, Callable[[tuple], list]]:
        from minidb.planner import build_query  # planner imports this module
        outer = Outer(self.scope, self.grouping, self.visible, self.ctx.outer, self.ctx.depth)
        child = QueryContext(self.ctx.db, self.ctx.runtime, self.ctx.depth + 1, outer)
        plan = build_query(query, child)
        self.ctx.absorb(child)
        return plan, run_plan(plan, self.ctx.runtime, child.correlated)

    def _single_column(self, plan: Any, what: str) -> None:
        if len(plan.columns) != 1:
            raise SQLSyntaxError(f"{what} must return exactly one column, not "
                                 f"{len(plan.columns)}")

    def _Subquery(self, e: n.Subquery) -> Fn:
        plan, rows = self._plan(e.query)
        self._single_column(plan, "a scalar subquery")

        def scalar(env: tuple) -> Any:
            result = rows(env)
            if len(result) > 1:
                raise SQLRuntimeError("scalar subquery returned more than one row")
            return result[0][0] if result else None
        return scalar

    def _InSubquery(self, e: n.InSubquery) -> Fn:
        xf = self.compile(e.operand)
        plan, rows = self._plan(e.query)
        self._single_column(plan, "the subquery of IN")
        negated = e.negated
        last: list = [None, None]  # (rows, their InIndex): an uncorrelated result is reused

        def in_subquery(env: tuple) -> Any:
            x = xf(env)
            result_rows = rows(env)
            if last[0] is not result_rows:
                last[0], last[1] = result_rows, InIndex([r[0] for r in result_rows])
            result = last[1].lookup(x)
            if negated and result is not None:
                return not result
            return result
        return in_subquery

    def _Exists(self, e: n.Exists) -> Fn:
        _, rows = self._plan(e.query)
        return lambda env: len(rows(env)) > 0

    def _aggregate(self, e: n.FuncCall) -> Fn:
        if self.aggregates is None:
            raise SQLSyntaxError(f"aggregate function {e.name.upper()}() is not allowed in "
                                 f"{self.clause}")
        if e.star:
            if e.name != "count":
                raise SQLSyntaxError(f"{e.name.upper()}(*) is not allowed")
            arg = None
        else:
            if len(e.args) != 1:
                raise SQLSyntaxError(f"{e.name.upper()}() takes exactly one argument")
            inner = ExprCompiler(self.scope, "an aggregate argument (aggregates cannot be "
                                 "nested)", self.ctx)
            arg = inner.compile(e.args[0])
        self.aggregates.append(AggregateSpec(e.name, e.distinct, e.star, arg))
        idx = self.scope.width + len(self.aggregates) - 1
        return lambda env: env[idx]


_BINARY_OPS: dict[str, Callable[[Any, Any], Any]] = {
    "+": v.add, "-": v.sub, "*": v.mul, "/": v.div, "%": v.mod, "||": v.concat,
    "LIKE": v.like, **v.COMPARISONS,
}
