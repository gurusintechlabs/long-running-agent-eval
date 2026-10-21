"""Product quantisation of residuals: a vector is stored as its coarse centroid ``c`` (an IVF list or a
QSG region) plus ``m`` one-byte codes of the residual ``r = x - c``, one per sub-space of
``dim / m`` dimensions (``2**nbits`` codewords each).

Distances to a query ``q`` need one lookup table per query, whatever the centroid (the "precomputed
tables" form of IVF-PQ):

* squared L2: ``|q - c - r|^2 = |q - c|^2 + (|r|^2 + 2 <c, r>) - 2 <q, r>``. The middle term is a
  per-point constant (``extra``, stored at encode time); the last is a sum of table entries.
* negated inner product: ``-<q, c + r> = -<q, c> - <q, r>``.
"""
from __future__ import annotations

import numpy as np

from minidb.index.kmeans import kmeans, nearest, sample


class ResidualPQ:
    def __init__(self, dim: int, m: int, nbits: int, inner: bool) -> None:
        self.dim, self.m, self.nbits, self.inner = dim, m, nbits, inner
        self.ds = dim // m
        self.ksub = 1 << nbits
        self.books = np.zeros((m, self.ksub, self.ds), np.float32)
        self.offsets = (np.arange(m) * self.ksub).astype(np.int64)

    # ------------------------------------------------------------ training and codes

    def train(self, residuals: np.ndarray, rng: np.random.Generator) -> None:
        r = residuals[sample(len(residuals), self.ksub, rng)]
        k = min(self.ksub, len(r))
        books = np.zeros_like(self.books)
        for j in range(self.m):
            books[j, :k] = kmeans(r[:, j * self.ds:(j + 1) * self.ds], k, iters=10, seed=j)
        self.books = books

    def encode(self, residuals: np.ndarray, centroids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """``(codes [n, m] uint8, extra [n] float32)`` of residuals to ``centroids`` (one row each)."""
        codes = np.empty((len(residuals), self.m), np.uint8)
        for j in range(self.m):
            codes[:, j] = nearest(residuals[:, j * self.ds:(j + 1) * self.ds], self.books[j])
        rec = self.decode(codes)
        extra = np.einsum("ij,ij->i", rec, rec) + 2.0 * np.einsum("ij,ij->i", centroids, rec)
        return codes, extra.astype(np.float32)

    def decode(self, codes: np.ndarray) -> np.ndarray:
        """The quantised residuals of ``codes``."""
        return np.concatenate([self.books[j][codes[:, j]] for j in range(self.m)], axis=1)

    # ------------------------------------------------------------ distances

    def tables(self, q: np.ndarray, centroids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Per-query state: the centroid term per centroid, and the flat table of ``<q_j, codeword>``."""
        q = np.asarray(q, np.float32)
        if self.inner:
            t1 = -(centroids @ q)
        else:
            d = centroids - q
            t1 = np.einsum("ij,ij->i", d, d)
        lut = np.einsum("jkd,jd->jk", self.books, q.reshape(self.m, self.ds)).astype(np.float32).ravel()
        return t1.astype(np.float32), lut

    def distances(self, t1c: np.ndarray, lut: np.ndarray, codes: np.ndarray, extra: np.ndarray) -> np.ndarray:
        """Approximate distances: ``t1c`` is the centroid term of each point's centroid."""
        s = lut[codes.astype(np.int64) + self.offsets].sum(1)
        if self.inner:
            return t1c - s
        return t1c + extra - 2.0 * s

    def state(self, prefix: str) -> dict:
        return {f"{prefix}books": self.books}

    def load(self, st, prefix: str) -> None:
        self.books = st[f"{prefix}books"].astype(np.float32)
