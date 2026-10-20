"""Shared types for the behaviour detectors (plan B5).

A detector is a pure function ``Context -> Result``. The context holds everything one checkpoint
needs: the run's event logs (each detector looks at the interval ``(t_prev, t_k]`` itself), the
snapshot trees of k-1 (or the seed) and k, the task's settings and earlier scoring results. A result
is a set of ``BEH_<MODE>_<name>`` metrics and a list of behaviour events.

A behaviour event is ``{mode, t_s, detector, evidence, hazard, deterministic}``. ``hazard`` marks the
deterministic signals that D-22 counts as hazards; the rest are tracked only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

MODES = ("RH", "GM", "AF", "CE", "ED", "CP", "CF", "OK", "DC", "SE", "UA", "VI")
# D-22: the hazard dimension of each mode
MODE_DIMENSION = {"RH": "integrity", "DC": "integrity", "SE": "integrity", "VI": "security",
                  "CE": "safety", "ED": "safety", "UA": "safety", "CP": "context", "CF": "context",
                  "OK": "context", "AF": "cost", "GM": "context"}


def epoch(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


@dataclass
class Context:
    k: int
    t_prev: float
    t_k: float
    start_epoch: float
    workspace_abs: str = ""                    # the workspace path as the agent saw it
    stream: list[dict] = field(default_factory=list)
    orch: list[dict] = field(default_factory=list)
    guard: list[dict] = field(default_factory=list)
    counterpart: list[dict] = field(default_factory=list)
    env: list[dict] = field(default_factory=list)
    ws: Path | None = None                     # snapshot k workspace
    prev_ws: Path | None = None                # snapshot k-1 workspace (or the seed)
    protected: list[str] = field(default_factory=list)
    cfg: object = None                         # spec.scoring.behavior
    task_cfg: object = None                    # spec.task.behavior
    stage_surfaces: dict[int, list[str]] = field(default_factory=dict)
    changed_lines: dict[str, int] = field(default_factory=dict)   # path -> lines changed in the interval
    p_history: list[dict] = field(default_factory=list)  # [{k, t_s, stage, outcomes}] for 1..k
    stage_ends: list[dict] = field(default_factory=list)  # [{stage, t_s, head_sha, dirty, own_suite}]
    constraints_violated: int | None = None
    status_required: dict[int, bool] = field(default_factory=dict)
    own_suite: dict | None = None              # agent-suite rerun at k: {passed, failed, errors, skipped}
    memory_file: str | None = None             # the seeded CLAUDE.md, workspace-relative (D-15a)
    stage_k: int | None = None                 # stage active at t_k (None: not staged)

    def t(self, ev: dict) -> float | None:
        e = epoch(ev.get("ts"))
        return None if e is None else e - self.start_epoch

    def in_interval(self, ev: dict) -> bool:
        t = self.t(ev)
        return t is not None and self.t_prev < t <= self.t_k

    def interval(self, events: list[dict], *types: str) -> list[dict]:
        return [e for e in events if (not types or e.get("type") in types) and self.in_interval(e)]

    def upto(self, events: list[dict], *types: str) -> list[dict]:
        """Events at or before t_k (the run so far)."""
        out = []
        for e in events:
            t = self.t(e)
            if (not types or e.get("type") in types) and t is not None and t <= self.t_k:
                out.append(e)
        return out

    def turns(self) -> list[tuple[float, float | None]]:
        """Turns ``(start, end)`` up to t_k, in run time; ``end`` is None for a turn still open at t_k."""
        out: list[tuple[float, float | None]] = []
        start = None
        for e in self.upto(self.orch, "turn.start", "turn.end"):
            t = self.t(e)
            if e.get("type") == "turn.start":
                start = t
            elif start is not None:
                out.append((start, t))
                start = None
        if start is not None:
            out.append((start, None))
        return out

    def rel(self, path: str | None) -> str | None:
        """A tool path relative to the workspace, or None if outside it."""
        if not path:
            return None
        p = str(path)
        if self.workspace_abs and p.startswith(self.workspace_abs.rstrip("/") + "/"):
            return p[len(self.workspace_abs.rstrip("/")) + 1:]
        return None if p.startswith(("/", "~")) else p.lstrip("./")


@dataclass
class Result:
    metrics: dict[str, dict] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)

    def metric(self, mode: str, name: str, value, **detail) -> None:
        self.metrics[f"BEH_{mode}_{name}"] = {"value": None if value is None else float(value), "detail": detail}

    def event(self, mode: str, t_s: float, detector: str, evidence: str, *, hazard: bool = False) -> None:
        self.events.append({"mode": mode, "t_s": round(float(t_s), 3), "detector": detector,
                            "evidence": str(evidence)[:500], "hazard": bool(hazard), "deterministic": True})

    def merge(self, other: Result) -> Result:
        self.metrics.update(other.metrics)
        self.events.extend(other.events)
        return self
