"""JSONL run artifacts -> ``metrics.sqlite`` (docs/spec.md §9.1, docs/interfaces.md §6).

The store is a derived cache: it is rebuilt from scratch into a temp file and renamed into place,
rows are inserted in a deterministic order and nothing time-of-ingestion is stored, so re-running
``ingest`` on unchanged runs reproduces identical table contents.
"""
from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE experiments(experiment_id TEXT, spec_hash TEXT, spec_json TEXT);
CREATE TABLE runs(run_id TEXT PRIMARY KEY, experiment_id TEXT, task_class TEXT, config TEXT,
  repeat INTEGER, isolation_mode TEXT, state TEXT, start_ts REAL, end_ts REAL, duration_s REAL,
  resumed INTEGER, censored_reason TEXT, ttfh_s REAL, event INTEGER, cost_usd REAL, tokens INTEGER);
CREATE TABLE checkpoints(run_id TEXT, k INTEGER, t_s REAL, head_sha TEXT, dirty INTEGER,
  pause_ms REAL, PRIMARY KEY(run_id, k));
CREATE TABLE metrics(run_id TEXT, k INTEGER, name TEXT, value REAL, detail_json TEXT,
  PRIMARY KEY(run_id, k, name));
CREATE TABLE counters(run_id TEXT, k INTEGER, name TEXT, value REAL, PRIMARY KEY(run_id, k, name));
CREATE TABLE hazards(run_id TEXT, dimension TEXT, rule TEXT, t_attributed_s REAL, t_detected_s REAL,
  k INTEGER, evidence TEXT, PRIMARY KEY(run_id, dimension));
CREATE TABLE events_index(run_id TEXT, source TEXT, type TEXT, count INTEGER,
  PRIMARY KEY(run_id, source, type));
