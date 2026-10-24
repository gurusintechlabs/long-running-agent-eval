"""Test outcome matrix, flips and regressions for the heatmap (U3). Numbers come from
``analysis.degradation`` (called, not reimplemented) over the ingested ``metrics.sqlite``."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import HTTPException, Query

from analysis import degradation as dg
from ui_server import store
from ui_server.deps import open_store, run_dir_or_404

CODES = {"passed": "p", "failed": "f", "error": "e", "skipped": "s", None: "-"}
MAX_TESTS = 5000


def _rate_point(r: dg.RatePoint) -> dict:
    d = asdict(r)
    d["overall"], d["established"] = r.overall, r.established
    d["tiers"] = {t: list(v) for t, v in r.tiers.items()}
    return d


def register(app, settings) -> None:
    @app.get("/api/runs/{rid}/tests")
    def run_tests(rid: str, suite: str = Query("hidden", max_length=40)):
        rd = run_dir_or_404(settings, rid)
        mf = store.read_json(rd / "manifest.json") or {}
        rid = mf.get("run_id") or rid
        with open_store(settings) as con:
            ingested = bool(con is not None and con.execute("SELECT 1 FROM runs WHERE run_id=?", (rid,)).fetchone())
            suites = ([r[0] for r in con.execute("SELECT DISTINCT suite FROM test_outcomes WHERE run_id=? ORDER BY 1",
                                                 (rid,))] if ingested else [])
        if not ingested:
            return {"run_id": rid, "ingested": False, "has_outcomes": False, "suite": suite, "suites": [],
                    "reason": "this run is not in metrics.sqlite yet; re-ingest to see test outcomes"}
        if suites and suite not in suites:
            raise HTTPException(400, f"suite must be one of {', '.join(suites)}")
        db = settings.db_path
        m = dg.load_matrix(db, rid, suite)
        body = {"run_id": rid, "ingested": True, "suite": suite, "suites": suites, "has_outcomes": bool(m),
                "legend": {"p": "passed", "f": "failed", "e": "error", "s": "skipped", "-": "not scored"}}
        with open_store(settings) as con:
            cps = [{"k": r["k"], "t_s": r["t_s"], "head_sha": r["head_sha"]} for r in con.execute(
                "SELECT k, t_s, head_sha FROM checkpoints WHERE run_id=? ORDER BY k", (rid,))]
        body["checkpoints"] = cps
        body["stages"] = [{"stage": s, "t_s": t, "interrupted": i} for s, t, i in dg.stage_deliveries(db, rid)]
        if not m:
            return {**body, "points": [], "tests": [], "flips": [], "timelines": [], "pass_rates": [],
                    "status_counts": [], "stage_effects": [], "window_rates": [], "summary": None,
                    "tests_truncated": False}
        tests = m.tests[:MAX_TESTS]
        body["points"] = [asdict(p) for p in m.points]
        body["tests"] = [{"id": t, "tier": m.tier[t], "cells": "".join(CODES.get(o, "-") for o in m.outcome[t])}
                         for t in tests]
        body["tests_truncated"] = len(m.tests) > MAX_TESTS
        body["flips"] = [asdict(f) for f in dg.flip_events(db, rid, suite)]
        body["timelines"] = [{**asdict(t), "relapsed": t.relapsed} for t in dg.timelines(db, rid, suite)]
        body["pass_rates"] = [_rate_point(r) for r in dg.pass_rates(db, rid, suite)]
        body["status_counts"] = dg.status_counts(db, rid, suite)
        body["stage_effects"] = dg.stage_effects(db, rid, suite)
        body["window_rates"] = dg.window_rates(db, rid, 3600.0, suite)
        body["summary"] = dg.run_summary(db, rid, suite)
        return body
