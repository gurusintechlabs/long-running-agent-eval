"""Static dashboard v1 (docs/spec.md §10): Jinja2 + matplotlib PNGs built from ``metrics.sqlite``.

No server and no network: CSS is inline and figures are relative PNG files next to the HTML.
``collect_context`` is shared with ``report.build`` (the one-page PDF stub).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from analysis import behavior, degradation, survival, trends
from report import charts

TEMPLATES = Path(__file__).parent / "templates"
COST_LABEL = "estimated (API-equivalent)"


def env() -> Environment:
    return Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]),
                       undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)


def fmt_min(seconds: float | None) -> str:
    return "-" if seconds is None else f"{seconds / 60:.1f} min"


def _query(con: sqlite3.Connection, sql: str, args: tuple = ()) -> list[dict]:
    cur = con.execute(sql, args)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def incidents(runs: list[dict], hazards: list[dict]) -> list[dict]:
    """Hazards (all dimensions, incl. guardrail safety violations) plus kills, budget stops and
    interruptions, ordered by run then time."""
    out = []
    for h in hazards:
        out.append({"run_id": h["run_id"], "t_s": h["t_attributed_s"], "kind": f"hazard: {h['dimension']}",
                    "detail": f"{h['rule']} (checkpoint {h['k']}): {h['evidence']}"})
    for r in runs:
        t = r["duration_s"]
        if r["state"] == "KILLED":
            safety = next((h for h in hazards if h["run_id"] == r["run_id"] and h["dimension"] == "safety"), None)
            out.append({"run_id": r["run_id"], "t_s": t, "kind": "guardrail kill",
                        "detail": safety["rule"] if safety else "no safety hazard recorded"})
        elif r["state"] == "BUDGET_EXHAUSTED":
            out.append({"run_id": r["run_id"], "t_s": t, "kind": "budget stop", "detail": "per-run budget reached"})
        elif r["state"] == "INTERRUPTED":
            out.append({"run_id": r["run_id"], "t_s": t, "kind": "interruption",
                        "detail": r["censored_reason"] or "interrupted"})
        elif r["state"] == "FAILED":
            out.append({"run_id": r["run_id"], "t_s": t, "kind": "failed run", "detail": "excluded from survival"})
    out.sort(key=lambda i: (i["run_id"], i["t_s"] if i["t_s"] is not None else 1e18, i["kind"]))
    for i in out:
        i["t_min"] = fmt_min(i["t_s"])
    return out


MAX_DEGRADATION_RUNS = 12
_SAFE = "".join(chr(c) for c in range(128) if chr(c).isalnum()) + "-_"


def _pct(v: float | None) -> str:
    return "-" if v is None else f"{100 * v:.0f}%"


def degradation_context(db_path: Path, experiment_id: str, fig_dir: Path) -> dict:
    """Degradation figures and tables; ``{"has_data": False}`` when no run has per-commit data."""
    rids = degradation.runs_with_data(db_path, experiment_id)
    if not rids:
        return {"has_data": False}
    shown = rids[:MAX_DEGRADATION_RUNS]
    runs, intervals, windows = [], [], []
    for rid in shown:
        safe = "".join(c if c in _SAFE else "_" for c in rid)
        m = degradation.load_matrix(db_path, rid)
        flips = degradation.flip_events(db_path, rid)
        rates = degradation.pass_rates(db_path, rid)
        iv = degradation.fill_intervals(db_path, rid)
        belief = degradation.belief_gap(db_path, rid)
        stages = [(s, t) for s, t, _ in degradation.stage_deliveries(db_path, rid)]
        comp = [i["t1"] for i in iv if i["compactions"]]
        names = {"heatmap": f"deg_{safe}_heatmap.png", "tiers": f"deg_{safe}_tiers.png",
                 "fill": f"deg_{safe}_regressions_fill.png", "belief": f"deg_{safe}_belief.png"}
        charts.outcome_heatmap(m, flips, fig_dir / names["heatmap"], stages=stages, title=f"{rid}: test outcomes")
        charts.tier_rate_chart(rates, fig_dir / names["tiers"], stages=stages, compactions=comp,
                               title=f"{rid}: pass rate per tier")
        charts.regression_fill_chart(iv, flips, fig_dir / names["fill"], title=f"{rid}: regressions vs context fill")
        charts.belief_gap_chart(belief, fig_dir / names["belief"], title=f"{rid}: belief gap")
        summ = degradation.run_summary(db_path, rid)
        bs = degradation.belief_summary(belief)
        effects = [{**e, **{k: _pct(e[k]) for k in ("carried_before", "carried_after", "carried_end",
                                                    "retired_before", "introduced_end")}}
                   for e in degradation.stage_effects(db_path, rid)]
        status = degradation.status_counts(db_path, rid)
        runs.append({"run_id": rid, "figs": names, "summary": {
            **summ, "mean_ttfr": fmt_min(summ["mean_ttfr_s"]), "est_min": _pct(summ["established_min"]),
            "est_final": _pct(summ["established_final"]), "overall_final": _pct(summ["overall_final"])},
            "belief": {**bs, "gap_frac": _pct(bs["gap_frac"])}, "effects": effects,
            "final_status": status[-1] if status else None,
            "staged": len(degradation.stage_deliveries(db_path, rid)) > 1})
        intervals += iv
        windows.append(degradation.window_rates(db_path, rid))
    pooled_windows = []
    for w in range(max((len(x) for x in windows), default=0)):
        sel = [x[w] for x in windows if len(x) > w]
        n, h = sum(i["regressions"] for i in sel), sum(i["hours"] for i in sel)
        pooled_windows.append({"window": w + 1, "runs": len(sel), "regressions": n, "hours": f"{h:.2f}",
                               "per_hour": "-" if h <= 0 else f"{n / h:.1f}"})
    fmt = lambda r: "-" if r is None else f"{r:.1f}"  # noqa: E731
    bins = [{"label": f"{b['lo']:.2f}-{b['hi']:.2f}" if b["hi"] else f">= {b['lo']:.2f}",
             "intervals": b["intervals"], "regressions": b["regressions"], "per_hour": fmt(b["per_hour"])}
            for b in degradation.fill_bins(intervals)]
    comp_eff = [{**e, "per_hour": fmt(e["per_hour"])} for e in degradation.compaction_effect(intervals)]
    top = [{**r, "ttfr": fmt_min(r["ttfr_s"]), "first_pass": fmt_min(r["first_pass_t"])}
           for r in degradation.top_relapsers(db_path, shown)]
    return {"has_data": True, "runs": runs, "skipped_runs": len(rids) - len(shown), "bins": bins,
            "compaction_effect": comp_eff, "windows": pooled_windows, "top": top}


MAX_BEHAVIOR_RUNS = 12


def behavior_context(db_path: Path, experiment_id: str, fig_dir: Path) -> dict:
    """Behaviour and security panels (plan B5b); ``{"has_data": False}`` without behaviour or SEC data."""
    if not behavior.has_data(db_path, experiment_id):
        return {"has_data": False}
    curves = behavior.mode_survival(db_path, experiment_id)
    charts.survival_chart(curves, fig_dir / "beh_survival.png",
                          title="Per-mode survival: runs without a hazard of the mode (Kaplan-Meier, 95% CI)")
    fmt = lambda v: "-" if v is None else f"{v:.2f}"  # noqa: E731
    hours = [{"hour": r["hour"], "agent_hours": f"{r['agent_hours']:.2f}",
              "cells": {m: (f"{c['events']} ({c['hazards']}) · {fmt(c['per_hour'])}/h" if (c := r["modes"].get(m))
                            else "-") for m in behavior.ALL_MODES}} for r in behavior.incidence_by_hour(db_path, experiment_id)]
    fills = [{"label": f"{b['lo']:.2f}-{b['hi']:.2f}" if b["hi"] else f">= {b['lo']:.2f}",
              "agent_hours": f"{b['agent_hours']:.2f}",
              "cells": {m: (f"{c['events']} ({c['hazards']}) · {fmt(c['per_hour'])}/h" if (c := b["modes"].get(m))
                            else "-") for m in behavior.ALL_MODES}} for b in behavior.incidence_by_fill(db_path, experiment_id)]
    runs, episodes = [], []
    for rid in behavior.run_ids(db_path, experiment_id):
        tl = behavior.timeline(db_path, rid)
        trend = behavior.security_trend(db_path, rid)
        has_sec = any(r["new_high"] is not None or r["exploits_failed"] is not None for r in trend)
        eps = behavior.stuck_episodes(db_path, rid)
        if not (tl["events"] or has_sec or eps):
            continue
        episodes += [{**e, "run_id": rid, "t_min": fmt_min(e["t_s"])} for e in eps]
        if len(runs) >= MAX_BEHAVIOR_RUNS:
            continue
        safe = "".join(c if c in _SAFE else "_" for c in rid)
        figs = {"timeline": f"beh_{safe}_timeline.png", "security": None}
        charts.behavior_timeline(tl, fig_dir / figs["timeline"], title=f"{rid}: behaviour timeline")
        if has_sec:
            figs["security"] = f"beh_{safe}_security.png"
            charts.security_trend_chart(trend, fig_dir / figs["security"], title=f"{rid}: security trend")
        af = behavior.af_anomalies(db_path, rid)
        runs.append({"run_id": rid, "figs": figs, "anomalies": af["anomalies"],
                     "events": [{**e, "t_min": fmt_min(e["t_s"])} for e in tl["events"]]})
    cost = sum(v or 0.0 for (v,) in behavior._rows(
        db_path, "SELECT m.value FROM metrics m JOIN runs r USING(run_id) WHERE r.experiment_id=? AND "
                 "m.name='behavior_judge_cost_usd'", (experiment_id,)))
    return {"has_data": True, "modes": behavior.ALL_MODES, "table": behavior.mode_table(db_path, experiment_id),
            "survival": [{"label": c["label"], "median": fmt_min(c["median"]) if c["median"] is not None
                          else survival.NOT_REACHED} for c in curves],
            "hours": hours, "fills": fills, "runs": runs, "episodes": episodes,
            "escalation": behavior.escalation_summary(episodes), "judge_cost": f"${cost:.2f}"}


def collect_context(db_path: Path, experiment_id: str, out_dir: Path) -> dict:
    """Render the figures into ``out_dir/figures`` and return the template context."""
    db_path, out_dir = Path(db_path), Path(out_dir)
    fig_dir = out_dir / "figures"
    con = sqlite3.connect(db_path)
    try:
        exp = _query(con, "SELECT * FROM experiments WHERE experiment_id=? ORDER BY spec_hash", (experiment_id,))
        if not exp:
            raise LookupError(f"experiment {experiment_id!r} not found in {db_path}")
        runs = _query(con, "SELECT * FROM runs WHERE experiment_id=? ORDER BY config, repeat, run_id",
                      (experiment_id,))
        hazards = _query(con, "SELECT h.* FROM hazards h JOIN runs r USING(run_id) WHERE r.experiment_id=? "
                              "ORDER BY h.run_id, h.t_attributed_s, h.dimension", (experiment_id,))
        n_cp = dict(con.execute("SELECT run_id, COUNT(*) FROM checkpoints GROUP BY run_id"))
    finally:
        con.close()
    haz_by_run: dict[str, list[dict]] = {}
    for h in hazards:
        haz_by_run.setdefault(h["run_id"], []).append(h)

    # survival, one curve per (task class, config)
    groups = survival.survival_inputs(db_path, experiment_id)
    curves, summaries = [], []
    for (cls, cfg), (ts, es) in sorted(groups.items()):
        s = survival.summarize(ts, es)
        label = f"{cls} / config {cfg} (n={s['n']}, events={s['events']})"
        curves.append({"label": label, "km": s["km"], "headline": s["headline"]})
        lo, hi = s["median_ci_boot"]
        med = fmt_min(s["median"]) if s["median"] is not None else survival.NOT_REACHED
        summaries.append({"label": label, "n": s["n"], "events": s["events"], "median": med,
                          "median_ci": f"{fmt_min(lo)} to {fmt_min(hi) if hi is not None else survival.NOT_REACHED}",
                          "headline": survival.headline_text(s["headline"]),
                          "headline_s": s["headline"]})
    figs = {"survival": charts.survival_chart(curves, fig_dir / "survival.png").name}

    series = trends.metric_series(db_path, experiment_id)
    charts.metric_strips(series, fig_dir / "metric_strips.png")
    cost = trends.counter_series(db_path, experiment_id, "cum_cost_usd")
    charts.cost_chart(cost, fig_dir / "cost.png")
    fill = trends.counter_series(db_path, experiment_id, "context_fill_max")
    comp = {}
    for rid, (t, v) in trends.counter_series(db_path, experiment_id, "compactions").items():
        comp[rid] = [tt for tt, vv in zip(t, v, strict=True) if vv and vv > 0]
    charts.context_chart(fill, fig_dir / "context_fill.png", compactions=comp,
                         hazards={rid: [(h["t_attributed_s"], h["dimension"]) for h in hs]
                                  for rid, hs in haz_by_run.items()})

    deg = degradation_context(db_path, experiment_id, fig_dir)
    beh = behavior_context(db_path, experiment_id, fig_dir)

    rows = []
    for r in runs:
        rows.append({**r, "duration": fmt_min(r["duration_s"]), "ttfh": fmt_min(r["ttfh_s"]),
                     "cost": "-" if r["cost_usd"] is None else f"${r['cost_usd']:.2f}",
                     "tokens_fmt": f"{r['tokens']:,}" if r["tokens"] is not None else "-",
                     "checkpoints": n_cp.get(r["run_id"], 0),
                     "outcome": ("hazard" if r["event"] == 1 else
                                 f"censored ({r['censored_reason']})" if r["event"] == 0 else
                                 f"excluded ({r['censored_reason'] or r['state'].lower()})")})
    modes = sorted({r["isolation_mode"] for r in runs if r["isolation_mode"]})
    return {"experiment_id": experiment_id, "spec_hash": exp[0]["spec_hash"], "runs": rows,
            "incidents": incidents(runs, hazards), "summaries": summaries, "figures": figs, "degradation": deg, "behavior": beh,
            "cost_label": COST_LABEL, "isolation_modes": modes, "not_isolated": "local" in modes,
            "n_censored_limit": sum(1 for r in runs if r["censored_reason"] in ("usage_limit", "usage-limit"))}


def build_dashboard(db_path: Path, experiment_id: str, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    ctx = collect_context(db_path, experiment_id, out_dir)
    html = env().get_template("dashboard.html.j2").render(**ctx)
    path = out_dir / "dashboard.html"
    path.write_text(html, encoding="utf-8")
    return path
