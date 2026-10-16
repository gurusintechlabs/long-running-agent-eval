"""Staged task briefs (docs/interfaces.md §9, proposed decision D-18).

A staged task delivers its brief in parts during the run instead of all at t=0, so the agent has
to revise earlier work (new features, change requests) while the run is long. Stage 0 is the t=0
prompt; stage s is delivered at the first turn boundary at or after ``at_frac × duration``, or by
interrupting a turn that is still running at ``(at_frac + max_wait_frac) × duration``.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml


class StageError(ValueError):
    pass


@dataclass(frozen=True)
class Stage:
    id: int
    prompt: Path
    at_frac: float
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
    max_wait_frac: float


def load_stages(path: Path | str) -> StagePlan:
    path = Path(path)
    try:
        doc = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise StageError(f"cannot read {path}: {exc}") from exc
    raw = doc.get("stages") or []
    unknown = set(doc) - {"stages", "max_wait_frac"}
    if unknown:
        raise StageError(f"unknown keys {sorted(unknown)}")
    stages = []
    for i, s in enumerate(raw):
        if not isinstance(s, dict) or set(s) - {"id", "prompt", "at_frac", "kind"}:
            raise StageError(f"stage {i}: expected {{id, prompt, at_frac[, kind]}}, got {s!r}")
        prompt = (path.parent / s["prompt"]).resolve()
        if not prompt.is_file():
            raise StageError(f"stage {i}: prompt file not found: {prompt}")
        stages.append(Stage(int(s["id"]), prompt, float(s["at_frac"]), s.get("kind", "feature")))
    if not stages:
        raise StageError("no stages")
    if [s.id for s in stages] != list(range(len(stages))):
        raise StageError("stage ids must be 0, 1, 2, ... in order")
    if stages[0].at_frac != 0.0:
        raise StageError("stage 0 must have at_frac 0")
    fracs = [s.at_frac for s in stages]
    if fracs != sorted(fracs) or len(set(fracs)) != len(fracs) or fracs[-1] >= 1.0:
        raise StageError("at_frac must increase strictly and stay below 1")
    if any(s.kind not in ("feature", "change_request") for s in stages):
        raise StageError("kind must be feature or change_request")
    wait = float(doc.get("max_wait_frac", 0.05))
    if not 0 < wait < 1:
        raise StageError("max_wait_frac must be in (0, 1)")
    return StagePlan(stages, wait)


class StageScheduler:
    """Which stage is due, given run time. Delivered stages are remembered (and restored on resume)."""

    def __init__(self, plan: StagePlan, duration_s: float, elapsed: Callable[[], float],
                 delivered: set[int] | None = None):
        self.plan = plan
        self.duration_s = duration_s
        self.elapsed = elapsed
        self.delivered: set[int] = set(delivered or {0})

    def due(self) -> Stage | None:
        """The earliest undelivered stage whose time has come (one per turn, in order)."""
        now = self.elapsed()
        for s in self.plan.stages:
            if s.id not in self.delivered:
                return s if s.at_frac * self.duration_s <= now else None
        return None

    def overdue(self) -> bool:
        """A due stage has waited past its grace window: the running turn should be interrupted."""
        s = self.due()
        return s is not None and self.elapsed() >= (s.at_frac + self.plan.max_wait_frac) * self.duration_s

    def mark_delivered(self, stage: Stage) -> None:
        self.delivered.add(stage.id)

    def active(self) -> int:
        return max(self.delivered)
