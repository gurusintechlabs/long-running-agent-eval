"""Run-id allowlist and path containment (UI-4)."""
from __future__ import annotations

import re
from pathlib import Path

_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", re.ASCII)


def valid_run_id(rid: object) -> bool:
    return isinstance(rid, str) and _RUN_ID.fullmatch(rid) is not None


def resolve_run_dir(runs_dir: Path, rid: str) -> Path | None:
    """The run's directory, or None when the id is malformed, absent, not a directory, or resolves
    (e.g. through a symlink) to somewhere outside ``runs_dir``."""
    if not valid_run_id(rid):
        return None
    root = runs_dir.resolve()
    try:
        p = (root / rid).resolve()
    except (OSError, RuntimeError):
        return None
    if p.parent != root or not p.is_dir():
        return None
    return p


def scrub_paths(obj, repo_root: Path, home: Path):
    """Copy of a JSON value with the repo root and home directory shortened (``<repo>``, ``~``)."""
    if isinstance(obj, str):
        out = obj.replace(str(repo_root), "<repo>")
        return out.replace(str(home), "~") if str(home) not in ("/", "") else out
    if isinstance(obj, dict):
        return {k: scrub_paths(v, repo_root, home) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub_paths(v, repo_root, home) for v in obj]
    return obj
