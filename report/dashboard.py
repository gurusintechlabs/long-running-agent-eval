"""Static dashboard v1 (docs/spec.md §10): Jinja2 + matplotlib PNGs built from ``metrics.sqlite``.

No server and no network: CSS is inline and figures are relative PNG files next to the HTML.
``collect_context`` is shared with ``report.build`` (the one-page PDF stub).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from analysis import survival, trends
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
            "incidents": incidents(runs, hazards), "summaries": summaries, "figures": figs,
            "cost_label": COST_LABEL, "isolation_modes": modes, "not_isolated": "local" in modes,
            "n_censored_limit": sum(1 for r in runs if r["censored_reason"] in ("usage_limit", "usage-limit"))}


def build_dashboard(db_path: Path, experiment_id: str, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    ctx = collect_context(db_path, experiment_id, out_dir)
    html = env().get_template("dashboard.html.j2").render(**ctx)
    path = out_dir / "dashboard.html"
    path.write_text(html, encoding="utf-8")
    return path
