"""The real agent: the installed Claude Code CLI, headless (docs/spec.md §5.1 RUNNING)."""
from __future__ import annotations

import shutil
from pathlib import Path

from runner.runtimes.base import TurnContext

EMPTY_MCP = '{"mcpServers": {}}'


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
