"""The real agent: the installed Claude Code CLI, headless (docs/spec.md §5.1 RUNNING)."""
from __future__ import annotations

import shutil
from pathlib import Path

from runner.runtimes.base import TurnContext

EMPTY_MCP = '{"mcpServers": {}}'
# The agent's tools: an explicit allowlist of core coding tools (CLI >= 2.1 also offers tools that
# message other local sessions, trigger remote or scheduled agents, run workflows or load skills,
# none of which belong in an isolated, comparable run). No web tools (design §2 egress allowlist).
# Verified against CLI 2.1.301 (probe init, 2026-10-17): Task comes with TaskStop (stops its own
# sub-tasks); MultiEdit/TodoWrite/BashOutput/KillShell no longer exist.
AGENT_TOOLS = ("Bash", "Read", "Edit", "Write", "Glob", "Grep", "NotebookEdit", "Task", "TaskStop")


def safe_mode_for(task, mcp_servers: set[str]) -> tuple[bool, str | None]:
    """Whether a run uses ``--safe-mode``, and why not. Verified on CLI 2.1.301 (plan B3): safe mode
    keeps the workspace ``CLAUDE.md`` out of memory and ignores ``--mcp-config`` servers. A task that
    seeds project rules (D-15a) or has counterpart MCP servers (D-28) therefore runs without it. The
    rest of the clean-memory setup still applies: user settings excluded (``--setting-sources``), the
    user's ``CLAUDE.md`` and rules moved aside, ``--strict-mcp-config``, built-in plugins off,
    slash commands off, and the pre-flight ``init`` check (built-in agents only)."""
    reasons = []
    if getattr(task, "workspace_memory", None):
        reasons.append("task.workspace_memory (safe mode would not load the workspace CLAUDE.md)")
    if mcp_servers:
        reasons.append(f"counterpart mcp servers {sorted(mcp_servers)} (safe mode ignores --mcp-config)")
    return (not reasons, "; ".join(reasons) or None)


class ClaudeCodeRuntime:
    name = "claude_code"
    needs_venv = True
    uses_real_agent = True

    def __init__(self, claude_bin: str, model: str, auto_memory: str = "cli_default"):
        if auto_memory != "cli_default":
            raise NotImplementedError("agent.auto_memory='off' is not implemented until its "
                                      "mechanism is verified against the installed CLI (Phase 1 findings)")
        self.claude_bin = claude_bin
        self.model = model
        self.allowed_tools = set(AGENT_TOOLS)
        self.allowed_mcp: set[str] = set()  # counterpart MCP servers of the task (plan B3)
        self.safe_mode = True                # see safe_mode_for

    def build_command(self, ctx: TurnContext) -> list[str]:
        mcp = ctx.mcp_config
        if mcp is None:  # no counterpart MCP server: an explicitly empty config
            mcp = ctx.art / "empty-mcp.json"
            mcp.parent.mkdir(parents=True, exist_ok=True)
            if not mcp.exists():
                mcp.write_text(EMPTY_MCP)
        cmd = [self.claude_bin, "-p", ctx.prompt,
               "--output-format", "stream-json", "--verbose",
               "--model", self.model,
               "--settings", str(ctx.settings_path),
               "--setting-sources", "project,local",
               "--strict-mcp-config", "--mcp-config", str(mcp),
               "--disable-slash-commands",  # no skills at all, bundled ones included
               "--tools", ",".join(AGENT_TOOLS),
               "--dangerously-skip-permissions"]
        if self.safe_mode:  # clean memory (D-15): no CLAUDE.md, skills, plugins, hooks, custom agents
            cmd.append("--safe-mode")
        cmd += ["--session-id", ctx.session_id] if ctx.first_turn else ["--resume", ctx.session_id]
        return cmd

    def path_dirs(self) -> list[str]:
        dirs = []
        for tool in (self.claude_bin, "node"):
            found = shutil.which(tool)
            if found and str(Path(found).parent) not in dirs:
                dirs.append(str(Path(found).parent))
        return dirs
