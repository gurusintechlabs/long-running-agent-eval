"""Value semantics: SQL types, storage coercion, comparison, arithmetic, LIKE."""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from minidb.lexer import INT_MAX, INT_MIN
from minidb.protocol import SQLRuntimeError, SQLTypeError


def kind(v: Any) -> str:
    """'null', 'bool', 'int', 'real' or 'text'."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "real"
    if isinstance(v, str):
        return "text"
    raise SQLTypeError(f"unsupported value {v!r}")


def is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def type_name(v: Any) -> str:
    return {"null": "NULL", "bool": "BOOLEAN", "int": "INTEGER", "real": "REAL",
            "text": "TEXT"}[kind(v)]


def coerce(value: Any, col_type: str, column: str = "") -> Any:
    """Convert ``value`` for storage in a column of ``col_type`` (tier 5 rules)."""
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
    where = f" column {column}" if column else ""
    raise SQLTypeError(f"cannot store {type_name(value)} value {value!r} in {col_type}{where}")


def check_int(v: int) -> int:
    if not INT_MIN <= v <= INT_MAX:
        raise SQLRuntimeError("integer overflow")
    return v


def compare(a: Any, b: Any) -> int:
    """-1/0/1 for two non-NULL values of comparable types, else TypeError."""
    ka, kb = kind(a), kind(b)
    if ka in ("int", "real") and kb in ("int", "real") or ka == kb and ka in ("text", "bool"):
        return (a > b) - (a < b)
    raise SQLTypeError(f"cannot compare {type_name(a)} with {type_name(b)}")


def sort_compare(a: Any, b: Any) -> int:
    """Like ``compare`` but NULL sorts before everything."""
    if a is None:
        return 0 if b is None else -1
    if b is None:
        return 1
    return compare(a, b)


def arith(op: str, a: Any, b: Any) -> Any:
    if a is None or b is None:
        return None
    if not (is_number(a) and is_number(b)):
        raise SQLTypeError(f"operator {op} needs numbers, got {type_name(a)} and {type_name(b)}")
    both_int = isinstance(a, int) and isinstance(b, int)
    if op == "+":
        r = a + b
    elif op == "-":
        r = a - b
    elif op == "*":
        r = a * b
    elif op in ("/", "%"):
        if op == "%" and not both_int:
            raise SQLTypeError("operator % needs INTEGER operands")
        if b == 0:
            raise SQLRuntimeError("division by zero")
        if not both_int:
            r = a / b
        else:
            q = abs(a) // abs(b)
            if (a < 0) != (b < 0):
                q = -q
            r = q if op == "/" else a - b * q
    else:
        raise SQLTypeError(f"unknown operator {op}")
    return check_int(r) if both_int else float(r)


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
    c = compare(a, b)
    return {"=": c == 0, "<>": c != 0, "<": c < 0, "<=": c <= 0, ">": c > 0, ">=": c >= 0}[op]


def truth(v: Any, what: str = "condition") -> Any:
    """Check a value used as a boolean: returns True, False or None."""
    if v is None or isinstance(v, bool):
        return v
    raise SQLTypeError(f"{what} must be BOOLEAN, got {type_name(v)}")


@lru_cache(maxsize=256)
def _like_regex(pattern: str) -> re.Pattern:
    parts = []
    for ch in pattern:
        if ch == "%":
            parts.append(".*")
        elif ch == "_":
            parts.append(".")
        else:
            parts.append(re.escape(ch))
    return re.compile("".join(parts), re.DOTALL)


def like(value: Any, pattern: Any) -> Any:
    if value is None or pattern is None:
        return None
    if kind(value) != "text" or kind(pattern) != "text":
        raise SQLTypeError("LIKE needs TEXT operands")
    return _like_regex(pattern).fullmatch(value) is not None


def hash_key(v: Any) -> Any:
    """Key for grouping / DISTINCT: equal per '=' (1 and 1.0 match), NULLs equal, bools apart."""
    return ("b", v) if isinstance(v, bool) else v
