"""Live view endpoints (docs/ui-api-live.md): stream, live status, display-event feed.

* ``GET /api/runs/{id}/stream``       Server-Sent-Events framing over a ``fetch`` response (token in a header)
* ``GET /api/runs/{id}/live``         incremental status snapshot (cost, clock, checkpoints, budget, activity)
* ``GET /api/runs/{id}/feed``         one page of display events (same renderer as the stream)
* ``GET /api/runs/{id}/feed/event``   one event, with larger preview caps
* ``GET /api/feed-schema``            the display-event description

Everything here only reads the run directory.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import anyio
from fastapi import HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ui_server import deps, feed, feed_reader, live_state, store
from ui_server.safety import scrub_paths
from ui_server.tailer import CursorError, list_event_files, parse_ref, read_line_at

MAX_STREAMS = 6
POLL_S = 0.25
STATUS_EVERY_S = 1.0
DEAD_GRACE_S = 3.0
SSE_HEADERS = {"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"}


def sse(event: str, data: dict, eid: str | None = None) -> bytes:
    """One SSE message. ``ensure_ascii`` plus compact JSON guarantees a single ``data:`` line."""
    head = (f"id: {eid}\n" if eid else "") + f"event: {event}\n"
    return (head + "data: " + json.dumps(data, ensure_ascii=True, separators=(",", ":")) + "\n\n").encode("ascii")


def register(app, settings) -> None:
    home = Path.home()
    state = {"streams": 0}

    def scrub(obj):
        return scrub_paths(obj, settings.repo_root, home)

    def _bad(exc: Exception):
        raise HTTPException(400, str(exc)[:200])

    def _opts(sources: str | None, level: str):
        if level not in feed.LEVELS:
            raise HTTPException(400, "level must be info or debug")
        try:
            return feed_reader.parse_sources(sources)
        except CursorError as exc:
            _bad(exc)

    @app.get("/api/feed-schema")
    def feed_schema():
        return feed.schema()

    @app.get("/api/runs/{rid}/live")
    def live(rid: str, series: bool = True):
        d = deps.run_dir_or_404(settings, rid)
        mf = store.read_json(d / "manifest.json") or {}
        snap = live_state.REGISTRY.get(d).snapshot(mf, series=series)
        return scrub(snap)

    @app.get("/api/runs/{rid}/feed")
    def feed_page(rid: str, from_: str = Query("tail", alias="from"), limit: int = 200, sources: str | None = None,
                  level: str = "info", fold: bool = True, ref_from: str | None = None, ref_to: str | None = None):
        d = deps.run_dir_or_404(settings, rid)
        src = _opts(sources, level)
        try:
            if ref_from or ref_to:
                if not (ref_from and ref_to):
                    raise CursorError("ref_from and ref_to go together")
                return scrub(feed_reader.read_range(d, ref_from, ref_to, level=level))
            if from_ not in ("start", "now", "tail") and not from_.startswith("v1:"):
                raise CursorError("from must be start, now, tail or a v1: cursor")
            return scrub(feed_reader.read_page(d, from_, limit, sources=src, level=level, fold=fold))
        except CursorError as exc:
            _bad(exc)

    @app.get("/api/runs/{rid}/feed/event")
    def feed_event(rid: str, ref: str):
        d = deps.run_dir_or_404(settings, rid)
        try:
            source, off = parse_ref(ref)
        except CursorError as exc:
            _bad(exc)
        path = list_event_files(d / "events").get(source)
        data, size = read_line_at(path, off) if path else (None, 0)
        if data is None:
            raise HTTPException(404, "no complete event at that ref")
        try:
            ev = json.loads(data)
        except ValueError:
            ev = None
        if not isinstance(ev, dict):
            raise HTTPException(422, "that line is not a JSON object")
        ctx = feed.FeedContext(feed.load_clock(d), full=True)
        out = feed.display_event(source, off, ev, ctx)
        out["raw_bytes"] = size
        return scrub(out)

    @app.get("/api/runs/{rid}/stream")
    async def stream(rid: str, request: Request, from_: str = Query("tail", alias="from"), backlog: int = 200,
                     sources: str | None = None, level: str = "info", fold: bool = True,
                     follow: bool = True, heartbeat_s: float = 10.0):
        d = deps.run_dir_or_404(settings, rid)
        src = _opts(sources, level)
        mode = request.headers.get("last-event-id") or from_
        if mode not in ("start", "now", "tail") and not mode.startswith("v1:"):
            raise HTTPException(400, "from must be start, now, tail or a v1: cursor")
        heartbeat_s = min(60.0, max(0.2, heartbeat_s))
        if state["streams"] >= MAX_STREAMS:
            return JSONResponse({"detail": "too many open streams"}, status_code=429)
        try:
            start = await anyio.to_thread.run_sync(
                feed_reader.start_offsets, d / "events", mode, backlog, src, level)
        except CursorError as exc:
            _bad(exc)
        reader = feed_reader.FeedReader(d, start, sources=src, level=level, fold=fold)
        run_live = live_state.REGISTRY.get(d)

        async def gen():
            state["streams"] += 1
            try:
                yield b"retry: 2000\n\n"
                mf = store.read_json(d / "manifest.json") or {}
                end = mf.get("end") if isinstance(mf.get("end"), dict) else None
                yield sse("hello", scrub({
                    "run_id": mf.get("run_id") or rid, "schema": feed.SCHEMA_VERSION, "mode": mode,
                    "cursor": reader.cursor(), "live": end is None and store.pid_alive(mf.get("harness_pid")),
                    "ended": end is not None, "level": level, "sources": sorted(src) if src else None,
                    "fold": fold, "follow": follow, "heartbeat_s": heartbeat_s, "server_time": time.time()}))
                caught_up = False
                closing = end is not None     # already ended when we connected: decide at the first check
                ending_sent = False
                dead_since: float | None = None
                last_status = 0.0
                last_hb = time.monotonic()
                last_event = time.monotonic()
                while True:
                    if await request.is_disconnected():
                        return
                    batch = await anyio.to_thread.run_sync(reader.poll)
                    for ev, cur in batch:
                        yield sse("ev", scrub(ev), cur)
                    if batch or reader.last_consumed:
                        last_event = time.monotonic()
                        await asyncio.sleep(0)
                        continue
                    if not caught_up:
                        caught_up = True
                        yield sse("caught-up", {"cursor": reader.cursor(), "delivered": reader.delivered})
                        if not follow:
                            return
                    now = time.monotonic()
                    if now - last_status >= STATUS_EVERY_S:
                        last_status = now
                        mf = store.read_json(d / "manifest.json") or mf
                        end = mf.get("end") if isinstance(mf.get("end"), dict) else None
                        alive = store.pid_alive(mf.get("harness_pid"))
                        if end is not None:
                            if not ending_sent:
                                ending_sent = True
                                yield sse("run.ending", scrub({"state": end.get("state"), "end": end}))
                            await anyio.to_thread.run_sync(run_live.update)
                            pending = sorted(run_live.queued - run_live.finished)
                            if closing and (not pending or not alive):
                                yield sse("run.ended", scrub({
                                    "state": end.get("state"), "end": end, "scoring_complete": not pending,
                                    "cursor": reader.cursor()}))
                                return
                            closing = True        # one more empty poll after seeing the end, then decide
                        elif not alive:
                            dead_since = dead_since or now
                            if now - dead_since >= DEAD_GRACE_S:
                                yield sse("run.ended", {"state": "UNFINISHED", "end": None, "crashed": True,
                                                        "scoring_complete": False, "cursor": reader.cursor()})
                                return
                        else:
                            dead_since = None
                    if now - last_hb >= heartbeat_s:
                        last_hb = now
                        yield sse("heartbeat", {"t": time.time(), "cursor": reader.cursor(),
                                                "idle_s": round(now - last_event, 1)})
                    await asyncio.sleep(POLL_S)
            finally:
                state["streams"] -= 1

        return StreamingResponse(gen(), media_type="text/event-stream; charset=utf-8", headers=SSE_HEADERS)
