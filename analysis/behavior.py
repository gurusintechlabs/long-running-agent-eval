"""Behaviour analysis (plan B5b; docs/behavior-design.md §6, §9) over ``metrics.sqlite``.

Reads the ``behavior_events``, ``run_markers``, ``hazards``, ``metrics``, ``counters``, ``checkpoints``
and ``runs`` tables written by ``analysis.ingest``. Every result is derived from the logs (rule 5).

* **Per-mode survival**: time to the first *hazard* behaviour event of a mode, Kaplan-Meier over the
  survival set; runs without one are censored at their duration. VI is the ``security`` hazard
  (exploit tests). Other modes' hazards do not censor.
* **Incidence per agent-hour**: behaviour events (all, and hazards) per hour of agent time, by run
  hour (exposure: each run's duration split into hours) and by context-fill bin (exposure: checkpoint
  intervals by their ``context_fill_max``; time after the last checkpoint has no fill and is left out).
* **AF anomalies**: tool calls per minute per checkpoint interval, flagged against the prior intervals
  (robust z from median/MAD for spikes; a drop below ``drop_frac`` of the prior median, which covers
  the design's "under 10% of the baseline rate" stall); plus the run's AF loop and stall events.
* **Stuck episodes and risk escalation**: the ED detector's episodes (``lrae.beh.ed.stuck_episodes``) with
  their escalation slope (risk tier against attempt number).
* **Security trend**: new SAST findings by severity, open findings, exploit-test failures and AI-review
  findings per checkpoint.
"""
from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from statistics import median

from analysis import survival
from analysis.degradation import FILL_BINS
from scorer import metric_names as mn

ALL_MODES = ("RH", "GM", "AF", "CE", "ED", "CP", "CF", "OK", "DC", "SE", "UA", "VI")


def _rows(db_path: Path, sql: str, args: tuple = ()) -> list[tuple]:
    con = sqlite3.connect(db_path)
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.OperationalError:   # a store from before the behaviour tables
        return []
    finally:
        con.close()


def run_ids(db_path: Path, experiment_id: str) -> list[str]:
    return [r for (r,) in _rows(db_path, "SELECT run_id FROM runs WHERE experiment_id=? ORDER BY config, repeat, "
                                         "run_id", (experiment_id,))]


def has_data(db_path: Path, experiment_id: str) -> bool:
    return bool(_rows(db_path, "SELECT 1 FROM behavior_events b JOIN runs r USING(run_id) WHERE r.experiment_id=? "
                               "LIMIT 1", (experiment_id,)) or
                _rows(db_path, "SELECT 1 FROM metrics m JOIN runs r USING(run_id) WHERE r.experiment_id=? AND "
                               "(m.name LIKE 'lrae.beh.%' OR m.name LIKE 'lrae.sec.%' OR m.name LIKE 'BEH\\_%' ESCAPE '\\' "
                               "OR m.name LIKE 'SEC\\_%' ESCAPE '\\') LIMIT 1", (experiment_id,)))


# --- per-mode survival -----------------------------------------------------------------------------

def _first_hazard(db_path: Path, experiment_id: str, mode: str) -> dict[str, float]:
    if mode == "VI":
        return dict(_rows(db_path, "SELECT h.run_id, h.t_attributed_s FROM hazards h JOIN runs r USING(run_id) "
                                   "WHERE r.experiment_id=? AND h.dimension='security'", (experiment_id,)))
    return dict(_rows(db_path, "SELECT b.run_id, MIN(b.t_s) FROM behavior_events b JOIN runs r USING(run_id) "
                               "WHERE r.experiment_id=? AND b.mode=? AND b.hazard=1 GROUP BY b.run_id",
                      (experiment_id, mode)))


def mode_survival_inputs(db_path: Path, experiment_id: str, mode: str) -> dict[tuple[str, str], tuple[list, list]]:
    """``{(task_class, config): (times, events)}`` for one mode, over the survival set."""
    first = _first_hazard(db_path, experiment_id, mode)
    out: dict[tuple[str, str], tuple[list, list]] = {}
    for rid, cls, cfg, dur in _rows(db_path, "SELECT run_id, task_class, config, duration_s FROM runs WHERE "
                                             "experiment_id=? AND event IS NOT NULL ORDER BY run_id", (experiment_id,)):
        t, e = (first[rid], 1) if rid in first else (dur, 0)
        ts, es = out.setdefault((cls, cfg), ([], []))
        ts.append(float(t))
        es.append(e)
    return out


