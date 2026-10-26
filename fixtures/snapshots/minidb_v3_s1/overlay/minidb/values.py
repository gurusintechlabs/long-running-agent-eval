"""Value semantics: SQL types, storage coercion, comparison, arithmetic, LIKE.

A DATE is a ``datetime.date`` inside minidb and a 'YYYY-MM-DD' string on the wire (``to_wire``).
A VECTOR is a ``Vector`` (a tuple of floats) inside minidb and the text of a JSON array of floats on
the wire: the result protocol carries scalars only.
"""
from __future__ import annotations

import datetime
import json
import math
import re
from functools import lru_cache
from typing import Any

from minidb.lexer import INT_MAX, INT_MIN
from minidb.protocol import ConstraintError, SQLRuntimeError, SQLTypeError

_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
MAX_VECTOR_DIM = 4096


class Vector(tuple):
    """A VECTOR value. Vectors compare with ``=`` and ``<>`` only; ordering them is a TypeError."""

    __slots__ = ()

    def _no_order(self, other):
        raise SQLTypeError("VECTOR values cannot be ordered")

    __lt__ = __le__ = __gt__ = __ge__ = _no_order

    def wire(self) -> str:
        return json.dumps([float(x) for x in self])


def parse_vector(text: str) -> Vector:
    """``VECTOR '[1, 2.5]'``: a non-empty JSON array of at most 4096 finite numbers, else TypeError."""
    try:
        items = json.loads(text, parse_constant=lambda c: None)
    except (ValueError, RecursionError):
        raise SQLTypeError(f"malformed VECTOR literal {text[:40]!r}") from None
    if not isinstance(items, list) or not items or len(items) > MAX_VECTOR_DIM:
        raise SQLTypeError(f"a VECTOR literal must be a JSON array of 1 to {MAX_VECTOR_DIM} numbers")
    out = []
    for x in items:
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise SQLTypeError("a VECTOR literal may contain numbers only")
        f = float(x)
        if not math.isfinite(f):
            raise SQLTypeError("a VECTOR literal may contain finite numbers only")
        out.append(f)
    return Vector(out)


def vector_dim(col_type: str) -> int | None:
    """``n`` for a ``VECTOR(n)`` column type, else None."""
    return int(col_type[7:-1]) if col_type.startswith("VECTOR(") else None


def parse_date(text: str) -> datetime.date:
    """Exactly 'YYYY-MM-DD' of a valid date in 0001-01-01 .. 9999-12-31, else ValueError."""
    if not _DATE_RE.fullmatch(text):
        raise ValueError(f"not a date: {text!r}")
    return datetime.date(int(text[:4]), int(text[5:7]), int(text[8:]))


def to_wire(v: Any) -> Any:
    if isinstance(v, datetime.date):
        return v.isoformat()
    return v.wire() if isinstance(v, Vector) else v


def kind(v: Any) -> str:
    """'null', 'bool', 'int', 'real', 'text', 'date' or 'vector'."""
    if v is None:
        return "null"
    if isinstance(v, Vector):
        return "vector"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "real"
    if isinstance(v, str):
        return "text"
    if isinstance(v, datetime.date):
        return "date"
    raise SQLTypeError(f"unsupported value {v!r}")


def is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def type_name(v: Any) -> str:
    return {"null": "NULL", "bool": "BOOLEAN", "int": "INTEGER", "real": "REAL",
            "text": "TEXT", "date": "DATE", "vector": "VECTOR"}[kind(v)]


def coerce(value: Any, col_type: str, column: str = "") -> Any:
    """Convert ``value`` for storage in a column of ``col_type`` (section 5; CR-3: a value that
    does not fit is a ConstraintError)."""
    if value is None:
        return None
    k = kind(value)
    if col_type == "INTEGER" and k == "int":
        return value
    if col_type == "REAL" and k in ("int", "real"):
        return float(value)
    if col_type == "TEXT" and k == "text":
        return value
    if col_type == "BOOLEAN" and k == "bool":
        return value
    if col_type == "DATE" and k == "date":
        return value
    dim = vector_dim(col_type)
    if dim is not None and k == "vector":
        if len(value) != dim:
            raise SQLTypeError(f"cannot store a VECTOR({len(value)}) in {col_type}" + (f" column {column}" if column else ""))
        return value
    where = f" column {column}" if column else ""
    raise ConstraintError(f"cannot store {type_name(value)} value {value!r} in {col_type}{where}")


def check_int(v: int) -> int:
    if not INT_MIN <= v <= INT_MAX:
        raise SQLRuntimeError("integer overflow")
    return v


def compare(a: Any, b: Any) -> int:
    """-1/0/1 for two non-NULL values of comparable types, else TypeError."""
    ka, kb = kind(a), kind(b)
    if ka in ("int", "real") and kb in ("int", "real") or ka == kb and ka in ("text", "bool", "date"):
        return (a > b) - (a < b)
    raise SQLTypeError(f"cannot compare {type_name(a)} with {type_name(b)}")


def family(v: Any) -> str:
    """Comparison family of a non-NULL value: values of different families are incomparable."""
    k = kind(v)
    return "num" if k in ("int", "real") else k


