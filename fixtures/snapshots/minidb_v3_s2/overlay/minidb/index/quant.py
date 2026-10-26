"""Scalar quantisation (SQ8): every dimension mapped linearly onto 0..255 (uint8 codes).

Distances to a query are computed on the codes (``distances``), so traversal touches a quarter of the
memory of float32 vectors; exact distances are only computed for the final candidates.
"""
from __future__ import annotations

import numpy as np


class ScalarQuantizer:
    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.lo = np.zeros(dim, np.float32)
        self.scale = np.ones(dim, np.float32)
        self.trained_on = 0

    def train(self, x: np.ndarray) -> None:
        """Ranges from the data (values outside are clipped when encoded later)."""
        self.lo = x.min(0).astype(np.float32)
        hi = x.max(0).astype(np.float32)
        self.scale = np.maximum((hi - self.lo) / 255.0, np.float32(1e-12)).astype(np.float32)
        self.trained_on = len(x)

    def encode(self, x: np.ndarray) -> np.ndarray:
        return np.clip(np.rint((x - self.lo) / self.scale), 0, 255).astype(np.uint8)

    def prepare(self, q: np.ndarray, inner: bool) -> tuple:
        """Per-query state for ``distances``: the query in code space (squared L2), or the weights
        and offset of the inner product."""
        q = np.asarray(q, np.float32)
        if inner:
            return (q * self.scale, float(self.lo @ q))
        return ((q - self.lo) / self.scale,)

    def distances(self, codes: np.ndarray, prep: tuple, inner: bool) -> np.ndarray:
        """Approximate squared L2 distances (or negated inner products) from the query to ``codes``."""
        c = codes.astype(np.float32)
        if inner:
            return -(c @ prep[0] + prep[1])
        diff = (c - prep[0]) * self.scale
        return np.einsum("ij,ij->i", diff, diff)

    def state(self) -> dict:
        return {"lo": self.lo, "scale": self.scale, "trained_on": np.array(self.trained_on)}

    def load(self, st) -> None:
        self.lo, self.scale = st["lo"].astype(np.float32), st["scale"].astype(np.float32)
        self.trained_on = int(st["trained_on"])
