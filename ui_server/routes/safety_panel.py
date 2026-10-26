"""Safety panel data (docs/ui-api-live.md §5): ``GET /api/runs/{id}/safety`` and ``GET /api/rules``."""
from __future__ import annotations

from pathlib import Path

from fastapi import Query

from ui_server import deps, feed, live_state, rule_docs, safety_data, store
from ui_server.safety import scrub_paths


def register(app, settings) -> None:
    home = Path.home()

    def scrub_text(s: str) -> str:
        return scrub_paths(s, settings.repo_root, home)

    @app.get("/api/runs/{rid}/safety")
    def safety(rid: str, limit: int = Query(200, ge=1, le=1000)):
        d = deps.run_dir_or_404(settings, rid)
        mf = store.read_json(d / "manifest.json") or {}
        policy = rule_docs.load_policy(settings.repo_root, mf)
        snap = live_state.REGISTRY.get(d).snapshot(mf, series=False)
        body = safety_data.REGISTRY.get(d).build(
            manifest=mf, policy=policy, clock=feed.load_clock(d), budget=snap["budget"] | {
                "cost_usd": snap["cost"]["usd"], "tokens": snap["cost"]["tokens"]["total"]},
            scrub=scrub_text, limit=limit)
        body["state"] = snap["state"]
        body["live"] = snap["live"]
        return scrub_paths(body, settings.repo_root, home)

    @app.get("/api/rules")
    def rules():
        """The fallback rule table (what each rule protects), for the frontend's rule legend."""
        policy = rule_docs.load_policy(settings.repo_root, None)
        ids = sorted(set(rule_docs.RULE_DOCS) | set(policy.rules))
        return {"policy": {"source": policy.source, "file": policy.path, "sha256": policy.sha256},
                "rules": [rule_docs.explain(r, policy) for r in ids]}
