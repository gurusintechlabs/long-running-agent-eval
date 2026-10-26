"""Spec editor API (phase U6, docs/ui-api-specs.md). Writes only into ``spec/drafts``."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ui_server import spec_store as ss
from ui_server.settings import Settings
from ui_server.spec_ui import build_form_schema

_SUGGEST_ROOTS = ("fixtures", "guardrails")
_SUGGEST_MAX = 200


class SpecBody(BaseModel):
    data: dict[str, Any] | None = None
    yaml: str | None = None


class SaveBody(SpecBody):
    name: str
    overwrite: bool = False


class DuplicateBody(BaseModel):
    new_name: str | None = None
    source: str | None = None
    overwrite: bool = False


def register(app: FastAPI, settings: Settings) -> None:
    dirs = ss.SpecDirs(settings.repo_root)

    def guard(fn):
        try:
            return fn()
        except ss.StoreError as exc:
            raise HTTPException(exc.status, exc.detail) from exc

    @app.get("/api/specs")
    def specs_list():
        return {"specs": ss.list_specs(dirs), "drafts_dir": "spec/drafts", "examples_dir": "spec/examples"}

    @app.get("/api/specs/schema")
    def specs_schema():
        return build_form_schema()

    @app.get("/api/specs/paths")
    def specs_paths(q: str = Query("", max_length=200)):
        """Repo files to pick for path fields, as paths relative to ``spec/drafts`` (what a spec stores)."""
        root = settings.repo_root.resolve()
        q = q.strip().lstrip("./")
        out: list[dict] = []
        skip = {".git", "__pycache__", "node_modules", ".venv"}
        for top in _SUGGEST_ROOTS:
            base = root / top
            if not base.is_dir() or base.is_symlink():
                continue
            for dp, dns, fns in os.walk(base, followlinks=False):
                dns[:] = sorted(d for d in dns if d not in skip and not (Path(dp) / d).is_symlink())
                for n, kind in [(d, "dir") for d in dns] + [(f, "file") for f in sorted(fns)]:
                    rel = (Path(dp) / n).relative_to(root).as_posix()
                    if len(out) < _SUGGEST_MAX and (not q or q in rel) and not (Path(dp) / n).is_symlink():
                        out.append({"value": "../../" + rel, "repo_path": rel, "kind": kind})
        return {"paths": out, "truncated": len(out) >= _SUGGEST_MAX}

    @app.post("/api/specs/validate")
    def specs_validate(body: SpecBody):
        _, res = guard(lambda: ss.check_text_or_data(body.data, body.yaml, dirs))
        return res.to_json()

    @app.post("/api/specs/save")
    def specs_save(body: SaveBody):
        res = guard(lambda: ss.save_draft(dirs, body.name, body.data, body.yaml, body.overwrite))
        return JSONResponse(res, status_code=200 if res["saved"] else 422)

    @app.get("/api/specs/{name}")
    def specs_get(name: str, source: str | None = Query(None, pattern="^(draft|example)$")):
        return guard(lambda: ss.load_one(dirs, name, source))

    @app.post("/api/specs/{name}/duplicate")
    def specs_duplicate(name: str, body: DuplicateBody | None = None):
        b = body or DuplicateBody()
        res = guard(lambda: ss.duplicate(dirs, name, b.new_name, b.source, b.overwrite))
        return JSONResponse(res, status_code=200 if res["saved"] else 422)

    @app.delete("/api/specs/{name}")
    def specs_delete(name: str):
        guard(lambda: ss.delete_draft(dirs, name))
        return {"deleted": True, "name": name}
