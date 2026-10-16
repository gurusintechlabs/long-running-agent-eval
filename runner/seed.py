"""Deterministic seed repositories (docs/spec.md §4.1 ``task.seed_repo`` / ``seed_commit``).

A seed is a plain folder of files. It is turned into a one-commit git repo with a fixed identity
and date, so the commit SHA depends only on the file contents. The SHA is pinned in the spec; if
the fixture drifts the build is refused rather than silently running a different task. (Same
procedure as ``fixtures/build_seed.py``, which this must keep matching.)
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from runner.workdir import WorkdirError

DATE = "2026-01-01T00:00:00Z"
IDENT = {
    "GIT_AUTHOR_NAME": "LRAE Seed", "GIT_AUTHOR_EMAIL": "seed@lrae.invalid",
    "GIT_COMMITTER_NAME": "LRAE Seed", "GIT_COMMITTER_EMAIL": "seed@lrae.invalid",
    "GIT_AUTHOR_DATE": DATE, "GIT_COMMITTER_DATE": DATE,
}
MESSAGE = "Seed: items service"
IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", ".venv", ".git", ".DS_Store")


def _git(cwd: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(IDENT)
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    out = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
    if out.returncode != 0:
        raise WorkdirError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout.strip()


def build_seed_repo(src: Path, target: Path) -> str:
    """Copy ``src`` into ``target`` as a fresh one-commit repo; return the commit SHA."""
    target = Path(target)
    if target.exists() and any(target.iterdir()):
        raise WorkdirError(f"seed build target is not empty: {target}")
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, target, ignore=IGNORE, dirs_exist_ok=True)
    for p in target.rglob("*"):  # the tree hash must not depend on the checkout umask
        if p.is_file() and ".git" not in p.parts:
            p.chmod(0o644)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "core.autocrlf", "false")
    _git(target, "config", "core.filemode", "false")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "--no-gpg-sign", "-m", MESSAGE)
    return _git(target, "rev-parse", "HEAD")


def _head(repo: Path) -> str | None:
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else None


def ensure_seed_repo(seed: Path, seed_commit: str, cache_root: Path) -> Path:
    """Return a git repo containing ``seed_commit``: ``seed`` itself if it already is one, else a
    cached deterministic build of it. Raises if the build does not produce the pinned SHA."""
    seed = Path(seed)
    if (seed / ".git").exists():
        check = subprocess.run(["git", "cat-file", "-e", f"{seed_commit}^{{commit}}"], cwd=seed,
                               capture_output=True)
        if check.returncode != 0:
            raise WorkdirError(f"seed repo {seed} does not contain pinned commit {seed_commit}")
        return seed
    cached = Path(cache_root) / seed_commit
    if cached.exists() and _head(cached) == seed_commit:
        return cached
    shutil.rmtree(cached, ignore_errors=True)
    built = build_seed_repo(seed, cached)
    if built != seed_commit:
        shutil.rmtree(cached, ignore_errors=True)
        raise WorkdirError(f"seed fixture {seed} builds to {built}, but the spec pins {seed_commit}; "
                           "the fixture changed. Rebuild it deliberately and update seed_commit.")
    return cached
