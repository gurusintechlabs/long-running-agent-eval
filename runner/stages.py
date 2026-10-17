"""Staged task briefs (docs/interfaces.md §9, decision D-18).

A staged task gives the agent its brief in parts: stage 0 at the start, then each next stage as soon
as the agent finishes the current one, i.e. as soon as its ``claude -p`` turn ends successfully.
Later stages add features or overturn earlier behaviour (change requests), so the agent has to
revise its own work deep into a long session. There is no clock: nothing waits, and the run ends
when the agent finishes the last stage (or at ``run.duration_min``, whichever comes first).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml


class StageError(ValueError):
    pass


@dataclass(frozen=True)
class Stage:
    id: int
    prompt: Path
    kind: str = "feature"

    @property
    def text(self) -> str:
        return self.prompt.read_text()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.prompt.read_bytes()).hexdigest()


@dataclass(frozen=True)
class StagePlan:
    stages: list[Stage]


def load_stages(path: Path | str) -> StagePlan:
    path = Path(path)
    try:
        doc = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise StageError(f"cannot read {path}: {exc}") from exc
    unknown = set(doc) - {"stages"}
    if unknown:
        raise StageError(f"unknown keys {sorted(unknown)}")
    stages = []
    for i, s in enumerate(doc.get("stages") or []):
        if not isinstance(s, dict) or "prompt" not in s or set(s) - {"id", "prompt", "kind"}:
            raise StageError(f"stage {i}: expected {{id, prompt[, kind]}}, got {s!r}")
        prompt = (path.parent / s["prompt"]).resolve()
        if not prompt.is_file():
            raise StageError(f"stage {i}: prompt file not found: {prompt}")
        stages.append(Stage(int(s["id"]), prompt, s.get("kind", "feature")))
    if not stages:
        raise StageError("no stages")
    if [s.id for s in stages] != list(range(len(stages))):
        raise StageError("stage ids must be 0, 1, 2, ... in order")
    if any(s.kind not in ("feature", "change_request") for s in stages):
        raise StageError("kind must be feature or change_request")
    return StagePlan(stages)


class StageScheduler:
    """Hands out the stages in order. Delivered stages are remembered (and restored on resume)."""

    def __init__(self, plan: StagePlan, delivered: set[int] | None = None):
        self.plan = plan
        self.delivered: set[int] = set(delivered or {0})

    def next(self) -> Stage | None:
        """The next undelivered stage, or None when every stage has been delivered."""
        return next((s for s in self.plan.stages if s.id not in self.delivered), None)

    def mark_delivered(self, stage: Stage) -> None:
        self.delivered.add(stage.id)

    def active(self) -> int:
        return max(self.delivered)
