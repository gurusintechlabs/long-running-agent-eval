"""FastAPI app: local-only, token-guarded, read-mostly (docs/ui-design.md §3, §6)."""
from __future__ import annotations

import hmac
import os
import subprocess
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from ui_server import __version__, safefs, store
from ui_server.autoingest import AutoIngest
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
    background: list[AutoIngest] = []

    @asynccontextmanager
    async def lifespan(_app):
        for b in background:
            b.start()
        try:
            yield
        finally:
            for b in background:
                b.stop()

    app = FastAPI(title="LRAE UI", version=__version__, docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    safefs.register_root(settings.runs_dir)
    ingest_lock = threading.Lock()
    home = Path.home()

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.headers.get("host", "")
        origin = request.headers.get("origin")
        path = request.url.path
        if host not in settings.allowed_hosts:
            return secure_headers(_deny(403, "bad host"), path)
        if origin is not None and origin not in settings.allowed_origins:
            return secure_headers(_deny(403, "bad origin"), path)
        if path.startswith("/api/") or path == "/api":
            if not _token_ok(request, settings.token):
                return secure_headers(_deny(401, "missing or wrong token"), path)
        return secure_headers(await call_next(request), path)

    app.add_middleware(BodyLimit, limit=MAX_BODY_BYTES)    # outermost: refuses before anything reads the body

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

    def _store_status(with_mark: bool = False) -> dict:
        con = _con()
        try:
            return store.ingest_status(settings.runs_dir, con, settings.db_path, with_mark=with_mark)
        finally:
            if con:
                con.close()

    def _run_ingest() -> tuple[bool, str]:
        """The `lrae ingest` subprocess; the caller holds ``ingest_lock``."""
        try:
            proc = subprocess.run([*INGEST_CMD, str(settings.runs_dir)] if INGEST_CMD[-1] == "ingest" else INGEST_CMD,
                                  cwd=settings.repo_root, env=ingest_env(dict(os.environ)),
                                  capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            return False, "ingest timed out"
        return proc.returncode == 0, scrub_paths((proc.stdout + proc.stderr)[-4000:], settings.repo_root, home)

    auto = (AutoIngest(status_fn=lambda: _store_status(with_mark=True), run_fn=_run_ingest, lock=ingest_lock)
            if settings.auto_ingest else None)
    if auto is not None:
        background.append(auto)

    @app.get("/api/ingest/status")
    def ingest_status():
        st = _store_status()
        st["auto"] = auto.state() if auto is not None else {"enabled": False}
        return st

    @app.post("/api/ingest")
    def ingest():
        if not ingest_lock.acquire(blocking=False):
            return JSONResponse({"ok": False, "output": "an ingest is already running"}, status_code=409)
        try:
            ok, out = _run_ingest()
        finally:
            ingest_lock.release()
        return JSONResponse({"ok": ok, "output": out}, status_code=200 if ok else 500)

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


def secure_headers(response, path: str):
    """The same headers on every response, including 401/403/413."""
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


MAX_BODY_BYTES = 1024 * 1024
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class BodyLimit:
    """Pure ASGI: a request body above ``limit`` bytes is answered 413 before any route sees it. The
    body is buffered (at most ``limit``) and replayed, so chunked uploads are bounded too."""

    def __init__(self, app, limit: int = MAX_BODY_BYTES):
        self.app, self.limit = app, limit

    async def _refuse(self, scope, send):
        resp = secure_headers(JSONResponse({"detail": f"request body is larger than {self.limit} bytes"},
                                           status_code=413), scope.get("path", ""))
        await resp(scope, None, send)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in _BODY_METHODS:
            return await self.app(scope, receive, send)
        for k, v in scope["headers"]:
            if k == b"content-length":
                try:
                    if int(v) > self.limit:
                        return await self._refuse(scope, send)
                except ValueError:
                    return await self._refuse(scope, send)
        chunks: list[dict] = []
        total = 0
        while True:
            msg = await receive()
            if msg["type"] != "http.request":      # disconnect
                return None
            total += len(msg.get("body", b""))
            if total > self.limit:
                return await self._refuse(scope, send)
            chunks.append(msg)
            if not msg.get("more_body"):
                break
        replay = iter(chunks)

        async def replayed():
            nxt = next(replay, None)
            return nxt if nxt is not None else await receive()

        return await self.app(scope, replayed, send)
