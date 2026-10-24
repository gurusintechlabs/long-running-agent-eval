"""Paged, read-only access to ``runs/<id>/events/*.jsonl`` (U3).

Design rules (docs/ui-api-events.md has the API view):

* Files are never loaded whole. A request seeks to a byte offset and reads forward line by line.
* A **cursor** is a server-issued token mapping to a server-chosen file; no user text ever becomes
  part of a path. Single source: ``"<source>:<byte offset of a line start>"``. Merged feed:
  ``"m:<source>=<offset>,<source>=<offset>,..."`` (the next unread line of each source).
* An unterminated last line (still being written, or torn) is invisible: the cursor stays in front
  of it, so the next poll returns it once it is complete.
* A light per-file index (counts by type, sampled line offsets) is cached in memory keyed by
  path, and revalidated by size and mtime. A file that only grew is indexed incrementally.
"""
from __future__ import annotations

import fnmatch
import heapq
import json
import re
import threading
from bisect import bisect_left
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

SOURCES = ("agent_stream", "otel", "orchestrator", "guardrail", "counterpart", "env", "scorer")
SOURCE_RANK = {s: i for i, s in enumerate(SOURCES)}

MAX_LINE = 8 * 1024 * 1024          # a longer line is reported as oversized, never parsed
SAMPLE_EVERY = 256                  # one index sample per this many lines
DEFAULT_LIMIT, MAX_LIMIT = 200, 1000
DEFAULT_MAX_CHARS, MAX_MAX_CHARS = 2_000, 20_000
FULL_MAX_CHARS = 1_000_000
EVENT_JSON_CAP = 32_000             # serialised payload above this is replaced by a preview
FULL_EVENT_JSON_CAP = 4_000_000
PAGE_BYTES_CAP = 4_000_000          # approximate response size cap for one page
MAX_SCAN_BYTES = 16 * 1024 * 1024   # bytes examined per request (filters can skip a lot)
MAX_Q = 200
MAX_TYPES = 20
_CACHE_MAX_FILES = 64

_HDR = re.compile(rb'^\{"ts":"([^"]*)","mono_ns":(\d+),"run_id":"[^"]*","source":"[^"]*",'
                  rb'"type":"([^"]*)","seq":(\d+)')
_CURSOR = re.compile(r"^([a-z_]{1,20}):(\d{1,15})$")
_MERGED = re.compile(r"^m:((?:[a-z_]{1,20}=\d{1,15})(?:,[a-z_]{1,20}=\d{1,15}){0,15})$")


class CursorError(ValueError):
    pass


def ts_epoch(ts) -> float | None:
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# ------------------------------------------------------------------------------------ line reading

def iter_lines(path: Path, offset: int = 0):
    """Yield ``(start, next_offset, raw | None)`` for each complete line from ``offset``.

    ``raw`` is None for a line longer than ``MAX_LINE`` (its extent is still skipped correctly).
    An unterminated last line is not yielded."""
    try:
        fh = open(path, "rb")
    except OSError:
        return
    with fh:
        fh.seek(offset)
        pos = offset
        while True:
            raw = fh.readline(MAX_LINE + 1)
            if not raw:
                return
            n = len(raw)
            if not raw.endswith(b"\n"):
                if n <= MAX_LINE:
                    return                      # torn or still being written
                # oversized: skip to the end of the line
                done = False
                while True:
                    chunk = fh.readline(1 << 20)
                    if not chunk:
                        break
                    n += len(chunk)
                    if chunk.endswith(b"\n"):
                        done = True
                        break
                if not done:
                    return
                yield pos, pos + n, None
                pos += n
                continue
            yield pos, pos + n, raw
            pos += n


def header(raw: bytes) -> tuple[str, int, str, int] | None:
    """``(ts, mono_ns, type, seq)`` from the fixed envelope prefix (no JSON parse), else a parse."""
    m = _HDR.match(raw)
    if m:
        return m.group(1).decode("utf-8", "replace"), int(m.group(2)), m.group(3).decode("utf-8", "replace"), \
            int(m.group(4))
    try:
        e = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(e, dict) or not isinstance(e.get("type"), str):
        return None
    seq = e.get("seq")
    return str(e.get("ts") or ""), int(e.get("mono_ns") or 0) if isinstance(e.get("mono_ns"), int) else 0, \
        e["type"], seq if isinstance(seq, int) else -1


# ------------------------------------------------------------------------------------ the index

