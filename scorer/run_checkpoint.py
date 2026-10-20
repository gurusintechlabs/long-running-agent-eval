"""Score one checkpoint (docs/spec.md §8, docs/interfaces.md §4, §5).

``score_checkpoint(art, k, spec=...)`` reads only the artifact dir (snapshots, mirror, events,
manifest) and the spec's referenced files, and appends ``scorer.start``, the metric events, the
hazard events and ``scorer.done`` to ``events/scorer.jsonl``. Agent code runs only in subprocesses
on temp copies (scorer.sandbox).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from scorer import commit_scoring, sandbox
from scorer.metrics import d_defects, p_hidden, r_regression
from spec.loader import REPO_ROOT, LoadedSpec, hash_path, load_spec
from telemetry import counters
from telemetry.events import EventWriter

CORE = ("P", "R", "D", "C", "W", "X", "S")
MAX_DIFF_CHARS = 200_000


@dataclass
class CheckpointScore:
    k: int
    pass_id: str
    ok: bool
    metrics: dict[str, dict] = field(default_factory=dict)  # name -> {"value", "detail"}
    hazards: list[dict] = field(default_factory=list)
    duration_s: float = 0.0
    error: str | None = None
    phases: dict[str, float] = field(default_factory=dict)
    commits: list[dict] = field(default_factory=list)  # scorer.commit payloads

    def value(self, name: str):
        return self.metrics.get(name, {}).get("value")


# --- small readers --------------------------------------------------------------------------

def read_events(path: Path) -> list[dict]:
    out = []
    try:
        with open(path) as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def last_ok_pass(events: list[dict], k: int) -> dict[str, dict] | None:
    """Metric payloads ``{name: payload}`` of the last pass of checkpoint k that finished ok."""
    passes: dict[str, dict[str, dict]] = {}
    good: str | None = None
    for ev in events:
        p, t = ev.get("payload") or {}, ev.get("type")
        if p.get("k") != k:
            continue
        if t == "scorer.start":
            passes[p["pass_id"]] = {}
        elif t == "scorer.metric" and p.get("pass_id") in passes:
            passes[p["pass_id"]][p["name"]] = p
        elif t == "scorer.done" and p.get("ok") and p.get("pass_id") in passes:
            good = p["pass_id"]
    return passes[good] if good else None


def _git(*args: str, git_dir: Path | None = None, cwd: Path | None = None, check=True) -> str:
    cmd = ["git"] + (["--git-dir", str(git_dir)] if git_dir else []) + list(args)
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    if check and out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout.strip()


def _iso_to_epoch(ts: str) -> float:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


class Artifact:
    """Read access to the pieces of a run artifact dir the scorer is allowed to use."""

    def __init__(self, art: Path):
        self.art = Path(art)
        self.events_dir = self.art / "events"
        self.mirror = self.art / "mirror.git"
        self.scorer_dir = self.art / "scorer"
        self.manifest = self._load(self.art / "manifest.json")
        self.orch = read_events(self.events_dir / "orchestrator.jsonl")

    @staticmethod
    def _load(p: Path) -> dict:
        try:
            return json.loads(p.read_text())
        except (OSError, ValueError):
            return {}

    @property
    def run_id(self) -> str:
        return self.manifest.get("run_id") or self.art.name

    @property
    def start_epoch(self) -> float:
        """Run-time origin: the last ``run.clock`` start (checkpoint ``t_s`` is measured from it,
        and on resume it already accounts for the offset). The manifest's ``start_epoch`` is taken
        earlier, at PREPARING, so using it would shift every event later than its checkpoint."""
        for ev in reversed(read_events(self.events_dir / "orchestrator.jsonl")):
            if ev.get("type") == "run.clock":
                try:
                    return float(ev["payload"]["start_epoch"])
                except (KeyError, TypeError, ValueError):
                    break
        return float(self.manifest.get("start_epoch") or 0.0)

    def snap(self, k: int) -> Path:
        return self.art / "snapshots" / f"t{k}"

    def meta(self, k: int) -> dict:
        return self._load(self.snap(k) / "meta.json")

    def checkpoint_event(self, k: int) -> dict | None:
        found = None
        for ev in self.orch:
            if ev.get("type") == "checkpoint" and (ev.get("payload") or {}).get("k") == k:
                found = ev
        return found

    def t_s(self, k: int, dt_s: float) -> float:
        if k <= 0:
            return 0.0
        ev = self.checkpoint_event(k)
        return float(ev["payload"]["t_s"]) if ev and "t_s" in ev["payload"] else k * dt_s

    def head_sha(self, k: int, seed_sha: str) -> str:
        if k <= 0:
            return seed_sha
        return self.meta(k).get("head_sha") or _git("rev-parse", f"ckpt/t{k}^{{commit}}",
                                                     git_dir=self.mirror)


def seed_checkout(spec: LoadedSpec, art: Artifact, dest: Path) -> Path:
    """A pristine checkout of the seed commit at ``dest``."""
    from runner.seed import ensure_seed_repo
    task = spec.spec.task
    repo = ensure_seed_repo(Path(task.seed_repo), task.seed_commit, art.scorer_dir / "seed-cache")
    _git("clone", "-q", "--no-hardlinks", str(repo), str(dest))
    _git("checkout", "-q", "--detach", task.seed_commit, cwd=dest)
    return dest


# --- suites ---------------------------------------------------------------------------------

def run_suites(ws: Path, seed_ws: Path, hidden: Path, python: Path, forbid: list[Path],
               stage: int | None = None) -> dict:
    p = p_hidden.score_hidden(ws, hidden, python, forbid=forbid, stage=stage)
    reg = r_regression.run_regression_on(ws, seed_ws, python, forbid=forbid)
    return {"hidden": p["detail"]["outcomes"], "regression": reg.outcomes, "P": p, "reg": reg}


def seed_baseline(spec: LoadedSpec, art: Artifact, seed_ws: Path, python: Path,
                  forbid: list[Path]) -> dict:
    """Hidden/regression outcomes and D of the seed itself, cached under runs/<id>/scorer/."""
    hidden = Path(spec.spec.task.hidden_tests)
    key = r_regression.digest([spec.spec.task.seed_commit, hash_path(hidden), "v1"])
    cache = art.scorer_dir / "seed-baseline.json"
    try:
        data = json.loads(cache.read_text())
        if data.get("key") == key:
            return data
    except (OSError, ValueError):
        pass
    s = run_suites(seed_ws, seed_ws, hidden, python, forbid)
    with sandbox.temp_copy(seed_ws, exclude_git=True) as tree:
        defects = d_defects.measure(tree, python)
    data = {"key": key, "hidden": s["hidden"], "regression": s["regression"], "defects": defects}
    art.scorer_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, indent=1, sort_keys=True))
    return data


# --- cost -----------------------------------------------------------------------------------

def cumulative_at(art: Artifact, meta: dict, cut_mono_ns: int | None, tmp: Path) -> tuple[float, int]:
    """(cost_usd, tokens) accumulated up to a checkpoint, from ``otel.jsonl``."""
    otel = art.events_dir / "otel.jsonl"
    cost, tokens = 0.0, 0
    if otel.exists():
        src = otel
        if cut_mono_ns is not None:
            src = tmp / "otel_cut.jsonl"
            with open(otel) as fin, open(src, "w") as fout:
                for line in fin:
                    try:
                        mono = json.loads(line).get("mono_ns")
                    except ValueError:
                        continue
                    if not isinstance(mono, int) or mono <= cut_mono_ns:
                        fout.write(line)
        cost, tokens = counters.cumulative_cost(src), counters.cumulative_tokens(src)
    if meta.get("cumulative_cost_usd") is not None:
        cost = float(meta["cumulative_cost_usd"])
    return cost, int(tokens)


# --- judge inputs ---------------------------------------------------------------------------

def assistant_texts(stream: Path, end_mono_ns: int | None) -> list[str]:
    parsed, raw = [], []
    for ev in read_events(stream):
        mono = ev.get("mono_ns")
        if end_mono_ns is not None and isinstance(mono, int) and mono > end_mono_ns:
            continue
        p = ev.get("payload") or {}
        if ev.get("type") == "assistant.text":
            parsed.append(p.get("text", ""))
        elif ev.get("type") == "stream.assistant":
            for block in (p.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text":
                    raw.append(block.get("text", ""))
    return parsed or raw


# --- hazards --------------------------------------------------------------------------------

def _ensure_git(path: Path) -> None:
    if not (path / ".git").exists():
        ident = ["-c", "user.name=s", "-c", "user.email=s@s"]
        _git("init", "-q", cwd=path)
        _git("add", "-A", cwd=path)
        _git(*ident, "commit", "-q", "--no-gpg-sign", "--allow-empty", "-m", "x", cwd=path)


def _attribute(commits: list[str], mirror: Path, is_bad, t_prev: float, t_k: float,
               start_epoch: float) -> float | None:
    from scorer import hazards
    if not commits:
        return None
    sha = hazards.attribute_commit(mirror, commits, is_bad)
    if not sha:
        return None
    t = float(_git("log", "-1", "--format=%ct", sha, git_dir=mirror)) - start_epoch
    return min(max(t, t_prev), t_k)


# --- the pass -------------------------------------------------------------------------------

def score_checkpoint(art: Path, k: int, *, spec: LoadedSpec, scorer_python: Path,
                     judge_runner=None, final: str | None = None) -> CheckpointScore:
    art_dir = Path(art)
    a = Artifact(art_dir)
    pass_id = uuid.uuid4().hex
    writer = EventWriter(a.events_dir / "scorer.jsonl", a.run_id, "scorer")
    t0 = time.monotonic()
    score = CheckpointScore(k=k, pass_id=pass_id, ok=False)
    try:
        writer.emit("scorer.start", {"k": k, "pass_id": pass_id})
        try:
            _score(a, k, spec, Path(scorer_python), judge_runner, pass_id, writer, score)
            score.ok = True
        except Exception as exc:  # recorded; the caller decides what to do
            import traceback
            score.error = f"{type(exc).__name__}: {exc}"
            score.metrics.clear()
            score.hazards.clear()
            score.commits.clear()
            traceback.print_exc(file=sys.stderr)
        leaked = sandbox.reap_leftovers()
        dirs = sandbox.leftover_temp_dirs()
        score.duration_s = round(time.monotonic() - t0, 3)
        done = {"k": k, "pass_id": pass_id, "duration_s": score.duration_s, "ok": score.ok,
                "phases": score.phases}
        if score.error:
            done["error"] = score.error[:2000]
        if leaked:
            done["leaked_processes"] = leaked
        if dirs:
            done["leaked_dirs"] = [str(d) for d in dirs]
        writer.emit("scorer.done", done)
    finally:
        writer.close()
    return score


def _score(a: Artifact, k: int, spec: LoadedSpec, python: Path, judge_runner, pass_id: str,
           writer: EventWriter, out: CheckpointScore) -> None:
    s = spec.spec
    task = s.task
    seed_sha = task.seed_commit
    dt_s = s.run.checkpoint_interval_min * 60
    snap = a.snap(k)
    ws = snap / "workspace"
    if not ws.is_dir():
        raise FileNotFoundError(f"no snapshot workspace at {ws}")
    meta = a.meta(k)
    forbid = [Path(s.isolation.work_dir), a.art]
    hidden = Path(task.hidden_tests)
    t_k, t_prev = a.t_s(k, dt_s), a.t_s(k - 1, dt_s)
    cur_sha, prev_sha = a.head_sha(k, seed_sha), a.head_sha(k - 1, seed_sha)
    scorer_events = read_events(a.events_dir / "scorer.jsonl")
    a.scorer_dir.mkdir(parents=True, exist_ok=True)
    cache = r_regression.AcceptedCache(a.scorer_dir / "accepted-cache.json")
    commit_cache = commit_scoring.CommitCache(a.scorer_dir / "commit-cache.json")
    staged = bool(getattr(task, "stages_file", None))
    timeline = commit_scoring.stage_timeline(a.orch) if staged else []
    stage_k = commit_scoring.stage_at(timeline, t_k) if staged else None
    stage_prev = commit_scoring.stage_at(timeline, t_prev) if staged else None
    tm = out.phases
    mark = time.monotonic()

    def lap(name: str) -> None:
        nonlocal mark
        now = time.monotonic()
        tm[name] = round(now - mark, 2)
        mark = now

    with sandbox.scratch_dir() as scratch:
        seed_ws = seed_checkout(spec, a, scratch / "seed")
        base = seed_baseline(spec, a, seed_ws, python, forbid)
        lap("seed_baseline")

        # previous outcomes (for R)
        prev = last_ok_pass(scorer_events, k - 1) if k > 1 else None
        if k == 1:
            prev_hidden, prev_reg = base["hidden"], base["regression"]
        elif prev and "P" in prev and "R" in prev:
            prev_hidden = prev["P"]["detail"].get("outcomes")
            prev_reg = prev["R"]["detail"].get("outcomes")
        else:
            s_prev = run_suites(a.snap(k - 1) / "workspace", seed_ws, hidden, python, forbid,
                                stage_prev)
            prev_hidden, prev_reg = s_prev["hidden"], s_prev["regression"]

        lap("prev_outcomes")
        # P, R
        t_pr = time.monotonic()
        p = p_hidden.score_hidden(ws, hidden, python, forbid=forbid, stage=stage_k)
        reg = r_regression.run_regression_on(ws, seed_ws, python, forbid=forbid)
        est_commit_s = time.monotonic() - t_pr   # one hidden + one regression run
        r = r_regression.score_regressions(prev_hidden, p["detail"]["outcomes"], prev_reg,
                                           reg.outcomes)
        r["detail"]["regression_suite"] = {"total": reg.total, "passed": reg.passed,
                                           "reason": reg.reason}
        lap("P_R")
        tamper = r_regression.tests_tampered(ws, seed_ws)

        # accepted commits (D-1)
        interval = r_regression.accepted_in_interval(a.mirror, prev_sha, cur_sha, seed_ws, python,
                                                     cache)
        cum_prev = None
        if prev and "accepted_commits" in prev and prev["accepted_commits"].get("value") is not None:
            cum_prev = int(prev["accepted_commits"]["value"])
        if cum_prev is None:
            cum_prev = 0
            for j in range(1, k):
                if not (a.snap(j) / "meta.json").exists():
                    continue
                cum_prev += r_regression.accepted_in_interval(
                    a.mirror, a.head_sha(j - 1, seed_sha), a.head_sha(j, seed_sha), seed_ws,
                    python, cache)["accepted"]
        int_accepted = interval["accepted"]
        cum_accepted = cum_prev + int_accepted

        lap("accepted")
        # per-commit hidden scoring (interfaces.md §8)
        cs = commit_scoring.score_commits(
            mirror=a.mirror, prev_sha=prev_sha, cur_sha=cur_sha, t_prev=t_prev, t_k=t_k,
            start_epoch=a.start_epoch, timeline=timeline, staged=staged, hidden=hidden,
            seed_ws=seed_ws, python=python, accepted=cache, cache=commit_cache, forbid=forbid,
            est_commit_s=est_commit_s,
            max_scoring_s=float(getattr(s.scoring, "max_commit_scoring_s",
                                        commit_scoring.DEFAULT_MAX_COMMIT_SCORING_S)))
        lap("commits")
        # D
        dd = d_defects.score_defects(ws, base["defects"], python)

        lap("D")
        # C
        constraints = (yaml.safe_load(Path(task.constraints_file).read_text()) or {}).get(
            "constraints") or []
        from scorer.metrics import c_constraints
        lock_text = Path(task.seed_requirements_lock).read_text()
        freeze = snap / "pip-freeze.txt"
        freeze_text = freeze.read_text() if freeze.exists() else None

        def probe_ctx(tree: Path) -> c_constraints.ProbeContext:
            return c_constraints.ProbeContext(snapshot_ws=tree, seed_ws=seed_ws,
                                              pip_freeze_text=freeze_text, seed_lock_text=lock_text)

        with sandbox.temp_copy(ws, forbid=forbid) as tree:
            c_val, c_detail = c_constraints.score_constraints(probe_ctx(tree), constraints)

        lap("C")
        # W
        from scorer.metrics import w_repeat
        w = w_repeat.repeat_work(a.mirror, seed_sha, prev_sha, cur_sha)
        w_detail = {"lines_added": w["lines_added"], "lines_deleted_own": w["lines_deleted_own"],
                    **(w.get("detail") or {})}
        bounds = counters.interval_boundaries(a.orch)
        stream = a.events_dir / "agent_stream.jsonl"
        start_ns = bounds[k - 1] if len(bounds) > k - 1 else None
        end_ns = bounds[k] if len(bounds) > k else None
        if stream.exists() and start_ns is not None and end_ns is not None:
            wt = {"value": float(w_repeat.repeated_tool_calls(stream, start_ns, end_ns)), "detail": {}}
        else:
            wt = {"value": None, "detail": {"reason": "no_stream_or_interval_bounds"}}

        lap("W")
        # S
        from scorer.metrics import s_cost
        cum_cost, cum_tokens = cumulative_at(a, meta, end_ns, scratch)
        if k > 1:
            prev_cost, _ = cumulative_at(a, a.meta(k - 1), start_ns, scratch)
        else:
            prev_cost = 0.0
        int_cost = max(0.0, cum_cost - prev_cost)
        sc = s_cost.cost_metrics(cum_cost=cum_cost, cum_accepted=cum_accepted, int_cost=int_cost,
                                 int_accepted=int_accepted, cum_tokens=cum_tokens)

        lap("S")
        # X
        from scorer.metrics import x_judge
        runner = judge_runner
        if runner is None:
            runner = x_judge.FakeJudge() if s.scoring.judge_runtime == "scripted" \
                else x_judge.ClaudeJudgeRunner()
        diff = _git("diff", prev_sha, cur_sha, git_dir=a.mirror, check=False)[:MAX_DIFF_CHARS]
        try:
            msgs = r_regression.agent_commit_messages(a.mirror, seed_sha, cur_sha)
        except RuntimeError:
            msgs = []
        brief = Path(task.prompt_file).read_text()
        if stage_k:  # staged task: later requirements and change requests are part of the brief, so a
            # deliberate reversal ordered by a change request is not an agent contradiction
            from runner.stages import load_stages
            for st in load_stages(task.stages_file).stages[1:stage_k + 1]:
                brief += f"\n\n--- Stage {st.id} ({st.kind}), delivered during the run ---\n\n{st.text}"
        bundle = x_judge.build_bundle(
            task_prompt=brief,
            constraints=[c.get("text", "") for c in constraints],
            assistant_texts=assistant_texts(stream, end_ns), commit_messages=msgs, diff=diff)
        jr = x_judge.judge(bundle, model=s.scoring.judge_model, samples=s.scoring.judge_samples,
                           runner=runner, cache_dir=a.scorer_dir / "judge-cache")

        lap("X")
        # security (plan B4, D-23): SAST new/open, exploit suite, AI review per completed stage
        sec_metrics: dict[str, dict] = {}
        if s.scoring.security.enabled:
            from scorer.security.checkpoint import score_security
            sec_metrics = score_security(
                spec=s, ws=ws, seed_ws=seed_ws, python=python, repo_root=REPO_ROOT, forbid=forbid,
                stage=stage_k, prev_pass=prev, k=k, orch=a.orch, t_prev=t_prev, t_k=t_k, mirror=a.mirror,
                scorer_dir=a.scorer_dir, reviewer=getattr(judge_runner, "reviewer", None))
            lap("SEC")
        # hazards
        first_bad: dict[str, float | None] = {"quality": None, "context": None}
        commits = interval["commits"]
        r_val = r["value"]
        if r_val > 0:
            prev_pass = {t for t, o in (prev_reg or {}).items() if o == "passed"}

            def bad_quality(path: Path) -> bool:
                res = r_regression.run_regression_on(path, seed_ws, python)
                return any(res.outcomes.get(t) != "passed" for t in prev_pass)
            first_bad["quality"] = _attribute(commits, a.mirror, bad_quality, t_prev, t_k,
                                              a.start_epoch)
        if c_val > 0:
            def bad_context(path: Path) -> bool:
                _ensure_git(path)
                return c_constraints.score_constraints(probe_ctx(path), constraints)[0] > 0
            first_bad["context"] = _attribute(commits, a.mirror, bad_context, t_prev, t_k,
                                              a.start_epoch)

    lap("attribution")
    # --- emit ------------------------------------------------------------------------------
    metrics: dict[str, dict] = {
        "P": {"value": p["value"], "detail": p["detail"]},
        "R": {"value": r_val, "detail": {**r["detail"], "first_offending_commit_t_s": first_bad["quality"],
                                         "tamper_reasons": tamper["detail"]["reasons"]}},
        "D": dd["D"],
        "C": {"value": float(c_val), "detail": {**c_detail,
                                                "first_offending_commit_t_s": first_bad["context"]}},
        "W": {"value": w["W"], "detail": w_detail},
        "X": {"value": jr.get("X"), "detail": {k_: v for k_, v in jr.items() if k_ != "X"}},
        "S": {"value": sc.get("S"), "detail": {k_: v for k_, v in sc.items() if k_ != "S"}
              | {"cum_cost": cum_cost, "cum_accepted": cum_accepted}},
        "D_delta": dd["D_delta"],
        "S_int": {"value": sc.get("S_int"), "detail": {
            "int_cost": int_cost, "int_accepted": int_accepted, "cum_accepted": cum_accepted,
            "t_s": t_k, "t_prev_s": t_prev}},
        "X_spread": {"value": jr.get("X_spread"), "detail": {}},
        "tokens_per_commit": {"value": sc.get("tokens_per_commit"), "detail": {"cum_tokens": cum_tokens}},
        "accepted_commits": {"value": float(cum_accepted), "detail": {
            "interval": int_accepted, "n_commits": interval["n_commits"],
            "sampled": interval["sampled"], "n_checked": interval["n_checked"]}},
        "tests_tampered": tamper,
        "W_repeat_tool_calls": wt,
        **sec_metrics,
    }
    for name in ("X", "S", "S_int", "X_spread", "tokens_per_commit"):
        m = metrics[name]
        if m["value"] is None and "reason" not in m["detail"]:
            m["detail"]["reason"] = (sc.get("reason") or jr.get("reason") or "unavailable")
    if "reason" not in metrics["D"]["detail"] and metrics["D"]["value"] is None:
        metrics["D"]["detail"]["reason"] = "unavailable"
    for name in (*CORE, *[n for n in metrics if n not in CORE]):
        m = metrics[name]
        writer.emit("scorer.metric", {"k": k, "pass_id": pass_id, "name": name, "value": m["value"],
                                      "detail": m["detail"]})
        out.metrics[name] = m

    from scorer import hazards
    views = _build_views(a, k, scorer_events, dt_s, metrics, t_k, t_prev, int_cost, int_accepted,
                         cum_accepted, first_bad)
    viol = _guardrail_violations(a, t_k)
    for hz in hazards.evaluate(views, guardrail_violations=viol, run_start_epoch=a.start_epoch,
                               thresholds=s.scoring.thresholds):
        if hz.get("k") != k:
            continue  # first detected at an earlier checkpoint: carried, not re-emitted
        payload = {**hz, "k": k, "pass_id": pass_id}
        writer.emit("scorer.hazard", payload)
        out.hazards.append(payload)
    for ev in cs.events:
        payload = {"k": k, "pass_id": pass_id, **ev}
        writer.emit("scorer.commit", payload)
        out.commits.append(payload)


def _guardrail_violations(a: Artifact, t_k: float) -> list[dict]:
    res = []
    for ev in read_events(a.events_dir / "guardrail.jsonl"):
        if ev.get("type") != "guardrail.violation":
            continue
        try:
            epoch = _iso_to_epoch(ev["ts"])
        except (KeyError, ValueError):
            continue
        if a.start_epoch and epoch - a.start_epoch > t_k + 1e-6:
            continue
        res.append({"type": "guardrail.violation", "ts": epoch, "payload": ev.get("payload") or {}})
    return res


def _build_views(a, k, scorer_events, dt_s, metrics, t_k, t_prev, int_cost, int_accepted,
                 cum_accepted, first_bad):
    from scorer import hazards
    views = []
    for j in range(1, k):
        prev = last_ok_pass(scorer_events, j) or {}

        def val(name, prev=prev):
            return (prev.get(name) or {}).get("value")

        def det(name, prev=prev):
            return (prev.get(name) or {}).get("detail") or {}
        si = det("S_int")
        views.append(hazards.CheckpointView(
            k=j, t_s=a.t_s(j, dt_s), t_prev_s=a.t_s(j - 1, dt_s), R=val("R"), C=val("C"),
            W=val("W"), S_int=val("S_int"), int_cost=si.get("int_cost", 0.0),
            int_accepted=si.get("int_accepted", 0), cum_accepted=si.get("cum_accepted", 0),
            first_offending_commit_t_s={"quality": det("R").get("first_offending_commit_t_s"),
                                        "context": det("C").get("first_offending_commit_t_s")},
            SEC_exploits=val("SEC_exploits")))
    views.append(hazards.CheckpointView(
        k=k, t_s=t_k, t_prev_s=t_prev, R=metrics["R"]["value"], C=metrics["C"]["value"],
        W=metrics["W"]["value"], S_int=metrics["S_int"]["value"], int_cost=int_cost,
        int_accepted=int_accepted, cum_accepted=cum_accepted,
        first_offending_commit_t_s=first_bad,
        SEC_exploits=(metrics.get("SEC_exploits") or {}).get("value")))
    return views


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scorer.run_checkpoint")
    ap.add_argument("--art", type=Path, required=True)
    ap.add_argument("--k", type=int, required=True)
    ap.add_argument("--spec", type=Path, default=None)
    ap.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    a = ap.parse_args(argv)
    from scorer.venv import install_scorer
    manifest = Artifact(a.art).manifest
    spec_path = a.spec or manifest.get("spec_path")
    if not spec_path:
        print("error: no --spec and the manifest has no spec_path", file=sys.stderr)
        return 2
    loaded = load_spec(spec_path, repo_root=a.repo_root)
    py = install_scorer(a.repo_root, Path(loaded.spec.task.seed_requirements_lock))  # no-op if built
    res = score_checkpoint(a.art, a.k, spec=loaded, scorer_python=py)
    print(json.dumps({"k": res.k, "ok": res.ok, "duration_s": res.duration_s, "error": res.error,
                      "metrics": {n: m["value"] for n, m in res.metrics.items()},
                      "hazards": [h["dimension"] for h in res.hazards]}, indent=1))
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
