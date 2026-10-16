"""Synthetic ``runs/`` directories written per docs/interfaces.md, for ingest/dashboard tests."""
from __future__ import annotations

import json
from pathlib import Path

START = 1_800_000_000.0
CORE = ("P", "R", "D", "C", "W", "X", "S")


def _write(path: Path, events: list[dict], run_id: str, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"ts": "x", "mono_ns": i * 10, "run_id": run_id, "source": source,
                         "type": e["type"], "seq": i, "payload": e["payload"]})
             for i, e in enumerate(events)]
    path.write_text("\n".join(lines) + "\n")


def score_pass(k: int, pass_id: str, *, ok: bool = True, value: float = 0.5, hazards=()) -> list[dict]:
    ev = [{"type": "scorer.start", "payload": {"k": k, "pass_id": pass_id}}]
    for n in CORE:
        ev.append({"type": "scorer.metric", "payload": {"k": k, "pass_id": pass_id, "name": n,
                                                        "value": value + (0.01 * k if n == "P" else 0),
                                                        "detail": {}}})
    for h in hazards:
        ev.append({"type": "scorer.hazard", "payload": {"k": k, "pass_id": pass_id, **h}})
    ev.append({"type": "scorer.done", "payload": {"k": k, "pass_id": pass_id, "duration_s": 1.0, "ok": ok}})
    return ev


def hazard(dim="quality", t=1200.0, rule="R>0", evidence="regressed"):
    return {"dimension": dim, "rule": rule, "t_detected_s": t, "t_attributed_s": t, "evidence": evidence}


def make_run(runs_dir: Path, *, config="A", repeat=1, state="COMPLETED", hazards=(), n_cp=3,
             dt=600.0, censored_reason=None, experiment="exp-one", extra_passes=(), cls="L1",
             isolation="local", with_end=True, duration=None) -> str:
    rid = f"{experiment}-{config}-r{repeat:02d}-abcd1234"
    d = runs_dir / rid
    dur = duration if duration is not None else n_cp * dt
    mf = {"run_id": rid, "experiment_id": experiment, "config": config, "repeat": repeat,
          "spec_hash": "abcd1234" * 8, "isolation_mode": isolation, "start_epoch": START,
          "resumed": False, "spec": {"experiment_id": experiment, "task": {"class": cls, "id": "t"}}}
    if with_end:
        mf["end"] = {"state": state, "end_epoch": START + dur, "error": None, "checkpoints": n_cp}
        if censored_reason:
            mf["end"]["censored_reason"] = censored_reason
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps(mf))
    orch = [{"type": "run.clock", "payload": {"start_epoch": START, "offset_s": 0}}]
    for k in range(1, n_cp + 1):
        orch.append({"type": "checkpoint", "payload": {"k": k, "t_s": k * dt, "head_sha": f"sha{k}",
                                                       "dirty": False, "pause_ms": 12.0}})
    orch.append({"type": "state", "payload": {"from": "FINALIZING", "to": state}})
    _write(d / "events" / "orchestrator.jsonl", orch, rid, "orchestrator")
    sc: list[dict] = []
    for k in range(1, n_cp + 1):
        hz = [h for h in hazards if h["t_attributed_s"] <= k * dt and h["t_attributed_s"] > (k - 1) * dt]
        sc += score_pass(k, f"p{k}", hazards=hz)
    for ev in extra_passes:
        sc += ev
    _write(d / "events" / "scorer.jsonl", sc, rid, "scorer")
    return rid


def fake_counters(events_dir: Path, models_yaml=None) -> list[dict]:
    n = sum(1 for _ in open(events_dir / "orchestrator.jsonl") if '"checkpoint"' in _)
    return [{"k": k, "tokens_in": 100, "tokens_out": 50, "tokens_cache_read": 10,
             "tokens_cache_creation": 5, "cost_usd": 0.25, "cum_cost_usd": 0.25 * k,
             "context_fill_max": 0.1 * k, "compactions": 1 if k == 2 else 0} for k in range(1, n + 1)]
