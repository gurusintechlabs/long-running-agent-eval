"""Helpers shared by route modules."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException

from ui_server import store
from ui_server.safety import resolve_run_dir
from ui_server.settings import Settings


def run_dir_or_404(settings: Settings, rid: str) -> Path:
    """The run's directory (UI-4 checks applied), or HTTP 404."""
    d = resolve_run_dir(settings.runs_dir, rid)
    if d is None or store.read_json(d / "manifest.json") is None:
        raise HTTPException(404, "no such run")
    return d


@contextmanager
def open_store(settings: Settings):
    """Read-only metrics store (None when it does not exist yet)."""
    con = store.open_ro(settings.db_path)
    try:
        yield con
    finally:
        if con:
            con.close()
