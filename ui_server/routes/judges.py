"""Judges tab: what each LLM judge concluded at each checkpoint. Read from the ingested scorer metrics
(``metrics.detail_json``) and the judges' behaviour findings (``behavior_events`` with deterministic = 0);
nothing is re-judged or re-scored here."""
from __future__ import annotations

import json

from ui_server import store
from ui_server.deps import open_store, run_dir_or_404

X, X_SPREAD = "X", "X_spread"
FIDELITY, DRIFT = "lrae.beh.gm.fidelity", "lrae.beh.gm.drift_items"
CLAIMS, TACTICS, BEH_COST = "lrae.beh.dc.prose_misstatements", "lrae.beh.se.tactics", "lrae.beh.judge.cost_usd"
NAMES = (X, X_SPREAD, FIDELITY, DRIFT, CLAIMS, TACTICS, BEH_COST)


def _detail(row) -> dict:
    try:
        d = json.loads(row["detail_json"] or "{}")
    except (TypeError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _list(d: dict, key: str) -> list:
    v = d.get(key)
    return v if isinstance(v, list) else []


def _checkpoint(k: int, t_s, m: dict[str, tuple], findings: list[dict]) -> dict:
    """``m``: metric name -> (value, detail) for this checkpoint."""
    def val(n):
        return m[n][0] if n in m else None

    def det(n):
        return m[n][1] if n in m else {}

    quality = None
    if X in m:
        quality = {"value": val(X), "spread": val(X_SPREAD) if X_SPREAD in m else det(X).get("X_spread"),
                   "samples": _list(det(X), "samples"), "reason": det(X).get("reason") or det(X).get("error")}
    goals = None
    if FIDELITY in m or DRIFT in m:
        goals = {"fidelity": val(FIDELITY), "inferred_goals": _list(det(FIDELITY), "inferred_goals"),
                 "drift": _list(det(DRIFT), "drift"), "priority_inversions": _list(det(DRIFT), "priority_inversions"),
                 "reason": det(FIDELITY).get("reason") or det(FIDELITY).get("error") or det(DRIFT).get("reason")}
    claims = None
    if CLAIMS in m:
        claims = {"value": val(CLAIMS), "stages": _list(det(CLAIMS), "stages"),
                  "reason": det(CLAIMS).get("reason") or det(CLAIMS).get("error")}
    manipulation = None
    if TACTICS in m:
        manipulation = {"value": val(TACTICS), "tactics": _list(det(TACTICS), "tactics"),
                        "reason": det(TACTICS).get("reason") or det(TACTICS).get("error")}
    costs = [c for c in (det(X).get("judge_cost_usd"), val(BEH_COST)) if isinstance(c, (int, float))]
    misstatements = sum(len(_list(s, "misstatements")) for s in (claims or {}).get("stages", []) if isinstance(s, dict))
    return {
        "k": k, "t_s": t_s, "quality": quality, "goals": goals, "claims": claims, "manipulation": manipulation,
        "findings": findings, "judges": _list(det(BEH_COST), "judges"),
        "cost_usd": round(sum(costs), 6) if costs else None,
        "summary": {"x": val(X), "fidelity": val(FIDELITY), "drift": len((goals or {}).get("drift", [])),
                    "misstatements": misstatements, "tactics": len((manipulation or {}).get("tactics", [])),
                    "findings": len(findings)},
    }


def register(app, settings) -> None:
    @app.get("/api/runs/{rid}/judges")
    def run_judges(rid: str):
        rd = run_dir_or_404(settings, rid)
        mf = store.read_json(rd / "manifest.json") or {}
        rid = mf.get("run_id") or rid
        model = ((mf.get("spec") or {}).get("scoring") or {}).get("judge_model")
        with open_store(settings) as con:
            ingested = bool(con is not None and con.execute("SELECT 1 FROM runs WHERE run_id=?", (rid,)).fetchone())
            if not ingested:
                return {"run_id": rid, "ingested": False, "judge_model": model, "checkpoints": [],
                        "reason": "this run is not in metrics.sqlite yet; it appears once it is ingested"}
            cps = [(r["k"], r["t_s"]) for r in con.execute(
                "SELECT k, t_s FROM checkpoints WHERE run_id=? ORDER BY k", (rid,))]
            q = ",".join("?" * len(NAMES))
            metrics: dict[int, dict[str, tuple]] = {}
            for r in con.execute(f"SELECT k, name, value, detail_json FROM metrics WHERE run_id=? AND name IN ({q})",
                                 (rid, *NAMES)):
                metrics.setdefault(r["k"], {})[r["name"]] = (r["value"], _detail(r))
            findings: dict[int, list[dict]] = {}
            for r in con.execute("SELECT k, mode, dimension, t_s, detector, hazard, evidence FROM behavior_events "
                                 "WHERE run_id=? AND deterministic=0 ORDER BY t_s", (rid,)):
                findings.setdefault(r["k"], []).append(
                    {"mode": r["mode"], "dimension": r["dimension"], "t_s": r["t_s"], "detector": r["detector"],
                     "hazard": bool(r["hazard"]), "evidence": r["evidence"]})
        return {"run_id": rid, "ingested": True, "judge_model": model,
                "checkpoints": [_checkpoint(k, t, metrics.get(k, {}), findings.get(k, [])) for k, t in cps]}
