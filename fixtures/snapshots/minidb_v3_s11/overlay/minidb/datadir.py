"""Data directories (docs/STORAGE.md) and the writer lock protocol (ENVIRONMENT.md).

A writer opens a data dir in this order, so that a refused open never changes anything in it:

1. check the format: ``FORMAT`` must hold ``minidb-data 1`` or ``minidb-data 2``; a dir without
   ``FORMAT`` must be empty (apart from ``LOCK`` and our own temp files), else it is not a data dir;
2. take an exclusive, non-blocking ``fcntl.flock`` on ``DIR/LOCK``; if it is busy, report the holder
   (the content of ``LOCK``) and give up;
3. format 2 closed cleanly: check every file against ``MANIFEST.json`` (a mismatch refuses the open,
   still without changing anything);
4. only then migrate a format-1 dir (CR-5), initialise an empty dir as format 2, mark the manifest
   open, and record this process as the holder.

The lock is held until ``close()`` (or process exit). ``seal()``, after a clean shutdown, writes the
exact manifest and marks it closed.

``MANIFEST.json`` (format 2): ``{"format": 2, "state": "closed" | "open", "files": {path: {"size",
"sha256"}}}``. ``files`` lists every file under the dir but ``LOCK`` and the manifest itself, and is
exact whenever ``state`` is ``closed``. A dir whose manifest is ``open`` (or missing) was not closed
cleanly: its writer crashed, and the stores recover it as before (stage 7).

Migration from format 1 is crash-safe: the closed manifest of the format-2 dir (listing ``FORMAT``
with its new content) is written first, then ``FORMAT`` is replaced, each with a temp file and a
rename. A crash before the second rename leaves a format-1 dir (the stray manifest is rewritten by
the next migration); after it, a complete format-2 dir. The data files themselves do not move.

A read-only open (``--read-only``, stage 9) takes no lock and writes nothing, not even ``LOCK``: the
dir must already be a data dir (a missing or empty one is an error). It serves format 1 and 2,
migrates nothing, and reports a manifest mismatch on stderr instead of refusing.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sys
from pathlib import Path

FORMAT_V1 = "minidb-data 1"
FORMAT_V2 = "minidb-data 2"
FORMAT_LINE = FORMAT_V2
FORMAT_FILE = "FORMAT"
LOCK_FILE = "LOCK"
MANIFEST_FILE = "MANIFEST.json"
TEMP_FILES = (FORMAT_FILE + ".tmp", MANIFEST_FILE + ".tmp")
NOT_LISTED = (LOCK_FILE, MANIFEST_FILE)


class DataDirError(Exception):
    """The data dir cannot be used (exit status 2)."""


class LockBusy(DataDirError):
    """Another process holds the writer lock (exit status 3)."""

    def __init__(self, holder: str) -> None:
        super().__init__(f"the data dir is locked by: {holder or '(unknown holder)'}")
        self.holder = holder


def check_format(path: Path) -> int:
    """The format of the data dir at ``path`` (1 or 2), or 0 if it is missing or empty; else
    DataDirError."""
    if not path.exists():
        return 0
    if not path.is_dir():
        raise DataDirError("the data dir path exists and is not a directory")
    fmt = path / FORMAT_FILE
    if fmt.exists():
        try:
            line = fmt.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            line = None
        if line == FORMAT_V1:
            return 1
        if line == FORMAT_V2:
            return 2
        raise DataDirError(f"unsupported data dir format {line!r} (expected {FORMAT_V1!r} or {FORMAT_V2!r})")
    if any(p.name not in (LOCK_FILE, MANIFEST_FILE, *TEMP_FILES) for p in path.iterdir()):
        raise DataDirError("not a minidb data dir (no FORMAT file, and the directory is not empty)")
    return 0


# ------------------------------------------------------------------ the manifest

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def listing(path: Path) -> dict[str, dict]:
    """Every file under ``path`` (but LOCK and the manifest) with its size and SHA-256."""
    out = {}
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for name in sorted(files):
            p = Path(root) / name
            rel = p.relative_to(path).as_posix()
            if rel in NOT_LISTED or not p.is_file():
                continue
            out[rel] = {"size": p.stat().st_size, "sha256": _sha256(p)}
    return out


def read_manifest(path: Path) -> dict | None:
    try:
        m = json.loads((path / MANIFEST_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(m, dict) or m.get("format") != 2 or not isinstance(m.get("files"), dict):
        return None
    return m


def mismatches(path: Path, manifest: dict) -> list[str]:
    """Files that do not match a closed manifest: missing, changed (size or SHA-256), or not listed."""
    want, have = manifest["files"], listing(path)
    out = []
    for rel in sorted(set(want) | set(have)):
        if rel not in have:
            out.append(f"{rel}: missing")
        elif rel not in want:
            out.append(f"{rel}: not listed in {MANIFEST_FILE}")
        elif (want[rel].get("size"), want[rel].get("sha256")) != (have[rel]["size"], have[rel]["sha256"]):
            out.append(f"{rel}: size or SHA-256 differs from {MANIFEST_FILE}")
    return out


def _write_manifest(path: Path, state: str, files: dict) -> None:
    _write_atomic(path / MANIFEST_FILE, json.dumps({"format": 2, "state": state, "files": files}, indent=1,
                                                  sort_keys=True) + "\n")


def _verify(path: Path, *, read_only: bool) -> None:
    """Check a format-2 dir against its manifest if its last writer closed it cleanly."""
    m = read_manifest(path)
    if m is None or m.get("state") != "closed":
        if read_only:
            _report(f"{path}: the last writer did not close the data dir cleanly; files not verified")
        return
    bad = mismatches(path, m)
    if not bad:
        return
    msg = f"{path}: the data dir does not match {MANIFEST_FILE}: " + "; ".join(bad)
    if not read_only:
        raise DataDirError(msg)
    _report(msg)


def _report(msg: str) -> None:
    print(f"minidb: {msg}", file=sys.stderr, flush=True)


# ------------------------------------------------------------------ data dirs

class DataDir:
    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = Path(path).absolute()
        self.read_only = read_only
        self.format = 0
        self._lock_fd: int | None = None

    def open(self) -> DataDir:
        fmt = check_format(self.path)
        if self.read_only:
            if not fmt:
                raise DataDirError("a read-only server needs an existing data dir")
            if fmt == 2:
                _verify(self.path, read_only=True)
            self.format = fmt
            return self
        self._lock("minidb-server")
        try:
            fmt = check_format(self.path)       # again, under the lock
            if fmt == 2:
                _verify(self.path, read_only=False)
            self.record_holder()
            if fmt == 1:
                migrate_locked(self.path)
            elif fmt == 0:
                _init_empty(self.path)
            _write_manifest(self.path, "open", {})
            self.format = 2
        except BaseException:
            self.close()
            raise
        return self

    def migrate(self) -> bool:
        """``python -m minidb migrate``: migrate a format-1 dir under the writer lock; True if it did.
        A format-2 dir is left as it is."""
        if not check_format(self.path):
            raise DataDirError("not a minidb data dir (missing or empty)")
        self._lock("minidb-migrate")
        try:
            fmt = check_format(self.path)
            self.record_holder()
            if fmt == 1:
                migrate_locked(self.path)
            return fmt == 1
        finally:
            self.close()

    def _lock(self, who: str) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path / LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder = _read_holder(fd)
            os.close(fd)
            raise LockBusy(holder) from None
        self._lock_fd = fd
        self._holder = f"{who} pid {os.getpid()}\n".encode()

    def file(self, name: str) -> Path:
        return self.path / name

    def seal(self) -> None:
        """After a clean shutdown (everything written and closed): the exact manifest, closed."""
        if self._lock_fd is not None and not self.read_only:
            _write_manifest(self.path, "closed", listing(self.path))
            _fsync_dir(self.path)

    def close(self) -> None:
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(self._lock_fd)
                self._lock_fd = None

    def record_holder(self) -> None:
        if self._lock_fd is not None:
            os.ftruncate(self._lock_fd, 0)
            os.pwrite(self._lock_fd, self._holder, 0)


def _init_empty(path: Path) -> None:
    for name in TEMP_FILES + (MANIFEST_FILE,):
        (path / name).unlink(missing_ok=True)
    _write_atomic(path / FORMAT_FILE, FORMAT_V2 + "\n")     # no manifest yet: not closed cleanly


def migrate_locked(path: Path) -> None:
    """Format 1 -> 2 in place (the caller holds the lock); see the module docstring."""
    for name in TEMP_FILES:
        (path / name).unlink(missing_ok=True)
    files = listing(path)
    new_format = (FORMAT_V2 + "\n").encode()
    files[FORMAT_FILE] = {"size": len(new_format), "sha256": hashlib.sha256(new_format).hexdigest()}
    _write_manifest(path, "closed", files)
    _write_atomic(path / FORMAT_FILE, FORMAT_V2 + "\n")
    _fsync_dir(path)


def _read_holder(fd: int) -> str:
    try:
        return os.pread(fd, 4096, 0).decode("utf-8", "replace").strip()
    except OSError:
        return ""


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
