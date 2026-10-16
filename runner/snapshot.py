"""Checkpoint snapshots (docs/spec.md §5.1 CHECKPOINTING).

Pause the agent, copy the workspace and the agent state dir, resume, then write metadata and a
tag in a local bare *mirror* repo (never in the agent's repo; decision D-5).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from runner import memory
from runner.workdir import RunPaths

_IGNORED_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}


@dataclass(frozen=True)
class SnapshotInfo:
    k: int
    path: Path
    meta: dict


def worktree_hash(root: Path) -> str:
    """Content hash of the working tree, independent of ``.git`` and of cache directories."""
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _IGNORED_DIRS)
        for name in sorted(filenames):
            if name.endswith(".pyc"):
                continue
            p = Path(dirpath) / name
            rel = p.relative_to(root).as_posix()
            h.update(rel.encode() + b"\0")
            if p.is_symlink():
                h.update(b"L" + os.readlink(p).encode())
            else:
                h.update(p.read_bytes())
            h.update(b"\0")
    return h.hexdigest()


def _count_files(root: Path) -> int:
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIRS]
        n += sum(1 for f in filenames if not f.endswith(".pyc"))
    return n


def _git(cwd: Path | None, *args: str, git_dir: Path | None = None) -> str:
    cmd = ["git"]
    if git_dir is not None:
        cmd += ["--git-dir", str(git_dir)]
    proc = subprocess.run([*cmd, *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def update_mirror(mirror: Path, workspace: Path, k: int) -> None:
    """Fetch the workspace HEAD into the local mirror and tag it ``ckpt/t{k}``."""
    if not mirror.exists():
        subprocess.run(["git", "init", "-q", "--bare", str(mirror)], check=True)
    _git(None, "fetch", "-q", "--no-tags", str(workspace), "HEAD", git_dir=mirror)
    _git(None, "tag", "-f", f"ckpt/t{k}", "FETCH_HEAD", git_dir=mirror)


def take_snapshot(paths: RunPaths, k: int, *, state_dir: Path, proc=None,
                  cumulative_cost_usd: float | None = None,
                  pip_freeze_text: str | None = None) -> SnapshotInfo:
    dest = paths.snapshots / f"t{k}"
    if dest.exists():
        raise FileExistsError(f"snapshot already exists: {dest}")
    dest.mkdir(parents=True)

    t0 = time.monotonic()
    if proc is not None:
        proc.pause()
    try:
        shutil.copytree(paths.workspace, dest / "workspace", symlinks=True)
        memory.snapshot_state(state_dir, dest / "agent_state")
    finally:
        if proc is not None:
            proc.resume()
    pause_ms = round((time.monotonic() - t0) * 1000)

    snap_ws = dest / "workspace"
    status = _git(snap_ws, "status", "--porcelain")
    meta = {
        "k": k,
        "head_sha": _git(snap_ws, "rev-parse", "HEAD"),
        "head_tree": _git(snap_ws, "rev-parse", "HEAD^{tree}"),
        "dirty": bool(status),
        "worktree_hash": worktree_hash(snap_ws),
        "file_count": _count_files(snap_ws),
        "pause_ms": pause_ms,
        "cumulative_cost_usd": cumulative_cost_usd,
        "pip_freeze_hash": None,
    }
    if pip_freeze_text is not None:
        (dest / "pip-freeze.txt").write_text(pip_freeze_text)
        meta["pip_freeze_hash"] = hashlib.sha256(pip_freeze_text.encode()).hexdigest()
    (dest / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True))
    update_mirror(paths.mirror, snap_ws, k)  # fetch from the frozen copy, not the live repo
    return SnapshotInfo(k=k, path=dest, meta=meta)
