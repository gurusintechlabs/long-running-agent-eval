"""Read-only views of a run's ``mirror.git`` (U3, UI-5).

The repository content is hostile text (it was written by the agent under test). Git is run without a
shell, with a scrubbed environment, no system/global config, no hooks, no external diff or textconv
drivers, no pager and no external protocols; its output is size-capped while streaming.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")
MAX_COMMITS = 500
MAX_FILES = 2_000
DEFAULT_DIFF_BYTES, MAX_DIFF_BYTES = 400_000, 2_000_000
TIMEOUT_S = 20
_FS, _RS = "\x1f", "\x1e"

SAFE_CONFIG = ("-c", "core.hooksPath=/dev/null", "-c", "protocol.ext.allow=never", "-c", "core.fsmonitor=false",
               "-c", "core.pager=cat", "-c", "core.attributesFile=/dev/null",
               "-c", "core.quotepath=off", "-c", "safe.directory=*", "-c", "diff.renames=false")


class GitError(RuntimeError):
    pass


def valid_sha(s: object) -> bool:
    return isinstance(s, str) and SHA.fullmatch(s) is not None


def git_env() -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": "/nonexistent",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1", "LC_ALL": "C", "GIT_PAGER": "cat",
            "GIT_ATTR_NOSYSTEM": "1"}


def mirror_path(run_dir: Path) -> Path | None:
    """``<run>/mirror.git`` when it is a real directory inside the run dir, else None."""
    p = run_dir / "mirror.git"
    try:
        r = p.resolve()
    except (OSError, RuntimeError):
        return None
    return r if r.is_dir() and r.parent == run_dir.resolve() else None


def _git() -> str:
    g = shutil.which("git", path=git_env()["PATH"])
    if not g:
        raise GitError("git is not installed")
    return g


def run_git(repo: Path, args: list[str], cap: int) -> tuple[bytes, bool, int]:
    """Run ``git <args>`` (no shell); return ``(stdout up to cap bytes, truncated, returncode)``."""
    cmd = [_git(), *SAFE_CONFIG, "--no-pager", f"--git-dir={repo}", *args]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                env=git_env(), cwd="/", shell=False, close_fds=True)
    except OSError as e:
        raise GitError(f"cannot run git: {e}") from None
    out, truncated = b"", False
    try:
        assert proc.stdout is not None
        out = proc.stdout.read(cap + 1)
        if len(out) > cap:
            truncated, out = True, out[:cap]
            proc.kill()
        proc.wait(timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise GitError("git timed out") from None
    finally:
        if proc.stdout:
            proc.stdout.close()
    return out, truncated, proc.returncode if not truncated else 0


def has_commit(repo: Path, sha: str) -> bool:
    if not valid_sha(sha):
        return False
    _o, _t, rc = run_git(repo, ["cat-file", "-e", f"{sha}^{{commit}}"], 100)
    return rc == 0


def _text(b: bytes, limit: int | None = None) -> str:
    s = b.decode("utf-8", "replace").replace("\x00", "�")
    return s if limit is None else s[:limit]


EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def commits(repo: Path, base: str | None, head: str) -> tuple[list[dict], bool]:
    """Commits in ``base..head`` (newest first), at most MAX_COMMITS."""
    fmt = _FS.join(["%H", "%P", "%aI", "%an", "%s"]) + _RS
    out, trunc, rc = run_git(repo, ["log", f"--max-count={MAX_COMMITS + 1}", "--no-color", "--no-show-signature",
                                    f"--format={fmt}", (f"{base}..{head}" if base else head), "--"], 2_000_000)
    if rc != 0:
        raise GitError("git log failed")
    rows = []
    for rec in _text(out).split(_RS):
        rec = rec.strip("\n")
        if not rec:
            continue
        f = rec.split(_FS)
        if len(f) < 5 or not valid_sha(f[0]):
            continue
        rows.append({"sha": f[0], "parents": [p for p in f[1].split() if valid_sha(p)], "date": f[2],
                     "author": f[3][:100], "subject": f[4][:300]})
    over = len(rows) > MAX_COMMITS or trunc
    return rows[:MAX_COMMITS], over


def numstat(repo: Path, base: str, head: str) -> tuple[list[dict], bool]:
    out, trunc, rc = run_git(repo, ["diff", "--no-ext-diff", "--no-textconv", "--no-color", "--numstat", "-z",
                                    base, head, "--"], 2_000_000)
    if rc != 0:
        raise GitError("git diff failed")
    parts = [_text(x) for x in out.split(b"\x00")]
    files, i = [], 0
    while i < len(parts):
        f = parts[i].split("\t", 2)
        i += 1
        if len(f) != 3:
            continue
        a, d, name = f
        if name == "" and i + 1 < len(parts):        # rename/copy record: old and new path follow
            name = parts[i + 1]
            i += 2
        binary = a == "-"
        files.append({"path": name[:500], "added": None if binary else int(a), "deleted": None if binary else int(d),
                      "binary": binary})
    over = len(files) > MAX_FILES or trunc
    return files[:MAX_FILES], over


def diff_text(repo: Path, base: str, head: str, max_bytes: int) -> tuple[str, bool]:
    """Unified diff (binary files appear as 'Binary files differ'), cut at ``max_bytes``."""
    max_bytes = max(1000, min(max_bytes, MAX_DIFF_BYTES))
    out, trunc, rc = run_git(repo, ["diff", "--no-ext-diff", "--no-textconv", "--no-color", "--unified=3",
                                    "--src-prefix=a/", "--dst-prefix=b/", base, head, "--"], max_bytes)
    if rc != 0:
        raise GitError("git diff failed")
    return _text(out), trunc
