"""Transcript endpoints (U3)."""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Query

from ui_server import eventlog as el
from ui_server import transcript as tr
from ui_server.deps import run_dir_or_404
from ui_server.safety import scrub_paths


def _csv(v: str | None, cap: int = 30) -> list[str]:
    return [x for x in (v or "").split(",") if x][:cap]


def register(app, settings) -> None:
    home = Path.home()

    @app.get("/api/runs/{rid}/transcript")
    def transcript(rid: str, after: str | None = Query(None, max_length=100), limit: int = Query(tr.DEFAULT_LIMIT, ge=1),
                   tool: str | None = Query(None, max_length=1000), kind: str | None = Query(None, max_length=200),
                   q: str | None = Query(None, max_length=el.MAX_Q), errors_only: bool = False,
                   turn: int | None = Query(None, ge=1, le=100000), around: str | None = Query(None, max_length=100),
                   around_seq: int | None = Query(None, ge=0), around_t_s: float | None = Query(None, ge=0, le=1e9),
                   before: int = Query(20, ge=0, le=200), after_n: int = Query(5, ge=0, le=200),
                   max_chars: int = Query(1500, ge=50, le=tr.KEEP_CHARS)):
        rl = el.RunLog(run_dir_or_404(settings, rid))
        kinds = _csv(kind)
        if any(k not in tr.KINDS for k in kinds):
            raise HTTPException(400, f"kind must be among {', '.join(tr.KINDS)}")
        try:
            body = tr.query(rl, after=after, limit=min(limit, tr.MAX_LIMIT), tools=_csv(tool), kinds=kinds, q=q,
                            errors_only=errors_only, turn=turn, around=around, around_seq=around_seq,
                            around_t_s=around_t_s, ctx_before=before, ctx_after=after_n, max_chars=max_chars)
        except el.CursorError as e:
            raise HTTPException(400, str(e)) from None
        return scrub_paths({"run_id": rid, **body}, settings.repo_root, home)

    @app.get("/api/runs/{rid}/transcript/item")
    def transcript_item(rid: str, cursor: str = Query(..., max_length=100)):
        """Full tool input, result event and (when present) the full result text of one item."""
        rl = el.RunLog(run_dir_or_404(settings, rid))
        try:
            d = tr.item_detail(rl, cursor)
        except el.CursorError as e:
            raise HTTPException(400, str(e)) from None
        if d is None:
            raise HTTPException(404, "no transcript item at this cursor")
        return scrub_paths({"run_id": rid, **d}, settings.repo_root, home)
