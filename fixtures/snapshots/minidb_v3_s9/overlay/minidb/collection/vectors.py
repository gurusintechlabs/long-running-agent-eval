"""Where a collection keeps its float32 vectors, by slot.

* ``MemoryVectors``: one numpy array (``flat`` collections, whose every search scans all vectors);
* ``DiskVectors``: the file ``vectors.f32`` in the collection directory, row ``s`` at byte
  ``s * dim * 4``, read with ``pread`` (indexed collections: an index answers from its own compact
  structure, and only its candidates are read back for exact scoring, so the vectors need not stay in
  memory).

Rows are written once (slots are never reused). The file is flushed to disk before a checkpoint that
relies on it; rows written after the last checkpoint are rewritten by log replay after a crash.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

FILE = "vectors.f32"


class MemoryVectors:
    kind = "memory"

    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.cap = 0
        self.data = np.zeros((0, dim), np.float32)

    def write(self, start: int, vecs: np.ndarray) -> None:
        end = start + len(vecs)
        if end > self.cap:
            cap = max(end, 2 * self.cap, 256)
            grown = np.zeros((cap, self.dim), np.float32)
            grown[: self.cap] = self.data[: self.cap]
            self.data, self.cap = grown, cap
        self.data[start:end] = vecs

    def rows(self, slots: np.ndarray) -> np.ndarray:
        return self.data[np.asarray(slots, np.int64)]

    def prefix(self, n: int) -> np.ndarray:
        return self.data[:n]

    def sync(self) -> None:
        pass

    def close(self) -> None:
        self.data = np.zeros((0, self.dim), np.float32)
        self.cap = 0


class DiskVectors:
    kind = "disk"

    def __init__(self, path: Path, dim: int, *, read_only: bool = False) -> None:
        self.path = Path(path)
        self.dim = dim
        self.row = dim * 4
        self.fd = os.open(self.path, os.O_RDONLY) if read_only else os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)

    def write(self, start: int, vecs: np.ndarray) -> None:
        data = np.ascontiguousarray(vecs, dtype="<f4").tobytes()
        view, off = memoryview(data), start * self.row
        while view:
            n = os.pwrite(self.fd, view, off)
            view, off = view[n:], off + n

    def rows(self, slots: np.ndarray) -> np.ndarray:
        """The rows of ``slots`` (in that order); runs of consecutive slots are read at once."""
        slots = np.asarray(slots, np.int64)
        out = np.empty((len(slots), self.dim), np.float32)
        if not len(slots):
            return out
        order = np.argsort(slots, kind="stable")
        s = slots[order]
        breaks = np.flatnonzero(np.diff(s) != 1) + 1
        starts = np.concatenate([[0], breaks])
        ends = np.concatenate([breaks, [len(s)]])
        for a, b in zip(starts.tolist(), ends.tolist(), strict=True):
            first = int(s[a])
            want = (b - a) * self.row
            buf = os.pread(self.fd, want, first * self.row)
            if len(buf) < want:
                buf += bytes(want - len(buf))
            out[order[a:b]] = np.frombuffer(buf, "<f4").reshape(b - a, self.dim)
        return out

    def prefix(self, n: int) -> np.ndarray:
        return self.rows(np.arange(n))

    def sync(self) -> None:
        os.fsync(self.fd)

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