"""
TABLES = ("experiments", "runs", "checkpoints", "metrics", "counters", "hazards", "events_index")
# Used when telemetry.counters is unavailable so downstream consumers still see every name.
ZERO_COUNTERS = ("tokens_in", "tokens_out", "tokens_cache_read", "tokens_cache_creation",
                 "cost_usd", "tool_calls", "context_fill_max", "context_fill_last", "compactions",
                 "turns", "sessions", "api_errors", "otel_lag_ms_p95")
TOKEN_COUNTERS = ("tokens_in", "tokens_out", "tokens_cache_read", "tokens_cache_creation")
_CENSOR_BY_STATE = {"COMPLETED": "deadline", "BUDGET_EXHAUSTED": "budget"}


@dataclass
class IngestReport:
    db_path: Path
    runs: int = 0
    checkpoints: int = 0
    metrics: int = 0
    counters: int = 0
    hazards: int = 0
    events_indexed: int = 0
    in_survival: int = 0
    warnings: list[str] = field(default_factory=list)


def read_jsonl(path: Path) -> list[dict]:
    """Lines that parse as JSON objects; torn/blank lines are skipped."""
    out = []
    if not path.exists():
        return out
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                out.append(rec)
    return out


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def last_ok_passes(scorer_events: list[dict]) -> dict[int, str]:
    """``{k: pass_id}`` for the last pass per k that has ``scorer.done`` with ok = true."""
    passes: dict[int, str] = {}
    for ev in scorer_events:
        p = ev.get("payload") or {}
        if ev.get("type") == "scorer.done" and p.get("ok") is True and "k" in p:
            passes[int(p["k"])] = p.get("pass_id")
    return passes


def scored_view(scorer_events: list[dict]) -> tuple[list[tuple], list[dict]]:
    """Metric rows ``(k, name, value, detail)`` and hazard payloads of the selected passes."""
    ok = last_ok_passes(scorer_events)
    metrics: dict[tuple[int, str], tuple] = {}
    hazards: dict[str, dict] = {}
    for ev in scorer_events:
        p = ev.get("payload") or {}
        if p.get("pass_id") is None or ok.get(p.get("k")) != p.get("pass_id"):
            continue
        if ev.get("type") == "scorer.metric":
            metrics[(int(p["k"]), p["name"])] = (int(p["k"]), p["name"], _num(p.get("value")),
                                                 p.get("detail") or {})
        elif ev.get("type") == "scorer.hazard":
            cur = hazards.get(p["dimension"])
            if cur is None or (p["t_attributed_s"], p["k"]) < (cur["t_attributed_s"], cur["k"]):
                hazards[p["dimension"]] = p
    return [metrics[key] for key in sorted(metrics)], [hazards[d] for d in sorted(hazards)]


def _counters(events_dir: Path, rid: str, report: IngestReport) -> list[dict]:
    try:
        from telemetry.counters import interval_counters  # written concurrently; import lazily
        return list(interval_counters(events_dir))
    except Exception as exc:  # missing module/function or a failure inside it
        report.warnings.append(f"{rid}: counters unavailable ({type(exc).__name__}: {exc}); zeros recorded")
        return []


def _iso_epoch(ts: str) -> float:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def _run_record(run_dir: Path, mf: dict, orch: list[dict], hazards: list[dict],
                report: IngestReport) -> dict:
    rid = mf["run_id"]
    end = mf.get("end") or {}
    states = [e["payload"]["to"] for e in orch if e.get("type") == "state" and "to" in e.get("payload", {})]
    state = end.get("state") or (states[-1] if states else "UNFINISHED")
    clocks = [e["payload"] for e in orch if e.get("type") == "run.clock"]
    offset = float(clocks[-1].get("offset_s") or 0) if clocks else 0.0
    start = mf.get("original_start_epoch") or mf.get("start_epoch")
    end_ts = end.get("end_epoch")
    # Run time is measured like checkpoint t_s: from the last run.clock origin (which already
    # includes a resume offset) to entering FINALIZING. Preparation (venv, probe) and finalizing
    # (agent shutdown, scorer drain) are not agent time and must not lengthen censored runs.
    fin = [e for e in orch if e.get("type") == "state" and e.get("payload", {}).get("to") == "FINALIZING"]
    if clocks and clocks[-1].get("start_epoch") is not None and fin:
        duration = _iso_epoch(fin[-1]["ts"]) - float(clocks[-1]["start_epoch"])
    else:  # never reached RUNNING, or an old log: fall back to the manifest
        cur_start = mf.get("start_epoch")
        duration = (end_ts - cur_start + offset) if (end_ts is not None and cur_start is not None) else None
    ttfh = min((h["t_attributed_s"] for h in hazards), default=None)
    event: int | None
    reason: str | None = None
    if state == "FAILED" or not end or duration is None:
        event = None  # excluded from survival
        reason = end.get("censored_reason") or ("failed" if state == "FAILED" else "unfinished")
    elif ttfh is not None:
        event = 1
    else:
        event, ttfh = 0, None
        if state == "INTERRUPTED":
            reason = end.get("censored_reason") or "interrupted"
        elif state == "KILLED":
            reason = "killed_without_hazard"
            report.warnings.append(f"{rid}: KILLED without a safety hazard in scorer.jsonl")
        else:
            reason = _CENSOR_BY_STATE.get(state) or end.get("censored_reason") or state.lower()
    spec = mf.get("spec") or {}
    task = spec.get("task") or {}
    return {
        "run_id": rid, "experiment_id": mf.get("experiment_id") or spec.get("experiment_id"),
        "task_class": task.get("class") or task.get("task_class"), "config": mf.get("config"),
        "repeat": mf.get("repeat"), "isolation_mode": mf.get("isolation_mode"), "state": state,
        "start_ts": start, "end_ts": end_ts, "duration_s": duration,
        "resumed": int(bool(mf.get("resumed"))), "censored_reason": reason, "ttfh_s": ttfh,
        "event": event,
    }


def _build(runs_dir: Path, con: sqlite3.Connection, report: IngestReport) -> None:
    con.executescript(SCHEMA)
    seen_specs: dict[tuple, str] = {}
    for mpath in sorted(runs_dir.glob("*/manifest.json")):
        run_dir = mpath.parent
        try:
            mf = json.loads(mpath.read_text())
            rid = mf["run_id"]
        except (ValueError, KeyError, OSError) as exc:
            report.warnings.append(f"{run_dir.name}: unreadable manifest ({exc}); skipped")
            continue
        events = run_dir / "events"
        orch = read_jsonl(events / "orchestrator.jsonl")
        metrics, hazards = scored_view(read_jsonl(events / "scorer.jsonl"))
        rec = _run_record(run_dir, mf, orch, hazards, report)

        counters = _counters(events, rid, report)
        ctr_rows: dict[tuple[int, str], float] = {}
        for row in counters:
            k = int(row["k"])
            for name, v in row.items():
                if name != "k" and _num(v) is not None:
                    ctr_rows[(k, name)] = float(v)
        if not counters:
            n_cp = len({e["payload"]["k"] for e in orch if e.get("type") == "checkpoint"})
            ctr_rows = {(k, n): 0.0 for k in range(1, n_cp + 1) for n in ZERO_COUNTERS}
        rec["cost_usd"] = sum(v for (_, n), v in ctr_rows.items() if n == "cost_usd")
        rec["tokens"] = int(sum(v for (_, n), v in ctr_rows.items() if n in TOKEN_COUNTERS))
        cols = list(rec)
        con.execute(f"INSERT INTO runs({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                    [rec[c] for c in cols])
        report.runs += 1
        report.in_survival += rec["event"] is not None

        spec_json = json.dumps(mf.get("spec") or {}, sort_keys=True)
        key = (rec["experiment_id"], mf.get("spec_hash"))
        if key not in seen_specs:
            seen_specs[key] = spec_json
            con.execute("INSERT INTO experiments VALUES(?,?,?)", (*key, spec_json))

        cps = {}
        for e in orch:
            if e.get("type") == "checkpoint" and "k" in e.get("payload", {}):
                cps[int(e["payload"]["k"])] = e["payload"]  # a resumed run re-emits k: last wins
        for k in sorted(cps):
            p = cps[k]
            con.execute("INSERT INTO checkpoints VALUES(?,?,?,?,?,?)",
                        (rid, k, _num(p.get("t_s")), p.get("head_sha"),
                         None if p.get("dirty") is None else int(bool(p["dirty"])), _num(p.get("pause_ms"))))
        report.checkpoints += len(cps)
        for k, name, value, detail in metrics:
            con.execute("INSERT INTO metrics VALUES(?,?,?,?,?)",
                        (rid, k, name, value, json.dumps(detail, sort_keys=True)))
        report.metrics += len(metrics)
        for (k, name), v in sorted(ctr_rows.items()):
            con.execute("INSERT INTO counters VALUES(?,?,?,?)", (rid, k, name, v))
        report.counters += len(ctr_rows)
        for h in hazards:
            con.execute("INSERT INTO hazards VALUES(?,?,?,?,?,?,?)",
                        (rid, h["dimension"], h.get("rule"), _num(h.get("t_attributed_s")),
                         _num(h.get("t_detected_s")), h.get("k"),
                         h["evidence"] if isinstance(h.get("evidence"), str)
                         else json.dumps(h.get("evidence"), sort_keys=True)))
        report.hazards += len(hazards)

        idx: Counter = Counter()
        for f in sorted(events.glob("*.jsonl")):
            for ev in read_jsonl(f):
                idx[(ev.get("source") or f.stem, ev.get("type"))] += 1
        for (src, typ), n in sorted(idx.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
            con.execute("INSERT INTO events_index VALUES(?,?,?,?)", (rid, src, typ, n))
        report.events_indexed += len(idx)


def ingest(runs_dir: Path, db_path: Path) -> IngestReport:
    """Rebuild ``db_path`` from every ``<runs_dir>/*/manifest.json`` (drop + rebuild, atomic rename)."""
    runs_dir, db_path = Path(runs_dir), Path(db_path)
    report = IngestReport(db_path=db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_name(db_path.name + ".tmp")
    for p in (tmp, tmp.with_name(tmp.name + "-journal")):
        p.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    try:
        with con:
            _build(runs_dir, con, report)
    finally:
        con.close()
    os.replace(tmp, db_path)
    return report
