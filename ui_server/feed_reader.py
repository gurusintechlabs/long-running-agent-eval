"""Turns merged log lines into display events, for the stream and the paged feed (docs/ui-api-live.md §2, §4).

``FeedReader`` owns a :class:`~ui_server.tailer.Merger`, the run clock, the open-tool-call table and the
telemetry folder. ``poll()`` returns ``[(display_event, cursor_after)]`` where ``cursor_after`` is the resume
cursor to use after that event. Strictly read-only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ui_server import feed
from ui_server.tailer import (
    MAX_LINE,
    CursorError,
    FileTail,
    Merger,
    check_boundary,
    encode_cursor,
    list_event_files,
    locate_tail,
    parse_cursor,
    parse_ref,
)

_SRC = re.compile(r"[A-Za-z0-9_-]{1,40}")
BACKLOG_MAX = 2000
RANGE_MAX = 500


def parse_sources(text: str | None) -> frozenset[str] | None:
    """``"agent_stream,guardrail"`` to a set; ``None`` (all sources) for empty. Unknown names are fine
    (they simply match no file); malformed ones are rejected."""
    if not text:
        return None
    out = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if not _SRC.fullmatch(part):
            raise CursorError(f"bad source name {part[:40]!r}")
        out.add(part)
    return frozenset(out) or None


def start_offsets(events_dir: Path, mode: str, backlog: int, sources, level: str) -> dict[str, int]:
    """Byte offsets to start from: ``start``, ``now``, ``tail`` (last ``backlog`` visible events) or a cursor."""
    files = list_event_files(events_dir)
    if mode == "start":
        return {}
    if mode in ("now", "tail"):
        n = 0 if mode == "now" else max(0, min(int(backlog), BACKLOG_MAX))

        def visible(src: str, typ: str | None) -> bool:
            return (sources is None or src in sources) and (level == "debug" or feed.level_of(src, typ) == "info")
        return locate_tail(events_dir, n, visible)
    pos = parse_cursor(mode)
    return {s: check_boundary(files[s], off) for s, off in pos.items() if s in files}


class FeedReader:
    def __init__(self, run_dir: Path, start: dict[str, int], *, sources=None, level: str = "info",
                 fold: bool = True, full: bool = False):
        self.run_dir = Path(run_dir)
        self.merger = Merger(self.run_dir / "events", start)
        self.pos: dict[str, int] = dict(start)
        self.sources = sources
        self.level = level
        self.ctx = feed.FeedContext(feed.load_clock(self.run_dir), full=full)
        self.folder = feed.Folder() if fold else None
        self.delivered = 0
        self.last_consumed = 0

    def cursor(self) -> str:
        for s in self.merger.tails:
            self.pos.setdefault(s, 0)
        return encode_cursor(self.pos)

    def drained(self) -> bool:
        return self.merger.drained()

    def poll(self, max_events: int = 500) -> list[tuple[dict, str]]:
        out: list[tuple[dict, str]] = []
        items = self.merger.poll(max_events)
        self.last_consumed = len(items)
        for it in items:
            self.pos[it.source] = it.end
            if self.sources is not None and it.source not in self.sources:
                continue
            if it.data is None:
                out.append((feed.placeholder_event(it.source, it.start, it.ts, "oversize", it.size, self.ctx),
                            self.cursor()))
                continue
            if self.level == "info" and it.type is not None and feed.level_of(it.source, it.type) == "debug":
                continue
            try:
                ev = json.loads(it.data) if len(it.data) <= MAX_LINE else None
            except ValueError:
                ev = None
            if not isinstance(ev, dict):
                out.append((feed.placeholder_event(it.source, it.start, it.ts, "invalid", it.size, self.ctx),
                            self.cursor()))
                continue
            d = feed.display_event(it.source, it.start, ev, self.ctx)
            if self.folder is not None:
                d = self.folder.apply(d)
                if d is None:
                    continue
            if self.level == "info" and d["level"] == "debug":
                continue
            out.append((d, self.cursor()))
        self.delivered += len(out)
        return out


def read_page(run_dir: Path, mode: str, limit: int, *, sources=None, level: str = "info", fold: bool = True) -> dict:
    """One page of display events from ``mode`` (``start`` | ``now`` | ``tail`` | cursor)."""
    limit = max(1, min(int(limit), 1000))
    events_dir = Path(run_dir) / "events"
    start = start_offsets(events_dir, mode, limit, sources, level)
    r = FeedReader(run_dir, start, sources=sources, level=level, fold=fold)
    events: list[dict] = []
    cursor = encode_cursor(start) if start else "v1:"
    at_end = False
    while len(events) < limit:
        got = r.poll(500)
        if not got and r.last_consumed == 0:
            at_end = r.drained()
            break
        for d, cur in got:
            events.append(d)
            cursor = cur
            if len(events) >= limit:
                break
        else:
            cursor = r.cursor()     # everything polled was delivered (or filtered): resume after it
    if at_end:
        cursor = r.cursor()
    if fold:
        events = _dedupe_fold(events)
    return {"events": events, "next_cursor": cursor, "at_end": at_end, "from": mode, "count": len(events)}


def _dedupe_fold(events: list[dict]) -> list[dict]:
    """Keep the folded row once (at its first position) with its latest counts."""
    last = {}
    for e in events:
        if e["id"] == feed.Folder.ID:
            last[e["id"]] = e
    out, seen = [], False
    for e in events:
        if e["id"] == feed.Folder.ID:
            if not seen:
                seen = True
                out.append(last[e["id"]])
            continue
        out.append(e)
    return out


def read_range(run_dir: Path, ref_from: str, ref_to: str, *, level: str = "info") -> dict:
    """Display events of one source between two refs (inclusive), for incident contexts."""
    src_a, off_a = parse_ref(ref_from)
    src_b, off_b = parse_ref(ref_to)
    if src_a != src_b:
        raise CursorError("ref_from and ref_to must name the same source")
    if off_b < off_a:
        raise CursorError("ref_to is before ref_from")
    path = list_event_files(Path(run_dir) / "events").get(src_a)
    if path is None:
        return {"events": [], "count": 0, "source": src_a, "truncated": False}
    off_a = check_boundary(path, off_a)
    tail = FileTail(path, off_a)
    ctx = feed.FeedContext(feed.load_clock(run_dir))
    events: list[dict] = []
    truncated = False
    done = False
    while not done:
        lines, at_eof = tail.read()
        for ln in lines:
            if ln.start > off_b:
                done = True
                break
            if ln.data is None:
                events.append(feed.placeholder_event(src_a, ln.start, "", "oversize", ln.size, ctx))
                continue
            try:
                ev = json.loads(ln.data)
            except ValueError:
                ev = None
            if not isinstance(ev, dict):
                events.append(feed.placeholder_event(src_a, ln.start, "", "invalid", ln.size, ctx))
                continue
            d = feed.display_event(src_a, ln.start, ev, ctx)
            if level == "info" and d["level"] == "debug":
                continue
            events.append(d)
            if len(events) >= RANGE_MAX:
                truncated, done = True, True
                break
        if at_eof:
            break
    return {"events": events, "count": len(events), "source": src_a, "truncated": truncated}
