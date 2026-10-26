"""A GLASS-style HNSW index: a layered proximity graph, searched on SQ8 codes.

Nodes are the collection's slots. Construction works in batches (an upsert request at a time): for
each new node and layer, the candidate neighbours are the exact nearest nodes of that layer (one
matrix product per chunk of new nodes), from which the HNSW heuristic keeps a diverse set of ``m``
(``2 m`` on layer 0). Reverse links keep each node's list diverse and bounded: a new neighbour that an
existing one already covers is skipped, otherwise it replaces the neighbour it covers (or the
farthest). Every link stores its distance, so maintaining links needs one small product.

Search descends greedily through the upper layers, runs a beam search on layer 1 and then on layer
0 (both on SQ8 codes), and returns up to ``ef`` accepted nodes; the caller re-ranks them exactly.
Deleted nodes stay in the graph as waypoints but are never returned.

Graph distance: squared L2 (``l2``; ``cosine`` on normalised vectors) or the negated inner product
(``dot``).
"""
from __future__ import annotations

import heapq
import json
import math
from pathlib import Path

import numpy as np

from minidb.index.quant import ScalarQuantizer

MAX_LEVEL = 15
CHUNK_FLOATS = 1 << 22          # distance-matrix chunk size during construction


class HNSWIndex:
    kind = "hnsw"

    def __init__(self, dim: int, metric: str, m: int = 16, ef_construction: int = 200, seed: int = 0) -> None:
        self.dim, self.metric, self.m, self.efc = dim, metric, m, ef_construction
        self.m0 = 2 * m
        self.ml = 1.0 / math.log(m)
        self.inner = metric == "dot"
        self.rng = np.random.default_rng(seed)
        self.cap = 0
        self.data = np.zeros((0, dim), np.float32)
        self.sq = np.zeros(0, np.float32)
        self.level = np.zeros(0, np.int8)          # -1: not in the graph
        self.nb0 = np.zeros((0, self.m0), np.int32)
        self.nd0 = np.zeros((0, self.m0), np.float32)
        self.cnt0 = np.zeros(0, np.int16)
        self.upper: dict[int, dict[int, tuple[list[int], list[float]]]] = {}
        self.dead = np.zeros(0, bool)
        self.codes = np.zeros((0, dim), np.uint8)
        self.quant = ScalarQuantizer(dim)
        self.entry = -1
        self.top = -1
        self.size = 0                              # nodes ever added

    def config(self) -> dict:
        return {"type": "hnsw", "m": self.m, "ef_construction": self.efc}

    # ------------------------------------------------------------ storage

    def _grow(self, need: int) -> None:
        if need <= self.cap:
            return
        cap = max(need, 2 * self.cap, 1024)

        def grown(a, shape, fill):
            b = np.full(shape, fill, a.dtype)
            b[: len(a)] = a
            return b
        self.data = grown(self.data, (cap, self.dim), 0)
        self.sq = grown(self.sq, (cap,), 0)
        self.level = grown(self.level, (cap,), -1)
        self.nb0 = grown(self.nb0, (cap, self.m0), -1)
        self.nd0 = grown(self.nd0, (cap, self.m0), 0)
        self.cnt0 = grown(self.cnt0, (cap,), 0)
        self.dead = grown(self.dead, (cap,), False)
        self.codes = grown(self.codes, (cap, self.dim), 0)
        self.cap = cap

    def _transform(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, np.float32)
        if self.metric == "cosine":
            norms = np.linalg.norm(x, axis=-1, keepdims=True)
            x = x / np.where(norms == 0, 1, norms)
        return x.astype(np.float32)

    def _set_vectors(self, slots: np.ndarray, vectors: np.ndarray) -> None:
        x = self._transform(vectors)
        self.data[slots] = x
        self.sq[slots] = np.einsum("ij,ij->i", x, x)

    def _retrain_if_needed(self) -> None:
        members = np.flatnonzero(self.level[: self.cap] >= 0)
        if self.quant.trained_on and len(members) < 2 * self.quant.trained_on:
            return
        self.quant.train(self.data[members])
        self.codes[members] = self.quant.encode(self.data[members])

    # ------------------------------------------------------------ distances

    def _gd(self, a: np.ndarray, asq: np.ndarray, b: np.ndarray, bsq: np.ndarray) -> np.ndarray:
        ip = a @ b.T
        if self.inner:
            return -ip
        return asq[:, None] - 2.0 * ip + bsq[None, :]

    def _gd_to(self, p: int, rows: np.ndarray) -> np.ndarray:
        ip = self.data[rows] @ self.data[p]
        if self.inner:
            return -ip
        return self.sq[rows] - 2.0 * ip + self.sq[p]

    # ------------------------------------------------------------ construction

    def add(self, slots: np.ndarray, vectors: np.ndarray) -> None:
        """Insert new nodes (slots not yet in the graph) with their vectors."""
        slots = np.asarray(slots, np.int64)
        if not len(slots):
            return
        self._grow(int(slots.max()) + 1)
        self._set_vectors(slots, vectors)
        lv = np.minimum((-np.log(1.0 - self.rng.random(len(slots))) * self.ml).astype(np.int64), MAX_LEVEL)
        self.level[slots] = lv
        self.dead[slots] = False
        self.size += len(slots)
        self._retrain_if_needed()
        if self.quant.trained_on and len(slots):
            self.codes[slots] = self.quant.encode(self.data[slots])
        for lc in range(int(lv.max()), -1, -1):
            self._link_layer(slots[lv >= lc], lc)
        top_new = int(lv.max())
        if top_new > self.top or self.entry < 0:
            self.top = top_new
            self.entry = int(slots[int(np.argmax(lv))])

    def _link_layer(self, new: np.ndarray, lc: int) -> None:
        members = np.flatnonzero((self.level[: self.cap] >= lc) & ~self.dead[: self.cap])
        if len(members) <= 1:
            return
        mmax = self.m0 if lc == 0 else self.m
        c = min(self.efc, len(members) - 1)
        p_cand = min(c, 2 * mmax)
        md, msq = self.data[members], self.sq[members]
        rows = max(1, CHUNK_FLOATS // len(members))
        for i0 in range(0, len(new), rows):
            chunk = new[i0:i0 + rows]
            d = self._gd(self.data[chunk], self.sq[chunk], md, msq)
            d[np.arange(len(chunk)), np.searchsorted(members, chunk)] = np.inf      # not itself
            part = np.argpartition(d, p_cand - 1, axis=1)[:, :p_cand]
            for r, p in enumerate(chunk.tolist()):
                dq = d[r, part[r]]
                order = np.argsort(dq, kind="stable")
                cand, dq = members[part[r][order]], dq[order]
                sel, seld = self._select(cand, dq, mmax)
                self._set_links(p, lc, sel, seld)
                for nb, dn in zip(sel.tolist(), seld.tolist(), strict=True):
                    self._add_reverse(nb, p, dn, lc, mmax)

    def _select(self, cand: np.ndarray, dq: np.ndarray, mmax: int) -> tuple[np.ndarray, np.ndarray]:
        """The HNSW neighbour heuristic: keep a candidate unless a kept one is closer to it than the
        new node is; fill up with the closest pruned ones."""
        cv = self.data[cand]
        pair = self._gd(cv, self.sq[cand], cv, self.sq[cand])
        keep: list[int] = []
        pruned: list[int] = []
        for i in range(len(cand)):
            if keep and (pair[i, keep] < dq[i]).any():
                pruned.append(i)
                continue
            keep.append(i)
            if len(keep) >= mmax:
                break
        keep += pruned[: mmax - len(keep)]
        return cand[keep], dq[keep]

    def _neighbours(self, p: int, lc: int) -> np.ndarray:
        if lc == 0:
            return self.nb0[p, : self.cnt0[p]]
        links = self.upper.get(lc, {}).get(p)
        return np.asarray(links[0], np.int64) if links else np.zeros(0, np.int64)

    def _set_links(self, p: int, lc: int, sel: np.ndarray, seld: np.ndarray) -> None:
        if lc == 0:
            self.nb0[p, : len(sel)] = sel
            self.nd0[p, : len(sel)] = seld
            self.cnt0[p] = len(sel)
        else:
            self.upper.setdefault(lc, {})[p] = (sel.tolist(), seld.tolist())

    def _add_reverse(self, n: int, p: int, d_pn: float, lc: int, mmax: int) -> None:
        if lc == 0:
            cnt = int(self.cnt0[n])
            nbrs, dists = self.nb0[n, :cnt], self.nd0[n, :cnt]
        else:
            links = self.upper.setdefault(lc, {}).setdefault(n, ([], []))
            nbrs, dists = np.asarray(links[0], np.int64), np.asarray(links[1], np.float32)
            cnt = len(nbrs)
        if p in nbrs:
            return
        if cnt < mmax:
            j = cnt
        else:
            d_p = self._gd_to(p, nbrs)                         # p to each current neighbour
            if (d_p < d_pn).any():                             # p is reachable through one of them
                covered = np.flatnonzero(d_p < dists)          # neighbours that p covers
                if not len(covered):
                    return
                j = int(covered[np.argmax(dists[covered])])
            else:
                j = int(np.argmax(dists))
        if lc == 0:
            self.nb0[n, j], self.nd0[n, j] = p, d_pn
            if j == cnt:
                self.cnt0[n] = cnt + 1
        elif j == cnt:
            links[0].append(p)
            links[1].append(d_pn)
        else:
            links[0][j], links[1][j] = p, d_pn

    def mark_dead(self, slot: int) -> None:
        if slot < self.cap:
            self.dead[slot] = True

    # ------------------------------------------------------------ search

    def search(self, q: np.ndarray, k: int, ef: int, allowed: np.ndarray | None) -> np.ndarray:
        """Up to ``max(ef, k)`` accepted slots near ``q`` (approximate). ``allowed``: a bool mask over
        slots (dead nodes are never accepted)."""
        if self.entry < 0:
            return np.zeros(0, np.int64)
        x = self._transform(np.asarray(q, np.float32)[None, :])[0]
        prep = self.quant.prepare(x, self.inner)
        ep = self.entry
        dep = float(self.quant.distances(self.codes[[ep]], prep, self.inner)[0])
        for lc in range(self.top, 1, -1):
            improved = True
            while improved:
                improved = False
                nb = self._neighbours(ep, lc)
                if len(nb):
                    d = self.quant.distances(self.codes[nb], prep, self.inner)
                    j = int(np.argmin(d))
                    if d[j] < dep:
                        dep, ep, improved = float(d[j]), int(nb[j]), True
        seeds = [(dep, ep)]
        if self.top >= 1:
            seeds = self._beam(prep, seeds, max(ef, 32), 1, None)
        ok = ~self.dead[: self.cap]
        if allowed is not None:
            ok = ok.copy()
            ok[: len(allowed)] &= allowed
            ok[len(allowed):] = False
        res = self._beam(prep, seeds, max(ef, k), 0, ok)
        return np.array([v for _, v in res], np.int64)

    def _beam(self, prep: tuple, seeds: list, ef: int, lc: int, ok: np.ndarray | None) -> list:
        visited = np.zeros(self.cap, bool)
        cand: list = []
        res: list = []                                       # max-heap (-d, node) of accepted nodes
        for d, v in seeds:
            if visited[v]:
                continue
            visited[v] = True
            heapq.heappush(cand, (d, v))
            if ok is None or ok[v]:
                heapq.heappush(res, (-d, v))
        while len(res) > ef:
            heapq.heappop(res)
        codes, quant, inner = self.codes, self.quant, self.inner
        nb0, cnt0 = self.nb0, self.cnt0
        while cand:
            d, c = heapq.heappop(cand)
            if len(res) >= ef and d > -res[0][0]:
                break
            nb = nb0[c, : cnt0[c]] if lc == 0 else self._neighbours(c, lc)
            nb = nb[~visited[nb]]
            if not len(nb):
                continue
            visited[nb] = True
            dd = quant.distances(codes[nb], prep, inner)
            acc = ok[nb] if ok is not None else np.ones(len(nb), bool)
            bound = -res[0][0] if len(res) >= ef else math.inf
            for dv, v, a in zip(dd.tolist(), nb.tolist(), acc.tolist(), strict=True):
                if dv < bound or len(res) < ef:
                    heapq.heappush(cand, (dv, v))
                    if a:
                        heapq.heappush(res, (-dv, v))
                        if len(res) > ef:
                            heapq.heappop(res)
                        if len(res) >= ef:
                            bound = -res[0][0]
        return sorted((-d, v) for d, v in res)

    # ------------------------------------------------------------ persistence

    def save(self, path: Path, stamp: dict) -> None:
        """The graph (not the vectors, which the collection restores) to ``path``, atomically."""
        n = self.cap
        up_nodes, up_off, up_nbrs, up_d, up_lc = [], [0], [], [], []
        for lc, layer in sorted(self.upper.items()):
            for node, (nbrs, dists) in sorted(layer.items()):
                up_lc.append(lc)
                up_nodes.append(node)
                up_nbrs.extend(nbrs)
                up_d.extend(dists)
                up_off.append(len(up_nbrs))
        tmp = path.with_name(path.name + ".tmp.npz")
        np.savez(tmp, level=self.level[:n], nb0=self.nb0[:n], nd0=self.nd0[:n], cnt0=self.cnt0[:n],
                 dead=self.dead[:n], up_lc=np.array(up_lc, np.int64), up_nodes=np.array(up_nodes, np.int64),
                 up_off=np.array(up_off, np.int64), up_nbrs=np.array(up_nbrs, np.int64),
                 up_d=np.array(up_d, np.float32), entry=np.array(self.entry), top=np.array(self.top),
                 size=np.array(self.size), stamp=np.array(json.dumps(stamp, sort_keys=True)),
                 **{f"quant_{k}": v for k, v in self.quant.state().items()})
        tmp.replace(path)

    def load(self, path: Path, stamp: dict, vectors: np.ndarray) -> bool:
        """Restore a saved graph if its stamp matches; ``vectors``: the collection's slot vectors."""
        try:
            st = np.load(path, allow_pickle=False)
            if str(st["stamp"]) != json.dumps(stamp, sort_keys=True):
                return False
        except (OSError, ValueError, KeyError):
            return False
        n = len(st["level"])
        self._grow(max(n, len(vectors)))
        self.level[:n], self.nb0[:n], self.nd0[:n] = st["level"], st["nb0"], st["nd0"]
        self.cnt0[:n], self.dead[:n] = st["cnt0"], st["dead"]
        self.upper = {}
        off = st["up_off"]
        for i, (lc, node) in enumerate(zip(st["up_lc"].tolist(), st["up_nodes"].tolist(), strict=True)):
            a, b = int(off[i]), int(off[i + 1])
            self.upper.setdefault(lc, {})[node] = (st["up_nbrs"][a:b].tolist(), st["up_d"][a:b].tolist())
        self.entry, self.top, self.size = int(st["entry"]), int(st["top"]), int(st["size"])
        self.quant.load({k[6:]: st[k] for k in st.files if k.startswith("quant_")})
        members = np.flatnonzero(self.level[:n] >= 0)
        self._set_vectors(members, vectors[members])
        self.codes[members] = self.quant.encode(self.data[members])
        return True
