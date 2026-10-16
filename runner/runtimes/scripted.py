"""Scripted runtime: launches ``runner.runtimes.scripted_agent`` as a stand-in for ``claude -p``."""
from __future__ import annotations

import sys
from pathlib import Path

from runner.runtimes.base import TurnContext


class ScriptedRuntime:
    name = "scripted"
    needs_venv = False
    uses_real_agent = False

    def __init__(self, script: Path | str):
        self.script = Path(script)

    def build_command(self, ctx: TurnContext) -> list[str]:
        # The agent's "session transcript" lives in the state dir so snapshots capture it.
        return [sys.executable, "-m", "runner.runtimes.scripted_agent",
                "--script", str(self.script), "--workspace", str(ctx.workspace),
                "--otel", ctx.otel_endpoint, "--run-start", str(ctx.run_start_epoch),
                "--session-id", ctx.session_id, "--state", str(ctx.state_dir / "script-state.json")]

    def path_dirs(self) -> list[str]:
        return [str(Path(sys.executable).parent)]
