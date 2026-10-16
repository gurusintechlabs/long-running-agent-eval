"""Clean-memory handling for each run (docs/spec.md §3.2 L-1, L-3; decision D-15).

The Claude Code CLI keeps per-workspace session transcripts and auto-memory under
``~/.claude/projects/<encoded workspace path>/`` (the "agent state dir"). This module computes
that path, checks it starts empty, snapshots/restores/deletes it, checks the workspace and its
ancestors for memory files, and can move the user's own ``CLAUDE.md`` aside for the run.
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

MEMORY_FILES = ("CLAUDE.md", "CLAUDE.local.md")
USER_MEMORY_ENTRIES = ("CLAUDE.md", "rules")


class MemoryError_(RuntimeError):
    """A clean-memory invariant does not hold."""


def default_claude_home() -> Path:
    return Path.home() / ".claude"


def encode_project_path(path: str | os.PathLike) -> str:
    """Encode an absolute path the way the CLI names project dirs: non-alphanumerics -> '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def state_dir(workspace: str | os.PathLike, claude_home: Path | None = None) -> Path:
    home = claude_home or default_claude_home()
    return home / "projects" / encode_project_path(Path(workspace).resolve())


def assert_empty(sd: Path) -> None:
    if sd.exists() and any(sd.iterdir()):
        raise MemoryError_(f"agent state dir is not empty at run start: {sd}")


def snapshot_state(sd: Path, dest: Path) -> None:
    """Copy the state dir into ``dest`` (an empty dir is created if the state dir is absent)."""
    if dest.exists():
        shutil.rmtree(dest)
    if sd.exists():
        shutil.copytree(sd, dest, symlinks=True)
    else:
        dest.mkdir(parents=True)


def restore_state(snapshot: Path, sd: Path) -> None:
    if sd.exists():
        shutil.rmtree(sd)
    sd.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(snapshot, sd, symlinks=True)


def delete_state(sd: Path) -> None:
    shutil.rmtree(sd, ignore_errors=True)


def clean_workspaces(workspaces: list[Path], claude_home: Path | None = None) -> list[Path]:
    """Delete the state dirs of exactly these workspaces. Never touches other projects."""
    removed = []
    for ws in workspaces:
        sd = state_dir(ws, claude_home)
        if sd.exists():
            delete_state(sd)
            removed.append(sd)
    return removed


def check_ancestors(workspace: Path, home: Path, stop_at: Path | None = None) -> None:
    """L-1: no CLAUDE.md/CLAUDE.local.md in any ancestor; no .claude/ in any ancestor but $HOME."""
    ws = Path(workspace).resolve()
    home = Path(home).resolve()
    stop = Path(stop_at).resolve() if stop_at else Path(ws.anchor)
    for parent in ws.parents:
        for name in MEMORY_FILES:
            if (parent / name).exists():
                raise MemoryError_(f"{name} found in ancestor of workspace: {parent / name}")
        if parent != home and (parent / ".claude").exists():
            raise MemoryError_(f".claude/ found in ancestor of workspace: {parent / '.claude'}")
        if parent == stop:
            break


def check_seed_checkout(root: Path) -> None:
    """L-3: the seed checkout carries no project memory anywhere in the tree."""
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        if ".git" in dirnames:
            dirnames.remove(".git")
        for name in filenames:
            if name in MEMORY_FILES:
                raise MemoryError_(f"{name} in seed checkout: {Path(dirpath) / name}")
        if ".claude" in dirnames:
            raise MemoryError_(f".claude/ in seed checkout: {Path(dirpath) / '.claude'}")


class UserMemoryGuard:
    """Move the user's CLAUDE.md and rules/ aside for a run (mechanism 3 in spec §3.2 L-3).

    A lock file records the move so a crashed run is recovered by :meth:`recover`.
    """

    ASIDE = ".lrae-aside"

    def __init__(self, claude_home: Path, lock: Path):
        self.home = Path(claude_home)
        self.lock = Path(lock)
        self.moved: list[str] = []

    def engage(self) -> list[str]:
        present = [n for n in USER_MEMORY_ENTRIES if (self.home / n).exists()]
        if self.lock.exists():
            raise MemoryError_(f"user-memory lock already held: {self.lock}")
        if not present:
            return []
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        self.lock.write_text("\n".join(present))
        for name in present:
            os.rename(self.home / name, self.home / (name + self.ASIDE))
        self.moved = present
        return present

    def restore(self) -> None:
        for name in self.moved:
            aside = self.home / (name + self.ASIDE)
            if aside.exists():
                os.rename(aside, self.home / name)
        self.moved = []
        self.lock.unlink(missing_ok=True)

    @classmethod
    def recover(cls, claude_home: Path, lock: Path) -> bool:
        """Restore anything a crashed run left moved aside. True if something was restored."""
        lock = Path(lock)
        if not lock.exists():
            return False
        guard = cls(claude_home, lock)
        guard.moved = [n for n in lock.read_text().split("\n") if n]
        guard.restore()
        return True

    def __enter__(self) -> UserMemoryGuard:
        self.engage()
        return self

    def __exit__(self, *exc) -> None:
        self.restore()
