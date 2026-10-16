from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class TurnContext:
    prompt: str
    session_id: str
    first_turn: bool
    workspace: Path
    art: Path
    settings_path: Path
    otel_endpoint: str
    run_start_epoch: float
    state_dir: Path


class Runtime(Protocol):
    name: str
    needs_venv: bool
    uses_real_agent: bool

    def build_command(self, ctx: TurnContext) -> list[str]: ...

    def path_dirs(self) -> list[str]: ...
