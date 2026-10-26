"""Vector indexes of a collection: their configuration objects, search parameters and construction.

* ``{"type": "flat"}``: exact search, no index structure;
* ``{"type": "hnsw", "m": 16, "ef_construction": 200}``: GLASS-style graph (``hnsw.py``);
* ``{"type": "ivf_flat", "nlist": 256}`` and ``{"type": "ivf_pq", "nlist": 256, "m": 16, "nbits": 8}``:
  Vearch-style inverted files (``ivf.py``);
* ``{"type": "qsg", "degree": 32, "m": 16}``: QSG-NGT-style quantised graph (``qsg.py``).

IVF and ``qsg`` indexes are trained: on the current points when the index is set, or, for a
collection with too few points (``train_min``), as soon as it has enough; searches are exact until
then.
"""
from __future__ import annotations

from typing import Any

from minidb.collection.points import Invalid, is_int

FLAT = {"type": "flat"}
DEFAULT_EF, MAX_EF = 64, 2000
# parameter: (lowest, highest, default)
LIMITS = {
    "hnsw": {"m": (4, 64, 16), "ef_construction": (16, 1000, 200)},
    "ivf_flat": {"nlist": (1, 4096, 256)},
    "ivf_pq": {"nlist": (1, 4096, 256), "m": (1, 4096, 16), "nbits": (4, 8, 8)},
    "qsg": {"degree": (8, 128, 32), "m": (1, 4096, 16)},
}
HNSW_LIMITS = LIMITS["hnsw"]
TYPES = ("flat", *LIMITS)


def parse_index(obj: Any, dim: int | None = None) -> dict:
    """A validated, normalised index object (defaults filled in). ``dim``: the collection's dimension
    (product quantisers need ``m`` to divide it)."""
    if not isinstance(obj, dict):
        raise Invalid("an index must be an object such as {\"type\": \"hnsw\"}")
    kind = obj.get("type")
    if kind == "flat":
        if set(obj) != {"type"}:
            raise Invalid("a flat index takes no parameters")
        return dict(FLAT)
    if kind not in LIMITS:
        raise Invalid(f"'type' must be one of {', '.join(TYPES)}")
    limits = LIMITS[kind]
    unknown = set(obj) - {"type", *limits}
    if unknown:
        raise Invalid(f"unknown {kind} parameter {min(unknown)!r}")
    out = {"type": kind}
    for key, (lo, hi, default) in limits.items():
        v = obj.get(key, default)
        if not is_int(v) or not lo <= v <= hi:
            raise Invalid(f"'{key}' must be an integer from {lo} to {hi}")
        out[key] = v
    if "m" in out and kind != "hnsw" and dim is not None and dim % out["m"]:
        raise Invalid(f"'m' ({out['m']}) must divide the collection's dimension ({dim})")
    return out


def parse_params(params: Any, cfg: dict) -> dict:
    """Search parameters: ``ef`` (graphs; 1 to 2,000, default 64) and ``nprobe`` (IVF; 1 to ``nlist``,
    default 16 or ``nlist`` if smaller). Both are validated whatever the index; each index uses its own."""
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise Invalid("'params' must be an object")
    out = {"ef": _int(params, "ef", DEFAULT_EF, 1, MAX_EF)}
    nlist = cfg.get("nlist")
    hi = nlist if nlist is not None else 4096
    out["nprobe"] = _int(params, "nprobe", min(16, hi), 1, hi)
    return out


def _int(body: dict, field: str, default: int, lo: int, hi: int) -> int:
    v = body.get(field, default)
    if v is None:
        v = default
    if not is_int(v) or not lo <= v <= hi:
        raise Invalid(f"'{field}' must be an integer from {lo} to {hi}")
    return v


def build(cfg: dict, dim: int, metric: str):
    """An empty index structure for ``cfg`` (None for flat)."""
    kind = cfg["type"]
    if kind == "flat":
        return None
    if kind == "hnsw":
        from minidb.index.hnsw import HNSWIndex
        return HNSWIndex(dim, metric, m=cfg["m"], ef_construction=cfg["ef_construction"])
    if kind in ("ivf_flat", "ivf_pq"):
        from minidb.index.ivf import IVFIndex
        return IVFIndex(cfg, dim, metric)
    from minidb.index.qsg import QSGIndex
    return QSGIndex(cfg, dim, metric)
