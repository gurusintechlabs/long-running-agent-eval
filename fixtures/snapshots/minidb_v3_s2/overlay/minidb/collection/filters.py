"""Payload filters: parsed and validated once, then evaluated per point.

    filter    := {"must": [cond], "should": [cond], "must_not": [cond]}   (each optional)
    cond      := filter
               | {"key": "a.b", "match": {"value": v}} | {"key": ..., "match": {"any": [v, ...]}}
               | {"key": ..., "range": {"gt" | "gte" | "lt" | "lte": number, ...}}
               | {"has_id": [id, ...]}

Matching: numbers compare by value (1 matches 1.0) but never match booleans; an array at the path
matches when any element does; a missing key or null satisfies no match or range. Filters nest at most
``MAX_DEPTH`` levels.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from minidb.collection.points import Invalid, is_number, parse_id

MAX_DEPTH = 8
CLAUSES = ("must", "should", "must_not")
RANGE_OPS = ("gt", "gte", "lt", "lte")
_MISSING = object()

Pred = Callable[[Any, Any], bool]          # (point id, payload) -> bool


def compile_filter(obj: Any, parse_point_id: Callable[[Any], Any] = parse_id) -> Pred | None:
    """The predicate of a filter, or None when it matches every point (absent, null or ``{}``)."""
    if obj is None:
        return None
    pred = _filter(obj, 1, parse_point_id)
    return None if pred is _ALL else pred


def _all(pid, payload) -> bool:
    return True


_ALL: Pred = _all


def _filter(obj: Any, depth: int, pid_parser) -> Pred:
    if depth > MAX_DEPTH:
        raise Invalid(f"filters nest at most {MAX_DEPTH} levels")
    if not isinstance(obj, dict):
        raise Invalid("a filter must be an object")
    unknown = set(obj) - set(CLAUSES)
    if unknown:
        raise Invalid(f"unknown filter clause {min(unknown)!r}")
    parts: dict[str, list[Pred]] = {}
    for clause in CLAUSES:
        if clause not in obj:
            continue
        conds = obj[clause]
        if not isinstance(conds, list):
            raise Invalid(f"'{clause}' must be an array of conditions")
        parts[clause] = [_condition(c, depth, pid_parser) for c in conds]
    must, should, must_not = parts.get("must", []), parts.get("should", []), parts.get("must_not", [])
    if not (must or should or must_not):
        return _ALL

    def pred(pid, payload) -> bool:
        for c in must:
            if not c(pid, payload):
                return False
        if should and not any(c(pid, payload) for c in should):
            return False
        for c in must_not:
            if c(pid, payload):
                return False
        return True
    return pred


def _condition(c: Any, depth: int, pid_parser) -> Pred:
    if not isinstance(c, dict):
        raise Invalid("a condition must be an object")
    if "has_id" in c:
        if set(c) != {"has_id"} or not isinstance(c["has_id"], list):
            raise Invalid("'has_id' must be an array of point ids")
        ids = {pid_parser(x) for x in c["has_id"]}
        return lambda pid, payload: pid in ids
    if "key" not in c:
        return _filter(c, depth + 1, pid_parser)
    key = c["key"]
    if not isinstance(key, str) or not key or any(not part for part in key.split(".")):
        raise Invalid("'key' must be a dotted path such as \"a.b\"")
    path = key.split(".")
    rest = set(c) - {"key"}
    if rest == {"match"}:
        test = _match(c["match"])
    elif rest == {"range"}:
        test = _range(c["range"])
    else:
        raise Invalid("a key condition needs exactly one of 'match' or 'range'")

    def cond(pid, payload) -> bool:
        return any(test(v) for v in _values(payload, path))
    return cond


def _scalar(v: Any) -> bool:
    return isinstance(v, (str, bool)) or (is_number(v) and math.isfinite(v))


def _same(a: Any, b: Any) -> bool:
    """Equality for match: numbers by value, never a boolean against a number."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if is_number(a):
        return is_number(b) and a == b
    return isinstance(b, str) and a == b


def _key(v: Any) -> tuple:
    """Hash key with ``_same`` semantics: 1 and 1.0 share a key, True and 1 do not."""
    if isinstance(v, bool):
        return ("b", v)
    return ("n", v) if is_number(v) else ("s", v)


def _match(m: Any) -> Callable[[Any], bool]:
    if not isinstance(m, dict) or len(m) != 1 or not ({"value", "any"} & set(m)):
        raise Invalid("'match' must be {\"value\": v} or {\"any\": [v, ...]}")
    if "value" in m:
        want = m["value"]
        if not _scalar(want):
            raise Invalid("'match.value' must be a string, number or boolean")
        return lambda v: _same(want, v)
    options = m["any"]
    if not isinstance(options, list) or not all(_scalar(o) for o in options):
        raise Invalid("'match.any' must be an array of strings, numbers or booleans")
    keys = {_key(o) for o in options}            # a set: cost per point does not grow with the list
    return lambda v: _scalar(v) and _key(v) in keys


def _range(r: Any) -> Callable[[Any], bool]:
    if not isinstance(r, dict) or not r or set(r) - set(RANGE_OPS):
        raise Invalid("'range' must have one or more of gt, gte, lt, lte")
    for op, bound in r.items():
        if not is_number(bound) or not math.isfinite(bound):
            raise Invalid(f"'range.{op}' must be a number")
    gt, gte, lt, lte = (r.get(op) for op in RANGE_OPS)

    def test(v) -> bool:
        if not is_number(v):
            return False
        return ((gt is None or v > gt) and (gte is None or v >= gte)
                and (lt is None or v < lt) and (lte is None or v <= lte))
    return test


def _values(payload: Any, path: list[str]) -> list:
    """The values at ``path``; arrays (at the end or on the way) contribute each element."""
    current = [payload]
    for part in path:
        nxt = []
        for node in current:
            if isinstance(node, dict):
                v = node.get(part, _MISSING)
                if v is not _MISSING:
                    nxt.append(v)
            elif isinstance(node, list):
                nxt.extend(e[part] for e in node if isinstance(e, dict) and part in e)
        current = nxt
    out = []
    for v in current:
        if isinstance(v, list):
            out.extend(v)
        elif v is not None:
            out.append(v)
    return out
