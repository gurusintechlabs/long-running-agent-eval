"""Scalar functions and CAST.

``SCALARS`` maps a function name to ``(min args, max args or None, implementation)``. Unless the
name is in ``NULL_AWARE``, the compiler returns NULL when any argument is NULL and only calls the
implementation with non-NULL values. ``COALESCE`` is compiled specially (it short-circuits).
"""
from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Context, Decimal
from typing import Any

from minidb.lexer import INT_MAX, INT_MIN
from minidb.protocol import SQLRuntimeError, SQLTypeError
from minidb.values import check_int, compare_op, int_div, is_number, kind, type_name


def _text(name: str, v: Any) -> str:
    if kind(v) != "text":
        raise SQLTypeError(f"{name.upper()} needs TEXT, got {type_name(v)}")
    return v


def _int(name: str, v: Any) -> int:
    if kind(v) != "int":
        raise SQLTypeError(f"{name.upper()} needs an INTEGER, got {type_name(v)}")
    return v


def _abs(v: Any) -> Any:
    if not is_number(v):
        raise SQLTypeError(f"ABS needs a number, got {type_name(v)}")
    return check_int(abs(v)) if isinstance(v, int) else abs(v)


def _substr(s: Any, start: Any, length: Any = None) -> str:
    s, start = _text("substr", s), _int("substr", start)
    begin = max(start, 1)
    if length is None:
        return s[begin - 1:]
    length = _int("substr", length)
    if length < 0:
        raise SQLRuntimeError("SUBSTR length must not be negative")
    end = start + length  # exclusive, 1-based
    return s[begin - 1:end - 1] if end > begin else ""


_ROUND_CTX = Context(prec=1000)


def _round(x: Any, digits: Any = 0) -> Any:
    if not is_number(x):
        raise SQLTypeError(f"ROUND needs a number, got {type_name(x)}")
    digits = _int("round", digits)
    if digits < 0:
        raise SQLRuntimeError("ROUND digits must not be negative")
    if isinstance(x, int):
        return x
    d = Decimal(repr(x))
    if digits >= 400:
        return x
    q = d.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP, context=_ROUND_CTX)
    return float(q)


def _nullif(a: Any, b: Any) -> Any:
    return None if compare_op("=", a, b) is True else a


def _replace(s: Any, old: Any, new: Any) -> str:
    s, old, new = _text("replace", s), _text("replace", old), _text("replace", new)
    return s if old == "" else s.replace(old, new)


def _div(a: Any, b: Any) -> int:
    a, b = _int("div", a), _int("div", b)
    if b == 0:
        raise SQLRuntimeError("division by zero")
    return check_int(int_div(a, b))


def _typeof(v: Any) -> str:
    return type_name(v)


SCALARS = {
    "lower": (1, 1, lambda v: _text("lower", v).lower()),
    "upper": (1, 1, lambda v: _text("upper", v).upper()),
    "length": (1, 1, lambda v: len(_text("length", v))),
    "abs": (1, 1, _abs),
    "coalesce": (1, None, None),
    "typeof": (1, 1, _typeof),
    "substr": (2, 3, _substr),
    "round": (1, 2, _round),
    "nullif": (2, 2, _nullif),
    "replace": (3, 3, _replace),
    "trim": (1, 1, lambda v: _text("trim", v).strip(" ")),
    "div": (2, 2, _div),
}
NULL_AWARE = frozenset({"typeof", "nullif"})

# ------------------------------------------------------------------ CAST

_INT_RE = re.compile(r"[+-]?[0-9]+")
_REAL_RE = re.compile(r"[+-]?[0-9]+(\.[0-9]+)?")


def cast(v: Any, ty: str) -> Any:
    if v is None:
        return None
    k = kind(v)
    if ty == "TEXT":
        if k == "text":
            return v
        if k == "bool":
            return "TRUE" if v else "FALSE"
        return repr(v) if k == "real" else str(v)
    if ty == "INTEGER":
        if k == "int":
            return v
        if k == "bool":
            return 1 if v else 0
        if k == "real":
            r = math.trunc(v)
            if not INT_MIN <= r <= INT_MAX:
                raise SQLRuntimeError(f"{v!r} is out of range for INTEGER")
            return r
        text = v.strip(" ")
        if not _INT_RE.fullmatch(text):
            raise SQLRuntimeError(f"cannot convert {v!r} to INTEGER")
        r = int(text)
        if not INT_MIN <= r <= INT_MAX:
            raise SQLRuntimeError(f"{v!r} is out of range for INTEGER")
        return r
    if ty == "REAL":
        if k == "real":
            return v
        if k == "int":
            return float(v)
        if k == "bool":
            raise SQLTypeError("cannot cast BOOLEAN to REAL")
        text = v.strip(" ")
        if not _REAL_RE.fullmatch(text):
            raise SQLRuntimeError(f"cannot convert {v!r} to REAL")
        r = float(text)
        if not math.isfinite(r):
            raise SQLRuntimeError(f"{v!r} is out of range for REAL")
        return r
    # BOOLEAN
    if k == "bool":
        return v
    if k == "int":
        return v != 0
    if k == "real":
        raise SQLTypeError("cannot cast REAL to BOOLEAN")
    text = v.strip(" ").lower()
    if text not in ("true", "false"):
        raise SQLRuntimeError(f"cannot convert {v!r} to BOOLEAN")
    return text == "true"
