"""Pre-flight checks (docs/spec.md §5.1 PREPARING step 5). Any failed check means the run FAILS."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from runner import memory

KNOWN_TOOLS = {
    "Task", "Bash", "Glob", "Grep", "LS", "ExitPlanMode", "Read", "Edit", "MultiEdit", "Write",
    "NotebookRead", "NotebookEdit", "WebFetch", "TodoWrite", "WebSearch", "BashOutput", "KillBash",
    "KillShell", "SlashCommand",  # reported by CLI 1.0.126
}


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""


class PreflightError(RuntimeError):
    def __init__(self, failed: list[Check]):
        self.failed = failed
        super().__init__("pre-flight failed: " + "; ".join(f"{c.name}: {c.detail}" for c in failed))


def require(checks: list[Check]) -> list[Check]:
    failed = [c for c in checks if not c.ok]
    if failed:
        raise PreflightError(failed)
    return checks


def _ok(name: str, fn) -> Check:
    try:
        fn()
        return Check(name, True)
    except memory.MemoryError_ as exc:
        return Check(name, False, str(exc))


def _check_no_harness_paths(work: Path, repo_root: Path, forbidden_names: list[str]) -> Check:
    name = "L-4 no harness paths"
    repo = Path(repo_root).resolve()
    for dirpath, dirnames, filenames in os.walk(work):
        dirnames[:] = [d for d in dirnames if d != ".git" and not (Path(dirpath) == work and d == "venv")]
        for entry in [*dirnames, *filenames]:
            p = Path(dirpath) / entry
            rel = p.relative_to(work)
            if entry in forbidden_names:
                return Check(name, False, f"harness-named path inside work dir: {rel}")
            if p.is_symlink():
                target = Path(os.path.realpath(p))
                if target == repo or repo in target.parents:
                    return Check(name, False, f"symlink {rel} resolves into the repo")
    return Check(name, True)


def run_static_checks(paths, *, repo_root: Path, claude_home: Path, home: Path,
                      forbidden_names: list[str] | None = None,
                      check_state_empty: bool = True) -> list[Check]:
    """Checks that need no agent process: L-1, L-3 (empty state dir), L-4.

    ``check_state_empty=False`` is for resume, where the state dir was asserted empty and then
    deliberately restored from the snapshot before pre-flight runs.
    """
    ws = paths.workspace
    checks = [_ok("L-1 ancestors", lambda: memory.check_ancestors(ws, home=home))]
    if check_state_empty:
        checks.append(_ok("L-3 state dir empty",
                          lambda: memory.assert_empty(memory.state_dir(ws, claude_home))))
    checks.append(_check_no_harness_paths(paths.work, repo_root, forbidden_names or []))
    return checks


def check_claude_version(claude_bin: str, expected: str) -> Check:
    name = "L-6 cli version"
    try:
        out = subprocess.run([claude_bin, "--version"], capture_output=True, text=True, timeout=30,
                             env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
                                  "DISABLE_AUTOUPDATER": "1"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Check(name, False, f"cannot run {claude_bin}: {exc}")
    actual = out.stdout.strip().split(" ")[0] if out.stdout.strip() else ""
    if out.returncode != 0 or actual != expected:
        return Check(name, False, f"installed {actual or '?'} != spec {expected}")
    return Check(name, True, actual)


def find_init(lines) -> dict | None:
    for line in lines:
        try:
            msg = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(msg, dict) and msg.get("type") == "system" and msg.get("subtype") == "init":
            return msg
    return None


# Agents built into CLI 2.1.301; `statusline-setup` appears only without --safe-mode (verified B3).
# A custom agent (~/.claude/agents) or a new built-in in a later CLI fails pre-flight until listed.
BUILTIN_AGENTS = {"claude", "Explore", "general-purpose", "Plan", "statusline-setup"}


def evaluate_init(init: dict, allowed_tools: set[str] | None = None,
                  allowed_mcp: set[str] | None = None) -> list[Check]:
    """L-3: no MCP servers other than the task's counterparts (``allowed_mcp``, which must be
    connected), no plugins (built-ins are switched off in the harness settings) or user skills; only
    the allowed built-in tools plus the counterparts' ``mcp__<server>__*`` tools."""
    checks = []
    allowed_mcp = set(allowed_mcp or ())
    servers = init.get("mcp_servers") or []
    bad = []
    seen = set()
    for s in servers:
        name = s.get("name") if isinstance(s, dict) else str(s)
        seen.add(name)
        if name not in allowed_mcp or (isinstance(s, dict) and s.get("status") not in (None, "connected")):
            bad.append(f"{name} ({s.get('status')})" if isinstance(s, dict) else str(s))
    bad += [f"{n} (missing)" for n in sorted(allowed_mcp - seen)]
    checks.append(Check("L-3 only the task's mcp servers", not bad, ", ".join(bad)))
    tools = init.get("tools") or []
    allowed = allowed_tools if allowed_tools is not None else KNOWN_TOOLS
    odd = [t for t in tools if (t.split("__")[1] not in allowed_mcp if t.startswith("mcp__") else t not in allowed)]
    checks.append(Check("L-3 only built-in tools", not odd, "unexpected tools: " + ", ".join(odd)))
    agents = [a for a in (init.get("agents") or []) if a not in BUILTIN_AGENTS]
    checks.append(Check("L-3 only built-in agents", not agents, ", ".join(map(str, agents))))
    plugins = list(init.get("plugins") or [])
    extras = {k: init[k] for k in ("skills", "slash_commands_custom") if init.get(k)}
    if plugins:
        extras["plugins"] = plugins
    checks.append(Check("L-3 no plugins or user skills", not extras, json.dumps(extras)[:2000]))
    return checks
