"""Compare API (phase U7, docs/ui-api-compare.md): overlay runs and Kaplan-Meier survival.

Read-only. Metric series come from the ``metrics.sqlite`` cache; survival comes from
``analysis.survival`` (called, not reimplemented), so the chart cannot drift from the dashboard.
"""
from __future__ import annotations

import math
import re
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query

from analysis import survival as sv
from analysis.trends import CORE_METRICS
from ui_server import deps, store
from ui_server.safety import scrub_paths, valid_run_id
from ui_server.settings import Settings

MAX_RUNS = 8
COUNTERS = ("cum_cost_usd", "cost_usd", "context_fill_max", "compactions")
SUMMARY_FIELDS = ("duration_s", "ttfh_s", "cost_usd", "tokens", "hazard_count", "checkpoints")
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", re.ASCII)
COST_NOTE = "estimated (API-equivalent) cost, not a bill"


def clean(v):
    """JSON-safe copy: NaN and infinities become null (Starlette refuses to encode them)."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    return v


def valid_label(s: object) -> bool:
    return isinstance(s, str) and _LABEL.fullmatch(s) is not None


def _per_run_series(con: sqlite3.Connection, rid: str) -> tuple[dict, dict]:
    t_by_k = {r["k"]: r["t_s"] for r in con.execute("SELECT k, t_s FROM checkpoints WHERE run_id=?", (rid,))}

    def collect(rows) -> dict:
        out: dict[str, dict] = {}
        for r in rows:
            s = out.setdefault(r["name"], {"k": [], "t_s": [], "value": []})
            s["k"].append(r["k"])
            s["t_s"].append(t_by_k.get(r["k"]))
            s["value"].append(r["value"])
        return out

    metrics = collect(con.execute("SELECT name, k, value FROM metrics WHERE run_id=? ORDER BY name, k", (rid,)))
    marks = ",".join("?" * len(COUNTERS))
    counters = collect(con.execute(f"SELECT name, k, value FROM counters WHERE run_id=? AND name IN ({marks}) "
                                   "ORDER BY name, k", (rid, *COUNTERS)))
    return metrics, counters


def _last(vals: list) -> float | None:
    for v in reversed(vals):
        if isinstance(v, (int, float)) and math.isfinite(v):
            return float(v)
    return None


def _metric_order(names: set[str]) -> list[str]:
    core = [m for m in CORE_METRICS if m in names]
    return core + sorted(names - set(core))


def build_compare(settings: Settings, ids: list[str]) -> dict:
    runs, notes = [], []
    with deps.open_store(settings) as con:
        db = store.db_runs(con)
        for rid in ids:
            d = deps.run_dir_or_404(settings, rid)
            mf = store.read_json(d / "manifest.json") or {}
            real = mf.get("run_id") or rid
            summary = store.run_summary(d, mf, db.get(real))
            _, cps = store.checkpoints(d, con, real)
            if summary["ingested"] and con is not None:
                metrics, counters = _per_run_series(con, real)
                haz = store.hazards(con, real)
            else:
                metrics, counters, haz = {}, {}, []
                notes.append(f"{real}: not ingested; only checkpoint times are available. "
                             "Re-ingest to compare metrics, hazards and cost series.")
            runs.append({"run_id": real, "summary": summary, "ingested": summary["ingested"],
                         "checkpoints": [{"k": c["k"], "t_s": c["t_s"]} for c in cps],
                         "series": metrics, "counters": counters, "hazards": haz})
    names: set[str] = set()
    for r in runs:
        names |= set(r["series"])
    metric_names = _metric_order(names)

    base = runs[0]
    aligned: dict[str, dict] = {}
    metric_deltas = []
    for m in metric_names:
        ks = sorted({k for r in runs for k in r["series"].get(m, {}).get("k", [])})
        vals: dict[str, list | None] = {}
        for r in runs:
            s = r["series"].get(m)
            byk = dict(zip(s["k"], s["value"], strict=True)) if s else {}
            vals[r["run_id"]] = [byk.get(k) for k in ks] if s else None
        aligned[m] = {"k": ks, "values": vals}
        final = {r["run_id"]: _last(r["series"][m]["value"]) if m in r["series"] else None for r in runs}
        finite = {rid: [v for v in (vs or []) if isinstance(v, (int, float)) and math.isfinite(v)]
                  for rid, vs in vals.items()}
        b = final[base["run_id"]]
        metric_deltas.append({
            "metric": m, "final": final,
            "mean": {rid: (sum(v) / len(v) if v else None) for rid, v in finite.items()},
            "min": {rid: (min(v) if v else None) for rid, v in finite.items()},
            "max": {rid: (max(v) if v else None) for rid, v in finite.items()},
            "delta_vs_base": {rid: (None if b is None or v is None or rid == base["run_id"] else v - b)
                              for rid, v in final.items()}})
    summary_deltas = []
    for f in SUMMARY_FIELDS:
        sv_ = {r["run_id"]: r["summary"].get(f) for r in runs}
        b = sv_[base["run_id"]]
        summary_deltas.append({"field": f, "values": sv_, "delta_vs_base": {
            rid: (None if b is None or v is None or rid == base["run_id"] else v - b)
            for rid, v in sv_.items()}})
    body = {"run_ids": [r["run_id"] for r in runs], "base": base["run_id"], "runs": runs,
            "metrics": metric_names, "aligned_by_k": aligned, "metric_deltas": metric_deltas,
            "summary_deltas": summary_deltas, "not_ingested": [r["run_id"] for r in runs if not r["ingested"]],
            "notes": notes, "cost_note": COST_NOTE}
    return scrub_paths(clean(body), settings.repo_root, Path.home())


def _km_json(km: sv.KM, times: list[float], events: list[int]) -> dict:
    cens = sorted(t for t, e in zip(times, events, strict=True) if e == 0)
    return {"times": km.times.tolist(), "surv": km.surv.tolist(), "lower": km.lower.tolist(),
            "upper": km.upper.tolist(), "n_risk": km.n_risk.tolist(), "n_event": km.n_event.tolist(),
            "censor_times": cens, "censor_surv": [km.survival_at(t) for t in cens]}


def build_survival(db_path: Path, experiment: str, configs: set[str] | None, dimension: str | None) -> dict:
    con = store.open_ro(db_path)
    if con is None:
        raise HTTPException(404, "no metrics store yet (ingest first)")
    try:
        rows = con.execute("SELECT task_class, config, event, censored_reason, state FROM runs "
                           "WHERE experiment_id=?", (experiment,)).fetchall()
    finally:
        con.close()
    if not rows:
        raise HTTPException(404, "experiment not in the metrics store (ingest first)")
    groups_in = sv.survival_inputs(db_path, experiment, dimension)
    excluded: dict[str, int] = {}
    for _cls, _cfg, ev, reason, state in rows:
        if ev is None:
            key = reason or (state or "unknown").lower()
            excluded[key] = excluded.get(key, 0) + 1
    out = []
    for (cls, cfg), (ts, es) in sorted(groups_in.items()):
        if configs and cfg not in configs:
            continue
        reasons: dict[str, int] = {}
        for c2, g2, ev, reason, _ in rows:
            if (c2, g2) == (cls, cfg) and ev == 0:
                reasons[reason or "unspecified"] = reasons.get(reason or "unspecified", 0) + 1
        item = {"task_class": cls, "config": cfg, "label": f"{cls} / config {cfg}",
                "n": len(ts), "events": int(sum(es)), "censored": len(ts) - int(sum(es)),
                "censored_by_reason": reasons}
        try:
            s = sv.summarize(ts, es)
            lo, hi = s["median_ci_boot"]
            item.update({
                "available": True, "km": _km_json(s["km"], ts, es), "median_s": s["median"],
                "median_text": sv.NOT_REACHED if s["median"] is None else f"{s['median'] / 60:.1f} min",
                "median_ci_boot_s": [lo, hi], "median_ci_hi_not_reached": hi is None,
                "headline_s": s["headline"], "headline_available": True,
                "headline_text": sv.headline_text(s["headline"])})
        except (ValueError, ArithmeticError) as exc:  # pragma: no cover - defensive
            item.update({"available": False, "headline_available": False,
                         "headline_text": "not available", "error": str(exc)})
        out.append(item)
    return clean({"experiment": experiment, "dimension": dimension, "groups": out, "excluded": excluded,
                  "runs_total": len(rows), "target": 0.8, "level": 0.90,
                  "note": None if out else "no run of this experiment is in the survival set"})


def register(app: FastAPI, settings: Settings) -> None:
    @app.get("/api/compare")
    def compare(runs: str = Query("", max_length=2000)):
        ids = list(dict.fromkeys(p.strip() for p in runs.split(",") if p.strip()))
        if not ids:
            raise HTTPException(400, "pass runs=<id>,<id>")
        if len(ids) > MAX_RUNS:
            raise HTTPException(400, f"at most {MAX_RUNS} runs can be compared")
        if any(not valid_run_id(i) for i in ids):
            raise HTTPException(400, "malformed run id")
        return build_compare(settings, ids)

    @app.get("/api/survival")
    def survival(experiment: str = Query("", max_length=200), config: str = Query("", max_length=500),
                 dimension: str = Query("", max_length=64)):
        if not valid_label(experiment):
            raise HTTPException(400, "pass a valid experiment=<id>")
        cfgs = {c.strip() for c in config.split(",") if c.strip()}
        if any(not valid_label(c) for c in cfgs) or (dimension and not valid_label(dimension)):
            raise HTTPException(400, "malformed config or dimension")
        return build_survival(settings.db_path, experiment, cfgs or None, dimension or None)