def check_real(v: float) -> float:
    if not math.isfinite(v):
        raise SQLRuntimeError("REAL result is not finite")
    return v


def date_arith(op: str, a: Any, b: Any) -> Any:
    """DATE + INTEGER, INTEGER + DATE, DATE - INTEGER, DATE - DATE; anything else TypeError."""
    ka, kb = kind(a), kind(b)
    try:
        if op == "+" and ka == "date" and kb == "int":
            return a + datetime.timedelta(days=b)
        if op == "+" and ka == "int" and kb == "date":
            return b + datetime.timedelta(days=a)
        if op == "-" and ka == "date" and kb == "int":
            return a - datetime.timedelta(days=b)
        if op == "-" and ka == "date" and kb == "date":
            return (a - b).days
    except OverflowError:
        raise SQLRuntimeError("DATE result out of range") from None
    raise SQLTypeError(f"operator {op} cannot combine {type_name(a)} and {type_name(b)}")


def arith(op: str, a: Any, b: Any) -> Any:
    if a is None or b is None:
        return None
    if isinstance(a, datetime.date) or isinstance(b, datetime.date):
        return date_arith(op, a, b)
    if not (is_number(a) and is_number(b)):
        raise SQLTypeError(f"operator {op} needs numbers, got {type_name(a)} and {type_name(b)}")
    both_int = isinstance(a, int) and isinstance(b, int)
    if op == "+":
        r = a + b
    elif op == "-":
        r = a - b
    elif op == "*":
        r = a * b
    elif op == "/":
        if b == 0:
            raise SQLRuntimeError("division by zero")
        return check_real(a / b)  # CR-2: always REAL; int / int is correctly rounded
    elif op == "%":
        if not both_int:
            raise SQLTypeError("operator % needs INTEGER operands")
        if b == 0:
            raise SQLRuntimeError("division by zero")
        r = a - b * int_div(a, b)
    else:
        raise SQLTypeError(f"unknown operator {op}")
    return check_int(r) if both_int else check_real(float(r))


def int_div(a: int, b: int) -> int:
    """Integer quotient truncated toward zero (b != 0)."""
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def negate(a: Any) -> Any:
    if a is None:
        return None
    if not is_number(a):
        raise SQLTypeError(f"cannot negate {type_name(a)}")
    return check_int(-a) if isinstance(a, int) else -a


def concat(a: Any, b: Any) -> Any:
    if a is None or b is None:
        return None
    if kind(a) != "text" or kind(b) != "text":
        raise SQLTypeError(f"|| needs TEXT operands, got {type_name(a)} and {type_name(b)}")
    return a + b


def compare_op(op: str, a: Any, b: Any) -> Any:
    if a is None or b is None:
        return None
    if isinstance(a, Vector) or isinstance(b, Vector):
        if op not in ("=", "<>") or not (isinstance(a, Vector) and isinstance(b, Vector)):
            raise SQLTypeError(f"operator {op} cannot compare {type_name(a)} with {type_name(b)}")
        return tuple.__eq__(a, b) == (op == "=")
    c = compare(a, b)
    return {"=": c == 0, "<>": c != 0, "<": c < 0, "<=": c <= 0, ">": c > 0, ">=": c >= 0}[op]


def truth(v: Any, what: str = "condition") -> Any:
    """Check a value used as a boolean: returns True, False or None."""
    if v is None or isinstance(v, bool):
        return v
    raise SQLTypeError(f"{what} must be BOOLEAN, got {type_name(v)}")


@lru_cache(maxsize=256)
def _like_plan(pattern: str) -> tuple[list[re.Pattern], list[int]]:
    """The pattern split at ``%`` into fixed-length segments (``_`` = any one character)."""
    parts = pattern.split("%")
    segs = [re.compile("".join("." if ch == "_" else re.escape(ch) for ch in p), re.DOTALL) for p in parts]
    return segs, [len(p) for p in parts]


def _like_match(value: str, pattern: str) -> bool:
    """LIKE without backtracking: the first segment matches at the start, the last at the end, and
    each middle one at its leftmost position after the previous one (greedy is exact for ``%``).
    Linear in ``len(value)`` times the segment length, whatever the pattern."""
    segs, lens = _like_plan(pattern)
    if len(segs) == 1:
        return len(value) == lens[0] and segs[0].fullmatch(value) is not None
    end = len(value) - lens[-1]
    if end < lens[0] or segs[0].match(value) is None:
        return False
    pos = lens[0]
    for seg, n in zip(segs[1:-1], lens[1:-1], strict=True):
        if not n:
            continue
        m = seg.search(value, pos, end)
        if m is None:
            return False
        pos = m.end()
    return pos <= end and segs[-1].fullmatch(value, end) is not None


def like(value: Any, pattern: Any) -> Any:
    if value is None or pattern is None:
        return None
    if kind(value) != "text" or kind(pattern) != "text":
        raise SQLTypeError("LIKE needs TEXT operands")
    return _like_match(value, pattern)


def hash_key(v: Any) -> Any:
    """Key for grouping / DISTINCT: equal per '=' (1 and 1.0 match), NULLs equal, bools apart."""
    return ("b", v) if isinstance(v, bool) else v
