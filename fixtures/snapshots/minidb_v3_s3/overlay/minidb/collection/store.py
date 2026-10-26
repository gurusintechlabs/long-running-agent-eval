"""Durable collections: points in memory, a write-ahead log and snapshots in the data dir.

Layout, under ``DIR/collections/<name>/`` (names are validated, so a name is always one plain
directory entry):

* ``collection.json``: name, dim, metric and index configuration (replaced atomically);
* ``snapshot.bin``: a header line ``MINIDB-COLLECTION 1``, a JSON line ``{"seq", "slots", "ids",
  "payloads"}``, then ``slots x dim`` little-endian float32 values (written to a temp file, then
  renamed);
* ``wal.log``: one JSON line per acknowledged change, written with a single ``write`` before the
  request is answered: ``{"seq", "op": "u", "ids", "payloads", "vectors": <base64 float32>}`` or
  ``{"seq", "op": "d", "ids"}``. A torn last line (a crash mid-write) is discarded on recovery, so a
  request is applied completely or not at all.

* ``index.npz``: the index structure as of the snapshot (stamped with its ``seq``), so a restart
  does not rebuild the graph; points logged after it are added on replay.

Points live in slots. A slot is never reused: an update or delete marks the old slot dead, so slot
numbers stay stable for an index. Checkpoints (on size, and at shutdown) write the snapshot and
truncate the log; records already in the snapshot (``seq <= snapshot seq``) are skipped on replay.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from minidb import index as indexes
from minidb.collection.filters import compile_filter
from minidb.collection.points import id_key, valid_name
from minidb.locks import RWLock

SNAPSHOT_MAGIC = b"MINIDB-COLLECTION 1\n"
CHECKPOINT_BYTES = 64 << 20
BUILD_BATCH = 1000
COLLECTIONS_DIR = "collections"


class NotFound(LookupError):
    pass


class Exists(Exception):
    pass


class Collection:
    def __init__(self, path: Path, name: str, dim: int, metric: str, index_cfg: dict | None = None) -> None:
        self.path, self.name, self.dim, self.metric = Path(path), name, dim, metric
        self.index_cfg = dict(index_cfg or indexes.FLAT)
        self.index = indexes.build(self.index_cfg, dim, metric)
        self.lock = RWLock()
        self.cap = 0
        self.n_slots = 0
        self.vectors = np.zeros((0, dim), np.float32)
        self.live = np.zeros(0, bool)
        self.ids: list[Any] = []
        self.payloads: list[Any] = []
        self.slot_of: dict[Any, int] = {}
        self.seq = 0
        self.wal_bytes = 0
        self._wal_fd: int | None = None

    # ------------------------------------------------------------ lifecycle

    @classmethod
    def create(cls, root: Path, name: str, dim: int, metric: str, index_cfg: dict | None = None) -> Collection:
        tmp = root / f".tmp-{name}-{uuid.uuid4().hex}"
        tmp.mkdir(parents=True)
        cfg = dict(index_cfg or indexes.FLAT)
        (tmp / "collection.json").write_text(json.dumps({"name": name, "dim": dim, "metric": metric, "index": cfg}))
        (tmp / "wal.log").write_bytes(b"")
        final = root / name
        try:
            os.rename(tmp, final)
        except OSError:
            shutil.rmtree(tmp, ignore_errors=True)
            raise Exists(name) from None
        c = cls(final, name, dim, metric, cfg)
        c._open_wal()
        return c

    @classmethod
    def load(cls, path: Path) -> Collection:
        meta = json.loads((path / "collection.json").read_text())
        c = cls(path, meta["name"], int(meta["dim"]), meta["metric"], meta.get("index"))
        c._load_snapshot()
        c._load_index()
        c._replay()
        c._open_wal()
        return c

    def close(self) -> None:
        with self.lock.write():
            if self._wal_fd is not None:
                self._checkpoint()
                os.close(self._wal_fd)
                self._wal_fd = None

    # ------------------------------------------------------------ queries

    def count(self) -> int:
        return len(self.slot_of)

    def info(self) -> dict:
        return {"name": self.name, "dim": self.dim, "metric": self.metric, "points": self.count(),
                "index": dict(self.index_cfg)}

    def get(self, pid: Any) -> dict | None:
        with self.lock.read():
            slot = self.slot_of.get(pid)
            if slot is None:
                return None
            return {"id": pid, "vector": self.vectors[slot].astype(float).tolist(), "payload": self.payloads[slot]}

    @property
    def descending(self) -> bool:
        """CR-1: similarities (cosine, dot) rank highest first; l2 distances lowest first."""
        return self.metric != "l2"

    def scores(self, q: np.ndarray, slots: np.ndarray) -> np.ndarray:
        """Exact scores (float64) of ``slots``: the l2 distance, the cosine similarity or the inner
        product (CR-1)."""
        v = self.vectors[slots].astype(np.float64)
        if self.metric == "l2":
            d = v - q
            return np.sqrt(np.einsum("ij,ij->i", d, d))
        dots = v @ q
        if self.metric == "dot":
            return dots
        return dots / (np.linalg.norm(v, axis=1) * np.linalg.norm(q))

    def matching_slots(self, pred: Any) -> np.ndarray:
        """Live slots whose point matches the compiled filter ``pred`` (None: every point)."""
        slots = np.flatnonzero(self.live[: self.n_slots])
        if pred is None:
            return slots
        ids, payloads = self.ids, self.payloads
        return np.array([s for s in slots.tolist() if pred(ids[s], payloads[s])], dtype=np.int64)

    def search(self, q: np.ndarray, k: int, flt: Any = None, *, ef: int = indexes.DEFAULT_EF,
               with_payload: bool = False, with_vector: bool = False) -> list[dict]:
        return self.query(q, k, compile_filter(flt), ef=ef, with_payload=with_payload, with_vector=with_vector)[0]

    def query(self, q: np.ndarray, k: int, pred: Any, *, ef: int = indexes.DEFAULT_EF, with_payload: bool = False,
              with_vector: bool = False) -> tuple[list[dict], dict]:
        """``(results, explain)``: exact over the matching points (flat), or the index's candidates
        re-ranked exactly (hnsw)."""
        with self.lock.read():
            if self.index is None:
                slots = self.matching_slots(pred)
                explain = {"index": "flat", "exact": True, "ef": None, "candidates": len(slots)}
            else:
                ef = max(ef, k)
                allowed = None
                if pred is not None:
                    allowed = np.zeros(self.n_slots, bool)
                    allowed[self.matching_slots(pred)] = True
                slots = self.index.search(q, k, ef, allowed)
                explain = {"index": self.index.kind, "exact": False, "ef": ef, "candidates": len(slots)}
            return self.results(slots, self.scores(q, slots), k, with_payload, with_vector), explain

    def set_index(self, cfg: dict) -> None:
        """Replace the index: built over the current points, then recorded and checkpointed."""
        with self.lock.write():
            if self._wal_fd is None:
                raise NotFound(self.name)
            index = indexes.build(cfg, self.dim, self.metric)
            if index is not None:
                live = np.flatnonzero(self.live[: self.n_slots])
                for i in range(0, len(live), BUILD_BATCH):
                    batch = live[i:i + BUILD_BATCH]
                    index.add(batch, self.vectors[batch])
            meta = {"name": self.name, "dim": self.dim, "metric": self.metric, "index": cfg}
            tmp = self.path / "collection.json.tmp"
            tmp.write_text(json.dumps(meta))
            os.replace(tmp, self.path / "collection.json")
            self.index_cfg, self.index = dict(cfg), index
            self._checkpoint()

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
        out = []
        for i in order:
            s = int(slots[i])
            r = {"id": self.ids[s], "score": float(scores[i])}
            if with_payload:
                r["payload"] = self.payloads[s]
            if with_vector:
                r["vector"] = self.vectors[s].astype(float).tolist()
            out.append(r)
        return out

    # ------------------------------------------------------------ changes

    def upsert(self, ids: list, vecs: np.ndarray, payloads: list) -> int:
        with self.lock.write():
            if ids:
                self._log({"op": "u", "ids": ids, "payloads": payloads,
                           "vectors": base64.b64encode(vecs.astype("<f4").tobytes()).decode("ascii")})
                self._apply_upsert(ids, vecs, payloads)
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
        v = np.zeros((cap, self.dim), np.float32)
        v[: self.n_slots] = self.vectors[: self.n_slots]
        live = np.zeros(cap, bool)
        live[: self.n_slots] = self.live[: self.n_slots]
        self.vectors, self.live, self.cap = v, live, cap

    def _apply_upsert(self, ids: list, vecs: np.ndarray, payloads: list) -> np.ndarray:
        start = self.n_slots
        self._grow(start + len(ids))
        for pid in ids:
            old = self.slot_of.get(pid)
            if old is not None:
                self.live[old] = False
                self.payloads[old] = None
                self.ids[old] = None
                self._slot_died(old)
        slots = np.arange(start, start + len(ids))
        self.vectors[start: start + len(ids)] = vecs
        self.live[start: start + len(ids)] = True
        self.ids.extend(ids)
        self.payloads.extend(payloads)
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
                self._slot_died(s)

    def _slots_added(self, slots: np.ndarray) -> None:
        if self.index is not None:
            self.index.add(slots, self.vectors[slots])

    def _slot_died(self, slot: int) -> None:
        if self.index is not None:
            self.index.mark_dead(slot)

    # ------------------------------------------------------------ files

    def _open_wal(self) -> None:
        self._wal_fd = os.open(self.path / "wal.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)

    def _log(self, rec: dict) -> None:
        if self._wal_fd is None:          # dropped while this request waited for the lock
            raise NotFound(self.name)
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
        header = json.dumps({"seq": self.seq, "slots": n, "ids": self.ids[:n], "payloads": self.payloads[:n]},
                            separators=(",", ":"), ensure_ascii=False).encode()
        tmp = self.path / "snapshot.bin.tmp"
        with open(tmp, "wb") as fh:
            fh.write(SNAPSHOT_MAGIC)
            fh.write(header + b"\n")
            fh.write(self.vectors[:n].astype("<f4").tobytes())
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
        if self.index is None:
            p.unlink(missing_ok=True)
        else:
            self.index.save(p, self._index_stamp())

    def _load_index(self) -> None:
        """After the snapshot, before the log: the saved graph if it matches, else a rebuild."""
        if self.index is None:
            return
        p = self.path / "index.npz"
        if p.exists() and self.index.load(p, self._index_stamp(), self.vectors[: self.n_slots]):
            return
        self.index = indexes.build(self.index_cfg, self.dim, self.metric)
        live = np.flatnonzero(self.live[: self.n_slots])
        for i in range(0, len(live), BUILD_BATCH):
            batch = live[i:i + BUILD_BATCH]
            self.index.add(batch, self.vectors[batch])

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
        vecs = np.frombuffer(data, dtype="<f4", count=n * self.dim, offset=end + 1).reshape(n, self.dim)
        self._grow(n)
        self.vectors[:n] = vecs
        self.ids = list(head["ids"])
        self.payloads = list(head["payloads"])
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
        if good < len(data):
            with open(p, "r+b") as fh:
                fh.truncate(good)
        self.wal_bytes = good

    def _replay_record(self, rec: dict) -> None:
        ids = [_restore_id(pid) for pid in rec["ids"]]
        if rec["op"] == "u":
            vecs = np.frombuffer(base64.b64decode(rec["vectors"]), dtype="<f4").reshape(len(ids), self.dim)
            if len(rec["payloads"]) != len(ids):
                raise ValueError("bad record")
            self._apply_upsert(ids, vecs, rec["payloads"])
        elif rec["op"] == "d":
            self._apply_delete(ids)
        else:
            raise ValueError("bad record")


def _restore_id(pid: Any) -> Any:
    return pid


class Catalog:
    """Every collection of a data dir."""

    def __init__(self, data_dir: Path) -> None:
        self.root = Path(data_dir) / COLLECTIONS_DIR
        self.lock = threading.Lock()
        self.colls: dict[str, Collection] = {}
        if self.root.exists():
            for d in sorted(self.root.iterdir()):
                if d.name.startswith("."):
                    shutil.rmtree(d, ignore_errors=True)      # an interrupted create or delete
                elif d.is_dir() and valid_name(d.name) and (d / "collection.json").exists():
                    self.colls[d.name] = Collection.load(d)

    def get(self, name: str) -> Collection:
        c = self.colls.get(name)
        if c is None:
            raise NotFound(name)
        return c

    def list(self) -> list[Collection]:
        return [self.colls[n] for n in sorted(self.colls)]

    def create(self, name: str, dim: int, metric: str, index_cfg: dict | None = None) -> Collection:
        assert valid_name(name)
        with self.lock:
            if name in self.colls:
                raise Exists(name)
            self.root.mkdir(exist_ok=True)
            c = Collection.create(self.root, name, dim, metric, index_cfg)
            self.colls[name] = c
            return c

    def drop(self, name: str) -> None:
        with self.lock:
            c = self.colls.pop(name, None)
            if c is None:
                raise NotFound(name)
        with c.lock.write():
            if c._wal_fd is not None:
                os.close(c._wal_fd)
                c._wal_fd = None
            trash = self.root / f".trash-{name}-{uuid.uuid4().hex}"
            os.rename(c.path, trash)
            shutil.rmtree(trash, ignore_errors=True)

    def close(self) -> None:
        for c in list(self.colls.values()):
            c.close()