def mode_survival(db_path: Path, experiment_id: str) -> list[dict]:
    """One Kaplan-Meier curve per (mode, task class, config) that has at least one event."""
    out = []
    for mode in ALL_MODES:
        for (cls, cfg), (ts, es) in sorted(mode_survival_inputs(db_path, experiment_id, mode).items()):
            if not sum(es):
                continue
            km = survival.kaplan_meier(ts, es)
            out.append({"mode": mode, "label": f"{mode} · {cls} / {cfg} (n={len(ts)}, events={sum(es)})",
                        "km": km, "n": len(ts), "events": sum(es), "median": km.median()})
    return out


# --- incidence -------------------------------------------------------------------------------------

def _events(db_path: Path, experiment_id: str) -> list[tuple]:
    return _rows(db_path, "SELECT b.run_id, b.t_s, b.mode, b.hazard FROM behavior_events b JOIN runs r "
                          "USING(run_id) WHERE r.experiment_id=? AND b.t_s IS NOT NULL", (experiment_id,))


def _add(modes: dict, mode: str, hazard: int) -> None:
    m = modes.setdefault(mode, {"events": 0, "hazards": 0, "per_hour": None})
    m["events"] += 1
    m["hazards"] += int(bool(hazard))


def _rates(rows: list[dict]) -> list[dict]:
    for r in rows:
        for m in r["modes"].values():
            m["per_hour"] = round(m["events"] / r["agent_hours"], 4) if r["agent_hours"] > 0 else None
    return rows


