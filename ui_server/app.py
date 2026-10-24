"""FastAPI app: local-only, token-guarded, read-mostly (docs/ui-design.md §3, §6)."""
from __future__ import annotations

import hmac
import os
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from ui_server import __version__, store
from ui_server.safety import resolve_run_dir, scrub_paths
from ui_server.settings import Settings

INGEST_CMD = [sys.executable, "-m", "runner.cli", "ingest"]
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
PLACEHOLDER = ("<!doctype html><meta charset=utf-8><title>LRAE</title><body style=\"font:16px system-ui;"
               "margin:2rem\"><h1>LRAE UI</h1><p>The web bundle has not been built yet "
               "(<code>cd ui/web &amp;&amp; npm run build</code>). The JSON API is up under "
               "<code>/api</code>.</p>")


def ingest_env(base: dict[str, str]) -> dict[str, str]:
    """Environment for the ingest subprocess (UI-7): nothing from the host except PATH and locale."""
    keep = ("PATH", "LANG", "LC_ALL", "TMPDIR")
    return {k: base[k] for k in keep if k in base}


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="LRAE UI", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    ingest_lock = threading.Lock()
    home = Path.home()

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.headers.get("host", "")
        origin = request.headers.get("origin")
        if host not in settings.allowed_hosts:
            return _deny(403, "bad host")
        if origin is not None and origin not in settings.allowed_origins:
            return _deny(403, "bad origin")
        if request.url.path.startswith("/api/") or request.url.path == "/api":
            if not _token_ok(request, settings.token):
                return _deny(401, "missing or wrong token")
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def _con():
        return store.open_ro(settings.db_path)

    def _runs():
        con = _con()
        try:
            return store.list_runs(settings.runs_dir, con)
        finally:
            if con:
                con.close()

    def _run_dir(rid: str) -> Path:
        d = resolve_run_dir(settings.runs_dir, rid)
        if d is None or store.read_json(d / "manifest.json") is None:
            raise HTTPException(404, "no such run")
        return d

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__}

    @app.get("/api/runs")
    def runs():
        return {"runs": _runs()}

    @app.get("/api/experiments")
    def experiments():
        return {"experiments": store.experiments(_runs())}

    @app.get("/api/runs/{rid}")
    def run_detail(rid: str):
        d = _run_dir(rid)
        mf = store.read_json(d / "manifest.json")
        con = _con()
        try:
            row = store.db_runs(con).get(mf.get("run_id") or rid)
            body = {"run": store.run_summary(d, mf, row), "manifest": store.run_detail_manifest(mf),
                    "hazards": store.hazards(con, mf.get("run_id") or rid) if row else []}
        finally:
            if con:
                con.close()
        return scrub_paths(body, settings.repo_root, home)

    @app.get("/api/runs/{rid}/checkpoints")
    def run_checkpoints(rid: str):
        d = _run_dir(rid)
        con = _con()
        try:
            ingested, rows = store.checkpoints(d, con, rid)
        finally:
            if con:
                con.close()
        return {"run_id": rid, "ingested": ingested, "checkpoints": rows}

    @app.get("/api/ingest/status")
    def ingest_status():
        con = _con()
        try:
            return store.ingest_status(settings.runs_dir, con, settings.db_path)
        finally:
            if con:
                con.close()

    @app.post("/api/ingest")
    def ingest():
        if not ingest_lock.acquire(blocking=False):
            return JSONResponse({"ok": False, "output": "an ingest is already running"}, status_code=409)
        try:
            proc = subprocess.run([*INGEST_CMD, str(settings.runs_dir)] if INGEST_CMD[-1] == "ingest" else INGEST_CMD,
                                  cwd=settings.repo_root, env=ingest_env(dict(os.environ)),
                                  capture_output=True, text=True, timeout=600)
            out = (proc.stdout + proc.stderr)[-4000:]
            return JSONResponse({"ok": proc.returncode == 0, "output": out},
                                status_code=200 if proc.returncode == 0 else 500)
        except subprocess.TimeoutExpired:
            return JSONResponse({"ok": False, "output": "ingest timed out"}, status_code=500)
        finally:
            ingest_lock.release()

    from ui_server.routes import register_all
    register_all(app, settings)  # phase route modules (ui_server/routes/*.py)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    def api_404(rest: str):
        raise HTTPException(404, "no such endpoint")

    dist = settings.web_dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        index = dist / "index.html"
        if not index.is_file():
            return HTMLResponse(PLACEHOLDER)
        if path:
            try:
                f = (dist / path).resolve()
            except (OSError, RuntimeError):
                f = None
            if f is not None and f.is_file() and f.is_relative_to(dist):
                return FileResponse(f)
        return FileResponse(index)

    return app


def _token_ok(request: Request, token: str) -> bool:
    got = request.headers.get("x-lrae-token")
    if got is None:
        auth = request.headers.get("authorization", "")
        got = auth[7:] if auth.lower().startswith("bearer ") else None
    return got is not None and hmac.compare_digest(got.encode(), token.encode())


def _deny(code: int, msg: str) -> JSONResponse:
    return JSONResponse({"detail": msg}, status_code=code)
