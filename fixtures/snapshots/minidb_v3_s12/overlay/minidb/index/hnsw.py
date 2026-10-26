"""A GLASS-style HNSW index: a layered proximity graph, searched on SQ8 codes.

Nodes are the collection's slots. Construction works in batches (an upsert request at a time). For
each new node and layer, the candidate neighbours are the nearest nodes of that layer, from which the
HNSW heuristic keeps a diverse set of ``m`` (``2 m`` on layer 0). Reverse links keep each node's list
diverse and bounded: a node that receives new neighbours re-runs the heuristic over its old and new
ones. Every link stores its distance.

Layer 0 at scale (stage 12) uses a **coarse quantiser** (k-means, ``COARSE_MIN`` nodes and up):

* construction candidates of a new node come from the members of the ``PROBE`` cells nearest to its
  own cell, not from every node, so a batch costs ``O(batch x N / cells)`` instead of
  ``O(batch x N)``;
* the neighbour heuristic and the reverse-link merge run for the whole batch at once (numpy), not
  node by node;
* a search starts its layer-0 beam from the representatives of the ``SEEDS`` cells nearest to the
  query. Clustered data otherwise strands a greedy descent in the wrong cluster: the links of a
  cluster's points stay inside it.

Upper layers (a ``1 / m`` share of the nodes each) keep exact candidates and the per-node path.
``dot`` keeps the exact path everywhere: L2 cells are no guide to inner products.

Search runs a beam on layer 0 (on SQ8 codes) from the seeds (or, below ``COARSE_MIN``, descends
greedily through the upper layers and runs a beam on layer 1 first), and returns up to ``ef``
accepted nodes; the caller re-ranks them exactly. Deleted nodes stay in the graph as waypoints but
are never returned.

Graph distance: squared L2 (``l2``; ``cosine`` on normalised vectors) or the negated inner product
(``dot``).
"""
from __future__ import annotations

import heapq
import json
import math
from pathlib import Path

import numpy as np

from minidb.index import kmeans as km
from minidb.index.base import Hits
from minidb.index.quant import ScalarQuantizer

MAX_LEVEL = 15
CHUNK_FLOATS = 1 << 22          # distance-matrix chunk size during construction
BUILD_BATCH = 1000
COARSE_MIN = 8192               # layer-0 nodes before the coarse quantiser is trained
POINTS_PER_CELL = 200
MAX_CELLS = 1024
PROBE = 10                      # cells whose members are a new node's candidates
SEEDS = 4                       # cells whose representatives seed a search
REPS = 4                        # representatives per cell (random members: a cell may straddle clusters)
REVERSE = 16                    # a new node's closest neighbours that link back to it
MAX_INCOMING = 8                # new reverse links per node and batch (the closest)
MERGE_ROWS = 2048               # nodes per batched heuristic


