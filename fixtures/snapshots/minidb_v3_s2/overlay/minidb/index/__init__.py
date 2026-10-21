"""Vector indexes of a collection: their configuration objects and construction.

``{"type": "flat"}`` (exact search, no index structure) or
``{"type": "hnsw", "m": 16, "ef_construction": 200}``.
"""
from __future__ import annotations

from typing import Any

from minidb.collection.points import Invalid, is_int

FLAT = {"type": "flat"}
HNSW_LIMITS = {"m": (4, 64, 16), "ef_construction": (16, 1000, 200)}
DEFAULT_EF, MAX_EF = 64, 2000


def parse_index(obj: Any) -> dict:
    """A validated, normalised index object (defaults filled in)."""
    if not isinstance(obj, dict):
        raise Invalid("an index must be an object such as {\"type\": \"hnsw\"}")
    kind = obj.get("type")
    if kind == "flat":
        if set(obj) != {"type"}:
            raise Invalid("a flat index takes no parameters")
        return dict(FLAT)
    if kind == "hnsw":
        unknown = set(obj) - {"type", *HNSW_LIMITS}
        if unknown:
            raise Invalid(f"unknown hnsw parameter {min(unknown)!r}")
        out = {"type": "hnsw"}
        for key, (lo, hi, default) in HNSW_LIMITS.items():
            v = obj.get(key, default)
            if not is_int(v) or not lo <= v <= hi:
                raise Invalid(f"'{key}' must be an integer from {lo} to {hi}")
            out[key] = v
        return out
    raise Invalid("'type' must be flat or hnsw")


def build(cfg: dict, dim: int, metric: str):
    """An empty index structure for ``cfg`` (None for flat)."""
    if cfg["type"] == "flat":
        return None
    from minidb.index.hnsw import HNSWIndex
    return HNSWIndex(dim, metric, m=cfg["m"], ef_construction=cfg["ef_construction"])
