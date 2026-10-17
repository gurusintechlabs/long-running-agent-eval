"""Score a plain working copy as checkpoint 1 against the seed (``lrae score --snapshot``).

The copy is wrapped into a synthetic artifact dir (snapshots/t1, mirror.git with ``ckpt/t1``,
empty events, manifest) so the normal scoring pass runs unchanged. The judge is the deterministic
FakeJudge unless a runner is passed in: this entry point never spends.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from scorer.run_checkpoint import CheckpointScore, _git, score_checkpoint
from spec.loader import REPO_ROOT, LoadedSpec

IDENT = ["-c", "user.name=agent", "-c", "user.email=agent@lrae.local", "-c", "commit.gpgsign=false"]


def _load_builder(repo_root: Path):
    path = repo_root / "fixtures" / "snapshots" / "build.py"
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found")
    spec = importlib.util.spec_from_file_location("lrae_snapshot_build", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _has_seed_ancestor(ws: Path, seed_commit: str) -> bool:
    if not (ws / ".git").exists():
        return False
    r = subprocess.run(["git", "merge-base", "--is-ancestor", seed_commit, "HEAD"], cwd=ws,
                       capture_output=True)
    return r.returncode == 0


def _synthesize(src: Path, dest: Path, seed_repo: Path, seed_commit: str) -> None:
    """seed checkout + one commit holding the plain copy's files."""
    _git("clone", "-q", "--no-hardlinks", str(seed_repo), str(dest))
    _git("checkout", "-q", "--detach", seed_commit, cwd=dest)
    for child in dest.iterdir():
        if child.name != ".git":
            shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
    shutil.copytree(src, dest, symlinks=True, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".git"))
    _git("add", "-A", cwd=dest)
    _git(*IDENT, "commit", "-q", "--allow-empty", "-m", "snapshot", cwd=dest)


def score_snapshot_dir(name_or_path: str | Path, spec: LoadedSpec, out_art: Path, *,
                       scorer_python: Path | None = None, repo_root: Path = REPO_ROOT,
                       judge_runner=None) -> CheckpointScore:
    from runner.seed import ensure_seed_repo
    from runner.snapshot import update_mirror
    from scorer.metrics.x_judge import FakeJudge
    from scorer.venv import install_scorer

    repo_root, out_art = Path(repo_root), Path(out_art)
    task = spec.spec.task
    py = Path(scorer_python) if scorer_python else install_scorer(repo_root, Path(task.seed_requirements_lock))
    seed_repo = ensure_seed_repo(Path(task.seed_repo), task.seed_commit,
                                 out_art.parent / ".seed-cache")
    cand = Path(str(name_or_path))
    if out_art.exists() and any(out_art.iterdir()):
        raise FileExistsError(f"artifact dir is not empty: {out_art}")
    snap = out_art / "snapshots" / "t1"
    ws = snap / "workspace"
    snap.mkdir(parents=True)
    (out_art / "events").mkdir()
    if task.stages_file:  # a standalone snapshot is scored against the final stage (interfaces.md §9)
        from runner.stages import load_stages
        from telemetry.events import EventWriter
        last = load_stages(task.stages_file).stages[-1].id
        with EventWriter(out_art / "events" / "orchestrator.jsonl", "standalone", "orchestrator") as w:
            w.emit("stage.delivered", {"stage": last, "t_s": 0.0, "interrupted": False, "standalone": True})
    with tempfile.TemporaryDirectory(prefix="lrae-standalone-") as tmp:
        tmp = Path(tmp)
        if cand.is_dir() and not (cand / "snapshot.yaml").is_file():
            src = cand
        else:  # a named fixture snapshot definition
            name = cand.name if cand.is_dir() else str(name_or_path)
            src = _load_builder(repo_root).materialize(name, tmp / "built", repo_root)
        if _has_seed_ancestor(src, task.seed_commit):
            shutil.copytree(src, ws, symlinks=True)
        else:
            _synthesize(src, ws, seed_repo, task.seed_commit)
    status = _git("status", "--porcelain", cwd=ws)
    meta = {"k": 1, "head_sha": _git("rev-parse", "HEAD", cwd=ws),
            "head_tree": _git("rev-parse", "HEAD^{tree}", cwd=ws), "dirty": bool(status),
            "cumulative_cost_usd": 0.0, "pip_freeze_hash": None, "standalone": True}
    (snap / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True))
    update_mirror(out_art / "mirror.git", ws, 1)
    (out_art / "manifest.json").write_text(json.dumps({
        "run_id": out_art.name, "experiment_id": spec.spec.experiment_id, "seed_commit": task.seed_commit,
        "spec_path": str(spec.path), "start_epoch": time.time(), "standalone": True}, indent=2))
    return score_checkpoint(out_art, 1, spec=spec, scorer_python=py,
                            judge_runner=judge_runner or FakeJudge())
