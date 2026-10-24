"""Reports API (phase U7, docs/ui-api-compare.md): list, serve and rebuild ``runs/reports/<exp>/``.

Serving is allowlist-only (UI-4). Rebuilding runs the real CLI (``lrae dashboard`` / ``lrae report
--pdf``) as a subprocess with a scrubbed environment (UI-7), one at a time.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ui_server import deps, store
from ui_server.safety import scrub_paths, valid_run_id
from ui_server.settings import Settings

# Served names: exactly these, plus figures/<png>. Anything else is a 404.
TOP_FILES = {"dashboard.html": "text/html; charset=utf-8", "report.pdf": "application/pdf"}
_FIGURE = re.compile(r"figures/[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.png", re.ASCII)
REPORT_CSP = ("sandbox; default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
              "base-uri 'none'; form-action 'none'; frame-ancestors 'self'")
_FILE_PATH = re.compile(r"^/api/reports/[^/]+/file$")
ENV_KEEP = ("PATH", "LANG", "LC_ALL", "TMPDIR", "LRAE_CHROME")
TAIL = 4000
BUILD_TIMEOUT_S = 420
COST_NOTE = "estimated (API-equivalent) cost, not a bill"


def build_env(base: dict[str, str]) -> dict[str, str]:
    """Environment for the report CLI (UI-7). Only PATH, locale and TMPDIR, plus ``LRAE_CHROME`` so the
    operator's Chrome override reaches ``report.build.find_chrome``. No ``HOME``: the CLI only reads
    ``metrics.sqlite`` and runs Chrome with a throwaway ``--user-data-dir``; matplotlib gets its own cache dir.
    """
    env = {k: base[k] for k in ENV_KEEP if k in base}
    env["MPLCONFIGDIR"] = str(Path(env.get("TMPDIR", "/tmp")) / "lrae-ui-mpl")
    return env


def is_served_name(name: str) -> bool:
    return name in TOP_FILES or _FIGURE.fullmatch(name) is not None


def media_type(name: str) -> str:
    return TOP_FILES.get(name) or "image/png"


class RebuildBody(BaseModel):
    kind: str
    allow_stale: bool = False


class _ReportCSP:
    """Outermost ASGI wrapper: the app-wide middleware stamps one CSP on every response, so the served
    dashboard's sandbox CSP is set here, after it, for ``/api/reports/<exp>/file`` HTML only."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not _FILE_PATH.match(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        async def send2(msg):
            if msg["type"] == "http.response.start":
                hs = list(msg.get("headers", []))
                ctype = next((v for k, v in hs if k.lower() == b"content-type"), b"")
                if ctype.startswith(b"text/html"):
                    hs = [(k, v) for k, v in hs if k.lower() != b"content-security-policy"]
                    hs.append((b"content-security-policy", REPORT_CSP.encode()))
                    msg = {**msg, "headers": hs}
            await send(msg)

        await self.app(scope, receive, send2)


def _contained(root: Path, p: Path) -> Path | None:
    """``p`` resolved, if it is a regular file inside ``root`` and not reached through a symlink."""
    try:
        if p.is_symlink():
            return None
        r = p.resolve()
    except (OSError, RuntimeError):
        return None
    return r if r.is_file() and r.is_relative_to(root) else None


def chrome_status() -> dict:
    try:
        from report.build import find_chrome
        find_chrome()
        return {"available": True, "error": None}
    except Exception as exc:  # ChromeNotFound, or an import problem
        return {"available": False, "error": str(exc)}


