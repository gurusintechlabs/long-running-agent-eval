"""Collection snapshots (stage 7): portable tar archives, kept per collection in the data dir.

An archive holds exactly two regular files:

* ``collection.json``: ``{"format": 1, "dim", "metric", "index", "embedding"?}``;
* ``points.bin``: the collection snapshot format of ``store.py`` (``MINIDB-COLLECTION 1``, a JSON
  header ``{"seq": 0, "slots", "ids", "payloads", "vectors": "inline", "texts"?}``, then the float32
  vectors), holding the live points only.

The index structure is not in the archive: a restore rebuilds it from the points (in the background,
like any open), so nothing in an archive is ever used as a file name, a link or a code path. Archives
come from users: ``parse_archive`` reads only those two members, by name, into memory, and checks
every field before anything is written.

Stored snapshots live in ``DIR/snapshots/<collection>/<n>-<name>.tar`` (``n`` orders them by
creation), are written to a temp file and renamed, and are deleted with their collection.
"""
from __future__ import annotations

import io
import json
import os
import re
import secrets
import shutil
import tarfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from minidb import index as indexes
from minidb.collection import points as pv

ARCHIVE_FORMAT = 1
MAGIC = b"MINIDB-COLLECTION 1\n"
MEMBERS = ("collection.json", "points.bin")
MAX_ARCHIVE = 256 << 20
NAME_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,127}")
SNAPSHOTS_DIR = "snapshots"
FILE_RE = re.compile(r"(\d{8})-([a-z0-9][a-z0-9_.-]{0,127})\.tar")


class InvalidArchive(ValueError):
    """The archive is not a usable snapshot (400)."""


class SnapshotExists(Exception):
    pass


def valid_name(name: Any) -> bool:
    return isinstance(name, str) and NAME_RE.fullmatch(name) is not None


# ------------------------------------------------------------------ archives

