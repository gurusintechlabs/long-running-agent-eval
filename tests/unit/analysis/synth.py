"""Synthetic ``runs/`` directories written per docs/interfaces.md, for ingest/dashboard tests."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

START = 1_800_000_000.0
CORE = ("P", "R", "D", "C", "W", "X", "S")


def iso(t_s: float) -> str:
    """Envelope timestamp for run time ``t_s`` (run.clock start_epoch is START)."""
    return datetime.fromtimestamp(START + t_s, UTC).isoformat().replace("+00:00", "Z")


def _write(path: Path, events: list[dict], run_id: str, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"ts": e.get("ts", "x"), "mono_ns": i * 10, "run_id": run_id, "source": source,
                         "type": e["type"], "seq": i, "payload": e["payload"]})
             for i, e in enumerate(events)]
    path.write_text("\n".join(lines) + "\n")


def score_pass(k: int, pass_id: str, *, ok: bool = True, value: float = 0.5, hazards=(),
               details: dict | None = None, commits=(), behavior=(), metrics: dict | None = None) -> list[dict]:
    """``details``: ``{metric name: detail dict}`` (e.g. P -> outcomes/tiers); ``commits``: payloads of
    ``scorer.commit`` events (``k`` and ``pass_id`` are filled in)."""
    ev = [{"type": "scorer.start", "payload": {"k": k, "pass_id": pass_id}}]
    for n in CORE:
        ev.append({"type": "scorer.metric", "payload": {"k": k, "pass_id": pass_id, "name": n,
                                                        "value": value + (0.01 * k if n == "P" else 0),
                                                        "detail": (details or {}).get(n, {})}})
    for name, (v, det) in (metrics or {}).items():
        ev.append({"type": "scorer.metric", "payload": {"k": k, "pass_id": pass_id, "name": name, "value": v,
                                                        "detail": det}})
    for c in commits:
        ev.append({"type": "scorer.commit", "payload": {"k": k, "pass_id": pass_id, **c}})
    for b in behavior:
        ev.append({"type": "scorer.behavior", "payload": {"k": k, "pass_id": pass_id, **b}})
    for h in hazards:
        ev.append({"type": "scorer.hazard", "payload": {"k": k, "pass_id": pass_id, **h}})
    ev.append({"type": "scorer.done", "payload": {"k": k, "pass_id": pass_id, "duration_s": 1.0, "ok": ok}})
    return ev


def beh_event(mode="AF", t=100.0, detector="loop", hazard=False, dimension="cost", evidence="12 cycles"):
    return {"mode": mode, "t_s": t, "detector": detector, "evidence": evidence, "hazard": hazard,
            "deterministic": True, "dimension": dimension}


def hazard(dim="quality", t=1200.0, rule="R>0", evidence="regressed"):
    return {"dimension": dim, "rule": rule, "t_detected_s": t, "t_attributed_s": t, "evidence": evidence}


def make_run(runs_dir: Path, *, config="A", repeat=1, state="COMPLETED", hazards=(), n_cp=3,
             dt=600.0, censored_reason=None, experiment="exp-one", extra_passes=(), cls="L1",
             isolation="local", with_end=True, duration=None, details_by_k=None, commits_by_k=None,
             stages=(), agent_runs=(), behavior_by_k=None, metrics_by_k=None) -> str:
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
    for st, t, interrupted in stages:
        orch.append({"type": "stage.delivered", "ts": iso(t),
                     "payload": {"stage": st, "t_s": t, "prompt_sha256": "0" * 64, "interrupted": interrupted}})
    for k in range(1, n_cp + 1):
        orch.append({"type": "checkpoint", "payload": {"k": k, "t_s": k * dt, "head_sha": f"sha{k}",
                                                       "dirty": False, "pause_ms": 12.0}})
    orch.append({"type": "state", "payload": {"from": "FINALIZING", "to": state}})
    _write(d / "events" / "orchestrator.jsonl", orch, rid, "orchestrator")
    sc: list[dict] = []
    for k in range(1, n_cp + 1):
        hz = [h for h in hazards if h["t_attributed_s"] <= k * dt and h["t_attributed_s"] > (k - 1) * dt]
        sc += score_pass(k, f"p{k}", hazards=hz, details=(details_by_k or {}).get(k),
                         commits=(commits_by_k or {}).get(k, ()), behavior=(behavior_by_k or {}).get(k, ()),
                         metrics=(metrics_by_k or {}).get(k))
    for ev in extra_passes:
        sc += ev
    _write(d / "events" / "scorer.jsonl", sc, rid, "scorer")
    if agent_runs:
        ag = [{"type": "agent.test_run", "ts": iso(t),
               "payload": {"session_id": "s", "tool_use_id": f"u{i}", "passed": p, "failed": f, "errors": e,
                           "skipped": sk, "raw_summary": ""}}
              for i, (t, p, f, e, sk) in enumerate(agent_runs)]
        _write(d / "events" / "agent_stream.jsonl", ag, rid, "agent_stream")
    return rid


# ---- a staged, degrading run with known answers (see tests/unit/analysis/test_degradation.py) ----
P_, F_, S_ = "passed", "failed", "skipped"
DEG_TESTS = ["t/test_t1_a.py::a", "t/test_t1_b.py::b", "t/test_t2_c.py::c", "t/test_t2_d.py::d",
             "t/test_t3_e.py::e", "t/test_t1_old.py::old"]
#                      a   b   c   d   e   old
DEG_COMMITS = [(100.0, [P_, P_, F_, F_, S_, P_]),
               (300.0, [P_, F_, P_, F_, S_, P_]),
               (500.0, [P_, P_, P_, P_, S_, P_]),
               (700.0, [F_, F_, P_, P_, F_, S_]),
               (900.0, [P_, P_, F_, P_, F_, S_]),
               (1100.0, [F_, P_, F_, P_, F_, S_])]
DEG_STAGES = [(0, 0.0, False), (1, 650.0, False)]
DEG_AGENT_RUNS = [(750.0, 10, 0, 0, 0), (1000.0, 9, 1, 0, 0), (1500.0, 8, 0, 0, 0)]


def _outs(vals):
    return dict(zip(DEG_TESTS, vals, strict=True))


def make_degrading_run(runs_dir: Path, *, repeat=1, tiers: bool = True, **kw) -> str:
    """3 checkpoints at 600/1200/1800 s; commits at the DEG_COMMITS times; stage 1 delivered at 650 s."""
    commits_by_k: dict[int, list[dict]] = {}
    for i, (t, vals) in enumerate(DEG_COMMITS):
        k = 1 if t <= 600 else 2 if t <= 1200 else 3
        commits_by_k.setdefault(k, []).append({
            "sha": f"c{i + 1}", "tree": f"tree{i + 1}", "t_s": t, "stage": 0 if t < 650 else 1,
            "hidden": _outs(vals), "regression": {}, "P": 0.5, "passed": 1, "total": 2,
            "sampled": False, "cached": False})
    cp_vals = {1: DEG_COMMITS[2][1], 2: DEG_COMMITS[5][1], 3: DEG_COMMITS[5][1]}
    details = {k: {"P": {"outcomes": _outs(v), **({"tiers": {"t/test_t1_old.py::old": 1}} if tiers else {})},
                   "R": {"outcomes": {}}} for k, v in cp_vals.items()}
    return make_run(runs_dir, repeat=repeat, n_cp=3, dt=600.0, details_by_k=details,
                    commits_by_k=commits_by_k, stages=DEG_STAGES, agent_runs=DEG_AGENT_RUNS, **kw)


def fake_counters(events_dir: Path, models_yaml=None) -> list[dict]:
    n = sum(1 for _ in open(events_dir / "orchestrator.jsonl") if '"checkpoint"' in _)
    return [{"k": k, "tokens_in": 100, "tokens_out": 50, "tokens_cache_read": 10,
             "tokens_cache_creation": 5, "cost_usd": 0.25, "cum_cost_usd": 0.25 * k,
             "context_fill_max": 0.1 * k, "compactions": 1 if k == 2 else 0} for k in range(1, n + 1)]
