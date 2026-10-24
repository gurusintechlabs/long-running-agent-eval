"""Run-detail timeline payload (U3)."""
from __future__ import annotations

from pathlib import Path

from ui_server import eventlog as el
from ui_server import store, timeline
from ui_server.deps import open_store, run_dir_or_404
from ui_server.safety import scrub_paths


def register(app, settings) -> None:
    @app.get("/api/runs/{rid}/timeline")
    def run_timeline(rid: str):
        rd = run_dir_or_404(settings, rid)
        mf = store.read_json(rd / "manifest.json") or {}
        rid = mf.get("run_id") or rid
        rl = el.RunLog(rd)
        with open_store(settings) as con:
            body = timeline.get(rl, rid, con, mf, settings.db_path)
        return scrub_paths(body, settings.repo_root, Path.home())