def _tar(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tf:
        for name, data in members.items():
            ti = tarfile.TarInfo(name)
            ti.size, ti.mode, ti.mtime = len(data), 0o644, 0
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def points_bin(ids: list, payloads: list, vectors: np.ndarray, texts: list | None) -> bytes:
    head = {"seq": 0, "slots": len(ids), "ids": ids, "payloads": payloads, "vectors": "inline"}
    if texts is not None:
        head["texts"] = texts
    return (MAGIC + json.dumps(head, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
            + np.ascontiguousarray(vectors, dtype="<f4").tobytes())


def build_archive(meta: dict, ids: list, payloads: list, vectors: np.ndarray, texts: list | None) -> bytes:
    """``meta``: dim, metric, index and (text collections) embedding."""
    head = {"format": ARCHIVE_FORMAT, **{k: meta[k] for k in ("dim", "metric", "index", "embedding") if k in meta}}
    return _tar({"collection.json": json.dumps(head).encode(),
                 "points.bin": points_bin(ids, payloads, vectors, texts)})


def _members(data: bytes) -> dict[str, bytes]:
    if not data:
        raise InvalidArchive("the body is empty")
    out: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tf:
            for m in tf:
                if not m.isreg() or m.name not in MEMBERS or m.name in out:
                    raise InvalidArchive("the archive holds an unexpected member")
                if m.size > MAX_ARCHIVE:
                    raise InvalidArchive("an archive member is too large")
                fh = tf.extractfile(m)
                blob = fh.read() if fh is not None else b""
                if len(blob) != m.size:
                    raise InvalidArchive("the archive is truncated")
                out[m.name] = blob
    except (tarfile.TarError, EOFError, OSError) as e:
        raise InvalidArchive("the body is not a readable tar archive") from e
    if set(out) != set(MEMBERS):
        raise InvalidArchive("the archive is not a minidb snapshot")
    return out


def parse_archive(data: bytes) -> tuple[dict, bytes]:
    """``(meta, points.bin)`` of a valid archive, else InvalidArchive."""
    m = _members(data)
    try:
        meta = json.loads(m["collection.json"].decode("utf-8"), parse_constant=_no_constant)
        if not isinstance(meta, dict) or meta.get("format") != ARCHIVE_FORMAT:
            raise InvalidArchive("unsupported snapshot format")
        dim, metric = pv.parse_collection_spec({"dim": meta.get("dim"), "metric": meta.get("metric")})
        index = indexes.parse_index(meta.get("index"), dim)
        embedding = pv.parse_embedding({k: meta[k] for k in ("embedding",) if k in meta}, dim)
    except (ValueError, UnicodeDecodeError, RecursionError, pv.Invalid) as e:
        raise InvalidArchive(f"invalid collection.json: {e}") from None
    out = {"dim": dim, "metric": metric, "index": index, **({"embedding": embedding} if embedding else {})}
    check_points(m["points.bin"], dim, metric, embedding is not None)
    return out, m["points.bin"]


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not valid JSON")


def check_points(blob: bytes, dim: int, metric: str, text: bool) -> None:
    """``points.bin`` must be exactly what ``points_bin`` writes for valid points."""
    if not blob.startswith(MAGIC):
        raise InvalidArchive("points.bin is not a collection snapshot")
    end = blob.find(b"\n", len(MAGIC))
    if end < 0:
        raise InvalidArchive("points.bin has no header")
    try:
        head = json.loads(blob[len(MAGIC):end].decode("utf-8"), parse_constant=_no_constant)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise InvalidArchive("points.bin has an invalid header") from None
    if not isinstance(head, dict) or head.get("vectors") != "inline" or head.get("seq") != 0:
        raise InvalidArchive("points.bin has an invalid header")
    n, ids, payloads = head.get("slots"), head.get("ids"), head.get("payloads")
    if not pv.is_int(n) or not isinstance(ids, list) or not isinstance(payloads, list) or not (
            len(ids) == len(payloads) == n):
        raise InvalidArchive("points.bin: inconsistent point counts")
    texts = head.get("texts")
    if text != (texts is not None) or (texts is not None and (
            not isinstance(texts, list) or len(texts) != n or not all(isinstance(x, str) for x in texts))):
        raise InvalidArchive("points.bin: texts do not match the collection")
    seen = set()
    try:
        for pid, payload in zip(ids, payloads, strict=True):
            if pv.parse_id(pid) != pid or pid in seen:
                raise InvalidArchive("points.bin: invalid or duplicate point id")
            seen.add(pid)
            pv.parse_payload(payload)
    except pv.Invalid as e:
        raise InvalidArchive(f"points.bin: {e}") from None
    body = blob[end + 1:]
    if len(body) != n * dim * 4:
        raise InvalidArchive("points.bin: the vector data has the wrong length")
    vecs = np.frombuffer(body, dtype="<f4")
    if not np.isfinite(vecs).all():
        raise InvalidArchive("points.bin: non-finite vector values")
    if metric == "cosine" and n and not np.abs(vecs.reshape(n, dim)).sum(1).all():
        raise InvalidArchive("points.bin: a zero vector in a cosine collection")


# ------------------------------------------------------------------ stored snapshots

class SnapshotStore:
    """The stored snapshots of every collection of a data dir."""

    def __init__(self, data_dir: Path) -> None:
        self.root = Path(data_dir) / SNAPSHOTS_DIR
        self.lock = threading.Lock()

    def _dir(self, collection: str) -> Path:
        assert pv.valid_name(collection)
        return self.root / collection

    def _files(self, collection: str) -> list[tuple[int, str, Path]]:
        d = self._dir(collection)
        if not d.is_dir():
            return []
        out = []
        for p in d.iterdir():
            m = FILE_RE.fullmatch(p.name)
            if m and p.is_file():
                out.append((int(m.group(1)), m.group(2), p))
        return sorted(out)

    def find(self, collection: str, name: str) -> Path | None:
        if not valid_name(name):
            return None
        return next((p for _, n, p in self._files(collection) if n == name), None)

    def list(self, collection: str) -> list[dict]:
        out = []
        for _, name, p in self._files(collection):
            st = p.stat()
            created = datetime.fromtimestamp(st.st_mtime, UTC).isoformat(timespec="milliseconds")
            out.append({"name": name, "size": st.st_size, "created": created.replace("+00:00", "Z")})
        return out

    def save(self, collection: str, name: str | None, data: bytes) -> dict:
        with self.lock:
            files = self._files(collection)
            if name is None:
                while True:
                    name = datetime.now(UTC).strftime("snap-%Y%m%d-%H%M%S-") + secrets.token_hex(2)
                    if all(n != name for _, n, _ in files):
                        break
            elif any(n == name for _, n, _ in files):
                raise SnapshotExists(name)
            d = self._dir(collection)
            d.mkdir(parents=True, exist_ok=True)
            seq = (files[-1][0] + 1) if files else 1
            tmp = d / f".tmp-{secrets.token_hex(8)}"
            with open(tmp, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, d / f"{seq:08d}-{name}.tar")
            return {"name": name, "size": len(data)}

    def delete(self, collection: str, name: str) -> bool:
        with self.lock:
            p = self.find(collection, name)
            if p is None:
                return False
            p.unlink()
            return True

    def drop_collection(self, collection: str) -> None:
        with self.lock:
            d = self._dir(collection)
            if d.exists():
                trash = self.root / f".trash-{collection}-{secrets.token_hex(8)}"
                os.rename(d, trash)
                shutil.rmtree(trash, ignore_errors=True)

    def clean(self) -> None:
        """Leftovers of interrupted saves and deletes (on open)."""
        if not self.root.is_dir():
            return
        for d in self.root.iterdir():
            if d.name.startswith("."):
                shutil.rmtree(d, ignore_errors=True)
            elif d.is_dir():
                for p in d.iterdir():
                    if p.name.startswith(".tmp-"):
                        p.unlink(missing_ok=True)