@dataclass
class FileIndex:
    path: str
    size: int = 0
    mtime_ns: int = 0
    ino: int = 0
    end: int = 0                       # offset just after the last complete line
    lines: int = 0
    bad: int = 0
    oversized: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    first_ts: str | None = None
    last_ts: str | None = None
    samples: list[tuple[int, int, int, float]] = field(default_factory=list)   # offset, line_no, seq, epoch
    clocks: list[tuple[float, float]] = field(default_factory=list)            # (start_epoch, offset_s)

    def summary(self) -> dict:
        return {"bytes": self.size, "lines": self.lines, "bad_lines": self.bad, "oversized_lines": self.oversized,
                "first_ts": self.first_ts, "last_ts": self.last_ts, "counts": dict(sorted(self.counts.items()))}


_cache: OrderedDict[str, FileIndex] = OrderedDict()
_lock = threading.Lock()


def get_index(path: Path) -> FileIndex:
    """The (cached, incrementally extended) index of ``path``; an empty index when it is missing."""
    key = str(path)
    try:
        st = path.stat()
    except OSError:
        return FileIndex(key)
    with _lock:
        idx = _cache.get(key)
        if idx is not None and (idx.size, idx.mtime_ns, idx.ino) == (st.st_size, st.st_mtime_ns, st.st_ino):
            _cache.move_to_end(key)
            return idx
        resume = idx is not None and idx.ino == st.st_ino and st.st_size >= idx.end and st.st_size >= idx.size
        new = _extend(path, idx if resume else FileIndex(key), st)
        _cache[key] = new
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX_FILES:
            _cache.popitem(last=False)
        return new


def _extend(path: Path, idx: FileIndex, st) -> FileIndex:
    for start, nxt, raw in iter_lines(path, idx.end):
        idx.end = nxt
        if raw is None:
            idx.oversized += 1
            idx.lines += 1
            continue
        h = header(raw)
        if h is None:
            if raw.strip():
                idx.bad += 1
            continue
        ts, _mono, typ, seq = h
        if idx.lines % SAMPLE_EVERY == 0:
            idx.samples.append((start, idx.lines, seq, ts_epoch(ts) or 0.0))
        idx.lines += 1
        idx.counts[typ] = idx.counts.get(typ, 0) + 1
        idx.first_ts = idx.first_ts or ts
        idx.last_ts = ts
        if typ == "run.clock":
            try:
                p = json.loads(raw).get("payload") or {}
                idx.clocks.append((float(p["start_epoch"]), float(p.get("offset_s") or 0)))
            except (ValueError, KeyError, TypeError, AttributeError):
                pass
    idx.size, idx.mtime_ns, idx.ino = st.st_size, st.st_mtime_ns, st.st_ino
    return idx


def clear_cache() -> None:
    with _lock:
        _cache.clear()


# ------------------------------------------------------------------------------------ run access

class RunLog:
    """Server-chosen event files of one run directory."""

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.events_dir = run_dir / "events"

    def path(self, source: str) -> Path:
        if source not in SOURCE_RANK:
            raise CursorError(f"unknown source {source!r}")
        p = self.events_dir / f"{source}.jsonl"
        try:
            r = p.resolve()
        except (OSError, RuntimeError):
            raise CursorError("bad event file") from None
        if r.parent != self.run_dir.resolve() / "events" or not r.is_file():
            # symlink out of the run's events dir, or a missing file: treat as empty
            return self.events_dir / "__missing__.jsonl"
        return r

    def index(self, source: str) -> FileIndex:
        return get_index(self.path(source))

    def clocks(self) -> list[tuple[float, float]]:
        return self.index("orchestrator").clocks

    def t_s(self, ts) -> float | None:
        return run_time(ts, self.clocks())

    def epoch_of_t(self, t_s: float) -> float | None:
        clocks = self.clocks()
        if not clocks:
            return None
        use = clocks[0]
        for start, off in clocks:
            if off <= t_s + 1e-6:
                use = (start, off)
        return use[0] + (t_s - use[1])

    def summary(self) -> dict:
        out = {}
        for s in SOURCES:
            i = self.index(s)
            if i.size or self.path(s).is_file():
                out[s] = i.summary()
        return out


def run_time(ts, clocks: list[tuple[float, float]]) -> float | None:
    """Run time (checkpoint t_s axis) of an envelope ts: same rule as ``analysis.ingest._clock_t``."""
    e = ts_epoch(ts)
    if e is None or not clocks:
        return None
    use = clocks[0]
    for start, off in clocks:
        if start <= e + 1e-6:
            use = (start, off)
    return e - use[0] + use[1]


# ------------------------------------------------------------------------------------ cursors

def make_cursor(source: str, offset: int) -> str:
    return f"{source}:{offset}"


def parse_cursor(cursor: str) -> tuple[str, int]:
    m = _CURSOR.match(cursor or "")
    if not m or m.group(1) not in SOURCE_RANK:
        raise CursorError("bad cursor")
    return m.group(1), int(m.group(2))


