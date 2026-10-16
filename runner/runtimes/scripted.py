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

    def render(self, art: Path) -> Path:
        """Canary scripts name harness paths with ``@@REPO@@``; the copy the agent replays has the real
        repo root (``runs/<id>/`` lives in the repo). Scripts without placeholders are used as is."""
        try:
            text = self.script.read_text()
        except OSError:  # the scripted agent reports a missing script itself
            return self.script
        if "@@REPO@@" not in text:
            return self.script
        out = Path(art) / "script.rendered.yaml"
        out.write_text(text.replace("@@REPO@@", str(Path(art).resolve().parent.parent)))
        return out

    def build_command(self, ctx: TurnContext) -> list[str]:
        # The agent's "session transcript" lives in the state dir so snapshots capture it.
        return [sys.executable, "-m", "runner.runtimes.scripted_agent",
                "--script", str(self.render(ctx.art)), "--workspace", str(ctx.workspace),
                "--otel", ctx.otel_endpoint, "--run-start", str(ctx.run_start_epoch),
                "--session-id", ctx.session_id, "--state", str(ctx.state_dir / "script-state.json")]

    def path_dirs(self) -> list[str]:
        return [str(Path(sys.executable).parent)]
