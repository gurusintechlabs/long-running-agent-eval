"""Tiny in-memory memo keyed by file signatures (path, size, mtime_ns); a changed file invalidates."""
from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

_MAX = 64
_memo: OrderedDict[tuple, object] = OrderedDict()
_lock = threading.Lock()


def signature(paths: list[Path]) -> tuple:
    out = []
    for p in paths:
        try:
            st = p.stat()
            out.append((str(p), st.st_size, st.st_mtime_ns))
        except OSError:
            out.append((str(p), -1, -1))
    return tuple(out)


def cached(name: str, paths: list[Path], build: Callable[[], object], extra: tuple = ()):
    key = (name, extra, signature(paths))
    with _lock:
        if key in _memo:
            _memo.move_to_end(key)
            return _memo[key]
    value = build()
    with _lock:
        _memo[key] = value
        while len(_memo) > _MAX:
            _memo.popitem(last=False)
    return value


def clear() -> None:
    with _lock:
        _memo.clear()