class HNSWIndex:
    kind = "hnsw"
    trained = True              # no training: points are linked as they arrive
    train_min = 0

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
        # coarse quantiser (layer 0 at scale)
        self.cells: np.ndarray | None = None       # [cells, dim] float32
        self.near: np.ndarray | None = None        # [cells, PROBE] cells nearest to each cell
        self.reps = np.zeros((0, REPS), np.int64)  # nodes of each cell (-1: none yet)
        self.cell = np.zeros(0, np.int32)          # cell of each node (-1: none)
        self.coarse_on = 0                         # graph size when the cells were trained
        self.lists: list[np.ndarray] = []          # nodes of each cell (first list_n[c] entries)
        self.list_n: list[int] = []

    def config(self) -> dict:
        return {"type": "hnsw", "m": self.m, "ef_construction": self.efc}

    def default_params(self) -> dict:
        return {}

    def train(self, slots: np.ndarray, fetch) -> None:
        for i in range(0, len(slots), BUILD_BATCH):
            part = slots[i:i + BUILD_BATCH]
            self.add(part, fetch(part))

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
        self.cell = grown(self.cell, (cap,), -1)
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
        if self.quant.trained_on and self.size < 2 * self.quant.trained_on:      # nodes never leave the graph
            return
        members = np.flatnonzero(self.level[: self.cap] >= 0)
        self.quant.train(self.data[members])
        self.codes[members] = self.quant.encode(self.data[members])

    # ------------------------------------------------------------ the coarse quantiser

    def _coarse_if_needed(self) -> bool:
        """Train (or retrain, when the graph has doubled) the cells over the live layer-0 nodes, then
        assign every node; True if it did."""
        if self.inner or self.size < COARSE_MIN or (self.coarse_on and self.size < 2 * self.coarse_on):
            return False
        members = np.flatnonzero((self.level[: self.cap] >= 0) & ~self.dead[: self.cap])
        n = len(members)
        if n < COARSE_MIN:
            return False
        k = int(min(MAX_CELLS, max(16, n // POINTS_PER_CELL)))
        sample = members[km.sample(n, k, self.rng)]
        cells = km.kmeans(self.data[sample], k, seed=int(self.rng.integers(1 << 31)))
        self.cells = cells
        self.near = km.nearest(cells, cells, min(PROBE, k))
        everyone = np.flatnonzero(self.level[: self.cap] >= 0)
        self.cell[everyone] = km.nearest(self.data[everyone], cells)
        self.reps = np.full((k, REPS), -1, np.int64)
        shuffled = members[self.rng.permutation(n)]
        by = self.cell[shuffled]
        order = np.argsort(by, kind="stable")                 # by cell, in random order within a cell
        by, shuffled = by[order], shuffled[order]
        rank = np.arange(n) - np.searchsorted(by, by)
        pick = rank < REPS
        self.reps[by[pick], rank[pick]] = shuffled[pick]
        self.coarse_on = self.size
        self._rebuild_lists()
        return True

    def _rebuild_lists(self) -> None:
        """Every cell's nodes (its candidate pool share), kept up to date as nodes arrive."""
        everyone = np.flatnonzero(self.level[: self.cap] >= 0)
        by = self.cell[everyone]
        order = np.argsort(by, kind="stable")
        starts = np.searchsorted(by[order], np.arange(len(self.cells) + 1))
        self.lists = [everyone[order][starts[c]:starts[c + 1]].copy() for c in range(len(self.cells))]
        self.list_n = [len(x) for x in self.lists]

    def _assign(self, slots: np.ndarray) -> None:
        if self.cells is None:
            return
        self.cell[slots] = km.nearest(self.data[slots], self.cells)
        for s, c in zip(slots.tolist(), self.cell[slots].tolist(), strict=True):
            free = np.flatnonzero(self.reps[c] < 0)
            if len(free):
                self.reps[c, free[0]] = s
            n, arr = self.list_n[c], self.lists[c]
            if n == len(arr):
                arr = self.lists[c] = np.concatenate([arr, np.empty(max(16, n), np.int64)])
            arr[n] = s
            self.list_n[c] = n + 1

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
        if not self._coarse_if_needed():           # (a training assigns every node itself)
            self._assign(slots)
        for lc in range(int(lv.max()), 0, -1):
            self._link_layer(slots[lv >= lc], lc)
        self._link_layer0(slots)
        top_new = int(lv.max())
        if top_new > self.top or self.entry < 0:
            self.top = top_new
            self.entry = int(slots[int(np.argmax(lv))])

    def _link_layer(self, new: np.ndarray, lc: int) -> None:
        """An upper layer: exact candidates, node by node."""
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

    def _link_layer0(self, new: np.ndarray) -> None:
        """Layer 0 for a whole batch: candidates (from the nearby cells once trained), the heuristic,
        then the reverse links, each for all nodes at once."""
        if self.cells is None:
            members = np.flatnonzero((self.level[: self.cap] >= 0) & ~self.dead[: self.cap])
            if len(members) <= 1:
                return
            width = min(self.efc, 2 * self.m0, len(members) - 1)
        else:
            members, width = None, min(self.efc, 2 * self.m0)
        cand, dist = self._candidates(new, members, width)
        sel, seld = self._select_batch(cand, dist, self.m0)
        counts = (sel >= 0).sum(1)
        self.nb0[new] = sel
        self.nd0[new] = seld
        self.cnt0[new] = counts
        keep = (sel >= 0) & (np.arange(self.m0)[None, :] < REVERSE)
        src = np.repeat(new, keep.sum(1))
        self._merge_reverse(sel[keep].astype(np.int64), src, seld[keep])

    def _candidates(self, new: np.ndarray, members: np.ndarray | None, width: int) -> tuple[np.ndarray, np.ndarray]:
        """The ``width`` nearest live layer-0 nodes of every new node (itself excluded), closest
        first; padded with -1 / inf. ``members``: every live node (no cells yet), else the pools of
        the cells near each new node's own."""
        cand = np.full((len(new), width), -1, np.int64)
        dist = np.full((len(new), width), np.inf, np.float32)
        if self.cells is None:
            groups = [(np.arange(len(new)), members)]
        else:
            mine = self.cell[new]
            groups = []
            for g in np.unique(mine).tolist():
                pool = np.concatenate([self.lists[c][: self.list_n[c]] for c in self.near[g].tolist()])
                groups.append((np.flatnonzero(mine == g), pool[~self.dead[pool]]))
        for rows_of, pool in groups:
            if not len(pool):
                continue
            step = max(1, CHUNK_FLOATS // len(pool))
            for i0 in range(0, len(rows_of), step):
                rows = rows_of[i0:i0 + step]
                nodes = new[rows]
                d = self._gd(self.data[nodes], self.sq[nodes], self.data[pool], self.sq[pool]).astype(np.float32)
                w = min(width + 1, len(pool))                    # + the node itself, dropped below
                part = np.argpartition(d, w - 1, axis=1)[:, :w] if w < len(pool) else \
                    np.broadcast_to(np.arange(len(pool)), (len(rows), len(pool)))
                pd = np.take_along_axis(d, part, 1)
                pc = pool[part]
                pd[pc == nodes[:, None]] = np.inf
                order = np.argsort(pd, axis=1, kind="stable")[:, : w - 1]
                pd = np.take_along_axis(pd, order, 1)
                pc = np.take_along_axis(pc, order, 1)
                pc[~np.isfinite(pd)] = -1
                cand[rows, : w - 1], dist[rows, : w - 1] = pc, pd
        return cand, dist

    def _select_batch(self, cand: np.ndarray, dq: np.ndarray, mmax: int) -> tuple[np.ndarray, np.ndarray]:
        """The heuristic of ``_select`` for every row at once. ``cand`` / ``dq``: rows sorted by
        distance, padded with -1 / inf. Returns ``mmax`` columns, padded with -1 / 0."""
        n, w = cand.shape
        out = np.full((n, mmax), -1, np.int32)
        outd = np.zeros((n, mmax), np.float32)
        for r0 in range(0, n, MERGE_ROWS):
            c, d = cand[r0:r0 + MERGE_ROWS], dq[r0:r0 + MERGE_ROWS]
            w = max(1, int((c >= 0).sum(1).max()))           # rows are packed left: drop the empty tail
            c, d = c[:, :w], d[:, :w]
            valid = c >= 0
            safe = np.where(valid, c, 0)
            v, vsq = self.data[safe], self.sq[safe]
            ip = np.matmul(v, v.transpose(0, 2, 1))
            pair = -ip if self.inner else vsq[:, :, None] - 2.0 * ip + vsq[:, None, :]
            keep = np.zeros(c.shape, bool)
            kept = np.zeros(len(c), np.int64)
            for i in range(w):
                covered = ((pair[:, i, :] < d[:, i, None]) & keep).any(1)
                take = valid[:, i] & ~covered & (kept < mmax)
                keep[:, i] = take
                kept += take
            # fill up with the closest pruned candidates
            spare = valid & ~keep
            rank = np.cumsum(spare, axis=1) - 1
            keep |= spare & (rank < (mmax - kept)[:, None])
            # the kept columns, in distance order, packed to the left
            pos = np.where(keep, np.arange(w)[None, :], w)
            pos.sort(axis=1)
            pos = pos[:, :mmax]
            ok = pos < w
            pos = np.minimum(pos, w - 1)
            sel = np.take_along_axis(c, pos, 1)
            seld = np.take_along_axis(d, pos, 1)
            out[r0:r0 + MERGE_ROWS, : pos.shape[1]] = np.where(ok, sel, -1)
            outd[r0:r0 + MERGE_ROWS, : pos.shape[1]] = np.where(ok, seld, 0)
        return out, outd

    def _merge_reverse(self, targets: np.ndarray, sources: np.ndarray, dists: np.ndarray) -> None:
        """Add the link ``target -> source`` for every pair: appended while a list has room, else the
        heuristic over the old and new neighbours decides (layer 0, all targets at once)."""
        if not len(targets):
            return
        order = np.lexsort((dists, targets))
        targets, sources, dists = targets[order], sources[order], dists[order]
        uniq, start, count = np.unique(targets, return_index=True, return_counts=True)
        m0 = self.m0
        rank = np.arange(len(targets)) - np.repeat(start, count)
        take = rank < MAX_INCOMING                          # the closest few per target and batch
        tpos = np.repeat(np.arange(len(uniq)), count)[take]
        new_c = np.full((len(uniq), MAX_INCOMING), -1, np.int64)
        new_d = np.full((len(uniq), MAX_INCOMING), np.inf, np.float32)
        new_c[tpos, rank[take]] = sources[take]
        new_d[tpos, rank[take]] = dists[take]
        old_c = self.nb0[uniq].astype(np.int64)
        old_d = self.nd0[uniq].astype(np.float32)
        old_n = self.cnt0[uniq].astype(np.int64)
        old_ok = np.arange(m0)[None, :] < old_n[:, None]
        old_c[~old_ok], old_d[~old_ok] = -1, np.inf
        dup = (new_c[:, :, None] == old_c[:, None, :]).any(2) & (new_c >= 0)
        new_c[dup], new_d[dup] = -1, np.inf
        n_new = (new_c >= 0).sum(1)
        fits = old_n + n_new <= m0
        if fits.any():                                      # room: append
            r = np.flatnonzero(fits)
            nc, nd = new_c[r], new_d[r]
            col = old_n[r][:, None] + np.cumsum(nc >= 0, axis=1) - 1
            ok = nc >= 0
            rows = np.repeat(uniq[r], ok.sum(1))
            self.nb0[rows, col[ok]] = nc[ok]
            self.nd0[rows, col[ok]] = nd[ok]
            self.cnt0[uniq[r]] = old_n[r] + n_new[r]
        r = np.flatnonzero(~fits)
        if not len(r):
            return
        uc = np.concatenate([old_c[r], new_c[r]], axis=1)
        ud = np.concatenate([old_d[r], new_d[r]], axis=1)
        o = np.argsort(ud, axis=1, kind="stable")
        uc, ud = np.take_along_axis(uc, o, 1), np.take_along_axis(ud, o, 1)
        sel, seld = self._select_batch(uc, ud, m0)
        self.nb0[uniq[r]] = sel
        self.nd0[uniq[r]] = seld
        self.cnt0[uniq[r]] = (sel >= 0).sum(1)

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
        if j == cnt:
            links[0].append(p)
            links[1].append(d_pn)
        else:
            links[0][j], links[1][j] = p, d_pn

    def mark_dead(self, slot: int) -> None:
        if slot < self.cap:
            self.dead[slot] = True

    # ------------------------------------------------------------ search

    def search(self, q: np.ndarray, k: int, params: dict, allowed: np.ndarray | None) -> Hits:
        """Up to ``max(ef, k)`` accepted slots near ``q`` (approximate). ``allowed``: a bool mask over
        slots (dead nodes are never accepted)."""
        slots = self._search(q, k, max(params.get("ef") or 64, k), allowed)
        return Hits(slots, len(slots), {})

    def _search(self, q: np.ndarray, k: int, ef: int, allowed: np.ndarray | None) -> np.ndarray:
        if self.entry < 0:
            return np.zeros(0, np.int64)
        x = self._transform(np.asarray(q, np.float32)[None, :])[0]
        prep = self.quant.prepare(x, self.inner)
        if self.cells is not None:
            dc = np.einsum("ij,ij->i", self.cells - x, self.cells - x)
            near = np.argpartition(dc, min(SEEDS, len(dc)) - 1)[:SEEDS] if len(dc) > SEEDS else np.arange(len(dc))
            reps = self.reps[near].ravel()
            reps = reps[reps >= 0]
            if len(reps):
                d = self.quant.distances(self.codes[reps], prep, self.inner)
                seeds = sorted(zip(d.tolist(), reps.tolist()))
                return self._layer0(prep, seeds, max(ef, k), allowed)
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
        return self._layer0(prep, seeds, max(ef, k), allowed)

    def _layer0(self, prep: tuple, seeds: list, ef: int, allowed: np.ndarray | None) -> np.ndarray:
        ok = ~self.dead[: self.cap]
        if allowed is not None:
            ok = ok.copy()
            n = min(len(allowed), self.cap)
            ok[:n] &= allowed[:n]
            ok[n:] = False
        res = self._beam(prep, seeds, ef, 0, ok)
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
        coarse = {}
        if self.cells is not None:
            coarse = {"cells": self.cells, "near": self.near, "reps": self.reps, "cell": self.cell[:n],
                      "coarse_on": np.array(self.coarse_on)}
        tmp = path.with_name(path.name + ".tmp.npz")
        np.savez(tmp, level=self.level[:n], nb0=self.nb0[:n], nd0=self.nd0[:n], cnt0=self.cnt0[:n],
                 dead=self.dead[:n], up_lc=np.array(up_lc, np.int64), up_nodes=np.array(up_nodes, np.int64),
                 up_off=np.array(up_off, np.int64), up_nbrs=np.array(up_nbrs, np.int64),
                 up_d=np.array(up_d, np.float32), entry=np.array(self.entry), top=np.array(self.top),
                 size=np.array(self.size), stamp=np.array(json.dumps(stamp, sort_keys=True)),
                 **{f"quant_{k}": v for k, v in self.quant.state().items()},
                 **{f"coarse_{k}": v for k, v in coarse.items()})
        tmp.replace(path)

    def load(self, path: Path, stamp: dict, fetch, live: np.ndarray) -> bool:
        """Restore a saved graph if its stamp matches; ``fetch(slots)``: the collection's vectors."""
        try:
            st = np.load(path, allow_pickle=False)
            if str(st["stamp"]) != json.dumps(stamp, sort_keys=True):
                return False
        except (OSError, ValueError, KeyError):
            return False
        n = len(st["level"])
        self._grow(n)
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
        self._set_vectors(members, fetch(members))
        self.codes[members] = self.quant.encode(self.data[members])
        if "coarse_cells" in st.files:
            self.cells, self.near = st["coarse_cells"], st["coarse_near"]
            self.reps, self.coarse_on = st["coarse_reps"].astype(np.int64), int(st["coarse_coarse_on"])
            self.cell[:n] = st["coarse_cell"]
            self._rebuild_lists()
        else:                                   # saved before the cells existed (stage 11 and earlier)
            self._coarse_if_needed()
        return True
