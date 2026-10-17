"""SQL values and the operations on them.

Values are represented by Python objects: None (NULL), bool (BOOLEAN), int (INTEGER), float
(REAL) and str (TEXT). Since ``bool`` is a subclass of ``int`` in Python, type tests here always
use ``type(v) is ...``. The functions in this module take non-NULL operands unless documented
otherwise; NULL propagation is done by the caller.
"""
from __future__ import annotations

import math
import operator
import re
from typing import Any

from minidb.lexer import INT64_MAX, INT64_MIN
from minidb.protocol import ConstraintError, SQLRuntimeError, SQLTypeError

# Comparable type classes: values of different classes cannot be compared.
NUMBER, TEXT, BOOL = "number", "text", "boolean"
_CLASS = {int: NUMBER, float: NUMBER, str: TEXT, bool: BOOL}


def type_name(v: Any) -> str:
    """The SQL type name of a value (as reported by TYPEOF)."""
    if v is None:
        return "NULL"
    return {bool: "BOOLEAN", int: "INTEGER", float: "REAL", str: "TEXT"}[type(v)]


def value_class(v: Any) -> str:
    return _CLASS[type(v)]


_COLUMN_CLASS = {"INTEGER": NUMBER, "REAL": NUMBER, "TEXT": TEXT, "BOOLEAN": BOOL}


def column_class(col_type: str) -> str:
    """The comparable type class of the non-NULL values of a column of ``col_type``."""
    return _COLUMN_CLASS[col_type]


def is_number(v: Any) -> bool:
    t = type(v)
    return t is int or t is float


def value_key(v: Any) -> Any:
    """Hashable key under which two values are equal exactly when they are duplicates
    (both NULL, or ``=`` is TRUE). Values of incomparable types get different keys."""
    if type(v) is bool:
        return ("b", v)
    return v


def check_int(v: int) -> int:
    if v < INT64_MIN or v > INT64_MAX:
        raise SQLRuntimeError("INTEGER result out of range")
    return v


def check_real(v: float) -> float:
    if not math.isfinite(v):
        raise SQLRuntimeError("REAL result is not finite")
    return v


# ---------------------------------------------------------------- arithmetic

def _arith_types(op: str, a: Any, b: Any) -> None:
    if not (is_number(a) and is_number(b)):
        raise SQLTypeError(f"operator {op} cannot be applied to {type_name(a)} and "
                           f"{type_name(b)}")


def add(a: Any, b: Any) -> Any:
    if type(a) is int and type(b) is int:  # fast path
        r = a + b
        if INT64_MIN <= r <= INT64_MAX:
            return r
        return check_int(r)
    _arith_types("+", a, b)
    return check_real(float(a) + float(b))


def sub(a: Any, b: Any) -> Any:
    if type(a) is int and type(b) is int:  # fast path
        r = a - b
        if INT64_MIN <= r <= INT64_MAX:
            return r
        return check_int(r)
    _arith_types("-", a, b)
    return check_real(float(a) - float(b))


def mul(a: Any, b: Any) -> Any:
    if type(a) is int and type(b) is int:  # fast path
        r = a * b
        if INT64_MIN <= r <= INT64_MAX:
            return r
        return check_int(r)
    _arith_types("*", a, b)
    return check_real(float(a) * float(b))


def div(a: Any, b: Any) -> float:
    """``a / b``: always REAL. For two INTEGERs, Python's int / int is the exact quotient
    rounded once to a double."""
    _arith_types("/", a, b)
    if b == 0:
        raise SQLRuntimeError("division by zero")
    if type(a) is int and type(b) is int:
        return check_real(a / b)
    return check_real(float(a) / float(b))


def int_div(a: Any, b: Any) -> int:
    """DIV(a, b): INTEGER division truncating toward zero."""
    if type(a) is not int or type(b) is not int:
        raise SQLTypeError(f"DIV() requires INTEGER arguments, got {type_name(a)} and "
                           f"{type_name(b)}")
    if b == 0:
        raise SQLRuntimeError("division by zero")
    q = abs(a) // abs(b)
    return check_int(q if (a < 0) == (b < 0) else -q)


def mod(a: Any, b: Any) -> Any:
    _arith_types("%", a, b)
    if type(a) is not int or type(b) is not int:
        raise SQLTypeError("operator % requires INTEGER operands")
    if b == 0:
        raise SQLRuntimeError("modulo by zero")
    r = abs(a) % abs(b)
    return -r if a < 0 else r


def negate(a: Any) -> Any:
    if type(a) is int:
        return check_int(-a)
    if type(a) is float:
        return -a
    raise SQLTypeError(f"unary - cannot be applied to {type_name(a)}")


def plus(a: Any) -> Any:
    if not is_number(a):
        raise SQLTypeError(f"unary + cannot be applied to {type_name(a)}")
    return a


def concat(a: Any, b: Any) -> str:
    if type(a) is not str or type(b) is not str:
        raise SQLTypeError(f"operator || cannot be applied to {type_name(a)} and "
                           f"{type_name(b)}")
    return a + b


# ---------------------------------------------------------------- comparison

def check_comparable(a: Any, b: Any, what: str = "compare") -> None:
    if _CLASS[type(a)] != _CLASS[type(b)]:
        raise SQLTypeError(f"cannot {what} {type_name(a)} with {type_name(b)}")


def _cmp(op: str):
    fn = {"=": operator.eq, "<>": operator.ne, "<": operator.lt, "<=": operator.le,
          ">": operator.gt, ">=": operator.ge}[op]

    def compare(a: Any, b: Any) -> bool:
        if type(a) is not type(b):
            check_comparable(a, b)
        return fn(a, b)
    return compare


COMPARISONS = {op: _cmp(op) for op in ("=", "<>", "<", "<=", ">", ">=")}


_like_cache: dict[str, re.Pattern] = {}


def like(s: Any, pattern: Any) -> bool:
    if type(s) is not str or type(pattern) is not str:
        raise SQLTypeError(f"LIKE requires TEXT operands, got {type_name(s)} and "
                           f"{type_name(pattern)}")
    rx = _like_cache.get(pattern)
    if rx is None:
        parts = []
        for ch in pattern:
            if ch == "%":
                parts.append(".*")
            elif ch == "_":
                parts.append(".")
            else:
                parts.append(re.escape(ch))
        rx = re.compile("".join(parts), re.DOTALL)
        if len(_like_cache) > 1000:
            _like_cache.clear()
        _like_cache[pattern] = rx
    return rx.fullmatch(s) is not None


def check_bool(v: Any, what: str) -> None:
    """Raise TypeError unless ``v`` is NULL or BOOLEAN."""
    if v is not None and type(v) is not bool:
        raise SQLTypeError(f"{what} requires BOOLEAN, got {type_name(v)}")


# ---------------------------------------------------------------- column storage

def coerce_to_column(v: Any, col_type: str, col_name: str) -> Any:
    """The value stored when ``v`` is assigned to a column of ``col_type``; a value that
    does not fit the type is a ConstraintError (a type constraint violation)."""
    if v is None:
        return None
    t = type(v)
    if col_type == "INTEGER" and t is int:
        return v
    if col_type == "REAL" and (t is float or t is int):
        return float(v)
    if col_type == "TEXT" and t is str:
        return v
    if col_type == "BOOLEAN" and t is bool:
        return v
    raise ConstraintError(f"type constraint violated: cannot store {type_name(v)} value in "
                          f"{col_type} column {col_name}")
