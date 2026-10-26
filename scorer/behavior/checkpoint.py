"""Behaviour scoring of one checkpoint (plan B5): builds the detector context from the artifact,
runs the agent-suite rerun (D-24) and every detector, and returns metrics and behaviour events.

Called from ``scorer.run_checkpoint`` when ``scoring.behavior.enabled``. Reads only what the scorer
may read (events, snapshots, mirror); agent code runs only inside the agent-suite sandbox.
"""
from __future__ import annotations

import difflib
import hashlib
from pathlib import Path

from scorer import metric_names as mn
from scorer import sandbox
from scorer.behavior import agent_suite, benchmark, modes
from scorer.behavior.core import MODE_DIMENSION, Context, epoch
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


MAX_DIFF_CHARS = 200_000


def changed_lines(prev: Path, cur: Path) -> dict[str, int]:
    return tree_diff(prev, cur)[0]


def harness_paths(ctx: Context) -> set[str]:
    """Workspace files the harness wrote, not the agent: decoys (``honey.provisioned``) and env-action
    commits (``env.mutated`` commit_file). They are left out of drift and of every judge diff."""
    out = {(e.get("payload") or {}).get("path") for e in ctx.env
           if e.get("type") == "env.mutated" and (e.get("payload") or {}).get("action") == "commit_file"}
    for e in ctx.orch:
        if e.get("type") == "honey.provisioned":
            out |= {ctx.rel(it.get("path")) for it in (e.get("payload") or {}).get("items") or []
                    if it.get("where") == "workspace"}
    return {p for p in out if p}


def tree_diff(prev: Path, cur: Path, exclude: set[str] = frozenset()) -> tuple[dict[str, int], str]:
    """``({path: lines added + removed}, unified diff text)`` between two trees (text files; .git
    ignored). Unlike the mirror diff, it includes uncommitted work."""
    def files(root: Path) -> dict[str, Path]:
        return {p.relative_to(root).as_posix(): p for p in sorted(root.rglob("*"))
                if p.is_file() and not p.is_symlink() and ".git" not in p.relative_to(root).parts
                and "__pycache__" not in p.relative_to(root).parts}
    a, b = files(prev), files(cur)
    out, text, size = {}, [], 0
    for rel in sorted((set(a) | set(b)) - set(exclude)):
        pa, pb = a.get(rel), b.get(rel)
        if pa and pb and hashlib.sha256(pa.read_bytes()).digest() == hashlib.sha256(pb.read_bytes()).digest():
            continue
        old = _text(pa) if pa else []
        new = _text(pb) if pb else []
        if old is None or new is None:
            continue
        lines = list(difflib.unified_diff(old, new, f"a/{rel}", f"b/{rel}", lineterm="", n=1))
        n = sum(1 for ln in lines if ln[:1] in "+-" and not ln.startswith(("+++", "---")))
        if n:
            out[rel] = n
            if size < MAX_DIFF_CHARS:
                chunk = "\n".join(lines)
                text.append(chunk)
                size += len(chunk)
    return out, "\n".join(text)[:MAX_DIFF_CHARS]


def _stage_starts(orch: list[dict]) -> dict[int, float]:
    out = {0: 0.0}
    for ev in orch:
        p = ev.get("payload") or {}
        if ev.get("type") == "stage.delivered" and "stage" in p:
            out[int(p["stage"])] = float(p.get("t_s") or 0.0)
    return out


def _authorized(stages, orch: list[dict], stage_k: int | None, start_epoch: float) -> dict[str, float | None]:
    """Globs authorised by the stages delivered up to ``stage_k`` -> the delivery time, on the clock of
    ``Context.t`` (event ``ts`` minus the run's start epoch, as for the guardrail findings it is compared
    with; the payload's ``t_s`` counts from a later origin). None when the log has no delivery of that
    stage (standalone scoring)."""
    if stage_k is None:
        return {}
    starts = {}
    for ev in orch:
        p, e = ev.get("payload") or {}, epoch(ev.get("ts"))
        if ev.get("type") == "stage.delivered" and "stage" in p and e is not None:
            starts[int(p["stage"])] = e - start_epoch
    out: dict[str, float | None] = {}
    for st in stages:
        if st.id <= stage_k:
            for g in st.authorizes:
                out.setdefault(g, starts.get(st.id))
    return out


def _benchmark_config(hidden: Path | None) -> dict | None:
    """The task's ``benchmark`` section of the hidden suite's scorer.yaml (None: the task has none)."""
    if hidden is None:
        return None
    from scorer.metrics import p_hidden
    try:
        cfg = p_hidden.load_config(hidden).get("benchmark")
    except (OSError, ValueError):
        return None
    return cfg if isinstance(cfg, dict) and cfg.get("visible") and cfg.get("hidden") else None


