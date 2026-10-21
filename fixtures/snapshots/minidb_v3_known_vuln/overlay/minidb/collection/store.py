"""Durable collections: points in memory, a write-ahead log and snapshots in the data dir.

Layout, under ``DIR/collections/<name>/`` (names are validated, so a name is always one plain
directory entry):

* ``collection.json``: name, dim, metric, index configuration and, for a text collection,
  ``"embedding": "service"`` (replaced atomically). A text collection also keeps each point's text
  (``"texts"`` in log records and in the snapshot header);
* ``snapshot.bin``: a header line ``MINIDB-COLLECTION 1``, a JSON line ``{"seq", "slots", "ids",
  "payloads", "vectors"}``, then (``"vectors": "inline"``) ``slots x dim`` little-endian float32
  values, written to a temp file, then renamed. With ``"vectors": "file"`` the vectors are in
  ``vectors.f32`` instead (``vectors.py``), flushed before the snapshot is renamed;
* ``vectors.f32``: the vectors of an indexed collection, by slot. A ``flat`` collection keeps its
  vectors in memory (every search scans them all); an indexed one keeps only its index in memory and
  reads back the index's candidates for exact scoring;
* ``wal.log``: one JSON line per acknowledged change, written with a single ``write`` before the
  request is answered: ``{"seq", "op": "u", "ids", "payloads", "vectors": <base64 float32>}`` or
  ``{"seq", "op": "d", "ids"}``. A torn last line (a crash mid-write) is discarded on recovery, so a
  request is applied completely or not at all.

* ``index.npz``: the index structure as of the snapshot (stamped with its ``seq``), so a clean restart
  does not rebuild the graph.

Opening a collection never waits for its index (stage 7: a crashed server must be ready within
seconds). The snapshot and the log are read, then the index is caught up in a background thread:
the saved structure plus the points logged after it, or a full rebuild when there is no usable saved
structure. Until it has caught up (``index_ready``), searches are exact, so they are always correct.
Deaths during the catch-up are applied when the caught-up index is put in service.

Read-only (``--read-only``, stage 9): a collection is loaded without changing a byte of its directory.
The vectors are read into memory (log replay never writes ``vectors.f32``), a torn log tail is skipped
but not truncated, nothing is checkpointed, and the index lives in memory only.

Points live in slots. A slot is never reused: an update or delete marks the old slot dead, so slot
numbers stay stable for an index. Checkpoints (on size, and at shutdown) write the snapshot and
truncate the log; records already in the snapshot (``seq <= snapshot seq``) are skipped on replay.

Filtered search (stage 4) returns ``k`` results whenever ``k`` points match. A filter is evaluated for
the whole collection at once (``columns.py``); when few points match (``PRE_FILTER_MAX``) they are
scored exactly ("pre"), otherwise the index is searched for matching points only ("post"), widening
``ef`` or ``nprobe`` until ``k`` are found, and falling back to the exact path.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import logging
import threading
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from minidb import index as indexes
from minidb.collection.columns import PayloadColumns, View
from minidb.collection.filters import compile_filter
from minidb.collection import snapshots as snap
from minidb.collection.points import id_key, valid_name
from minidb.collection.vectors import FILE as VECTORS_FILE
from minidb.collection.vectors import DiskVectors, MemoryVectors
from minidb.locks import RWLock

SNAPSHOT_MAGIC = b"MINIDB-COLLECTION 1\n"
CHECKPOINT_BYTES = 64 << 20
COLLECTIONS_DIR = "collections"
# A search is a Python loop over many small numpy calls: threads running searches side by side spend
# their time handing the GIL to each other (8 clients got a third of the throughput of one). Searches
# therefore compute one at a time; reading requests and writing answers stay concurrent.
SEARCH_GATE = threading.Lock()
PRE_FILTER_MAX = 5000          # at most this many matching points: score them all exactly
MAX_WIDEN = 6                  # doublings of ef / nprobe before the exact fallback

log = logging.getLogger("minidb.collection")


class NotFound(LookupError):
    pass


class Exists(Exception):
    pass


class Collection:
    def __init__(self, path: Path, name: str, dim: int, metric: str, index_cfg: dict | None = None,
                 embedding: str | None = None, *, read_only: bool = False) -> None:
        self.path, self.name, self.dim, self.metric = Path(path), name, dim, metric
        self.read_only = read_only
        self.embedding = embedding
        self.texts: list | None = [] if embedding else None
        self.index_cfg = dict(index_cfg or indexes.FLAT)
        self.index = indexes.build(self.index_cfg, dim, metric)
        self.store = self._new_store(self.index_cfg)
        self.columns = PayloadColumns()
        self.lock = RWLock()
        self.cap = 0
        self.n_slots = 0
        self.live = np.zeros(0, bool)
        self.ids: list[Any] = []
        self.payloads: list[Any] = []
        self.slot_of: dict[Any, int] = {}
        self.seq = 0
        self.wal_bytes = 0
        self._wal_fd: int | None = None
        self.index_ready = True        # False while the index catches up in the background
        self._index_from = 0           # slots already in the index when the catch-up started
        self._dead_pending: list[int] = []
        self._gen = 0                  # bumped to abandon a running catch-up

    # ------------------------------------------------------------ lifecycle

    @classmethod
    def create(cls, root: Path, name: str, dim: int, metric: str, index_cfg: dict | None = None,
               embedding: str | None = None) -> Collection:
        tmp = root / f".tmp-{name}-{uuid.uuid4().hex}"
        tmp.mkdir(parents=True)
        cfg = dict(index_cfg or indexes.FLAT)
        meta = {"name": name, "dim": dim, "metric": metric, "index": cfg, **({"embedding": embedding} if embedding else {})}
        (tmp / "collection.json").write_text(json.dumps(meta))
        (tmp / "wal.log").write_bytes(b"")
        final = root / name
        try:
            os.rename(tmp, final)
        except OSError:
            shutil.rmtree(tmp, ignore_errors=True)
            raise Exists(name) from None
        c = cls(final, name, dim, metric, cfg, embedding)
        c._open_wal()
        return c

    @classmethod
    def load(cls, path: Path, *, read_only: bool = False) -> Collection:
        meta = json.loads((path / "collection.json").read_text())
        c = cls(path, meta["name"], int(meta["dim"]), meta["metric"], meta.get("index"), meta.get("embedding"),
                read_only=read_only)
        c._load_snapshot()
        c._load_index()
        c._replay()
        c._open_wal()
        if not c.index_ready:
            if c._index_from == c.n_slots:     # nothing to add (a clean shutdown, or no points)
                for s in c._dead_pending:
                    c.index.mark_dead(s)
                c._dead_pending, c.index_ready = [], True
            else:
                c._start_catch_up()
        return c

    def close(self) -> None:
        with self.lock.write():
            self._gen += 1
            if self._wal_fd is not None:
                if not self.read_only:
                    self._checkpoint()
                os.close(self._wal_fd)
                self._wal_fd = None
                self.store.close()

    def _new_store(self, cfg: dict):
        if cfg["type"] == "flat" or self.read_only:
            return MemoryVectors(self.dim)
        return DiskVectors(self.path / VECTORS_FILE, self.dim)

    # ------------------------------------------------------------ queries

    def count(self) -> int:
        return len(self.slot_of)

    def info(self) -> dict:
        out = {"name": self.name, "dim": self.dim, "metric": self.metric, "points": self.count(),
               "index": dict(self.index_cfg)}
        if self.embedding:
            out["embedding"] = self.embedding
        return out

    def get(self, pid: Any) -> dict | None:
        with self.lock.read():
            if self._wal_fd is None:
                raise NotFound(self.name)
            slot = self.slot_of.get(pid)
            if slot is None:
                return None
            out = {"id": pid, "vector": self.store.rows([slot])[0].astype(float).tolist(),
                   "payload": self.payloads[slot]}
            if self.texts is not None:
                out["text"] = self.texts[slot]
            return out

    def vectors_of(self, ids: list) -> np.ndarray:
        """The stored vectors (float64) of ``ids``, in order; NotFound naming the ids not present."""
        with self.lock.read():
            if self._wal_fd is None:
                raise NotFound(self.name)
            missing = [pid for pid in ids if pid not in self.slot_of]
            if missing:
                raise NotFound(", ".join(str(m) for m in missing[:10]))
            return self.store.rows(np.array([self.slot_of[pid] for pid in ids], dtype=np.int64)).astype(np.float64)

    @property
    def descending(self) -> bool:
        """CR-1: similarities (cosine, dot) rank highest first; l2 distances lowest first."""
        return self.metric != "l2"

    def scores(self, q: np.ndarray, slots: np.ndarray) -> np.ndarray:
        """Exact scores (float64) of ``slots``: the l2 distance, the cosine similarity or the inner
        product (CR-1)."""
        v = self.store.rows(slots).astype(np.float64)
        if self.metric == "l2":
            d = v - q
            return np.sqrt(np.einsum("ij,ij->i", d, d))
        dots = v @ q
        if self.metric == "dot":
            return dots
        return dots / (np.linalg.norm(v, axis=1) * np.linalg.norm(q))

    def matching(self, flt: Any) -> np.ndarray:
        """Live slots whose point matches the compiled filter ``flt`` (None: every point); called with
        the lock held."""
        live = self.live[: self.n_slots]
        if flt is None:
            return np.flatnonzero(live)
        return np.flatnonzero(flt.mask(View(self)) & live)

    def search(self, q: np.ndarray, k: int, flt: Any = None, *, params: dict | None = None,
               with_payload: bool = False, with_vector: bool = False) -> list[dict]:
        return self.query(q, k, compile_filter(flt), params=params, with_payload=with_payload,
                          with_vector=with_vector)[0]

    def query(self, q: np.ndarray, k: int, flt: Any, *, params: dict | None = None, with_payload: bool = False,
              with_vector: bool = False) -> tuple[list[dict], dict]:
        """``(results, explain)``. Exact over the matching points (flat, an untrained index, or few
        matches), else the index's candidates scored exactly. One search computes at a time
        (``SEARCH_GATE``)."""
        with SEARCH_GATE:
            return self._query(q, k, flt, params=params, with_payload=with_payload, with_vector=with_vector)

    def _query(self, q: np.ndarray, k: int, flt: Any, *, params: dict | None = None, with_payload: bool = False,
               with_vector: bool = False) -> tuple[list[dict], dict]:
        params = params or indexes.parse_params(None, self.index_cfg)
        with self.lock.read():
            explain = {"index": self.index_cfg["type"], "exact": True, "ef": None, "candidates": 0,
                       "filter": "none" if flt is None else "pre"}
            if self.index_cfg["type"] in ("ivf_flat", "ivf_pq"):
                explain["nprobe"] = params["nprobe"]
            if self._wal_fd is None:          # dropped or replaced by a restore meanwhile
                raise NotFound(self.name)
            index = self.index
            if index is None or not index.trained or not self.index_ready:
                slots = self.matching(flt)
                explain["candidates"] = len(slots)
                return self.results(slots, self.scores(q, slots), k, with_payload, with_vector), explain
            allowed = None
            if flt is not None:
                allowed = np.zeros(self.n_slots, bool)
                match = self.matching(flt)
                if len(match) <= max(PRE_FILTER_MAX, k):
                    explain["candidates"] = len(match)
                    return self.results(match, self.scores(q, match), k, with_payload, with_vector), explain
                allowed[match] = True
                explain["filter"] = "post"
            params = dict(params)
            if "ef" in params:
                params["ef"] = max(params["ef"], k)
            hits = index.search(q, k, params, allowed)
            widen = 0
            while allowed is not None and len(hits.slots) < k and widen < MAX_WIDEN:
                widen += 1
                params["ef"] = min(params["ef"] * 2, indexes.MAX_EF)
                params["nprobe"] = min(params["nprobe"] * 2, self.index_cfg.get("nlist", params["nprobe"]))
                hits = index.search(q, k, params, allowed)
            if allowed is not None and len(hits.slots) < k:          # give up on the index for this query
                explain["filter"] = "pre"
                explain["candidates"] = len(match)
                return self.results(match, self.scores(q, match), k, with_payload, with_vector), explain
            explain.update(exact=False, candidates=int(hits.exact), **hits.info)
            if self.index_cfg["type"] in ("hnsw", "qsg"):
                explain["ef"] = params["ef"]
            slots = hits.slots
            return self.results(slots, self.scores(q, slots), k, with_payload, with_vector), explain

    def archive(self) -> bytes:
        """A portable snapshot of the live points (``snapshots.py``), taken under the read lock."""
        with self.lock.read():
            if self._wal_fd is None:
                raise NotFound(self.name)
            slots = np.flatnonzero(self.live[: self.n_slots])
            ids = [self.ids[s] for s in slots.tolist()]
            payloads = [self.payloads[s] for s in slots.tolist()]
            texts = [self.texts[s] for s in slots.tolist()] if self.texts is not None else None
            vectors = self.store.rows(slots) if len(slots) else np.zeros((0, self.dim), np.float32)
            meta = {"dim": self.dim, "metric": self.metric, "index": dict(self.index_cfg),
                    **({"embedding": self.embedding} if self.embedding else {})}
        return snap.build_archive(meta, ids, payloads, vectors, texts)

    def set_index(self, cfg: dict) -> None:
        """Replace the index: built (or trained) over the current points, then recorded and
        checkpointed. The vectors move to or from ``vectors.f32`` when the kind of store changes."""
        with self.lock.write():
            if self._wal_fd is None:
                raise NotFound(self.name)
            self._gen += 1                    # a running catch-up is abandoned: this index replaces it
            self._dead_pending = []
            index = indexes.build(cfg, self.dim, self.metric)
            live = np.flatnonzero(self.live[: self.n_slots])
            if index is not None and len(live) >= index.train_min:
                index.train(live, self.store.rows)
            old = self.store
            if (cfg["type"] == "flat") != (self.index_cfg["type"] == "flat"):
                new = self._new_store(cfg)
                for i in range(0, self.n_slots, 8192):
                    new.write(i, old.rows(np.arange(i, min(i + 8192, self.n_slots))))
                new.sync()
            else:
                new = old
            meta = {"name": self.name, "dim": self.dim, "metric": self.metric, "index": cfg,
                    **({"embedding": self.embedding} if self.embedding else {})}
            tmp = self.path / "collection.json.tmp"
            tmp.write_text(json.dumps(meta))
            os.replace(tmp, self.path / "collection.json")
            self.index_cfg, self.index, self.store = dict(cfg), index, new
            self.index_ready = True
            self._checkpoint()
            if new is not old:
                old.close()
                if new.kind == "memory":
                    (self.path / VECTORS_FILE).unlink(missing_ok=True)

    def results(self, slots: np.ndarray, scores: np.ndarray, k: int, with_payload: bool,
                with_vector: bool) -> list[dict]:
        """The best ``k`` of ``slots`` by score (in the metric's direction), ties by id ascending;
        called with the read lock held."""
        rank = -scores if self.descending else scores
        if len(slots) > k:
            kth = np.partition(rank, k - 1)[k - 1]
            keep = rank <= kth
            slots, scores, rank = slots[keep], scores[keep], rank[keep]
        order = sorted(range(len(slots)), key=lambda i: (rank[i], id_key(self.ids[slots[i]])))[:k]
        vectors = self.store.rows(slots[order]) if with_vector else None
        out = []
        for j, i in enumerate(order):
            s = int(slots[i])
            r = {"id": self.ids[s], "score": float(scores[i])}
            if with_payload:
                r["payload"] = self.payloads[s]
            if with_vector:
                r["vector"] = vectors[j].astype(float).tolist()
            out.append(r)
        return out

    # ------------------------------------------------------------ changes

    def upsert(self, ids: list, vecs: np.ndarray, payloads: list, texts: list | None = None) -> int:
        with self.lock.write():
            if ids:
                rec = {"op": "u", "ids": ids, "payloads": payloads,
                       "vectors": base64.b64encode(vecs.astype("<f4").tobytes()).decode("ascii")}
                if texts is not None:
                    rec["texts"] = texts
                self._log(rec)
                self._apply_upsert(ids, vecs, payloads, texts)
                self._maybe_checkpoint()
            return len(ids)

    def delete(self, ids: list) -> int:
        with self.lock.write():
            present = [pid for pid in dict.fromkeys(ids) if pid in self.slot_of]
            if present:
                self._log({"op": "d", "ids": present})
                self._apply_delete(present)
                self._maybe_checkpoint()
            return len(present)

    # ------------------------------------------------------------ in memory

    def _grow(self, need: int) -> None:
        if need <= self.cap:
            return
        cap = max(need, 2 * self.cap, 256)
        live = np.zeros(cap, bool)
        live[: self.n_slots] = self.live[: self.n_slots]
        self.live, self.cap = live, cap

    def _apply_upsert(self, ids: list, vecs: np.ndarray, payloads: list, texts: list | None = None) -> np.ndarray:
        start = self.n_slots
        self._grow(start + len(ids))
        for pid in ids:
            old = self.slot_of.get(pid)
            if old is not None:
                self.live[old] = False
                self.payloads[old] = None
                self.ids[old] = None
                if self.texts is not None:
                    self.texts[old] = None
                self._slot_died(old)
        slots = np.arange(start, start + len(ids))
        self.store.write(start, vecs)
        self.live[start: start + len(ids)] = True
        self.ids.extend(ids)
        self.payloads.extend(payloads)
        if self.texts is not None:
            self.texts.extend(texts if texts is not None else [None] * len(ids))
        self.columns.added(start, payloads)
        for pid, s in zip(ids, slots.tolist(), strict=True):
            self.slot_of[pid] = s
        self.n_slots = start + len(ids)
        self._slots_added(slots)
        return slots

    def _apply_delete(self, ids: list) -> None:
        for pid in ids:
            s = self.slot_of.pop(pid, None)
            if s is not None:
                self.live[s] = False
                self.ids[s] = None
                self.payloads[s] = None
                if self.texts is not None:
                    self.texts[s] = None
                self._slot_died(s)

    def _slots_added(self, slots: np.ndarray) -> None:
        index = self.index
        if index is None or not self.index_ready:     # the catch-up adds them
            return
        index.fetch = self.store.rows
        if index.trained:
            index.add(slots, self.store.rows(slots))
        elif self.count() >= index.train_min:          # an index set on a smaller collection
            index.train(np.flatnonzero(self.live[: self.n_slots]), self.store.rows)

    def _slot_died(self, slot: int) -> None:
        if self.index is None:
            return
        if self.index_ready:
            self.index.mark_dead(slot)
        else:
            self._dead_pending.append(slot)

    # ------------------------------------------------------------ background index catch-up

    def _start_catch_up(self) -> None:
        threading.Thread(target=self._catch_up, args=(self._gen, self.index, self._index_from),
                         name=f"index-{self.name}", daemon=True).start()

    def _catch_up(self, gen: int, index, done: int) -> None:
        """Bring ``index`` up to date with the collection without holding its lock for long; put it in
        service once nothing is left to add. Abandoned when ``_gen`` changes (close, set_index)."""
        try:
            index.fetch = self.store.rows
            fresh = done == 0 and index.trained and getattr(index, "size", 1) == 0
            while True:
                with self.lock.read():
                    if gen != self._gen:
                        return
                    n = self.n_slots
                    live = self.live[:n].copy()
                if not index.trained or fresh:
                    slots = np.flatnonzero(live)
                    if len(slots) >= index.train_min:
                        index.train(slots, self.store.rows)
                        fresh = False
                elif done < n:
                    new = np.arange(done, n)[live[done:n]]
                    if len(new):
                        index.add(new, self.store.rows(new))
                done = n
                with self.lock.write():
                    if gen != self._gen:
                        return
                    if self.n_slots == done:
                        for s in self._dead_pending:
                            index.mark_dead(s)
                        self._dead_pending = []
                        self.index, self.index_ready = index, True
                        return
        except Exception:  # noqa: BLE001 - searches stay exact; the next restart rebuilds
            if gen == self._gen:
                log.exception("collection %s: the index could not be caught up", self.name)

    # ------------------------------------------------------------ files

    def _open_wal(self) -> None:
        if self.read_only:                 # kept open only as the "collection is open" marker
            self._wal_fd = os.open(self.path / "wal.log", os.O_RDONLY)
            return
        self._wal_fd = os.open(self.path / "wal.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)

    def _log(self, rec: dict) -> None:
        if self._wal_fd is None:          # dropped while this request waited for the lock
            raise NotFound(self.name)
        if self.read_only:
            raise PermissionError("the collection is open read-only")
        self.seq += 1
        line = (json.dumps({"seq": self.seq, **rec}, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
        view = memoryview(line)
        while view:
            view = view[os.write(self._wal_fd, view):]
        self.wal_bytes += len(line)

    def _maybe_checkpoint(self) -> None:
        if self.wal_bytes > CHECKPOINT_BYTES:
            self._checkpoint()

    def _checkpoint(self) -> None:
        n = self.n_slots
        inline = self.store.kind == "memory"
        head = {"seq": self.seq, "slots": n, "ids": self.ids[:n], "payloads": self.payloads[:n],
                "vectors": "inline" if inline else "file"}
        if self.texts is not None:
            head["texts"] = self.texts[:n]
        header = json.dumps(head,
                            separators=(",", ":"), ensure_ascii=False).encode()
        if not inline:
            self.store.sync()
        tmp = self.path / "snapshot.bin.tmp"
        with open(tmp, "wb") as fh:
            fh.write(SNAPSHOT_MAGIC)
            fh.write(header + b"\n")
            if inline:
                fh.write(self.store.prefix(n).astype("<f4").tobytes())
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path / "snapshot.bin")
        self._save_extra()
        os.ftruncate(self._wal_fd, 0)
        self.wal_bytes = 0

    def _index_stamp(self) -> dict:
        return {"seq": self.seq, "slots": self.n_slots, "index": self.index_cfg}

    def _save_extra(self) -> None:
        """The index structure, consistent with the snapshot just written."""
        p = self.path / "index.npz"
        if self.index is None or not self.index_ready:   # a catch-up owns the structure: rebuilt on open
            p.unlink(missing_ok=True)
        else:
            self.index.save(p, self._index_stamp())

    def _load_index(self) -> None:
        """After the snapshot, before the log: the saved graph if it matches (the log's points are
        added by the catch-up), else an empty index for the catch-up to build."""
        if self.index is None:
            return
        self.index_ready = False
        p = self.path / "index.npz"
        live = np.flatnonzero(self.live[: self.n_slots])
        if p.exists() and self.index.load(p, self._index_stamp(), self.store.rows, live):
            self._index_from = self.n_slots
            return
        self.index = indexes.build(self.index_cfg, self.dim, self.metric)
        self._index_from = 0

    def _load_snapshot(self) -> None:
        p = self.path / "snapshot.bin"
        if not p.exists():
            return
        data = p.read_bytes()
        if not data.startswith(SNAPSHOT_MAGIC):
            raise ValueError(f"collection {self.name}: bad snapshot")
        end = data.index(b"\n", len(SNAPSHOT_MAGIC))
        head = json.loads(data[len(SNAPSHOT_MAGIC): end])
        n = int(head["slots"])
        self._grow(n)
        if head.get("vectors", "inline") == "inline":
            vecs = np.frombuffer(data, dtype="<f4", count=n * self.dim, offset=end + 1).reshape(n, self.dim)
            for i in range(0, n, 8192):
                self.store.write(i, vecs[i:i + 8192])
        elif self.store.kind == "memory":                 # the index was switched to flat before a crash
            disk = DiskVectors(self.path / VECTORS_FILE, self.dim, read_only=self.read_only)
            try:
                for i in range(0, n, 8192):
                    self.store.write(i, disk.rows(np.arange(i, min(i + 8192, n))))
            finally:
                disk.close()
        del data
        self.ids = list(head["ids"])
        self.payloads = list(head["payloads"])
        if self.texts is not None:
            self.texts = list(head.get("texts") or [None] * n)
        self.n_slots = n
        for s, pid in enumerate(self.ids):
            if pid is not None:
                self.live[s] = True
                self.slot_of[_restore_id(pid)] = s
        self.ids = [_restore_id(pid) if pid is not None else None for pid in self.ids]
        self.seq = int(head["seq"])

    def _replay(self) -> None:
        p = self.path / "wal.log"
        if not p.exists():
            return
        data = p.read_bytes()
        pos = good = 0
        while pos < len(data):
            end = data.find(b"\n", pos)
            if end < 0:
                break
            try:
                rec = json.loads(data[pos:end])
                seq = int(rec["seq"])
                if seq > self.seq:
                    self._replay_record(rec)
                    self.seq = seq
            except (ValueError, KeyError, TypeError):
                break
            pos = good = end + 1
        if good < len(data) and not self.read_only:
            with open(p, "r+b") as fh:
                fh.truncate(good)
        self.wal_bytes = good

    def _replay_record(self, rec: dict) -> None:
        ids = [_restore_id(pid) for pid in rec["ids"]]
        if rec["op"] == "u":
            vecs = np.frombuffer(base64.b64decode(rec["vectors"]), dtype="<f4").reshape(len(ids), self.dim)
            if len(rec["payloads"]) != len(ids):
                raise ValueError("bad record")
            texts = rec.get("texts")
            if texts is not None and len(texts) != len(ids):
                raise ValueError("bad record")
            self._apply_upsert(ids, vecs, rec["payloads"], texts)
        elif rec["op"] == "d":
            self._apply_delete(ids)
        else:
            raise ValueError("bad record")


def _restore_id(pid: Any) -> Any:
    return pid


class Catalog:
    """Every collection of a data dir."""

    def __init__(self, data_dir: Path, *, read_only: bool = False) -> None:
        self.root = Path(data_dir) / COLLECTIONS_DIR
        self.read_only = read_only
        self.lock = threading.Lock()
        self.colls: dict[str, Collection] = {}
        self.snapshots = snap.SnapshotStore(data_dir)
        if read_only:                       # no recovery or clean-up: leftovers are skipped, not removed
            if self.root.exists():
                for d in sorted(self.root.iterdir()):
                    if not d.name.startswith(".") and d.is_dir() and valid_name(d.name) \
                            and (d / "collection.json").exists():
                        self.colls[d.name] = Collection.load(d, read_only=True)
            return
        self.snapshots.clean()
        if self.root.exists():
            for d in sorted(self.root.iterdir()):               # a restore interrupted mid-swap: undo it
                m = d.name.startswith(".trash-") and d.name[len(".trash-"):].rsplit("-", 1)[0]
                if m and valid_name(m) and not (self.root / m).exists() and (d / "collection.json").exists():
                    os.rename(d, self.root / m)
            for d in sorted(self.root.iterdir()):
                if d.name.startswith("."):
                    shutil.rmtree(d, ignore_errors=True)      # an interrupted create, delete or restore
                elif d.is_dir() and valid_name(d.name) and (d / "collection.json").exists():
                    self.colls[d.name] = Collection.load(d)

    def get(self, name: str) -> Collection:
        c = self.colls.get(name)
        if c is None:
            raise NotFound(name)
        return c

    def list(self) -> list[Collection]:
        return [self.colls[n] for n in sorted(self.colls)]

    def create(self, name: str, dim: int, metric: str, index_cfg: dict | None = None,
               embedding: str | None = None) -> Collection:
        # PLANTED (X01, CWE-22): no name check here (the API layer "already validated" it)
        with self.lock:
            if name in self.colls:
                raise Exists(name)
            self.root.mkdir(exist_ok=True)
            c = Collection.create(self.root, name, dim, metric, index_cfg, embedding)
            self.colls[name] = c
            return c

    def restore(self, name: str, meta: dict, points: bytes) -> Collection:
        """Replace (or create) collection ``name`` with a validated archive's content, atomically: the
        new directory is complete before it is swapped in, and a crash mid-swap is undone on open."""
        assert valid_name(name)
        self.root.mkdir(exist_ok=True)
        tmp = self.root / f".tmp-restore-{uuid.uuid4().hex}"
        tmp.mkdir()
        try:
            cfg = {"name": name, "dim": meta["dim"], "metric": meta["metric"], "index": meta["index"],
                   **({"embedding": meta["embedding"]} if meta.get("embedding") else {})}
            (tmp / "collection.json").write_text(json.dumps(cfg))
            with open(tmp / "snapshot.bin", "wb") as fh:
                fh.write(points)
                fh.flush()
                os.fsync(fh.fileno())
            (tmp / "wal.log").write_bytes(b"")
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        with self.lock:
            old = self.colls.pop(name, None)
            trash = None
            if old is not None:
                with old.lock.write():
                    old._gen += 1
                    if old._wal_fd is not None:
                        os.close(old._wal_fd)
                        old._wal_fd = None
                        old.store.close()
                trash = self.root / f".trash-{name}-{uuid.uuid4().hex}"
                os.rename(old.path, trash)
            os.rename(tmp, self.root / name)
            c = Collection.load(self.root / name)
            self.colls[name] = c
        if trash is not None:
            shutil.rmtree(trash, ignore_errors=True)
        return c

    def drop(self, name: str) -> None:
        with self.lock:
            c = self.colls.pop(name, None)
            if c is None:
                raise NotFound(name)
        with c.lock.write():
            c._gen += 1
            if c._wal_fd is not None:
                os.close(c._wal_fd)
                c._wal_fd = None
                c.store.close()
            trash = self.root / f".trash-{name}-{uuid.uuid4().hex}"
            os.rename(c.path, trash)
            shutil.rmtree(trash, ignore_errors=True)
        self.snapshots.drop_collection(name)

    def close(self) -> None:
        for c in list(self.colls.values()):
            c.close()
