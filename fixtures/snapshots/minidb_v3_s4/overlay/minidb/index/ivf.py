"""Vearch-style inverted-file indexes: ``ivf_flat`` and ``ivf_pq``.

Training (k-means over a sample of the collection) yields ``nlist`` centroids; every point joins the
list of its nearest centroid. A search probes the ``nprobe`` lists whose centroids are nearest to the
query:

* ``ivf_flat`` keeps the vectors of its lists and scores the probed points exactly;
* ``ivf_pq`` keeps only product-quantisation codes of the residuals (``m`` bytes a point, see
  ``pq.py``), ranks the probed points on the codes and hands the best ``refine`` of them to the
  collection, which scores them exactly.

Points added after training join their nearest list without retraining. Deleted points stay in
their list and are skipped.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from minidb.index.base import Hits, transform
from minidb.index.kmeans import kmeans, nearest, sample
from minidb.index.pq import ResidualPQ

TRAIN_MIN = 1000


def refine_size(k: int) -> int:
    """How many ``ivf_pq`` candidates are scored exactly."""
    return max(200, 10 * k)


class IVFIndex:
    def __init__(self, cfg: dict, dim: int, metric: str, seed: int = 0) -> None:
        self.kind = cfg["type"]
        self.cfg = dict(cfg)
        self.dim, self.metric, self.nlist = dim, metric, cfg["nlist"]
        self.inner = metric == "dot"
        self.pq = ResidualPQ(dim, cfg["m"], cfg["nbits"], self.inner) if self.kind == "ivf_pq" else None
        self.rng = np.random.default_rng(seed)
        self.trained = False
        self.centroids = np.zeros((0, dim), np.float32)
        self.cap = 0
        self.assign = np.zeros(0, np.int32)          # list of each slot, -1: not indexed
        self.dead = np.zeros(0, bool)
        self.raw = np.zeros((0, dim), np.float32)     # ivf_flat: the (transformed) vectors
        self.codes = np.zeros((0, cfg.get("m", 1)), np.uint8)
        self.extra = np.zeros(0, np.float32)
        self.lists: list[np.ndarray] = []

    @property
    def train_min(self) -> int:
        return max(TRAIN_MIN, self.nlist)

    def default_params(self) -> dict:
        return {"nprobe": min(16, self.nlist)}

    # ------------------------------------------------------------ building

    def _grow(self, need: int) -> None:
        if need <= self.cap:
            return
        cap = max(need, 2 * self.cap, 1024)

        def grown(a, shape, fill):
            b = np.full(shape, fill, a.dtype)
            b[: len(a)] = a
            return b
        self.assign = grown(self.assign, (cap,), -1)
        self.dead = grown(self.dead, (cap,), False)
        if self.pq is None:
            self.raw = grown(self.raw, (cap, self.dim), 0)
        else:
            self.codes = grown(self.codes, (cap, self.pq.m), 0)
            self.extra = grown(self.extra, (cap,), 0)
        self.cap = cap

    def train(self, slots: np.ndarray, fetch) -> None:
        """Train on the points in ``slots`` (``fetch(slots)``: their raw vectors), then add them all."""
        pick = slots[sample(len(slots), self.nlist, self.rng)]
        x = transform(fetch(pick), self.metric)
        self.centroids = kmeans(x, self.nlist, seed=int(self.rng.integers(1 << 30)))
        if self.pq is not None:
            self.pq.train(x - self.centroids[nearest(x, self.centroids)], self.rng)
        self.lists = [np.zeros(0, np.int64) for _ in range(self.nlist)]
        self.trained = True
        for i in range(0, len(slots), 8192):
            part = slots[i:i + 8192]
            self.add(part, fetch(part))

    def add(self, slots: np.ndarray, vectors: np.ndarray) -> None:
        if not self.trained or not len(slots):
            return
        slots = np.asarray(slots, np.int64)
        self._grow(int(slots.max()) + 1)
        x = transform(vectors, self.metric)
        a = nearest(x, self.centroids)
        self.assign[slots] = a
        self.dead[slots] = False
        if self.pq is None:
            self.raw[slots] = x
        else:
            self.codes[slots], self.extra[slots] = self.pq.encode(x - self.centroids[a], self.centroids[a])
        order = np.argsort(a, kind="stable")
        bounds = np.searchsorted(a[order], np.arange(self.nlist + 1))
        for lst in np.flatnonzero(np.diff(bounds)):
            self.lists[lst] = np.concatenate([self.lists[lst], slots[order[bounds[lst]:bounds[lst + 1]]]])

    def mark_dead(self, slot: int) -> None:
        if slot < self.cap:
            self.dead[slot] = True

    # ------------------------------------------------------------ search

    def search(self, q: np.ndarray, k: int, params: dict, allowed: np.ndarray | None) -> Hits:
        nprobe = min(params.get("nprobe") or self.default_params()["nprobe"], self.nlist)
        x = transform(np.asarray(q, np.float32)[None, :], self.metric)[0]
        if self.pq is not None:
            t1, lut = self.pq.tables(x, self.centroids)
        elif self.inner:
            t1 = -(self.centroids @ x)
        else:
            d = self.centroids - x
            t1 = np.einsum("ij,ij->i", d, d)
        probe = np.argpartition(t1, nprobe - 1)[:nprobe] if nprobe < self.nlist else np.arange(self.nlist)
        parts = [self.lists[lst] for lst in probe.tolist() if len(self.lists[lst])]
        slots = np.concatenate(parts) if parts else np.zeros(0, np.int64)
        ok = ~self.dead[slots]
        if allowed is not None:
            inside = slots < len(allowed)
            ok &= inside
            ok[inside] &= allowed[slots[inside]]
        slots = slots[ok]
        info = {"nprobe": int(nprobe)}
        if not len(slots):
            return Hits(slots, 0, info)
        if self.pq is None:
            v = self.raw[slots]
            d = -(v @ x) if self.inner else np.einsum("ij,ij->i", v - x, v - x)
            keep = min(len(slots), 2 * k)
            exact = len(slots)
        else:
            d = self.pq.distances(t1[self.assign[slots]], lut, self.codes[slots], self.extra[slots])
            keep = min(len(slots), refine_size(k))
            exact = keep
        if keep < len(slots):
            slots = slots[np.argpartition(d, keep - 1)[:keep]]
        return Hits(slots, exact, info)

    # ------------------------------------------------------------ persistence

    def save(self, path: Path, stamp: dict) -> None:
        n = self.cap
        st = {"trained": np.array(self.trained), "centroids": self.centroids, "assign": self.assign[:n],
              "dead": self.dead[:n], "stamp": np.array(json.dumps(stamp, sort_keys=True))}
        if self.pq is not None:
            st.update(codes=self.codes[:n], extra=self.extra[:n], **self.pq.state("pq_"))
        tmp = path.with_name(path.name + ".tmp.npz")
        np.savez(tmp, **st)
        tmp.replace(path)

    def load(self, path: Path, stamp: dict, fetch, live: np.ndarray) -> bool:
        try:
            st = np.load(path, allow_pickle=False)
            if str(st["stamp"]) != json.dumps(stamp, sort_keys=True):
                return False
            trained = bool(st["trained"])
            assign, dead = st["assign"], st["dead"]
            codes = extra = None
            if self.pq is not None and trained:
                codes, extra = st["codes"], st["extra"]
                self.pq.load(st, "pq_")
            self.centroids = st["centroids"].astype(np.float32)
        except (OSError, ValueError, KeyError):
            return False
        self.trained = trained
        if not trained:
            return True
        n = len(assign)
        self._grow(n)
        self.assign[:n], self.dead[:n] = assign, dead
        if self.pq is not None:
            self.codes[:n], self.extra[:n] = codes, extra
        else:
            members = np.flatnonzero(self.assign[:n] >= 0)
            for i in range(0, len(members), 8192):
                part = members[i:i + 8192]
                self.raw[part] = transform(fetch(part), self.metric)
        members = np.flatnonzero(self.assign[:n] >= 0)
        a = self.assign[members]
        order = np.argsort(a, kind="stable")
        bounds = np.searchsorted(a[order], np.arange(self.nlist + 1))
        self.lists = [members[order[bounds[i]:bounds[i + 1]]] for i in range(self.nlist)]
        return True
