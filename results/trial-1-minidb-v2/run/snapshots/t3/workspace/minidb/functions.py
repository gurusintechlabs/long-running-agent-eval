"""Scalar functions and CAST."""
from __future__ import annotations

import decimal
import math
import re
from typing import Any, Callable

from minidb import values as v
from minidb.lexer import INT64_MAX, INT64_MIN
from minidb.protocol import SQLRuntimeError, SQLTypeError


def _require(fname: str, x: Any, kind: str) -> None:
    ok = {"text": type(x) is str, "integer": type(x) is int, "number": v.is_number(x)}[kind]
    if not ok:
        raise SQLTypeError(f"{fname}() requires {kind.upper() if kind != 'number' else 'a number'}"
                           f", got {v.type_name(x)}")


def _lower(s: Any) -> str:
    _require("LOWER", s, "text")
    return s.lower()


def _upper(s: Any) -> str:
    _require("UPPER", s, "text")
    return s.upper()


def _length(s: Any) -> int:
    _require("LENGTH", s, "text")
    return len(s)


def _abs(x: Any) -> Any:
    _require("ABS", x, "number")
    if type(x) is int:
        return v.check_int(abs(x))
    return abs(x)


def _typeof(x: Any) -> str:
    return v.type_name(x)


def _substr(s: Any, start: Any, length: Any = None) -> str:
    _require("SUBSTR", s, "text")
    _require("SUBSTR", start, "integer")
    if length is not None:
        _require("SUBSTR", length, "integer")
        if length < 0:
            raise SQLRuntimeError("SUBSTR() length must not be negative")
        end = start + length  # exclusive, 1-based
    else:
        end = len(s) + 1
    begin = max(start, 1)
    if end <= begin:
        return ""
    return s[begin - 1:end - 1]


_DECIMAL_CONTEXT = decimal.Context(prec=1000, rounding=decimal.ROUND_HALF_UP)


def _round(x: Any, digits: Any = 0) -> Any:
    _require("ROUND", x, "number")
    _require("ROUND", digits, "integer")
    if digits < 0:
        raise SQLRuntimeError("ROUND() digits must not be negative")
    if type(x) is int:
        return x
    d = decimal.Decimal(repr(x))
    if -d.as_tuple().exponent <= digits:
        return x  # already has at most ``digits`` decimal places
    rounded = d.quantize(decimal.Decimal(1).scaleb(-digits), context=_DECIMAL_CONTEXT)
    return v.check_real(float(rounded))


def _nullif(a: Any, b: Any) -> Any:
    if a is None or b is None:
        return a
    v.check_comparable(a, b)
    return None if a == b else a


def _replace(s: Any, old: Any, new: Any) -> str:
    for x in (s, old, new):
        _require("REPLACE", x, "text")
    if old == "":
        return s
    return s.replace(old, new)


def _trim(s: Any) -> str:
    _require("TRIM", s, "text")
    return s.strip(" ")


# name -> (min args, max args, implementation, propagates NULL)
# Functions that propagate NULL return NULL as soon as an argument is NULL, before calling the
# implementation. COALESCE is evaluated lazily and is handled by the compiler.
SCALAR_FUNCTIONS: dict[str, tuple[int, int, Callable[..., Any], bool]] = {
    "lower": (1, 1, _lower, True),
    "upper": (1, 1, _upper, True),
    "length": (1, 1, _length, True),
    "abs": (1, 1, _abs, True),
    "typeof": (1, 1, _typeof, False),
    "substr": (2, 3, _substr, True),
    "round": (1, 2, _round, True),
    "nullif": (2, 2, _nullif, False),
    "replace": (3, 3, _replace, True),
    "trim": (1, 1, _trim, True),
    "div": (2, 2, v.int_div, True),
}
FUNCTION_NAMES = frozenset(SCALAR_FUNCTIONS) | {"coalesce"}


# ---------------------------------------------------------------- CAST

_INT_TEXT = re.compile(r"[+-]?[0-9]+")
_REAL_TEXT = re.compile(r"[+-]?[0-9]+(\.[0-9]+)?")


def cast(x: Any, target: str) -> Any:
    """CAST(x AS target) for a non-NULL ``x``."""
    source = v.type_name(x)
    if source == target:
        return x
    if source == "INTEGER":
        if target == "REAL":
            return float(x)
        if target == "TEXT":
            return str(x)
        return x != 0
    if source == "REAL":
        if target == "INTEGER":
            result = math.trunc(x)
            if result < INT64_MIN or result > INT64_MAX:
                raise SQLRuntimeError(f"REAL value {x!r} is out of range for INTEGER")
            return result
        if target == "TEXT":
            return repr(x)
        raise SQLTypeError("cannot cast REAL to BOOLEAN")
    if source == "BOOLEAN":
        if target == "INTEGER":
            return 1 if x else 0
        if target == "TEXT":
            return "TRUE" if x else "FALSE"
        raise SQLTypeError("cannot cast BOOLEAN to REAL")
    # TEXT
    text = x.strip(" ")
    if target == "INTEGER":
        if _INT_TEXT.fullmatch(text):
            sign = "-" if text.startswith("-") else ""
            digits = text.lstrip("+-").lstrip("0") or "0"
            if len(digits) <= 19:  # also keeps int() clear of its digit-count limit
                result = int(sign + digits)
                if INT64_MIN <= result <= INT64_MAX:
                    return result
        raise SQLRuntimeError(f"cannot convert {x!r} to INTEGER")
    if target == "REAL":
        if _REAL_TEXT.fullmatch(text):
            result = float(text)
            if math.isfinite(result):
                return result
        raise SQLRuntimeError(f"cannot convert {x!r} to REAL")
    if text.isascii() and text.lower() in ("true", "false"):
        return text.lower() == "true"
    raise SQLRuntimeError(f"cannot convert {x!r} to BOOLEAN")
