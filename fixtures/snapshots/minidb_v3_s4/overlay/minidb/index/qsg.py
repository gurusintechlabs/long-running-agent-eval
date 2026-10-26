"""A QSG-NGT-style quantised graph (``qsg``): an ONNG-style proximity graph traversed on PQ codes,
with exact refinement.

Training, over the points present when the index is set:

1. coarse regions: k-means with about ``2 sqrt(n)`` centroids (from 16 to 1,024);
2. codes: every point is stored as its region plus ``m`` PQ bytes of its residual (``pq.py``); the
   graph search only ever touches these codes, never the vectors;
3. graph: a k-nearest-neighbour graph (``2 * degree`` exact neighbours per point, searched among the
   points of its ``KNN_PROBE`` nearest regions), made bidirectional (every reverse edge becomes a
   candidate, which raises the in-degree of hub-starved points), then path-pruned: an edge
   ``p -> c`` is dropped when a kept, closer neighbour ``b`` of ``p`` is nearer to ``c`` than ``p``
   is (a shorter two-hop path exists). Each point keeps at most ``degree`` edges, filled up with the
   nearest pruned ones.

A search starts at the representatives of the regions nearest to the query (plus one entry for every
part of the graph the representatives cannot reach), runs a beam search of
width ``ef`` on the quantised distances, and returns the best ``REFINE * ef`` points it evaluated;
the collection re-scores them exactly. Points added after training are linked by a graph search of
their own (on the codes; forward links chosen on exact vectors, reverse links on decoded ones),
without retraining. Deleted points stay in
the graph as waypoints.
"""
from __future__ import annotations

import heapq
import json
import math
from pathlib import Path

import numpy as np

from minidb.index.base import Hits, transform
from minidb.index.kmeans import kmeans, nearest, sample
from minidb.index.pq import ResidualPQ

TRAIN_MIN = 1000
KNN_PROBE = 8
ENTRY_SEEDS = 8
REFINE = 4
ADD_EF = 64


