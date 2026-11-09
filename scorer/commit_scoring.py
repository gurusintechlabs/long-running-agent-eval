"""Per-commit hidden scoring and stage lookup (docs/interfaces.md §8, §9).

For every agent commit in (t_{k-1}, t_k] (sampled evenly above ``MAX_SAMPLED_COMMITS``, and fewer
when the per-pass time budget would be exceeded) the commit's tree is materialised with ``git
archive`` and the hidden suite is run on it with ``LRAE_STAGE`` set to the stage active at the
commit's time. The pristine regression outcomes come from the accepted-commit run when it already
produced them (``AcceptedCache``), so a tree is never regression-tested twice. Results are cached by
(tree hash, stage) in ``runs/<id>/scorer/commit-cache.json``, together with the commit plan of each
interval, so that re-scoring a checkpoint reproduces the same ``scorer.commit`` events.
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from scorer import sandbox
from scorer.metrics import p_hidden, r_regression
from telemetry.runclock import RunClock, run_time

DEFAULT_MAX_COMMIT_SCORING_S = 600.0
WORKERS = 4


# --- stages ---------------------------------------------------------------------------------

def stage_timeline(orch_events: list[dict]) -> list[tuple[float, int]]:
    """``[(t_s, stage), ...]`` from the ``stage.delivered`` orchestrator events, in time order."""
    out = []
    for ev in orch_events:
        if ev.get("type") != "stage.delivered":
            continue
        p = ev.get("payload") or {}
        try:
            out.append((float(p["t_s"]), int(p["stage"])))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(out, key=lambda x: x[0])


def stage_at(timeline: list[tuple[float, int]], t_s: float) -> int:
    """The last stage delivered at or before ``t_s`` (0 before any delivery)."""
    stage = 0
    for t, s in timeline:
        if t <= t_s + 1e-9:
            stage = s
    return stage


def stage_for(orch_events: list[dict], t_s: float, *, staged: bool) -> int | None:
    """Stage to pass as ``LRAE_STAGE`` at ``t_s``; ``None`` for a task without a stages file."""
    return stage_at(stage_timeline(orch_events), t_s) if staged else None


# --- cache ----------------------------------------------------------------------------------

class CommitCache:
    """``{"trees": {"<tree>:<stage>": record}, "plans": {"<prev>..<cur>": [sha, ...]}}``."""

    def __init__(self, path: Path):
        self.path = Path(path)
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = {}
        self.trees: dict[str, dict] = data.get("trees") or {}
        self.plans: dict[str, list[str]] = data.get("plans") or {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"trees": self.trees, "plans": self.plans}, indent=1,
                                  sort_keys=True))
        os.replace(tmp, self.path)


@dataclass
class CommitScores:
    events: list[dict] = field(default_factory=list)   # scorer.commit payloads minus pass_id
    n_commits: int = 0
    n_scored: int = 0
    n_computed: int = 0
    budget_limited: bool = False


def _plan(commits: list[str], limit: int) -> list[str]:
    if limit >= len(commits):
        return list(commits)
    if limit <= 1:
        return commits[-1:]
    return r_regression.sample_evenly(commits, limit)


def score_commits(*, mirror: Path, prev_sha: str, cur_sha: str, t_prev: float, t_k: float,
                  start_epoch: float | RunClock, timeline: list[tuple[float, int]], staged: bool,
                  hidden: Path, seed_ws: Path, python: Path, accepted: r_regression.AcceptedCache,
                  cache: CommitCache, forbid: list[Path], est_commit_s: float,
                  max_scoring_s: float = DEFAULT_MAX_COMMIT_SCORING_S,
                  workers: int = WORKERS, tools_dir: Path | None = None) -> CommitScores:
    """Hidden (stage-aware) and regression outcomes for each sampled commit in (prev, cur]."""
    commits = r_regression.commits_between(mirror, prev_sha, cur_sha)
    out = CommitScores(n_commits=len(commits))
    if not commits:
        return out
    plan_key = f"{prev_sha}..{cur_sha}"
    chosen = cache.plans.get(plan_key)
    if chosen is None:
        limit = r_regression.MAX_SAMPLED_COMMITS
        if est_commit_s > 0 and max_scoring_s > 0:
            affordable = max(1, int(max_scoring_s * max(1, workers) / est_commit_s))
            if affordable < min(limit, len(commits)):
                limit, out.budget_limited = affordable, True
        chosen = _plan(commits, limit)
        cache.plans[plan_key] = chosen
    else:
        out.budget_limited = len(chosen) < min(r_regression.MAX_SAMPLED_COMMITS, len(commits))
    sampled = len(chosen) < len(commits)

    info = {}
    for sha in chosen:
        tree = r_regression._git(mirror, "rev-parse", f"{sha}^{{tree}}")
        epoch = float(r_regression._git(mirror, "log", "-1", "--format=%ct", sha))
        t = min(max(run_time(start_epoch, epoch), t_prev), t_k)
        stage = stage_at(timeline, t) if staged else None
        info[sha] = (tree, t, stage)
    keys = {sha: f"{tree}:{'-' if stage is None else stage}" for sha, (tree, _, stage) in info.items()}
    was_cached = {sha: keys[sha] in cache.trees for sha in chosen}

    todo: dict[str, str] = {}   # key -> sha
    for sha in chosen:
        if keys[sha] not in cache.trees:
            todo.setdefault(keys[sha], sha)

    def work(item: tuple[str, str]) -> tuple[str, dict, dict | None]:
        key, sha = item
        tree, _, stage = info[sha]
        with sandbox.scratch_dir(forbid) as scratch:
            src = scratch / "commit"
            r_regression.materialize_commit(mirror, sha, src)
            p = p_hidden.score_hidden(src, hidden, python, forbid=forbid, stage=stage, timing=False,
                                      tools_dir=tools_dir)
            d = p["detail"]
            reg_out = (accepted.data.get(tree) or {}).get("outcomes")
            new_acc = None
            if reg_out is None:
                res = r_regression.run_regression_on(src, seed_ws, python, forbid=forbid)
                reg_out = res.outcomes
                new_acc = {"green": res.green, "passed": res.passed, "total": res.total,
                           "reason": res.reason, "outcomes": res.outcomes}
        rec = {"hidden": d["outcomes"], "regression": reg_out, "P": p["value"],
               "passed": d["passed"], "total": d["active"], "skipped": d["skipped"]}
        return key, rec, new_acc

    if todo:
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(todo)))) as pool:
            for key, rec, new_acc in pool.map(work, todo.items()):
                cache.trees[key] = rec
                if new_acc is not None:
                    accepted.data[info[todo[key]][0]] = new_acc
        accepted.save()
    cache.save()
    out.n_computed = len(todo)

    for sha in chosen:   # oldest first: rev-list --reverse order is preserved by the plan
        tree, t, stage = info[sha]
        rec = cache.trees[keys[sha]]
        out.events.append({
            "sha": sha, "tree": tree, "t_s": round(t, 3), "stage": stage,
            "hidden": rec["hidden"], "regression": rec["regression"], "P": rec["P"],
            "passed": rec["passed"], "total": rec["total"], "skipped": rec["skipped"],
            "sampled": sampled, "budget_limited": out.budget_limited,
            "cached": was_cached[sha]})
    out.n_scored = len(chosen)
    return out

