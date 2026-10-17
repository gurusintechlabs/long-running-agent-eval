"""Expression binding and compilation.

An expression AST is checked against a ``Scope`` (all name and syntax checks happen here, before
any row is touched) and compiled into a Python closure ``fn(env) -> value``. ``env`` is a tuple:
the concatenated columns of the scope's sources (a joined row), followed, in grouped queries,
by the values of the query's aggregates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from minidb import nodes as n
from minidb import values as v
from minidb.protocol import SQLNameError, SQLSyntaxError, SQLTypeError

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

    def resolve(self, ref: n.ColumnRef, visible: Optional[int] = None) -> int:
        """Index in the row of the column ``ref``. Only the first ``visible`` sources may be
        referenced (None: all of them)."""
        if ref.table is not None:
            src = self.source(ref.table)
            if ref.name not in src.columns:
                raise SQLNameError(f"no such column: {ref.table}.{ref.name}")
            matches = [src]
        else:
            matches = [s for s in self.sources if ref.name in s.columns]
            if not matches:
                raise SQLNameError(f"no such column: {ref.name}")
            if len(matches) > 1:
                raise SQLNameError(f"column reference {ref.name} is ambiguous")
        src = matches[0]
        if visible is not None and self.sources.index(src) >= visible:
            raise SQLNameError(f"column {src.exposed}.{ref.name} cannot be referenced here "
                               "(its table is joined later)")
        return src.offset + src.columns.index(ref.name)


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
    return []


# ---------------------------------------------------------------- scalar functions

def _text_fn(name: str, impl: Callable[[str], Any]) -> Callable[[Any], Any]:
    def fn(x: Any) -> Any:
        if type(x) is not str:
            raise SQLTypeError(f"{name}() requires TEXT, got {v.type_name(x)}")
        return impl(x)
    return fn


def _abs(x: Any) -> Any:
    if type(x) is int:
        return v.check_int(abs(x))
    if type(x) is float:
        return abs(x)
    raise SQLTypeError(f"ABS() requires a number, got {v.type_name(x)}")


# one-argument functions: name -> implementation on a non-NULL argument
_UNARY_FUNCTIONS: dict[str, Callable[[Any], Any]] = {
    "lower": _text_fn("LOWER", str.lower),
    "upper": _text_fn("UPPER", str.upper),
    "length": _text_fn("LENGTH", len),
    "abs": _abs,
}
SCALAR_FUNCTIONS = frozenset(_UNARY_FUNCTIONS) | {"coalesce", "typeof"}


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
    """

    def __init__(self, scope: Scope, clause: str, *,
                 aggregates: Optional[list[AggregateSpec]] = None,
                 grouping: Optional[set[int]] = None,
                 visible: Optional[int] = None) -> None:
        self.scope = scope
        self.clause = clause
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
        idx = self.scope.resolve(e, self.visible)
        if self.grouping is not None and idx not in self.grouping:
            name = f"{e.table}.{e.name}" if e.table else e.name
            raise SQLSyntaxError(f"column {name} must appear in GROUP BY or be used in an "
                                 "aggregate")
        return lambda env: env[idx]

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
        if name not in SCALAR_FUNCTIONS:
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
        if len(args) != 1:
            raise SQLSyntaxError(f"{name.upper()}() takes exactly one argument")
        f = args[0]
        if name == "typeof":
            return lambda env: v.type_name(f(env))
        impl = _UNARY_FUNCTIONS[name]

        def call(env: tuple) -> Any:
            x = f(env)
            return None if x is None else impl(x)
        return call

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
                                 "nested)")
            arg = inner.compile(e.args[0])
        self.aggregates.append(AggregateSpec(e.name, e.distinct, e.star, arg))
        idx = self.scope.width + len(self.aggregates) - 1
        return lambda env: env[idx]


_BINARY_OPS: dict[str, Callable[[Any, Any], Any]] = {
    "+": v.add, "-": v.sub, "*": v.mul, "/": v.div, "%": v.mod, "||": v.concat,
    "LIKE": v.like, **v.COMPARISONS,
}
