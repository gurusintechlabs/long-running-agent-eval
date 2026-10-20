"""Behaviour scoring of one checkpoint (plan B5): builds the detector context from the artifact,
runs the agent-suite rerun (D-24) and every detector, and returns metrics and behaviour events.

Called from ``scorer.run_checkpoint`` when ``scoring.behavior.enabled``. Reads only what the scorer
may read (events, snapshots, mirror); agent code runs only inside the agent-suite sandbox.
"""
from __future__ import annotations

import difflib
import hashlib
from pathlib import Path

from scorer import sandbox
from scorer.behavior import agent_suite, modes
from scorer.behavior.core import MODE_DIMENSION, Context
from scorer.metrics import r_regression
from scorer.security.checkpoint import review_points

MAX_DIFF_BYTES = 1_000_000


def _text(p: Path) -> list[str] | None:
    try:
        if p.stat().st_size > MAX_DIFF_BYTES:
            return None
        return p.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return None


def changed_lines(prev: Path, cur: Path) -> dict[str, int]:
    """``{path: lines added + removed}`` between two trees (text files; .git ignored)."""
    def files(root: Path) -> dict[str, Path]:
        return {p.relative_to(root).as_posix(): p for p in sorted(root.rglob("*"))
                if p.is_file() and not p.is_symlink() and ".git" not in p.relative_to(root).parts
                and "__pycache__" not in p.relative_to(root).parts}
    a, b = files(prev), files(cur)
    out = {}
    for rel in sorted(set(a) | set(b)):
        pa, pb = a.get(rel), b.get(rel)
        if pa and pb and hashlib.sha256(pa.read_bytes()).digest() == hashlib.sha256(pb.read_bytes()).digest():
            continue
        old = _text(pa) if pa else []
        new = _text(pb) if pb else []
        if old is None or new is None:
            continue
        n = sum(1 for ln in difflib.unified_diff(old, new, lineterm="", n=0)
                if ln[:1] in "+-" and not ln.startswith(("+++", "---")))
        if n:
            out[rel] = n
    return out


def _stage_starts(orch: list[dict]) -> dict[int, float]:
    out = {0: 0.0}
    for ev in orch:
        p = ev.get("payload") or {}
        if ev.get("type") == "stage.delivered" and "stage" in p:
            out[int(p["stage"])] = float(p.get("t_s") or 0.0)
    return out


def score_behavior(*, spec, art, k: int, ws: Path, prev_ws: Path, t_prev: float, t_k: float, python: Path,
                   forbid: list[Path], p_history: list[dict], stage_k: int | None, stage_prev: int | None,
                   constraints_violated: int | None, read_events) -> tuple[dict[str, dict], list[dict]]:
    """``(metrics, events)``; events carry ``k`` and their mode's hazard flag."""
    s = spec.spec
    cfg, task = s.scoring.behavior, s.task
    ev_dir = art.events_dir
    stream = [e for e in read_events(ev_dir / "agent_stream.jsonl") if not str(e.get("type", "")).startswith("stream.")]

    stages = []
    if task.stages_file:
        from runner.stages import load_stages
        stages = load_stages(task.stages_file).stages
    lo = stage_prev if stage_prev is not None else 0
    hi = stage_k if stage_k is not None else lo
    surfaces = {st.id: list(st.surface) for st in stages if lo <= st.id <= hi and st.surface}

    metrics: dict[str, dict] = {}
    cache = agent_suite.SuiteCache(art.scorer_dir / "agent-suite-cache.json")
    own = None
    if cfg.agent_suite:
        own = cache.get_or_run(ws, python, forbid=forbid)
        metrics["agent_suite"] = {"value": float(own["failed"] + own["errors"]), "detail": own}

    starts = _stage_starts(art.orch)
    ends = []
    for pt in review_points(art.orch, t_prev, t_k):
        end = {**pt, "t_start": starts.get(pt["stage"], 0.0)}
        if cfg.agent_suite and pt.get("head_sha"):
            with sandbox.scratch_dir(forbid) as scratch:
                tree = scratch / "commit"
                r_regression.materialize_commit(art.mirror, pt["head_sha"], tree)
                end["own_suite"] = cache.get_or_run(tree, python, forbid=forbid)
        ends.append(end)

    ctx = Context(
        k=k, t_prev=t_prev, t_k=t_k, start_epoch=art.start_epoch,
        workspace_abs=str((art.manifest.get("paths") or {}).get("workspace") or ""),
        stream=stream, orch=art.orch, guard=read_events(ev_dir / "guardrail.jsonl"),
        counterpart=read_events(ev_dir / "counterpart.jsonl"), env=read_events(ev_dir / "env.jsonl"),
        ws=ws, prev_ws=prev_ws, protected=list(task.protected_paths), cfg=cfg,
        stage_surfaces=surfaces, changed_lines=changed_lines(prev_ws, ws), p_history=p_history,
        stage_ends=ends, constraints_violated=constraints_violated,
        status_required={st.id: st.status_block for st in stages}, own_suite=own,
        memory_file="CLAUDE.md" if task.workspace_memory else None, stage_k=stage_k)
    res = modes.run_all(ctx)
    metrics.update(res.metrics)
    events = [{"k": k, **e, "dimension": MODE_DIMENSION[e["mode"]]} for e in res.events]
    return metrics, events

