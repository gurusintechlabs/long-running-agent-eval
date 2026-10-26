"""k-means for the coarse quantisers (IVF lists, QSG regions) and the product-quantiser codebooks.

Training runs on a bounded sample (``SAMPLE_PER_CENTROID`` points per centroid), so its cost does not
grow with the collection. Distances are squared L2, computed in chunks with one matrix product each.
"""
from __future__ import annotations

import numpy as np

SAMPLE_PER_CENTROID = 64
CHUNK_FLOATS = 1 << 22


def sample(n: int, k: int, rng: np.random.Generator) -> np.ndarray:
    """Indices of a training sample of at most ``k * SAMPLE_PER_CENTROID`` of ``n`` points."""
    size = min(n, k * SAMPLE_PER_CENTROID)
    return np.sort(rng.choice(n, size, replace=False)) if size < n else np.arange(n)


def nearest(x: np.ndarray, c: np.ndarray, count: int = 1) -> np.ndarray:
    """For every row of ``x``, the index of its nearest centroid (``count`` > 1: the ``count``
    nearest, closest first)."""
    csq = np.einsum("ij,ij->i", c, c)
    rows = max(1, CHUNK_FLOATS // max(1, len(c)))
    out = np.empty((len(x), count), np.int64)
    for i in range(0, len(x), rows):
        d = csq[None, :] - 2.0 * (x[i:i + rows] @ c.T)
        if count == 1:
            out[i:i + rows, 0] = d.argmin(1)
        else:
            part = np.argpartition(d, count - 1, axis=1)[:, :count]
            order = np.argsort(np.take_along_axis(d, part, 1), axis=1)
            out[i:i + rows] = np.take_along_axis(part, order, 1)
    return out[:, 0] if count == 1 else out


def kmeans(x: np.ndarray, k: int, *, iters: int = 12, seed: int = 0) -> np.ndarray:
    """``k`` centroids (float32) of the rows of ``x`` (needs ``len(x) >= k``). Empty clusters are
    re-seeded from random points."""
    x = np.asarray(x, np.float32)
    rng = np.random.default_rng(seed)
    c = x[rng.choice(len(x), k, replace=False)].copy()
    for _ in range(iters):
        a = nearest(x, c)
        sums = np.zeros((k, x.shape[1]), np.float64)
        np.add.at(sums, a, x)
        cnt = np.bincount(a, minlength=k)
        full = cnt > 0
        c[full] = (sums[full] / cnt[full, None]).astype(np.float32)
        if not full.all():
            c[~full] = x[rng.choice(len(x), int((~full).sum()), replace=False)]
    return c
