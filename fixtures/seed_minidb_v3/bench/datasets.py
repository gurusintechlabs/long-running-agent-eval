"""Deterministic benchmark datasets: clustered Gaussian vectors, float32, with exact ground truth.

Data is generated from a fixed seed and cached in ``.bench-cache/`` at the repository root (not under
``bench/``, which must stay unchanged). Ids are ``0 .. n-1`` in generation order.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np

SIZES = {"small": 20_000, "medium": 100_000, "full": 200_000}
DIM = 96
CLUSTERS = 64
QUERIES = 500
VISIBLE_SEED = 20261019
ROOT = Path(__file__).resolve().parent.parent


def cache_dir() -> Path:
    return Path(os.environ.get("MINIDB_BENCH_CACHE", ROOT / ".bench-cache"))


def generate(n: int, *, seed: int, dim: int = DIM, queries: int = QUERIES) -> tuple[np.ndarray, np.ndarray]:
    """``(base [n, dim], queries [queries, dim])``: points around ``CLUSTERS`` random centres."""
    rng = np.random.default_rng(seed)
    centres = rng.normal(0.0, 1.0, (CLUSTERS, dim)).astype(np.float32)
    spread = rng.uniform(0.15, 0.45, CLUSTERS).astype(np.float32)
    which = rng.integers(0, CLUSTERS, n + queries)
    pts = centres[which] + rng.normal(0.0, 1.0, (n + queries, dim)).astype(np.float32) * spread[which, None]
    return pts[:n].astype(np.float32), pts[n:].astype(np.float32)


def ground_truth(base: np.ndarray, queries: np.ndarray, k: int = 10, metric: str = "l2") -> np.ndarray:
    """Exact top-``k`` ids per query (ties broken by id)."""
    out = np.empty((len(queries), k), dtype=np.int64)
    if metric == "l2":
        bn = (base * base).sum(1)
    elif metric == "cosine":
        base = base / np.linalg.norm(base, axis=1, keepdims=True)
    for i in range(0, len(queries), 64):
        q = queries[i:i + 64]
        if metric == "l2":
            d = bn[None, :] - 2.0 * (q @ base.T)          # |q|^2 is constant per row
        elif metric == "cosine":
            d = -((q / np.linalg.norm(q, axis=1, keepdims=True)) @ base.T)
        else:  # dot: larger is better
            d = -(q @ base.T)
        part = np.argpartition(d, k, axis=1)[:, :k]
        for j, row in enumerate(part):
            out[i + j] = row[np.lexsort((row, d[j, row]))]
    return out


def load(size: str = "small", *, seed: int = VISIBLE_SEED, metric: str = "l2"):
    """``(base, queries, ground_truth)`` for a named size, generated once and cached."""
    n = SIZES[size]
    key = hashlib.sha256(f"{n}-{seed}-{DIM}-{QUERIES}-{CLUSTERS}-{metric}-v1".encode()).hexdigest()[:16]
    path = cache_dir() / f"{size}-{key}.npz"
    if path.exists():
        z = np.load(path)
        return z["base"], z["queries"], z["gt"]
    base, queries = generate(n, seed=seed)
    gt = ground_truth(base, queries, metric=metric)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.npz")
    np.savez(tmp, base=base, queries=queries, gt=gt)
    tmp.replace(path)
    return base, queries, gt
