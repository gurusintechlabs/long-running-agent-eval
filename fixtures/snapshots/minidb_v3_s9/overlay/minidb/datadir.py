"""Data directories (docs/STORAGE.md) and the writer lock protocol (ENVIRONMENT.md).

A writer opens a data dir in this order, so that a refused open never changes anything in it:

1. check the format: ``FORMAT`` must hold ``minidb-data 1``; a dir without ``FORMAT`` must be empty
   (apart from ``LOCK``), else it is not a data dir;
2. take an exclusive, non-blocking ``fcntl.flock`` on ``DIR/LOCK``; if it is busy, report the holder
   (the content of ``LOCK``) and give up;
3. only then initialise an empty dir and record this process as the holder.

The lock is held until ``close()`` (or process exit).

A read-only open (``--read-only``, stage 9; ENVIRONMENT.md) takes no lock and writes nothing, not even
``LOCK``: the dir must already be a data dir (a missing or empty one is an error).
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path

FORMAT_LINE = "minidb-data 1"
FORMAT_FILE = "FORMAT"
LOCK_FILE = "LOCK"


class DataDirError(Exception):
    """The data dir cannot be used (exit status 2)."""


class LockBusy(DataDirError):
    """Another process holds the writer lock (exit status 3)."""

    def __init__(self, holder: str) -> None:
        super().__init__(f"the data dir is locked by: {holder or '(unknown holder)'}")
        self.holder = holder


def check_format(path: Path) -> bool:
    """True if ``path`` is a format-1 data dir, False if it is missing or empty; else DataDirError."""
    if not path.exists():
        return False
    if not path.is_dir():
        raise DataDirError("the data dir path exists and is not a directory")
    fmt = path / FORMAT_FILE
    if fmt.exists():
        try:
            line = fmt.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            line = None
        if line != FORMAT_LINE:
            raise DataDirError(f"unsupported data dir format {line!r} (expected {FORMAT_LINE!r})")
        return True
    if any(p.name != LOCK_FILE for p in path.iterdir()):
        raise DataDirError("not a minidb data dir (no FORMAT file, and the directory is not empty)")
    return False


class DataDir:
    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = Path(path).absolute()
        self.read_only = read_only
        self._lock_fd: int | None = None

    def open(self) -> DataDir:
        initialised = check_format(self.path)
        if self.read_only:
            if not initialised:
                raise DataDirError("a read-only server needs an existing data dir")
            return self
        self.path.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path / LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder = _read_holder(fd)
            os.close(fd)
            raise LockBusy(holder) from None
        self._lock_fd = fd
        try:
            if not initialised and not check_format(self.path):
                _write_atomic(self.path / FORMAT_FILE, FORMAT_LINE + "\n")
            os.ftruncate(fd, 0)
            os.pwrite(fd, f"minidb-server pid {os.getpid()}\n".encode(), 0)
        except BaseException:
            self.close()
            raise
        return self

    def file(self, name: str) -> Path:
        return self.path / name

    def close(self) -> None:
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(self._lock_fd)
                self._lock_fd = None


def _read_holder(fd: int) -> str:
    try:
        return os.pread(fd, 4096, 0).decode("utf-8", "replace").strip()
    except OSError:
        return ""


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
