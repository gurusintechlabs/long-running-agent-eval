"""Read-only tailing of a run's ``events/*.jsonl`` files (docs/ui-api-live.md §2).

Everything here only ever *reads*: files are opened ``O_RDONLY`` (and ``O_NOFOLLOW``), never written,
locked or touched, so a run in progress cannot notice the UI (CLAUDE.md: observe, don't interfere).

Pieces
* :class:`FileTail`: one file, by byte offset. Hands out only complete (newline-terminated) lines. A
  torn last line (the writer is mid-append) stays unread until its newline lands. A line longer than
  ``MAX_LINE`` is skipped without being buffered and reported as an oversize placeholder.
* :class:`Merger`: all ``*.jsonl`` files of one run merged in time order (``ts``), new files picked up
  as they appear. Per-file order is always kept. Bounded memory (about one chunk per file).
* Cursor helpers. A *resume cursor* is one byte offset per file: ``v1:agent_stream=1234,guardrail=0``.
  A *ref* names a single event: ``<source>:<byte offset of the line start>``.
* :func:`locate_tail`: where to start so the stream opens with the last N visible events, without
  reading the whole (tens of MB) logs.
"""
from __future__ import annotations

import os
import re
import stat
from collections import deque
from dataclasses import dataclass
from pathlib import Path

MAX_LINE = 1 << 20          # a longer line is skipped (reported, not buffered)
CHUNK = 256 << 10           # bytes read per file per refill
BACK_BLOCK = 64 << 10       # block size when scanning a file backwards
BACK_CAP = 8 << 20          # most bytes read backwards per file when looking for the last N events
CURSOR_PREFIX = "v1:"
_STEM = re.compile(r"[A-Za-z0-9_-]{1,40}")
_PREFIX = re.compile(rb'^\{\s*"ts"\s*:\s*"([^"\\]*)".{0,400}?"type"\s*:\s*"([^"\\]*)"', re.DOTALL)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


class CursorError(ValueError):
    """A cursor or ref that is malformed or does not sit on a line boundary."""


# ---- cursors ----------------------------------------------------------------------------------

def encode_cursor(pos: dict[str, int]) -> str:
    return CURSOR_PREFIX + ",".join(f"{s}={int(o)}" for s, o in sorted(pos.items()))


def parse_cursor(text: str) -> dict[str, int]:
    """``v1:a=1,b=2`` to ``{"a": 1, "b": 2}``. ``v1:`` alone is the empty cursor (start of everything)."""
    if not isinstance(text, str) or len(text) > 2000 or not text.startswith(CURSOR_PREFIX):
        raise CursorError("not a v1 cursor")
    out: dict[str, int] = {}
    body = text[len(CURSOR_PREFIX):]
    for part in filter(None, body.split(",")):
        name, sep, off = part.partition("=")
        if not sep or not _STEM.fullmatch(name) or not off.isascii() or not off.isdigit() or len(off) > 15:
            raise CursorError(f"bad cursor entry {part[:40]!r}")
        out[name] = int(off)
    return out


def make_ref(source: str, offset: int) -> str:
    return f"{source}:{int(offset)}"


def parse_ref(text: str) -> tuple[str, int]:
    name, sep, off = (text or "").partition(":")
    if not sep or not _STEM.fullmatch(name) or not off.isascii() or not off.isdigit() or len(off) > 15:
        raise CursorError("not a ref (<source>:<offset>)")
    return name, int(off)


# ---- one file ---------------------------------------------------------------------------------

@dataclass(slots=True)
class Line:
    start: int
    end: int                 # offset just after the newline
    data: bytes | None       # the line without its newline; None when it was longer than MAX_LINE
    size: int                # length in bytes (also set for oversize lines)