def parse_merged(cursor: str) -> dict[str, int]:
    m = _MERGED.match(cursor or "")
    if not m:
        raise CursorError("bad cursor")
    out = {}
    for part in m.group(1).split(","):
        s, o = part.split("=")
        if s not in SOURCE_RANK:
            raise CursorError("bad cursor")
        out[s] = int(o)
    return out


def make_merged(offsets: dict[str, int]) -> str:
    return "m:" + ",".join(f"{s}={offsets[s]}" for s in SOURCES if s in offsets)


def check_offset(path: Path, offset: int) -> None:
    """The offset must be 0 or the start of a line, and not beyond the file."""
    if offset == 0:
        return
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            if offset > fh.tell():
                raise CursorError("cursor is beyond the end of the file")
            fh.seek(offset - 1)
            if fh.read(1) != b"\n":
                raise CursorError("cursor is not at a line start")
    except OSError:
        raise CursorError("cursor does not match a file") from None


# ------------------------------------------------------------------------------------ truncation

def _cut(obj, max_chars: int):
    """Copy of a JSON value with long strings cut (with a marker). Returns ``(value, cut_any)``."""
    if isinstance(obj, str):
        if len(obj) > max_chars:
            return obj[:max_chars] + f"…[truncated {len(obj) - max_chars} more chars]", True
        return obj, False
    if isinstance(obj, dict):
        out, hit = {}, False
        for k, v in obj.items():
            out[k], h = _cut(v, max_chars)
            hit = hit or h
        return out, hit
    if isinstance(obj, list):
        items = [_cut(v, max_chars) for v in obj]
        return [i[0] for i in items], any(i[1] for i in items)
    return obj, False


def shape_payload(payload, max_chars: int, json_cap: int) -> tuple[object, bool]:
    p, hit = _cut(payload, max_chars)
    text = json.dumps(p, ensure_ascii=False, separators=(",", ":"))
    if len(text) > json_cap:
        return {"_truncated": True, "preview": text[:min(2000, json_cap)]}, True
    return p, hit


def build_event(source: str, start: int, raw: bytes | None, clocks, *, max_chars: int, json_cap: int,
                nbytes: int | None = None) -> dict:
    base = {"cursor": make_cursor(source, start), "source": source, "bytes": nbytes if nbytes is not None else
            (len(raw) if raw else 0)}
    if raw is None:
        return {**base, "ts": None, "t_s": None, "type": "_oversized", "seq": None, "payload": None,
                "truncated": True}
    try:
        e = json.loads(raw)
    except ValueError:
        e = None
    if not isinstance(e, dict):
        return {**base, "ts": None, "t_s": None, "type": "_unparsed", "seq": None, "payload": None,
                "truncated": False}
    payload, cut = shape_payload(e.get("payload"), max_chars, json_cap)
    return {**base, "ts": e.get("ts"), "t_s": _round(run_time(e.get("ts"), clocks)), "type": e.get("type"),
            "seq": e.get("seq"), "payload": payload, "truncated": cut}


def _round(v):
    return None if v is None else round(v, 3)


# ------------------------------------------------------------------------------------ filters

@dataclass
class Filters:
    types: tuple[str, ...] = ()
    q: bytes | None = None

    @classmethod
    def make(cls, type_: str | None, q: str | None) -> Filters:
        types = tuple(t for t in (type_ or "").split(",") if t)[:MAX_TYPES]
        for t in types:
            if len(t) > 80 or not re.fullmatch(r"[A-Za-z0-9_.*?-]+", t):
                raise CursorError("bad type filter")
        qb = None
        if q:
            if len(q) > MAX_Q:
                raise CursorError("q is too long")
            qb = q.lower().encode("utf-8")
        return cls(types, qb)

    def match(self, raw: bytes, typ: str) -> bool:
        if self.types and not any(fnmatch.fnmatchcase(typ, t) for t in self.types):
            return False
        return self.q is None or self.q in raw.lower()

    @property
    def active(self) -> bool:
        return bool(self.types or self.q)


class _Budget:
    def __init__(self, n: int):
        self.left = n
        self.capped = False


class _Stream:
    """Filtered forward reader of one source with one-item lookahead."""

    def __init__(self, source: str, path: Path, offset: int, flt: Filters, budget: _Budget):
        self.source, self.flt, self.budget = source, flt, budget
        self.gen = iter_lines(path, offset)
        self.scanned_to = offset
        self.peeked: tuple | None = None
        self.done = False

    def peek(self):
        if self.peeked is not None or self.done:
            return self.peeked
        for start, nxt, raw in self.gen:
            if self.budget.left <= 0:
                self.budget.capped = True
                self.done = True
                return None
            self.budget.left -= nxt - start
            self.scanned_to = nxt
            if raw is None:
                self.peeked = (0.0, start, nxt, None)
                return self.peeked
            h = header(raw)
            if h is None:
                continue
            if self.flt.active and not self.flt.match(raw, h[2]):
                continue
            self.peeked = (ts_epoch(h[0]) or 0.0, start, nxt, raw)
            return self.peeked
        self.done = True
        return None

    def take(self):
        item, self.peeked = self.peeked, None
        return item

    @property
    def cursor_offset(self) -> int:
        return self.peeked[1] if self.peeked is not None else self.scanned_to


