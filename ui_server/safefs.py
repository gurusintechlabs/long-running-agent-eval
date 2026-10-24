"""Symlink-proof reads of run artifacts (UH-5).

A run directory is written by the harness but also sits on the user's disk next to anything else, and
its contents (events/, scorer/, snapshots/, mirror.git ...) can be replaced by symlinks. Every reader of
a path under a registered runs directory goes through here: the path below the runs directory is walked
component by component with ``O_NOFOLLOW`` (directories via ``dir_fd``), so a symlinked ``events/``, a
symlinked ``events/x.jsonl`` or a symlinked ``manifest.json`` is simply "not there". Paths outside every
registered root (spec files, the metrics db) only get ``O_NOFOLLOW`` on the last component.

``register_root(runs_dir)`` is called by ``create_app``. The runs directory itself may be a symlink (the
user chose it); components below it may not.
"""
from __future__ import annotations

import contextlib
import os
import stat
from pathlib import Path

_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_ROOTS: list[tuple[str, ...]] = []    # absolute parts of registered runs dirs (given and resolved forms)


def register_root(runs_dir: Path) -> None:
    for form in {os.path.abspath(runs_dir), str(Path(runs_dir).resolve())}:
        parts = tuple(Path(form).parts)
        if parts not in _ROOTS:
            _ROOTS.append(parts)


def _split(path: os.PathLike | str) -> tuple[str, tuple[str, ...]] | None:
    """``(root, rel parts)`` when ``path`` is below a registered runs dir, else None."""
    parts = tuple(Path(os.path.abspath(path)).parts)
    best = None
    for root in _ROOTS:
        if len(parts) > len(root) and parts[:len(root)] == root and (best is None or len(root) > len(best)):
            best = root
    if best is None:
        return None
    return str(Path(*best)), parts[len(best):]


def open_fd(path: os.PathLike | str, *, directory: bool = False) -> int | None:
    """An fd for the regular file (or directory) at ``path``, or None when it is missing, special,
    or reached through a symlink below a registered runs dir."""
    split = _split(path)
    flags = os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC
    try:
        if split is None:
            fd = os.open(path, flags | (_O_DIRECTORY if directory else 0))
        else:
            root, rel = split
            cur = os.open(root, os.O_RDONLY | _O_DIRECTORY | _O_CLOEXEC)
            try:
                for name in rel[:-1]:
                    nxt = os.open(name, flags | _O_DIRECTORY, dir_fd=cur)
                    os.close(cur)
                    cur = nxt
                fd = os.open(rel[-1], flags | (_O_DIRECTORY if directory else 0), dir_fd=cur)
            finally:
                os.close(cur)
    except OSError:
        return None
    try:
        mode = os.fstat(fd).st_mode
        if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
            os.close(fd)
            return None
    except OSError:
        os.close(fd)
        return None
    return fd


@contextlib.contextmanager
def open_file(path: os.PathLike | str, mode: str = "rb"):
    """A buffered file object (binary or text), or None."""
    fd = open_fd(path)
    if fd is None:
        yield None
        return
    try:
        fh = os.fdopen(fd, mode, **({} if "b" in mode else {"encoding": "utf-8", "errors": "replace"}))
    except OSError:
        os.close(fd)
        yield None
        return
    with fh:
        yield fh


def stat_file(path: os.PathLike | str) -> os.stat_result | None:
    fd = open_fd(path)
    if fd is None:
        return None
    try:
        return os.fstat(fd)
    except OSError:
        return None
    finally:
        os.close(fd)


def is_file(path: os.PathLike | str) -> bool:
    return stat_file(path) is not None


def is_dir(path: os.PathLike | str) -> bool:
    fd = open_fd(path, directory=True)
    if fd is None:
        return False
    os.close(fd)
    return True


def listdir(path: os.PathLike | str) -> list[str]:
    """Names of the entries of a directory reached without symlinks ([] otherwise)."""
    fd = open_fd(path, directory=True)
    if fd is None:
        return []
    try:
        return os.listdir(fd)
    except OSError:
        return []
    finally:
        os.close(fd)


def read_bytes(path: os.PathLike | str, limit: int | None = None) -> bytes | None:
    with open_file(path) as fh:
        if fh is None:
            return None
        try:
            return fh.read() if limit is None else fh.read(limit)
        except OSError:
            return None


def read_text(path: os.PathLike | str, limit: int | None = None) -> str | None:
    b = read_bytes(path, limit)
    return None if b is None else b.decode("utf-8", errors="replace")


def no_symlinks_below(path: os.PathLike | str) -> bool:
    """True when ``path`` exists and no component below the registered runs dir is a symlink. For
    handing a path to another program (git): the final component is checked too."""
    split = _split(path)
    if split is None:
        return os.path.exists(path) and not os.path.islink(path)
    root, rel = split
    cur = Path(root)
    for name in rel:
        cur = cur / name
        try:
            if stat.S_ISLNK(os.lstat(cur).st_mode):
                return False
        except OSError:
            return False
    return True


def plain_dir(path: os.PathLike | str) -> bool:
    """A directory reached without symlinks whose entries are all plain files or directories (for
    handing the whole directory to library code that opens its files by name)."""
    names = listdir(path)
    if not is_dir(path):
        return False
    for name in names:
        try:
            if stat.S_ISLNK(os.lstat(Path(path) / name).st_mode):
                return False
        except OSError:
            return False
    return True
