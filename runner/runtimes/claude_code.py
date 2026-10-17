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

    def build_command(self, ctx: TurnContext) -> list[str]:
        empty_mcp = ctx.art / "empty-mcp.json"
        empty_mcp.parent.mkdir(parents=True, exist_ok=True)
        if not empty_mcp.exists():
            empty_mcp.write_text(EMPTY_MCP)
        cmd = [self.claude_bin, "-p", ctx.prompt,
               "--output-format", "stream-json", "--verbose",
               "--model", self.model,
               "--settings", str(ctx.settings_path),
               "--setting-sources", "project,local",
               "--strict-mcp-config", "--mcp-config", str(empty_mcp),
               # clean memory (D-15): no CLAUDE.md, skills, installed plugins, hooks, custom agents
               # or workflows; the login, built-in tools and built-in plugins still work
               "--safe-mode",
               "--disable-slash-commands",  # no skills at all, bundled ones included
               "--tools", ",".join(AGENT_TOOLS),
               "--dangerously-skip-permissions"]
        cmd += ["--session-id", ctx.session_id] if ctx.first_turn else ["--resume", ctx.session_id]
        return cmd

    def path_dirs(self) -> list[str]:
        dirs = []
        for tool in (self.claude_bin, "node"):
            found = shutil.which(tool)
            if found and str(Path(found).parent) not in dirs:
                dirs.append(str(Path(found).parent))
        return dirs
