"""One payload for the run-detail timeline (U3): checkpoints, stages, markers, hazards, behaviour,
guardrail incidents, compactions and per-checkpoint cost/context series.

Built from the run's log files (current even for a run in progress), with the store used for the
counters of ingested runs. Reuses the ``analysis.ingest`` helpers so the numbers equal the store's.
Cached in memory by file signatures."""
from __future__ import annotations

import json
from pathlib import Path

from analysis import ingest as ing
from ui_server import eventlog as el
from ui_server import safefs, sigcache
from ui_server import transcript as tr

MAX_INCIDENTS = 500
MAX_BEHAVIOR = 1000
EVIDENCE_CHARS = 600


def _events(rl: el.RunLog, source: str, types: set[str] | None = None, cap: int = 200_000) -> list[tuple[int, dict]]:
    out = []
    for start, _n, raw in el.iter_lines(rl.path(source)):
        if raw is None:
            continue
        if types is not None:
            h = el.header(raw)
            if h is None or h[2] not in types:
                continue
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append((start, e))
            if len(out) >= cap:
                break
    return out


def _r(v):
    return None if v is None else round(v, 3)


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _trim(s, n=EVIDENCE_CHARS):
    s = s if isinstance(s, str) else json.dumps(s, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + f"…[truncated {len(s) - n} more chars]"


def _guardrail(rl: el.RunLog) -> dict:
    evs = _events(rl, "guardrail")
    clocks = rl.clocks()
    viol, kill, budget, gaps = [], None, None, []
    stalled_n = 0
    stalled_at: list[float] = []
    by_rule: dict[str, dict] = {}
    total_viol = 0
    for off, e in evs:
        p = e.get("payload") if isinstance(e.get("payload"), dict) else {}
        typ = e.get("type")
        t = _r(el.run_time(e.get("ts"), clocks))
        cur = el.make_cursor("guardrail", off)
        if typ in ("guardrail.violation", "procmon.connection", "procmon.fixture_died", "platform.interruption"):
            total_viol += 1
            g = by_rule.setdefault(p.get("rule_id") or typ, {"rule_id": p.get("rule_id") or typ, "count": 0,
                                                              "severity": p.get("severity"), "action": p.get("action"),
                                                              "kills": 0})
            g["count"] += 1
            if len(viol) < MAX_INCIDENTS:
                viol.append({"cursor": cur, "type": typ, "t_s": t, "ts": e.get("ts"), "rule_id": p.get("rule_id"),
                             "severity": p.get("severity"), "action": p.get("action"), "channel": p.get("channel"),
                             "evidence": _trim(p.get("evidence") if "evidence" in p else
                                               {k: v for k, v in p.items() if k != "rule_id"}),
                             "stream_seq": p.get("stream_seq")})
        elif typ == "guardrail.kill":
            kill = {"cursor": cur, "t_s": t, "ts": e.get("ts"), "rule_id": p.get("rule_id"), "reason": p.get("reason"),
                    "freeze_latency_ms": p.get("freeze_latency_ms"),
                    "detect_to_freeze_ms": (round((p["frozen_mono_ns"] - p["detect_mono_ns"]) / 1e6, 3)
                                            if isinstance(p.get("frozen_mono_ns"), int)
                                            and isinstance(p.get("detect_mono_ns"), int) else None)}
            by_rule.setdefault(p.get("rule_id") or "kill", {"rule_id": p.get("rule_id") or "kill", "count": 0,
                                                            "severity": "kill", "action": "kill", "kills": 0})["kills"] += 1
        elif typ == "guardrail.budget":
            budget = {"cursor": cur, "t_s": t, **{k: v for k, v in p.items() if _num(v) is not None}}
        elif typ == "guardrail.telemetry_stalled":
            stalled_n += 1
            stalled_at.append(t if t is not None else -1.0)
        elif typ == "guardrail.telemetry_resumed" and len(gaps) < MAX_INCIDENTS:
            gaps.append({"t_s": t, "paused_s": p.get("paused_s")})
    status = ("killed" if kill else "violations" if any(
        v["severity"] == "violation" for v in viol) else "warnings" if viol else "clear")
    return {"status": status, "violations": viol, "violations_total": total_viol, "kill": kill, "budget": budget,
            "by_rule": sorted(by_rule.values(), key=lambda g: -g["count"]),
            "telemetry_stalls": {"count": stalled_n, "resumed": len(gaps), "first_t_s": stalled_at[0] if stalled_at
                                 else None, "gaps": gaps[:MAX_INCIDENTS]}}


def _link_transcript(rl: el.RunLog, items: list[dict]) -> None:
    """Add ``transcript_cursor`` to guardrail incidents that carry a stream_seq."""
    for it in items[:MAX_INCIDENTS]:
        seq = it.get("stream_seq")
        if isinstance(seq, int):
            r = el.locate(rl, "agent_stream", seq=seq)
            if r.get("found"):
                it["stream_cursor"] = r["cursor"]


def build(rl: el.RunLog, rid: str, con, mf: dict) -> dict:
    clocks_pairs = rl.clocks()
    orch = _events(rl, "orchestrator")
    orch_e = [e for _o, e in orch]
    scorer = [e for _o, e in _events(rl, "scorer", {"scorer.metric", "scorer.hazard", "scorer.behavior",
                                                    "scorer.done"})]
    env = [e for _o, e in _events(rl, "env")]
    clocks = [(float(a), float(b)) for a, b in clocks_pairs]

    cps: dict[int, dict] = {}
    cp_cursor: dict[int, str] = {}
    states, stages = [], {}
    for off, e in orch:
        p = e.get("payload") if isinstance(e.get("payload"), dict) else {}
        typ = e.get("type")
        if typ == "checkpoint" and isinstance(p.get("k"), int):
            cps[p["k"]] = p
            cp_cursor[p["k"]] = el.make_cursor("orchestrator", off)
        elif typ == "state":
            states.append({"cursor": el.make_cursor("orchestrator", off), "t_s": _r(el.run_time(e.get("ts"), clocks)),
                           "from": p.get("from"), "to": p.get("to")})
        elif typ == "stage.delivered" and "stage" in p:
            stages[p["stage"]] = {"cursor": el.make_cursor("orchestrator", off), "stage": p["stage"],
                                  "t_s": _r(_num(p.get("t_s"))), "kind": p.get("kind"),
                                  "interrupted": bool(p.get("interrupted"))}
    metric_rows, hazards = ing.scored_view(scorer)
    beh = ing.behavior_rows(scorer)

    ctr: dict[int, dict] = {}
    source = "none"
    if con is not None and con.execute("SELECT 1 FROM runs WHERE run_id=?", (rid,)).fetchone():
        for r in con.execute("SELECT k, name, value FROM counters WHERE run_id=?", (rid,)):
            ctr.setdefault(r["k"], {})[r["name"]] = r["value"]
        source = "store"
    else:
        try:
            from telemetry.counters import interval_counters
            if not safefs.plain_dir(rl.events_dir):    # the library opens files by name: no symlinks allowed
                raise OSError("events dir is not plain")
            for row in interval_counters(rl.events_dir):
                ctr[int(row["k"])] = {k: v for k, v in row.items() if k != "k" and _num(v) is not None}
            source = "logs" if ctr else "none"
        except Exception:  # noqa: BLE001 - counters are optional
            source = "none"
    cum = 0.0
    series = []
    for k in sorted(cps):
        c = ctr.get(k, {})
        cum += c.get("cost_usd") or 0.0
        p = cps[k]
        series.append({"k": k, "t_s": _r(_num(p.get("t_s"))), "cost_usd": c.get("cost_usd"),
                       "cum_cost_usd": _r(_num(p.get("cumulative_cost_usd")) if _num(p.get("cumulative_cost_usd"))
                                          is not None else (cum if c else None)),
                       "context_fill_max": c.get("context_fill_max"), "context_fill_last": c.get("context_fill_last"),
                       "compactions": c.get("compactions"), "tool_calls": c.get("tool_calls"),
                       "tokens_in": c.get("tokens_in"), "tokens_out": c.get("tokens_out")})

    gr = _guardrail(rl)
    _link_transcript(rl, gr["violations"])
    ix = tr.get_tindex(rl)
    compactions = [{"cursor": el.make_cursor("agent_stream", it["off"]), "t_s": it["t_s"], "trigger": it.get("trigger"),
                    "pre_tokens": it.get("pre_tokens")} for it in ix.items if it["kind"] == "compaction"]
    end = mf.get("end") if isinstance(mf.get("end"), dict) else None
    return {
        "run_id": rid, "source_of_counters": source,
        "end": end,
        "last_checkpoint_t_s": _r(max([_num(p.get("t_s")) or 0.0 for p in cps.values()], default=None)),
        "checkpoints": [{"cursor": cp_cursor[k], "k": k, "t_s": _r(_num(cps[k].get("t_s"))),
                         "head_sha": cps[k].get("head_sha"), "dirty": cps[k].get("dirty"),
                         "pause_ms": cps[k].get("pause_ms"), "final": cps[k].get("final"),
                         "cumulative_cost_usd": cps[k].get("cumulative_cost_usd")} for k in sorted(cps)],
        "stages": [stages[s] for s in sorted(stages)],
        "markers": [{"t_s": _r(t), "kind": kd, "label": lb}
                    for t, kd, lb in ing.markers(orch_e, env, clocks)],
        "states": states, "turns": [{k: (_r(v) if isinstance(v, float) else v) for k, v in t.items()
                                     if not k.endswith("_epoch")} for t in tr.turns(rl)],
        "hazards": [{"dimension": h.get("dimension"), "rule": h.get("rule"), "k": h.get("k"),
                     "t_attributed_s": _r(_num(h.get("t_attributed_s"))), "t_detected_s": _r(_num(h.get("t_detected_s"))),
                     "evidence": _trim(h.get("evidence"))} for h in hazards],
        "behavior": [{"k": k, "mode": mode, "dimension": dim, "t_s": _r(t), "detector": det, "severity": sev,
                      "hazard": bool(hz), "deterministic": bool(de), "evidence": _trim(evid)}
                     for k, mode, dim, t, det, sev, hz, de, evid in beh[:MAX_BEHAVIOR]],
        "behavior_total": len(beh),
        "guardrail": gr, "compactions": compactions, "series": series,
        "metrics_rows": len(metric_rows),
    }


def get(rl: el.RunLog, rid: str, con, mf: dict, db_path: Path) -> dict:
    files = [rl.path(s) for s in ("orchestrator", "scorer", "guardrail", "env", "agent_stream")]
    files += [db_path, rl.run_dir / "manifest.json"]
    return sigcache.cached("timeline", files, lambda: build(rl, rid, con, mf), extra=(rid, mf.get("end") is None))

