"""The pinned semgrep-rules checkout (plan B4): ``tools/semgrep-rules-<sha10>`` (gitignored).

Fetched once, harness-side, at the exact commit in ``scoring.security.semgrep_rules_commit``, so CE
results are reproducible. Concurrent scorers wait on a lock file.
"""
from __future__ import annotations

import fcntl
import shutil
import subprocess
from pathlib import Path

URL = "https://github.com/semgrep/semgrep-rules.git"


class RulesError(RuntimeError):
    pass


def rules_dir(repo_root: Path, sha: str) -> Path:
    return Path(repo_root) / "tools" / f"semgrep-rules-{sha[:10]}"


def _head(d: Path) -> str:
    return subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def ensure_rules(repo_root: Path, sha: str, url: str = URL) -> Path:
    d = rules_dir(repo_root, sha)
    if d.is_dir() and _head(d) == sha:
        return d
    d.parent.mkdir(parents=True, exist_ok=True)
    with open(d.parent / f".{d.name}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if d.is_dir() and _head(d) == sha:
            return d
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir()
        for cmd in (["git", "-C", str(d), "init", "-q"], ["git", "-C", str(d), "fetch", "-q", "--depth", "1", url, sha],
                    ["git", "-C", str(d), "checkout", "-q", "FETCH_HEAD"]):
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                shutil.rmtree(d, ignore_errors=True)
                raise RulesError(f"{' '.join(cmd[3:])} failed: {r.stderr.strip()[-300:]}")
        if _head(d) != sha:
            raise RulesError(f"semgrep-rules checkout is at {_head(d)}, wanted {sha}")
    return d