def incidence_by_hour(db_path: Path, experiment_id: str) -> list[dict]:
    """``[{hour, agent_hours, modes: {mode: {events, hazards, per_hour}}}]`` by run hour."""
    durs = dict(_rows(db_path, "SELECT run_id, duration_s FROM runs WHERE experiment_id=? AND duration_s > 0",
                      (experiment_id,)))
    n = max((math.ceil(d / 3600 - 1e-9) for d in durs.values()), default=0)
    rows = [{"hour": h, "agent_hours": sum(min(max(d - 3600 * h, 0.0), 3600.0) for d in durs.values()) / 3600,
             "modes": {}} for h in range(n)]
    for rid, t, mode, hz in _events(db_path, experiment_id):
        if rid in durs and 0 <= t <= durs[rid]:
            _add(rows[min(int(t // 3600), n - 1)]["modes"], mode, hz)
    return _rates(rows)


def incidence_by_fill(db_path: Path, experiment_id: str) -> list[dict]:
    """``[{lo, hi, intervals, agent_hours, modes}]`` by the interval's ``context_fill_max``."""
    cps: dict[str, list[tuple[int, float]]] = {}
    for rid, k, t in _rows(db_path, "SELECT c.run_id, c.k, c.t_s FROM checkpoints c JOIN runs r USING(run_id) "
                                    "WHERE r.experiment_id=? AND c.t_s IS NOT NULL ORDER BY c.run_id, c.k",
                           (experiment_id,)):
        cps.setdefault(rid, []).append((k, t))
    fill = {(rid, k): v for rid, k, v in _rows(
        db_path, "SELECT c.run_id, c.k, c.value FROM counters c JOIN runs r USING(run_id) WHERE r.experiment_id=? "
                 "AND c.name='context_fill_max'", (experiment_id,))}
    rows = [{"lo": lo, "hi": None if hi == math.inf else hi, "intervals": 0, "agent_hours": 0.0, "modes": {}}
            for lo, hi in FILL_BINS]

    def bin_of(v):
        return next((i for i, (lo, hi) in enumerate(FILL_BINS) if lo <= v < hi), None) if v is not None else None
    spans: dict[str, list[tuple[float, float, int | None]]] = {}
    for rid, pts in cps.items():
        prev = 0.0
        for k, t in pts:
            b = bin_of(fill.get((rid, k)))
            spans.setdefault(rid, []).append((prev, t, b))
            if b is not None:
                rows[b]["intervals"] += 1
                rows[b]["agent_hours"] += (t - prev) / 3600
            prev = t
    for rid, t, mode, hz in _events(db_path, experiment_id):
        b = next((b for t0, t1, b in spans.get(rid, []) if t0 < t <= t1 or (t0 == 0.0 and t == 0.0)), None)
        if b is not None:
            _add(rows[b]["modes"], mode, hz)
    return _rates(rows)


# --- AF anomalies ----------------------------------------------------------------------------------

def rate_anomalies(rates: list[float], *, window: int = 6, z: float = 4.0, min_prior: int = 3,
                   drop_frac: float = 0.1) -> list[dict]:
    """``[{i, kind: spike|drop, value, z?}]`` against the prior ``window`` values."""
    out = []
    for i, x in enumerate(rates):
        prior = [v for v in rates[max(0, i - window):i] if v is not None]
        if x is None or len(prior) < min_prior:
            continue
        med = median(prior)
        scale = max(1.4826 * median(abs(v - med) for v in prior), 1e-9 + 0.05 * med, 1e-9)
        score = (x - med) / scale
        if score > z:
            out.append({"i": i, "kind": "spike", "value": x, "z": round(score, 2)})
        elif med > 0 and x < drop_frac * med:
            out.append({"i": i, "kind": "drop", "value": x, "z": round(score, 2)})
    return out


def af_anomalies(db_path: Path, run_id: str, *, window: int = 6, z: float = 4.0, min_prior: int = 3,
                 drop_frac: float = 0.1) -> dict:
    cps = _rows(db_path, "SELECT k, t_s FROM checkpoints WHERE run_id=? AND t_s IS NOT NULL ORDER BY k", (run_id,))
    calls = dict(_rows(db_path, "SELECT k, value FROM counters WHERE run_id=? AND name='tool_calls'", (run_id,)))
    intervals, prev = [], 0.0
    for k, t in cps:
        mins = (t - prev) / 60
        v = calls.get(k)
        intervals.append({"k": k, "t0": prev, "t1": t,
                          "rate_per_min": None if v is None or mins <= 0 else v / mins})
        prev = t
    flags = rate_anomalies([i["rate_per_min"] for i in intervals], window=window, z=z, min_prior=min_prior,
                           drop_frac=drop_frac)
    for f in flags:
        intervals[f["i"]]["flag"] = f["kind"]
    ev = [{"t_s": t, "detector": d, "hazard": h, "evidence": e} for t, d, h, e in _rows(
        db_path, "SELECT t_s, detector, hazard, evidence FROM behavior_events WHERE run_id=? AND mode='AF' "
                 "ORDER BY t_s, detector", (run_id,))]
    return {"intervals": intervals, "anomalies": [{**f, "k": intervals[f["i"]]["k"]} for f in flags], "events": ev}


# --- stuck episodes --------------------------------------------------------------------------------

def stuck_episodes(db_path: Path, run_id: str) -> list[dict]:
    out = []
    for k, detail in _rows(db_path, "SELECT k, detail_json FROM metrics WHERE run_id=? AND "
                                    "name IN ('lrae.beh.ed.stuck_episodes', 'BEH_ED_stuck_episodes') ORDER BY k", (run_id,)):
        for ep in (json.loads(detail or "{}").get("episodes") or []):
            out.append({"k": k, "t_s": ep.get("t_s"), "command": ep.get("command"), "attempts": ep.get("attempts"),
                        "max_tier": ep.get("max_tier"), "escalation": ep.get("escalation")})
    return out


def escalation_summary(episodes: list[dict]) -> dict:
    n = len(episodes)
    esc = sum(1 for e in episodes if (e.get("escalation") or 0) > 0)
    tiers = [e.get("max_tier") or 0 for e in episodes]
    return {"episodes": n, "escalating": esc, "share_escalating": round(esc / n, 4) if n else None,
            "max_tier": max(tiers, default=None), "reached_tier4": sum(1 for t in tiers if t >= 4)}


# --- security trend and timeline -------------------------------------------------------------------

def security_trend(db_path: Path, run_id: str) -> list[dict]:
    rows: dict[int, dict] = {}
    for k, t in _rows(db_path, "SELECT k, t_s FROM checkpoints WHERE run_id=? ORDER BY k", (run_id,)):
        rows[k] = {"k": k, "t_s": t, "new_high": None, "new_medium": None, "new_low": None, "open": None,
                   "exploits_failed": None, "exploits_active": None, "exploits_inherited": None, "ai_findings": None}
    for k, name, v, detail in _rows(db_path, "SELECT k, name, value, detail_json FROM metrics WHERE run_id=? AND "
                                             "name IN ('lrae.sec.new','lrae.sec.open','lrae.sec.exploits','lrae.sec.ai',"
                                             "'SEC_new','SEC_open','SEC_exploits','SEC_ai')", (run_id,)):
        r = rows.get(k)
        if r is None:
            continue
        d = json.loads(detail or "{}")
        name = name if name.startswith(mn.SEC_PREFIX) else "lrae.sec." + name[4:]
        if name == mn.SEC_NEW:
            sev = d.get("new_by_severity") or {}
            r.update(new_high=int(sev.get("high", 0)), new_medium=int(sev.get("medium", 0)),
                     new_low=int(sev.get("low", 0)))
        elif name == mn.SEC_OPEN:
            r["open"] = v
        elif name == mn.SEC_EXPLOITS:
            inh = d.get("inherited")             # absent before inherited exploits were marked (2026-10-22)
            r.update(exploits_failed=v, exploits_active=d.get("active"),
                     exploits_inherited=None if inh is None else len(inh))
        else:
            r["ai_findings"] = v
    return [rows[k] for k in sorted(rows)]


def timeline(db_path: Path, run_id: str) -> dict:
    ev = [{"t_s": t, "k": k, "mode": m, "detector": d, "severity": s, "deterministic": det, "evidence": e}
          for t, k, m, d, s, det, e in _rows(
              db_path, "SELECT t_s, k, mode, detector, severity, deterministic, evidence FROM behavior_events "
                       "WHERE run_id=? ORDER BY t_s, mode, detector", (run_id,))]
    ev += [{"t_s": t, "k": k, "mode": "VI", "detector": rule, "severity": "hazard", "deterministic": 1, "evidence": e}
           for t, k, rule, e in _rows(db_path, "SELECT t_attributed_s, k, rule, evidence FROM hazards WHERE run_id=? "
                                              "AND dimension='security'", (run_id,))]
    ev.sort(key=lambda x: (x["t_s"], x["mode"], x["detector"]))
    mk = [{"t_s": t, "kind": kind, "label": label} for t, kind, label in _rows(
        db_path, "SELECT t_s, kind, label FROM run_markers WHERE run_id=? ORDER BY t_s, kind, label", (run_id,))]
    dur = _rows(db_path, "SELECT duration_s FROM runs WHERE run_id=?", (run_id,))
    return {"events": ev, "markers": mk, "duration_s": dur[0][0] if dur else None}


def mode_table(db_path: Path, experiment_id: str) -> list[dict]:
    """Per mode: runs with any event, runs with a hazard, events, hazard events and judge events."""
    agg = {m: {"mode": m, "runs_with_events": 0, "runs_with_hazard": 0, "events": 0, "hazard_events": 0,
               "judge_events": 0} for m in ALL_MODES}
    for mode, runs, hz_runs, n, hz, judged in _rows(db_path, """
            SELECT b.mode, COUNT(DISTINCT b.run_id), COUNT(DISTINCT CASE WHEN b.hazard=1 THEN b.run_id END),
                   COUNT(*), SUM(b.hazard), SUM(1 - b.deterministic)
            FROM behavior_events b JOIN runs r USING(run_id) WHERE r.experiment_id=? GROUP BY b.mode""",
                                                    (experiment_id,)):
        if mode in agg:
            agg[mode].update(runs_with_events=runs, runs_with_hazard=hz_runs, events=n, hazard_events=hz or 0,
                             judge_events=judged or 0)
    vi = _first_hazard(db_path, experiment_id, "VI")
    agg["VI"].update(runs_with_hazard=len(vi), runs_with_events=max(agg["VI"]["runs_with_events"], len(vi)))
    return [agg[m] for m in ALL_MODES]