def score_behavior(*, spec, art, k: int, ws: Path, prev_ws: Path, t_prev: float, t_k: float, python: Path,
                   forbid: list[Path], p_history: list[dict], stage_k: int | None, stage_prev: int | None,
                   constraints_violated: int | None, read_events, judge_runner=None, seed_ws: Path | None = None,
                   hidden: Path | None = None) -> tuple[dict[str, dict], list[dict]]:
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
        own = cache.get_or_run(ws, python, forbid=forbid, timeout_s=cfg.agent_suite_timeout_s)
        metrics[mn.AGENT_SUITE] = {"value": float(own["failed"] + own["errors"]) if agent_suite.finished(own) else None,
                                   "detail": own}

    bench = None
    bench_cfg = _benchmark_config(hidden) if cfg.benchmark and seed_ws is not None else None
    if bench_cfg:
        bench = benchmark.BenchmarkCache(art.scorer_dir / "benchmark-cache.json").get_or_run(
            ws, seed_ws, hidden, bench_cfg, python=python, forbid=forbid)

    starts = _stage_starts(art.orch)
    ends = []
    for pt in review_points(art.orch, t_prev, t_k):
        end = {**pt, "t_start": starts.get(pt["stage"], 0.0)}
        if cfg.agent_suite and pt.get("head_sha"):
            with sandbox.scratch_dir(forbid) as scratch:
                tree = scratch / "commit"
                r_regression.materialize_commit(art.mirror, pt["head_sha"], tree)
                end["own_suite"] = cache.get_or_run(tree, python, forbid=forbid, timeout_s=cfg.agent_suite_timeout_s)
        ends.append(end)

    ctx = Context(
        k=k, t_prev=t_prev, t_k=t_k, start_epoch=art.start_epoch,
        workspace_abs=str((art.manifest.get("paths") or {}).get("workspace") or ""),
        stream=stream, orch=art.orch, guard=read_events(ev_dir / "guardrail.jsonl"),
        counterpart=read_events(ev_dir / "counterpart.jsonl"), env=read_events(ev_dir / "env.jsonl"),
        ws=ws, prev_ws=prev_ws, protected=list(task.protected_paths), cfg=cfg,
        stage_surfaces=surfaces, p_history=p_history,
        stage_ends=ends, constraints_violated=constraints_violated,
        status_required={st.id: st.status_block for st in stages}, own_suite=own, benchmark=bench,
        authorized=_authorized(stages, art.orch, stage_k, art.start_epoch),
        memory_file="CLAUDE.md" if task.workspace_memory else None, stage_k=stage_k,
        opening_brief=Path(task.prompt_file).read_text())
    changed, diff = tree_diff(prev_ws, ws, exclude=harness_paths(ctx))
    ctx.changed_lines = changed
    res = modes.run_all(ctx)
    metrics.update(res.metrics)
    events = list(res.events)
    if cfg.judges:
        from scorer.judges.behavior import run_judges
        rules = Path(task.workspace_memory).read_text() if task.workspace_memory else ""
        jm, je = run_judges(ctx, stages=stages, rules=rules, diff=diff, det_events=res.events, names=cfg.judges,
                            model=s.scoring.judge_model, runner=behavior_judge_runner(s, judge_runner),
                            cache_dir=art.scorer_dir / "judge-cache")
        metrics.update(jm)
        events = sorted(events + je, key=lambda e: (e["t_s"], e["mode"], e["detector"]))
    events = [{"k": k, **e, "dimension": MODE_DIMENSION[e["mode"]]} for e in events]
    return metrics, events


def behavior_judge_runner(s, judge_runner=None):
    """scripted: the recorded answers (``judge_fixtures``) or the clean fake; otherwise the X judge's
    runner (the installed CLI, behind the spend gate). A test runner may carry its own ``behavior``."""
    if judge_runner is not None and getattr(judge_runner, "behavior", None) is not None:
        return judge_runner.behavior
    if s.scoring.judge_runtime == "scripted":
        from scorer.judges.base import FakeBehaviorJudge, RecordedJudge
        fx = s.scoring.behavior.judge_fixtures
        return RecordedJudge(Path(fx)) if fx else FakeBehaviorJudge()
    if judge_runner is not None:
        return judge_runner
    from scorer.metrics.x_judge import ClaudeJudgeRunner
    return ClaudeJudgeRunner()

