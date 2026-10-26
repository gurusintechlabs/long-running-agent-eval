"""W(t): repeat-work ratio and repeated tool calls (docs/spec.md §8.3 row 5).

W over the interval (prev, cur] = lines deleted in the interval that the agent itself added
earlier in the run (blamed, on ``prev``, to a commit in ``seed..prev``) / lines added in the
interval. Renames are followed (``-M``) and binary files are ignored.
"""
from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_BLAME_HEADER = re.compile(r"^([0-9a-f]{40}) \d+ (\d+)(?: \d+)?$")


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=repo,
                          capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def _parse_diff(patch: str) -> tuple[int, dict[str, list[int]]]:
    """Return ``(lines_added, {old path: [deleted old line numbers]})`` from a ``-U0`` patch."""
    added = 0
    deleted: dict[str, list[int]] = {}
    old_path: str | None = None
    old_line = 0
    in_hunk = False
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            in_hunk = False
            old_path = None
        elif not in_hunk and line.startswith("--- "):
            old_path = None if line == "--- /dev/null" else line[6:] if line.startswith("--- a/") else None
        elif not in_hunk and line.startswith("+++ "):
            pass
        elif (m := _HUNK.match(line)):
            in_hunk = True
            old_line = int(m.group(1))
        elif in_hunk and line.startswith("-"):
            if old_path is not None:
                deleted.setdefault(old_path, []).append(old_line)
            old_line += 1
        elif in_hunk and line.startswith("+"):
            added += 1
    return added, deleted


def _blame_commits(repo: Path, rev: str, path: str) -> dict[int, str]:
    """``{line number: commit sha}`` for every line of ``path`` at ``rev``."""
    out = _git(repo, "blame", "--porcelain", rev, "--", path)
    lines: dict[int, str] = {}
    for line in out.splitlines():
        m = _BLAME_HEADER.match(line)
        if m:
            lines[int(m.group(2))] = m.group(1)
    return lines


def repeat_work(repo: Path, seed_sha: str, prev_sha: str, cur_sha: str) -> dict:
    """W for the interval (prev, cur]. ``repo`` is a working copy or bare repo with all commits."""
    patch = _git(repo, "diff", "-M", "-U0", "--no-color", "--no-ext-diff",
                 "--src-prefix=a/", "--dst-prefix=b/", prev_sha, cur_sha)
    lines_added, deleted = _parse_diff(patch)
    from runner.envmut import is_harness_email
    log = _git(repo, "log", "--format=%H %ae", f"{seed_sha}..{prev_sha}").split("\n")
    own_commits = {sha for sha, _, email in (row.partition(" ") for row in log if row)
                   if not is_harness_email(email)}  # harness commits (env stages) are not own work
    total_deleted = sum(len(v) for v in deleted.values())
    own_deleted = 0
    if own_commits:
        for path, nums in deleted.items():
            blame = _blame_commits(repo, prev_sha, path)
            own_deleted += sum(1 for n in nums if blame.get(n) in own_commits)
    w = own_deleted / lines_added if lines_added else 0.0
    return {"W": w, "lines_added": lines_added, "lines_deleted_own": own_deleted,
            "detail": {"lines_deleted_total": total_deleted, "own_commits": len(own_commits),
                       "files_with_deletions": len(deleted)}}


def repeated_tool_calls(stream_events: Path, start_mono_ns: int, end_mono_ns: int) -> int:
    """Number of repeated ``tool.call`` events in ``(start, end]``: for each (tool, canonical
    input) seen n times, n - 1 are repeats. Reads the parsed events of ``agent_stream.jsonl``."""
    seen: Counter[tuple[str, str]] = Counter()
    with Path(stream_events).open(encoding="utf-8") as fh:
        for raw in fh:
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if ev.get("type") != "tool.call":
                continue
            mono = ev.get("mono_ns")
            if not isinstance(mono, int) or not start_mono_ns < mono <= end_mono_ns:
                continue
            p = ev.get("payload") or {}
            canon = json.dumps(p.get("input"), sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False)
            seen[(str(p.get("tool")), canon + str(p.get("input_sha256", "")))] += 1
    return sum(n - 1 for n in seen.values())
