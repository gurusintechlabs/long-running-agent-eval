"""Validation of client input for collections: names, ids, vectors, payloads and point batches.

Every function raises ``Invalid`` (a ``ValueError``) with a client-facing message; the HTTP layer
turns it into a 400. A batch is validated as a whole before anything is written.
"""
from __future__ import annotations

import json
import math
import re
import uuid
from typing import Any

import numpy as np

NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
UUID_RE = re.compile(r"[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
METRICS = ("l2", "cosine", "dot")
MAX_DIM = 4096
MAX_ID = 2 ** 63
MAX_PAYLOAD_BYTES = 65_536
MAX_BATCH = 1000
MAX_TEXT = 8192
EMBED_DIM = 96               # the shared embedding service's vectors (ENVIRONMENT.md)


class Invalid(ValueError):
    pass


def valid_name(name: Any) -> bool:
    return isinstance(name, str) and NAME_RE.fullmatch(name) is not None


def is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def parse_id(v: Any) -> int | str:
    """A point id from JSON (CR-2): a non-negative integer below 2^63, or a UUID string (any case, with
    or without hyphens), returned in canonical form (lowercase, hyphenated)."""
    if isinstance(v, str):
        if UUID_RE.fullmatch(v) is None:
            raise Invalid("a string point id must be a UUID")
        return str(uuid.UUID(v))
    if not is_int(v) or not 0 <= v < MAX_ID:
        raise Invalid("a point id must be a non-negative integer below 2^63 or a UUID")
    return v


def parse_path_id(text: str) -> int | str:
    """A point id from a URL path segment: digits are an integer, anything else must be a UUID."""
    if text.isascii() and text.isdigit() and len(text) <= 19:     # longer digit strings can only be UUIDs
        return parse_id(int(text))
    return parse_id(text)


def id_key(pid: Any) -> tuple:
    """Sort key of an id: integers first (by value), then UUIDs (by canonical string)."""
    return (1, pid) if isinstance(pid, str) else (0, pid)


def parse_collection_spec(body: dict) -> tuple[int, str]:
    dim, metric = body.get("dim"), body.get("metric", "l2")
    if not is_int(dim) or not 1 <= dim <= MAX_DIM:
        raise Invalid(f"'dim' must be an integer from 1 to {MAX_DIM}")
    if metric not in METRICS:
        raise Invalid("'metric' must be one of l2, cosine, dot")
    return dim, metric


def parse_embedding(body: dict, dim: int) -> str | None:
    """``"embedding": "service"`` makes a text collection (stage 6); its vectors come from the service."""
    emb = body.get("embedding")
    if emb is None:
        return None
    if emb != "service":
        raise Invalid("'embedding' must be \"service\" (or absent)")
    if dim != EMBED_DIM:
        raise Invalid(f"a text collection must have dim {EMBED_DIM} (the embedding service's dimension)")
    return emb


def parse_text(v: Any, what: str = "text") -> str:
    if not isinstance(v, str) or not v or len(v) > MAX_TEXT:
        raise Invalid(f"'{what}' must be a non-empty string of at most {MAX_TEXT} characters")
    return v


def parse_text_points(body: dict) -> tuple[list, list[str], list]:
    """``(ids, texts, payloads)`` of a text upsert, validated as a whole (as ``parse_points``)."""
    pts = body.get("points")
    if not isinstance(pts, list):
        raise Invalid("'points' must be an array")
    if len(pts) > MAX_BATCH:
        raise Invalid(f"at most {MAX_BATCH} points per request")
    ids, texts, payloads, seen = [], [], [], set()
    for i, p in enumerate(pts):
        if not isinstance(p, dict):
            raise Invalid(f"points[{i}] must be an object")
        if "id" not in p or "text" not in p:
            raise Invalid(f"points[{i}] needs 'id' and 'text'")
        try:
            pid = parse_id(p["id"])
            texts.append(parse_text(p["text"]))
            payloads.append(parse_payload(p.get("payload")))
        except Invalid as e:
            raise Invalid(f"points[{i}]: {e}") from None
        if pid in seen:
            raise Invalid(f"points[{i}]: duplicate id in the request")
        seen.add(pid)
        ids.append(pid)
    return ids, texts, payloads


def parse_vector(v: Any, dim: int, metric: str, what: str = "vector") -> np.ndarray:
    """A float32 vector of length ``dim``: finite after rounding, and not zero for cosine."""
    if not isinstance(v, list) or len(v) != dim:
        raise Invalid(f"'{what}' must be an array of {dim} numbers")
    if not all(is_number(x) for x in v):
        raise Invalid(f"'{what}' must contain numbers only")
    try:
        with np.errstate(over="ignore"):
            arr = np.array(v, dtype=np.float32)
    except OverflowError:
        raise Invalid(f"'{what}' contains a number out of range") from None
    if not np.isfinite(arr).all():
        raise Invalid(f"'{what}' contains a non-finite number (or one out of float32 range)")
    if metric == "cosine" and not arr.any():
        raise Invalid(f"'{what}' is a zero vector, which has no cosine")
    return arr


def parse_query_vector(v: Any, dim: int, metric: str) -> np.ndarray:
    """A query vector, kept at full (float64) precision."""
    if not isinstance(v, list) or len(v) != dim or not all(is_number(x) for x in v):
        raise Invalid(f"'vector' must be an array of {dim} numbers")
    if not all(math.isfinite(x) for x in v):
        raise Invalid("'vector' contains a non-finite number")
    arr = np.array(v, dtype=np.float64)
    if metric == "cosine" and not arr.any():
        raise Invalid("'vector' is a zero vector, which has no cosine")
    return arr


def parse_payload(p: Any) -> dict | None:
    if p is None:
        return None
    if not isinstance(p, dict):
        raise Invalid("'payload' must be a JSON object or null")
    if len(json.dumps(p, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise Invalid(f"'payload' is larger than {MAX_PAYLOAD_BYTES} bytes")
    return p


def parse_points(body: dict, dim: int, metric: str) -> tuple[list, np.ndarray, list]:
    """``(ids, vectors [n, dim] float32, payloads)`` of an upsert request."""
    pts = body.get("points")
    if not isinstance(pts, list):
        raise Invalid("'points' must be an array")
    if len(pts) > MAX_BATCH:
        raise Invalid(f"at most {MAX_BATCH} points per request")
    ids, vecs, payloads, seen = [], np.zeros((len(pts), dim), np.float32), [], set()
    for i, p in enumerate(pts):
        if not isinstance(p, dict):
            raise Invalid(f"points[{i}] must be an object")
        if "id" not in p or "vector" not in p:
            raise Invalid(f"points[{i}] needs 'id' and 'vector'")
        try:
            pid = parse_id(p["id"])
            vecs[i] = parse_vector(p["vector"], dim, metric)
            payloads.append(parse_payload(p.get("payload")))
        except Invalid as e:
            raise Invalid(f"points[{i}]: {e}") from None
        if pid in seen:
            raise Invalid(f"points[{i}]: duplicate id in the request")
        seen.add(pid)
        ids.append(pid)
    return ids, vecs, payloads


def parse_ids(v: Any) -> list:
    if not isinstance(v, list):
        raise Invalid("'ids' must be an array")
    return [parse_id(x) for x in v]


def parse_int(body: dict, field: str, default: int, lo: int, hi: int) -> int:
    v = body.get(field, default)
    if v is None:
        v = default
    if not is_int(v) or not lo <= v <= hi:
        raise Invalid(f"'{field}' must be an integer from {lo} to {hi}")
    return v


def parse_bool(body: dict, field: str, default: bool = False) -> bool:
    v = body.get(field, default)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise Invalid(f"'{field}' must be true or false")
    return v
