"""Per-run manifest (docs/spec.md §4.2)."""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path


def write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=str))
    os.replace(tmp, path)


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def update(path: Path, **fields) -> dict:
    data = load(path)
    data.update(fields)
    write(path, data)
    return data


def framework_version(repo_root: Path) -> dict:
    def g(*args):
        out = subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True)
        return out.stdout.strip() if out.returncode == 0 else None
    sha = g("rev-parse", "HEAD")
    return {"git_sha": sha, "dirty": bool(g("status", "--porcelain")) if sha else None}


def host_info() -> dict:
    return {"os": platform.platform(), "python": sys.version.split()[0], "machine": platform.machine()}