class QSGIndex:
    kind = "qsg"

    def __init__(self, cfg: dict, dim: int, metric: str, seed: int = 0) -> None:
        self.cfg = dict(cfg)
        self.dim, self.metric, self.degree = dim, metric, cfg["degree"]
        self.inner = metric == "dot"
        self.pq = ResidualPQ(dim, cfg["m"], 8, self.inner)
        self.rng = np.random.default_rng(seed)
        self.trained = False
        self.centroids = np.zeros((0, dim), np.float32)
        self.entries = np.zeros(0, np.int64)
        self.cap = 0
        self.region = np.zeros(0, np.int32)          # -1: not in the graph
        self.codes = np.zeros((0, self.pq.m), np.uint8)
        self.extra = np.zeros(0, np.float32)
        self.adj = np.zeros((0, self.degree), np.int32)
        self.dead = np.zeros(0, bool)
        self.fetch = None            # set by the collection: raw vectors of slots, for linking new points

    train_min = TRAIN_MIN

    def default_params(self) -> dict:
        return {}

    def _grow(self, need: int) -> None:
        if need <= self.cap:
            return
        cap = max(need, 2 * self.cap, 1024)

        def grown(a, shape, fill):
            b = np.full(shape, fill, a.dtype)
            b[: len(a)] = a
            return b
        self.region = grown(self.region, (cap,), -1)
        self.codes = grown(self.codes, (cap, self.pq.m), 0)
        self.extra = grown(self.extra, (cap,), 0)
        self.adj = grown(self.adj, (cap, self.degree), -1)
        self.dead = grown(self.dead, (cap,), False)
        self.cap = cap

    # ------------------------------------------------------------ training

    def train(self, slots: np.ndarray, fetch) -> None:
        slots = np.asarray(slots, np.int64)
        x = transform(fetch(slots), self.metric)
        n = len(x)
        nl = min(n, max(16, min(1024, int(2 * math.sqrt(n)))))
        self.centroids = kmeans(x[sample(n, nl, self.rng)], nl, iters=8, seed=int(self.rng.integers(1 << 30)))
        reg = nearest(x, self.centroids)
        self.pq.train(x - self.centroids[reg], self.rng)
        self._grow(int(slots.max()) + 1)
        self.region[slots] = reg
        self.dead[slots] = False
        for i in range(0, n, 8192):
            part = slice(i, i + 8192)
            c = self.centroids[reg[part]]
            self.codes[slots[part]], self.extra[slots[part]] = self.pq.encode(x[part] - c, c)
        local = self._build_graph(x, reg)
        self.adj[slots] = np.where(local >= 0, slots[np.maximum(local, 0)], -1)
        order = np.argsort(reg, kind="stable")
        bounds = np.searchsorted(reg[order], np.arange(nl + 1))
        entries = []
        for r in range(nl):
            mem = order[bounds[r]:bounds[r + 1]]
            if len(mem):
                d = x[mem] - self.centroids[r]
                entries.append(slots[mem[int(np.argmin(np.einsum("ij,ij->i", d, d)))]])
        self.entries = self._cover(np.array(entries, np.int64), slots)
        self.trained = True

    def _cover(self, entries: np.ndarray, slots: np.ndarray) -> np.ndarray:
        """``entries`` plus one entry per part of the graph they cannot reach (well-separated clusters
        give a k-NN graph without edges between them)."""
        member = np.zeros(self.cap, bool)
        member[slots] = True
        reached = np.zeros(self.cap, bool)
        out = list(entries.tolist())
        frontier = entries
        while True:
            while len(frontier):
                reached[frontier] = True
                nb = self.adj[frontier].ravel()
                nb = nb[nb >= 0]
                frontier = np.unique(nb[~reached[nb]])
            left = np.flatnonzero(member & ~reached)
            if not len(left):
                return np.array(out, np.int64)
            out.append(int(left[0]))
            frontier = left[:1]

    def _build_graph(self, x: np.ndarray, reg: np.ndarray) -> np.ndarray:
        """Adjacency [n, degree] over local indices (-1: no edge)."""
        n, deg = len(x), self.degree
        kk = 2 * deg
        sq = np.einsum("ij,ij->i", x, x)
        nl = len(self.centroids)
        order = np.argsort(reg, kind="stable")
        bounds = np.searchsorted(reg[order], np.arange(nl + 1))
        near = nearest(self.centroids, self.centroids, min(nl, KNN_PROBE))
        knn = np.full((n, kk), -1, np.int64)
        for r in range(nl):
            mem = order[bounds[r]:bounds[r + 1]]
            if not len(mem):
                continue
            others = [int(o) for o in near[r] if o != r] if near.ndim == 2 else []
            pool = np.concatenate([mem] + [order[bounds[o]:bounds[o + 1]] for o in others])
            d = sq[mem][:, None] - 2.0 * (x[mem] @ x[pool].T) + sq[pool][None, :]
            d[np.arange(len(mem)), np.arange(len(mem))] = np.inf          # pool starts with mem
            c = min(kk, len(pool) - 1)
            if c <= 0:
                continue
            part = np.argpartition(d, c - 1, axis=1)[:, :c]
            o = np.argsort(np.take_along_axis(d, part, 1), axis=1)
            knn[mem, :c] = pool[np.take_along_axis(part, o, 1)]
        rev: list[list[int]] = [[] for _ in range(n)]
        for i, row in enumerate(knn[:, :deg].tolist()):
            for j in row:
                if j >= 0:
                    rev[j].append(i)
        adj = np.full((n, deg), -1, np.int64)
        for i in range(n):
            cand = np.concatenate([knn[i], np.asarray(rev[i], np.int64)])
            cand = np.unique(cand[(cand >= 0) & (cand != i)])
            if not len(cand):
                continue
            sel = self._prune(x[i], x[cand], cand)
            adj[i, :len(sel)] = sel
        return adj

    def _prune(self, p: np.ndarray, cv: np.ndarray, cand: np.ndarray) -> np.ndarray:
        """Path pruning: the kept candidates (closest first), at most ``degree``."""
        dq = np.einsum("ij,ij->i", cv - p, cv - p)
        o = np.argsort(dq, kind="stable")
        cand, cv, dq = cand[o], cv[o], dq[o]
        csq = np.einsum("ij,ij->i", cv, cv)
        pair = csq[:, None] - 2.0 * (cv @ cv.T) + csq[None, :]
        keep: list[int] = []
        pruned: list[int] = []
        for t in range(len(cand)):
            if keep and (pair[t, keep] < dq[t]).any():
                pruned.append(t)
                continue
            keep.append(t)
            if len(keep) >= self.degree:
                break
        keep += pruned[: self.degree - len(keep)]
        return cand[keep]

    # ------------------------------------------------------------ incremental adds

    def _decoded(self, slots: np.ndarray) -> np.ndarray:
        return self.centroids[self.region[slots]] + self.pq.decode(self.codes[slots])

    def add(self, slots: np.ndarray, vectors: np.ndarray) -> None:
        if not self.trained or not len(slots):
            return
        slots = np.asarray(slots, np.int64)
        self._grow(int(slots.max()) + 1)
        x = transform(vectors, self.metric)
        reg = nearest(x, self.centroids)
        c = self.centroids[reg]
        codes, extra = self.pq.encode(x - c, c)
        for p, xp, r, cd, ex in zip(slots.tolist(), x, reg.tolist(), codes, extra.tolist(), strict=True):
            pool = self._beam(xp, ADD_EF, None)
            self.region[p], self.codes[p], self.extra[p], self.dead[p] = r, cd, ex, False
            if not len(pool):
                continue
            cand = pool[: 2 * self.degree]
            cv = transform(self.fetch(cand), self.metric) if self.fetch is not None else self._decoded(cand)
            sel = self._prune(xp, cv, cand)
            self.adj[p] = -1
            self.adj[p, :len(sel)] = sel
            for nb in sel.tolist():
                row = self.adj[nb]
                free = np.flatnonzero(row < 0)
                if len(free):
                    row[free[0]] = p
                    continue
                centre = self._decoded(np.array([nb]))[0]
                v = self._decoded(np.concatenate([row.astype(np.int64), [p]])) - centre
                d = np.einsum("ij,ij->i", v, v)
                j = int(np.argmax(d[:-1]))
                if d[-1] < d[j]:
                    row[j] = p

    def mark_dead(self, slot: int) -> None:
        if slot < self.cap:
            self.dead[slot] = True

    # ------------------------------------------------------------ search

    def _beam(self, x: np.ndarray, ef: int, ok: np.ndarray | None, pool_size: int | None = None) -> np.ndarray:
        """Evaluated nodes (accepted by ``ok``) by quantised distance, best first; at most
        ``pool_size`` (default ``2 * ef``)."""
        if not len(self.entries):
            return np.zeros(0, np.int64)
        t1, lut = self.pq.tables(x, self.centroids)
        pq, region, codes, extra, adj = self.pq, self.region, self.codes, self.extra, self.adj

        def dist(ix):
            return pq.distances(t1[region[ix]], lut, codes[ix], extra[ix])
        visited = np.zeros(self.cap, bool)
        de = dist(self.entries)
        seeds = self.entries[np.argsort(de)[:ENTRY_SEEDS]]
        sd = dist(seeds)
        visited[seeds] = True
        cand = list(zip(sd.tolist(), seeds.tolist(), strict=True))
        heapq.heapify(cand)
        beam = [(-d, v) for d, v in cand]
        heapq.heapify(beam)
        while len(beam) > ef:
            heapq.heappop(beam)
        ev_n, ev_d = [seeds], [sd]
        while cand:
            d, c = heapq.heappop(cand)
            if len(beam) >= ef and d > -beam[0][0]:
                break
            nb = adj[c]
            nb = nb[nb >= 0]
            nb = nb[~visited[nb]]
            if not len(nb):
                continue
            visited[nb] = True
            dd = dist(nb)
            ev_n.append(nb)
            ev_d.append(dd)
            bound = -beam[0][0] if len(beam) >= ef else math.inf
            for dv, v in zip(dd.tolist(), nb.tolist(), strict=True):
                if dv < bound or len(beam) < ef:
                    heapq.heappush(cand, (dv, v))
                    heapq.heappush(beam, (-dv, v))
                    if len(beam) > ef:
                        heapq.heappop(beam)
                    if len(beam) >= ef:
                        bound = -beam[0][0]
        nodes, ds = np.concatenate(ev_n).astype(np.int64), np.concatenate(ev_d)
        if ok is not None:
            inside = nodes < len(ok)
            keep = inside.copy()
            keep[inside] = ok[nodes[inside]]
            nodes, ds = nodes[keep], ds[keep]
        size = min(len(nodes), pool_size or 2 * ef)
        if size < len(nodes):
            part = np.argpartition(ds, size - 1)[:size]
            nodes, ds = nodes[part], ds[part]
        return nodes[np.argsort(ds, kind="stable")]

    def search(self, q: np.ndarray, k: int, params: dict, allowed: np.ndarray | None) -> Hits:
        ef = max(params.get("ef") or 64, k)
        x = transform(np.asarray(q, np.float32)[None, :], self.metric)[0]
        ok = ~self.dead[: self.cap]
        if allowed is not None:
            ok = ok.copy()
            n = min(len(allowed), self.cap)
            ok[:n] &= allowed[:n]
            ok[n:] = False
        slots = self._beam(x, ef, ok, REFINE * ef)
        return Hits(slots, len(slots), {})

    # ------------------------------------------------------------ persistence

    def save(self, path: Path, stamp: dict) -> None:
        n = self.cap
        st = {"trained": np.array(self.trained), "centroids": self.centroids, "entries": self.entries,
              "region": self.region[:n], "codes": self.codes[:n], "extra": self.extra[:n], "adj": self.adj[:n],
              "dead": self.dead[:n], "stamp": np.array(json.dumps(stamp, sort_keys=True)), **self.pq.state("pq_")}
        tmp = path.with_name(path.name + ".tmp.npz")
        np.savez(tmp, **st)
        tmp.replace(path)

    def load(self, path: Path, stamp: dict, fetch, live: np.ndarray) -> bool:
        try:
            st = np.load(path, allow_pickle=False)
            if str(st["stamp"]) != json.dumps(stamp, sort_keys=True):
                return False
            trained = bool(st["trained"])
            if trained:
                region, codes, extra, adj, dead = st["region"], st["codes"], st["extra"], st["adj"], st["dead"]
                self.pq.load(st, "pq_")
                self.centroids, self.entries = st["centroids"].astype(np.float32), st["entries"].astype(np.int64)
        except (OSError, ValueError, KeyError):
            return False
        self.trained = trained
        if trained:
            n = len(region)
            self._grow(n)
            self.region[:n], self.codes[:n], self.extra[:n], self.adj[:n], self.dead[:n] = region, codes, extra, adj, dead
        return True
