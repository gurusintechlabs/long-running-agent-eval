#!/usr/bin/env python3
"""Deterministically build a known snapshot as a git working copy.

    python fixtures/snapshots/build.py known_good /some/new/dir

The result is the seed at its pinned commit plus ONE agent commit (author/committer
``agent <agent@lrae.local>``, date 2026-01-01T00:00:00Z) holding the snapshot's overlay, so the
HEAD SHA depends only on the fixture files. ``snapshot.yaml`` per snapshot:
``{base: seed | <other snapshot>, commit_message, deletes: [paths], spec: <experiment spec>}``;
overlays of the base chain are applied first, then the snapshot's own, then its deletes. ``spec``
(optional; the nearest one along the base chain wins, default ``spec/examples/pilot.yaml``) names
the experiment spec whose ``task.seed_repo`` / ``task.seed_commit`` give the seed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
DEFAULT_SPEC = "spec/examples/pilot.yaml"
DATE = "2026-01-01T00:00:00Z"
IDENT = {
    "GIT_AUTHOR_NAME": "agent", "GIT_AUTHOR_EMAIL": "agent@lrae.local",
    "GIT_COMMITTER_NAME": "agent", "GIT_COMMITTER_EMAIL": "agent@lrae.local",
    "GIT_AUTHOR_DATE": DATE, "GIT_COMMITTER_DATE": DATE,
}


def _git(cwd: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(IDENT)
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    out = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout.strip()


def _chain(name: str) -> list[tuple[Path, dict]]:
    """Snapshot definitions from the root of the base chain down to ``name``."""
    chain: list[tuple[Path, dict]] = []
    while name != "seed":
        d = HERE / name
        if not (d / "snapshot.yaml").is_file() or len(chain) > 20:
            raise ValueError(f"unknown snapshot {name!r}")
        meta = yaml.safe_load((d / "snapshot.yaml").read_text())
        chain.append((d, meta))
        name = meta.get("base", "seed")
    return chain[::-1]


def materialize(name: str, dest: Path, repo_root: Path) -> Path:
    """Build snapshot ``name`` as a git working copy at ``dest`` (must not exist or be empty)."""
    from runner.seed import ensure_seed_repo
    from runner.workdir import clone_seed

    repo_root, dest = Path(repo_root), Path(dest)
    chain = _chain(name)
    spec_rel = next((m["spec"] for _, m in reversed(chain) if m.get("spec")), DEFAULT_SPEC)
    spec_path = repo_root / spec_rel
    task = yaml.safe_load(spec_path.read_text())["task"]
    seed_commit = task["seed_commit"]
    seed_src = (spec_path.parent / task["seed_repo"]).resolve()
    seed_repo = ensure_seed_repo(seed_src, seed_commit, repo_root / "runs" / ".seed-cache")
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"destination is not empty: {dest}")
    if dest.exists():
        dest.rmdir()
    memory = task.get("workspace_memory")       # D-15a: a task-owned CLAUDE.md in the seed
    clone_seed(seed_repo, seed_commit, dest,
               (spec_path.parent / memory).read_bytes() if memory else None)
    for d, meta in chain:
        overlay = d / "overlay"
        if overlay.is_dir():
            shutil.copytree(overlay, dest, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
        for rel in meta.get("deletes") or []:
            target = dest / rel
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)
    for p in dest.rglob("*"):  # the tree must not depend on the umask
        if p.is_file() and ".git" not in p.parts:
            p.chmod(0o644)
    _git(dest, "config", "--local", "user.name", "agent")
    _git(dest, "config", "--local", "user.email", "agent@lrae.local")
    _git(dest, "config", "--local", "core.filemode", "false")
    _git(dest, "add", "-A")
    # --allow-empty: a stage whose right answer is to change nothing (minidb_v3_s10) has no overlay
    _git(dest, "commit", "-q", "--no-gpg-sign", "--allow-empty", "-m", chain[-1][1]["commit_message"])
    return dest


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: build.py <snapshot name, e.g. known_good> <dest-dir>", file=sys.stderr)
        return 2
    root = HERE.parents[1]
    sys.path.insert(0, str(root))
    dest = materialize(argv[1], Path(argv[2]), root)
    print(_git(dest, "rev-parse", "HEAD"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
