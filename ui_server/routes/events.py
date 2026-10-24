"""Event log endpoints (U3): paged/merged events, one full event, summary, locate."""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Query

from ui_server import eventlog as el
from ui_server.deps import run_dir_or_404
from ui_server.safety import scrub_paths


def _bad(e: Exception):
    return HTTPException(400, str(e))


def register(app, settings) -> None:
    home = Path.home()

    def scrub(body):
        return scrub_paths(body, settings.repo_root, home)

    def runlog(rid: str) -> el.RunLog:
        return el.RunLog(run_dir_or_404(settings, rid))

    @app.get("/api/runs/{rid}/events")
    def events(rid: str, source: str | None = Query(None, max_length=200),
               type: str | None = Query(None, max_length=1000),  # noqa: A002
               after: str | None = Query(None, max_length=400), limit: int = Query(el.DEFAULT_LIMIT, ge=1),
               q: str | None = Query(None, max_length=400),
               max_chars: int = Query(el.DEFAULT_MAX_CHARS, ge=50)):
        rl = runlog(rid)
        names = [s for s in (source or "").split(",") if s] or list(el.SOURCES)
        if any(s not in el.SOURCE_RANK for s in names) or len(set(names)) != len(names):
            raise HTTPException(400, "unknown or repeated source")
        names.sort(key=el.SOURCE_RANK.get)
        try:
            flt = el.Filters.make(type, q)
            body = el.read_page(rl, names, after, flt, limit, max_chars)
        except el.CursorError as e:
            raise _bad(e) from None
        return scrub({"run_id": rid, **body})

    @app.get("/api/runs/{rid}/events/at")
    def event_at(rid: str, cursor: str = Query(..., max_length=100), full: bool = True):
        """The complete event that starts at ``cursor`` (strings up to 1M chars, payload up to 4 MB)."""
        rl = runlog(rid)
        try:
            ev = el.read_one(rl, cursor, full=full)
        except el.CursorError as e:
            raise _bad(e) from None
        if ev is None:
            raise HTTPException(404, "no event at this cursor")
        return scrub({"run_id": rid, "event": ev})

    @app.get("/api/runs/{rid}/events/summary")
    def events_summary(rid: str):
        """Per source: size, line count, first/last ts and counts by type (from the cached index)."""
        rl = runlog(rid)
        return {"run_id": rid, "sources": rl.summary(), "clocks": [
            {"start_epoch": a, "offset_s": b} for a, b in rl.clocks()]}

    @app.get("/api/runs/{rid}/events/locate")
    def events_locate(rid: str, source: str = Query(..., max_length=30), seq: int | None = Query(None, ge=0),
                      t_s: float | None = Query(None, ge=0, le=1e9)):
        """Cursor of the event with this ``seq`` or first at/after run time ``t_s`` (sampled-index seek)."""
        rl = runlog(rid)
        if (seq is None) == (t_s is None):
            raise HTTPException(400, "give exactly one of seq, t_s")
        try:
            return {"run_id": rid, "source": source, **el.locate(rl, source, seq=seq, t_s=t_s)}
        except el.CursorError as e:
            raise _bad(e) from None