def _open_ro(path: Path) -> int | None:
    try:
        return os.open(path, os.O_RDONLY | _O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return None


class FileTail:
    """Complete lines of one append-only file from a byte offset. Safe to call on a file that does
    not exist yet, is being appended, or is replaced by a shorter one (then it restarts at 0)."""

    def __init__(self, path: Path, offset: int = 0):
        self.path = Path(path)
        self.offset = max(0, int(offset))   # start of the first line not handed out yet
        self._skip_from: int | None = None  # start of an oversize line being skipped
        self._skip_pos = 0
        self.restarted = False

    def read(self, max_bytes: int = CHUNK) -> tuple[list[Line], bool]:
        """``(lines, at_eof)``. ``at_eof`` is False when the byte budget (not the file) stopped us."""
        fd = _open_ro(self.path)
        if fd is None:
            return [], True
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                return [], True
            size = st.st_size
            if size < self.offset or (self._skip_from is not None and size < self._skip_pos):
                self.offset, self._skip_from, self.restarted = 0, None, True
            out: list[Line] = []
            spent = 0
            while spent < max_bytes:
                if self._skip_from is not None:
                    pos = self._skip_pos
                    if pos >= size:
                        return out, True
                    block = os.pread(fd, min(CHUNK, size - pos), pos)
                    if not block:
                        return out, True
                    spent += len(block)
                    nl = block.find(b"\n")
                    if nl < 0:
                        self._skip_pos = pos + len(block)
                        continue
                    end = pos + nl + 1
                    out.append(Line(self._skip_from, end, None, end - self._skip_from - 1))
                    self.offset, self._skip_from = end, None
                    continue
                pos = self.offset
                if pos >= size:
                    return out, True
                block = os.pread(fd, min(CHUNK, size - pos), pos)
                if not block:
                    return out, True
                spent += len(block)
                if b"\n" not in block and pos + len(block) < size:
                    # a long line crossing the chunk: look at up to MAX_LINE + 1 bytes of it
                    block = os.pread(fd, min(MAX_LINE + 1, size - pos), pos)
                    spent += len(block)
                i = 0
                while True:
                    nl = block.find(b"\n", i)
                    if nl < 0:
                        break
                    if nl - i > MAX_LINE:
                        out.append(Line(pos + i, pos + nl + 1, None, nl - i))
                    else:
                        out.append(Line(pos + i, pos + nl + 1, block[i:nl], nl - i))
                    i = nl + 1
                self.offset = pos + i
                rest = len(block) - i
                if rest == 0:
                    continue
                if rest > MAX_LINE:         # an oversize line without its end yet: skip, do not buffer
                    self._skip_from, self._skip_pos = self.offset, self.offset + rest
                    continue
                if self.offset + rest >= size:
                    return out, True        # torn tail: wait for the writer to finish the line
            return out, self.offset >= size
        finally:
            os.close(fd)


# ---- merge ------------------------------------------------------------------------------------

def peek(data: bytes) -> tuple[str, str] | None:
    """``(ts, type)`` read from the line's envelope prefix without parsing the (maybe huge) payload."""
    m = _PREFIX.match(data[:600])
    if not m:
        return None
    try:
        return m.group(1).decode("utf-8", "replace"), m.group(2).decode("utf-8", "replace")
    except Exception:  # pragma: no cover
        return None


@dataclass(slots=True)
class Item:
    source: str
    start: int
    end: int
    ts: str
    type: str | None
    data: bytes | None
    size: int


def list_event_files(events_dir: Path) -> dict[str, Path]:
    """``{source: path}`` for the plain ``*.jsonl`` files in ``events/`` (no symlinks, no subdirs)."""
    out: dict[str, Path] = {}
    try:
        with os.scandir(events_dir) as it:
            for e in it:
                if not e.name.endswith(".jsonl"):
                    continue
                stem = e.name[:-6]
                if _STEM.fullmatch(stem) and e.is_file(follow_symlinks=False):
                    out[stem] = Path(e.path)
    except OSError:
        pass
    return out


class Merger:
    """Time-ordered merge of every ``events/*.jsonl``. ``poll()`` returns the next items (possibly
    none); call it again until it returns ``[]`` to drain a backlog. Items carry the raw line, so
    callers parse only what they use."""

    def __init__(self, events_dir: Path, start: dict[str, int] | None = None):
        self.events_dir = Path(events_dir)
        self.start = dict(start or {})
        self.tails: dict[str, FileTail] = {}
        self.buf: dict[str, deque[Item]] = {}
        self.eof: dict[str, bool] = {}

    def discover(self) -> None:
        for stem, path in list_event_files(self.events_dir).items():
            if stem not in self.tails:
                self.tails[stem] = FileTail(path, self.start.get(stem, 0))
                self.buf[stem] = deque()
                self.eof[stem] = False

    def _refill(self, stem: str) -> None:
        lines, at_eof = self.tails[stem].read(CHUNK)
        self.eof[stem] = at_eof
        if self.tails[stem].restarted:
            self.tails[stem].restarted = False
            self.buf[stem].clear()
        for ln in lines:
            ts, typ = "", None
            if ln.data is not None:
                pk = peek(ln.data)
                if pk:
                    ts, typ = pk
            self.buf[stem].append(Item(stem, ln.start, ln.end, ts, typ, ln.data, ln.size))

    def poll(self, max_events: int = 500) -> list[Item]:
        self.discover()
        for stem in self.tails:
            if not self.buf[stem] or (not self.eof[stem] and len(self.buf[stem]) < 64):
                for _ in range(8):
                    self._refill(stem)
                    if self.buf[stem] or self.eof[stem]:
                        break
        # a file we have not read to its end bounds how far the merge may go: its later lines could
        # still be older than another file's next line
        limits = [self.buf[s][-1].ts for s in self.tails if not self.eof[s] and self.buf[s]]
        limit = min(limits) if limits else None
        out: list[Item] = []
        while len(out) < max_events:
            best = None
            for s, q in self.buf.items():
                if q and (best is None or (q[0].ts, s) < (self.buf[best][0].ts, best)):
                    best = s
            if best is None:
                break
            if limit is not None and self.buf[best][0].ts > limit:
                break
            out.append(self.buf[best].popleft())
        return out

    def drained(self) -> bool:
        return all(self.eof.values()) and not any(self.buf.values())


# ---- where to start ---------------------------------------------------------------------------

def complete_end(path: Path) -> int:
    """Offset just after the last newline of the file (0 when there is none or the file is absent)."""
    fd = _open_ro(path)
    if fd is None:
        return 0
    try:
        size = os.fstat(fd).st_size
        pos = size
        while pos > 0:
            lo = max(0, pos - BACK_BLOCK)
            block = os.pread(fd, pos - lo, lo)
            nl = block.rfind(b"\n")
            if nl >= 0:
                return lo + nl + 1
            pos = lo
            if size - pos > BACK_CAP:
                break
        return 0
    finally:
        os.close(fd)


def locate_tail(events_dir: Path, n: int, visible) -> dict[str, int]:
    """Start offsets so that reading on from them yields about the last ``n`` visible events.

    ``visible(source, type)`` says whether an event counts. Each file is scanned backwards (at most
    ``BACK_CAP`` bytes). Files with nothing chosen start at their last complete line boundary.
    """
    files = list_event_files(events_dir)
    start = {s: complete_end(p) for s, p in files.items()}
    if n <= 0:
        return start
    cands: list[tuple[str, str, int]] = []   # (ts, source, line start)
    for s, p in files.items():
        end = start[s]
        fd = _open_ro(p)
        if fd is None:
            continue
        try:
            found = 0
            hi = end
            carry = b""
            scanned = 0
            while hi > 0 and found < n and scanned < BACK_CAP:
                lo = max(0, hi - BACK_BLOCK)
                block = os.pread(fd, hi - lo, lo) + carry
                scanned += hi - lo
                pieces = block.split(b"\n")
                # block = piece0 \n piece1 \n ... ; the last piece is empty when block ends at a newline
                carry = pieces[0] if lo > 0 else b""
                offs = []
                o = lo
                for pc in pieces:
                    offs.append(o)
                    o += len(pc) + 1
                first = 1 if lo > 0 else 0
                for pc, off in zip(reversed(pieces[first:]), reversed(offs[first:]), strict=True):
                    if not pc:
                        continue
                    pk = peek(pc) if len(pc) <= MAX_LINE else None
                    ts, typ = pk if pk else ("", None)
                    if visible(s, typ):
                        cands.append((ts, s, off))
                        found += 1
                        if found >= n:
                            break
                hi = lo
        finally:
            os.close(fd)
    cands.sort()
    chosen: dict[str, int] = {}
    for _ts, s, off in cands[-n:]:
        chosen[s] = min(chosen.get(s, off), off)
    for s, off in chosen.items():
        start[s] = off
    return start


def check_boundary(path: Path, offset: int) -> int:
    """``offset`` clamped to the file, verified to sit on a line start; CursorError otherwise."""
    fd = _open_ro(path)
    if fd is None:
        return 0
    try:
        size = os.fstat(fd).st_size
        if offset > size:
            return 0            # the file is shorter than the cursor: it was replaced, start over
        if offset == size or offset == 0:
            return offset
        if os.pread(fd, 1, offset - 1) != b"\n":
            raise CursorError("cursor does not sit on a line boundary")
        return offset
    finally:
        os.close(fd)


def read_line_at(path: Path, offset: int, limit: int = 4 * MAX_LINE) -> tuple[bytes | None, int]:
    """The line starting at ``offset`` and its length. ``(None, size)`` when absent, torn or too long."""
    fd = _open_ro(path)
    if fd is None:
        return None, 0
    try:
        size = os.fstat(fd).st_size
        if offset >= size or (offset > 0 and os.pread(fd, 1, offset - 1) != b"\n"):
            return None, 0
        pos, parts, total = offset, [], 0
        while pos < size:
            block = os.pread(fd, min(CHUNK, size - pos), pos)
            if not block:
                break
            nl = block.find(b"\n")
            if nl >= 0:
                parts.append(block[:nl])
                total += nl
                return (b"".join(parts) if total <= limit else None), total
            parts.append(block)
            total += len(block)
            pos += len(block)
            if total > limit:
                return None, total
        return None, total   # no newline yet: torn
    finally:
        os.close(fd)