def register(app: FastAPI, settings: Settings) -> None:
    app.add_middleware(_ReportCSP)
    lock = threading.Lock()
    reports_root = settings.runs_dir / "reports"

    def exp_dir(exp: str) -> Path | None:
        """The experiment's report directory (resolved, inside runs/reports), or None."""
        if not valid_run_id(exp):
            return None
        try:
            root = reports_root.resolve()
            d = (root / exp).resolve()
        except (OSError, RuntimeError):
            return None
        return d if d.parent == root and d.is_dir() else None

    def artifacts(d: Path) -> dict:
        out: dict = {"figures": []}
        for name in TOP_FILES:
            f = _contained(d, d / name)
            if f:
                st = f.stat()
                out[name] = {"name": name, "bytes": st.st_size, "mtime": st.st_mtime}
        fig = d / "figures"
        if fig.is_dir() and not fig.is_symlink():
            for p in sorted(fig.iterdir()):
                n = f"figures/{p.name}"
                f = _contained(d, p) if _FIGURE.fullmatch(n) else None
                if f:
                    out["figures"].append({"name": n, "bytes": f.stat().st_size, "mtime": f.stat().st_mtime})
        return out

    def db_experiments() -> dict[str, float | None]:
        """experiment id -> newest run end in the store (None when unknown)."""
        with deps.open_store(settings) as con:
            if con is None:
                return {}
            return {r[0]: r[1] for r in con.execute(
                "SELECT experiment_id, MAX(end_ts) FROM runs GROUP BY experiment_id") if r[0]}

    def ingest_state() -> dict:
        with deps.open_store(settings) as con:
            return store.ingest_status(settings.runs_dir, con, settings.db_path)

    @app.get("/api/reports")
    def reports_list():
        in_store = db_experiments()
        names = set(in_store)
        try:
            names |= {p.name for p in reports_root.iterdir() if p.is_dir() and not p.is_symlink()}
        except OSError:
            pass
        items = []
        for exp in sorted(n for n in names if valid_run_id(n)):
            d = exp_dir(exp)
            art = artifacts(d) if d else {"figures": []}
            has = any(k in art for k in TOP_FILES) or bool(art["figures"])
            built = [art[k]["mtime"] for k in TOP_FILES if k in art]
            items.append({"experiment_id": exp, "in_store": exp in in_store, "has_reports": has,
                          "dashboard": art.get("dashboard.html"), "pdf": art.get("report.pdf"),
                          "figures": art["figures"], "built_epoch": max(built) if built else None})
        items.sort(key=lambda i: (not i["has_reports"], i["experiment_id"]))
        store_epoch = settings.db_path.stat().st_mtime if settings.db_path.is_file() else None
        for i in items:
            i["older_than_store"] = bool(i["built_epoch"] and store_epoch and i["built_epoch"] < store_epoch)
        return {"experiments": items, "ingest": ingest_state(), "chrome": chrome_status(),
                "cost_note": COST_NOTE}

    @app.get("/api/reports/{experiment}/file")
    def report_file(experiment: str, name: str = Query("", max_length=200)):
        d = exp_dir(experiment)
        if d is None or not is_served_name(name):
            raise HTTPException(404, "no such report file")
        f = _contained(d, d / name)
        if f is None:
            raise HTTPException(404, "no such report file")
        headers = {"Content-Disposition": f'inline; filename="{f.name}"'} if name == "report.pdf" else None
        return FileResponse(f, media_type=media_type(name), headers=headers)

    def argv(exp: str, kind: str, out: Path) -> list[str]:
        base = [sys.executable, "-m", "runner.cli"]
        db = ["--db", str(settings.db_path), "--out", str(out)]
        if kind == "dashboard":
            return [*base, "dashboard", exp, *db]
        return [*base, "report", exp, "--pdf", *db]

    @app.post("/api/reports/{experiment}/rebuild")
    def rebuild(experiment: str, body: RebuildBody):
        if not valid_run_id(experiment):
            raise HTTPException(404, "no such experiment")
        if body.kind not in ("dashboard", "pdf"):
            raise HTTPException(422, "kind must be dashboard or pdf")
        if experiment not in db_experiments():
            raise HTTPException(404, {"code": "not_in_store",
                                      "message": "experiment is not in the metrics store; ingest first"})
        ing = ingest_state()
        if ing["stale"] and not body.allow_stale:
            raise HTTPException(409, {"code": "store_stale", "message": f"metrics store is stale: {ing['reason']}",
                                      "reason": ing["reason"]})
        if body.kind == "pdf":
            ch = chrome_status()
            if not ch["available"]:
                raise HTTPException(424, {"code": "chrome_not_found", "message": ch["error"]})
        if not lock.acquire(blocking=False):
            raise HTTPException(409, {"code": "busy", "message": "a report rebuild is already running"})
        t0 = time.monotonic()
        try:
            reports_root.mkdir(exist_ok=True)
            out = reports_root / experiment
            try:
                proc = subprocess.run(argv(experiment, body.kind, out), cwd=settings.repo_root,
                                      env=build_env(dict(os.environ)), capture_output=True, text=True,
                                      timeout=BUILD_TIMEOUT_S)
                tail = (proc.stdout + proc.stderr)[-TAIL:]
                ok, code = proc.returncode == 0, proc.returncode
            except subprocess.TimeoutExpired:
                tail, ok, code = f"timed out after {BUILD_TIMEOUT_S}s", False, None
        finally:
            lock.release()
        tail = scrub_paths(tail, settings.repo_root, Path.home())
        name = "dashboard.html" if body.kind == "dashboard" else "report.pdf"
        art = artifacts(exp_dir(experiment)) if exp_dir(experiment) else {}
        res = {"ok": ok, "kind": body.kind, "exit_code": code, "output": tail, "artifact": art.get(name),
               "duration_s": round(time.monotonic() - t0, 2), "stale_store": bool(ing["stale"])}
        return JSONResponse(res, status_code=200 if ok else 500)