def read_page(rl: RunLog, sources: list[str], after: str | None, flt: Filters, limit: int,
              max_chars: int = DEFAULT_MAX_CHARS, max_scan: int = MAX_SCAN_BYTES) -> dict:
    """One page of events from one source (cursor ``src:off``) or merged (cursor ``m:...``)."""
    limit = max(1, min(limit, MAX_LIMIT))
    max_chars = max(50, min(max_chars, MAX_MAX_CHARS))
    merged = len(sources) > 1
    offsets = {s: 0 for s in sources}
    if after:
        if merged:
            for s, o in parse_merged(after).items():
                if s in offsets:
                    offsets[s] = o
        else:
            s, o = parse_cursor(after)
            if s != sources[0]:
                raise CursorError("cursor belongs to another source")
            offsets[s] = o
    for s, o in offsets.items():
        check_offset(rl.path(s), o)
    budget = _Budget(max_scan)
    streams = {s: _Stream(s, rl.path(s), offsets[s], flt, budget) for s in sources}
    heap: list[tuple] = []
    for s, st in streams.items():
        it = st.peek()
        if it:
            heapq.heappush(heap, (it[0], SOURCE_RANK[s], it[1], s))
    clocks = rl.clocks()
    events, size = [], 0
    page_capped = False
    while heap and len(events) < limit:
        _e, _r, _o, s = heapq.heappop(heap)
        st = streams[s]
        _epoch, start, nxt, raw = st.take()
        ev = build_event(s, start, raw, clocks, max_chars=max_chars, json_cap=EVENT_JSON_CAP, nbytes=nxt - start)
        events.append(ev)
        size += min(ev["bytes"], EVENT_JSON_CAP) + 200
        nxt_item = st.peek()
        if nxt_item:
            heapq.heappush(heap, (nxt_item[0], SOURCE_RANK[s], nxt_item[1], s))
        if size >= PAGE_BYTES_CAP:
            page_capped = True
            break
    # anything still in the heap is peeked and unconsumed: its start is the cursor
    new = {s: streams[s].cursor_offset for s in sources}
    eof = not heap and all(st.done for st in streams.values()) and not budget.capped
    return {"mode": "merged" if merged else "single", "sources": sources, "events": events,
            "next": make_merged(new) if merged else make_cursor(sources[0], new[sources[0]]),
            "eof": eof, "scan_capped": budget.capped, "page_capped": page_capped, "limit": limit,
            "scanned_bytes": max_scan - budget.left}


def read_one(rl: RunLog, cursor: str, *, full: bool = True, max_chars: int | None = None) -> dict | None:
    """The event that starts at ``cursor`` (``src:off``), or None if no complete line starts there."""
    source, off = parse_cursor(cursor)
    path = rl.path(source)
    check_offset(path, off)
    for start, nxt, raw in iter_lines(path, off):
        mc = max_chars if max_chars is not None else (FULL_MAX_CHARS if full else DEFAULT_MAX_CHARS)
        return build_event(source, start, raw, rl.clocks(), max_chars=mc,
                           json_cap=FULL_EVENT_JSON_CAP if full else EVENT_JSON_CAP, nbytes=nxt - start)
    return None


def locate(rl: RunLog, source: str, *, seq: int | None = None, t_s: float | None = None) -> dict:
    """Cursor of the event with this ``seq``, or of the first event at/after run time ``t_s``."""
    path = rl.path(source)
    idx = get_index(path)
    if not idx.samples:
        return {"found": False}
    if seq is not None:
        j = bisect_left([s[2] for s in idx.samples], seq)
        j = max(0, j - 1)
        key = lambda h, e: h[3] == seq  # noqa: E731
    else:
        target = rl.epoch_of_t(t_s)
        if target is None:
            return {"found": False}
        j = max(0, bisect_left([s[3] for s in idx.samples], target) - 1)
        key = lambda h, e: (ts_epoch(h[0]) or 0.0) >= target  # noqa: E731
    for n, (start, _nxt, raw) in enumerate(iter_lines(path, idx.samples[j][0])):
        if n > 2 * SAMPLE_EVERY:
            break
        h = header(raw) if raw is not None else None
        if h is None:
            continue
        if key(h, None):
            return {"found": True, "cursor": make_cursor(source, start), "seq": h[3], "ts": h[0],
                    "t_s": _round(rl.t_s(h[0]))}
        if seq is not None and h[3] > seq:
            break
    return {"found": False}
