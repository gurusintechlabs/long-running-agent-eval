"""Pydantic models for the experiment spec (docs/spec.md §4.1)."""
from __future__ import annotations

import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MODEL_ID_RE = re.compile(r"^claude-[a-z0-9][a-z0-9.\-]*$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CONFIG_NAMES = ("A", "B", "C", "D", "E")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_model_id(v: str) -> str:
    if not MODEL_ID_RE.match(v):
        raise ValueError(f"model must be a full model ID (e.g. claude-opus-5-5), got {v!r}")
    return v


class Task(Strict):
    id: str
    task_class: str = Field(alias="class")
    prompt_file: str
    seed_repo: str
    seed_commit: str
    seed_requirements_lock: str
    constraints_file: str
    hidden_tests: str
    # Optional staged brief (docs/interfaces.md §9, proposed D-18). Stage 0's prompt must be prompt_file.
    stages_file: str | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("seed_commit")
    @classmethod
    def _sha(cls, v: str) -> str:
        if not SHA_RE.match(v):
            raise ValueError("seed_commit must be a full 40-char lowercase hex SHA")
        return v


class Agent(Strict):
    runtime: Literal["claude_code", "scripted"]
    claude_bin: str = "claude"
    claude_code_version: str
    model: str | None = None
    auto_memory: Literal["cli_default", "off"] = "cli_default"
    script: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Agent:
        if self.runtime == "scripted":
            if not self.script:
                raise ValueError("runtime 'scripted' requires agent.script")
        else:
            if self.script:
                raise ValueError("agent.script is only allowed with runtime 'scripted'")
            if self.model is None:
                raise ValueError("agent.model is required for runtime 'claude_code'")
        if self.model is not None:
            _check_model_id(self.model)
        return self


class Run(Strict):
    duration_min: float = Field(gt=0)
    checkpoint_interval_min: float = Field(gt=0)
    repeats: int = Field(ge=1)
    configs: list[str] = Field(min_length=1)
    seed: int = 0
    parallelism: int = Field(default=1, ge=1)

    @field_validator("configs")
    @classmethod
    def _configs(cls, v: list[str]) -> list[str]:
        bad = [c for c in v if c not in CONFIG_NAMES]
        if bad:
            raise ValueError(f"unknown configs {bad}; expected a subset of {CONFIG_NAMES}")
        return v

    @model_validator(mode="after")
    def _divides(self) -> Run:
        ratio = self.duration_min / self.checkpoint_interval_min
        if not math.isclose(ratio, round(ratio), abs_tol=1e-9) or round(ratio) < 1:
            raise ValueError("checkpoint_interval_min must divide duration_min")
        return self

    @property
    def checkpoint_count(self) -> int:
        return round(self.duration_min / self.checkpoint_interval_min)


class Budget(Strict):
    per_run_usd: float = Field(gt=0)
    per_run_tokens: int | None = Field(default=None, gt=0)
    experiment_usd: float = Field(gt=0)


class Isolation(Strict):
    mode: Literal["local", "docker"] = "local"
    work_dir: str = "~/lrae-work"
    keep_work_dir: bool = False


class Telemetry(Strict):
    protocol: Literal["http/json", "http/protobuf"] = "http/json"
    export_interval_ms: int = Field(default=1000, ge=100)


class Guardrails(Strict):
    policy_file: str


class Thresholds(Strict):
    repeat_work_ratio: float = 0.30
    cost_per_commit_multiplier: float = 2.0
    cost_baseline_checkpoints: int = 2


class Scoring(Strict):
    judge_model: str
    judge_samples: int = Field(default=3, ge=1)
    # claude_code = the installed CLI (spec §8.3.6); scripted = deterministic fake for tests and
    # scripted pilots (no spend).
    judge_runtime: Literal["claude_code", "scripted"] = "claude_code"
    # Wall-clock budget for scoring each commit of an interval (docs/interfaces.md §8); above it, sample.
    max_commit_scoring_s: float = Field(default=600.0, gt=0)
    thresholds: Thresholds = Thresholds()

    @field_validator("judge_model")
    @classmethod
    def _model(cls, v: str) -> str:
        return _check_model_id(v)


class Spec(Strict):
    spec_version: Literal[1]
    experiment_id: str
    task: Task
    agent: Agent
    run: Run
    budget: Budget
    isolation: Isolation = Isolation()
    telemetry: Telemetry = Telemetry()
    guardrails: Guardrails
    scoring: Scoring

    @field_validator("experiment_id")
    @classmethod
    def _eid(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", v):
            raise ValueError("experiment_id must match [a-z0-9]+(-[a-z0-9]+)*")
        return v


# --- harness configs (spec §4.3) -------------------------------------------------------------

class Gate(Strict):
    enabled: bool = False
    every_min: float | None = None  # None = every checkpoint


class Reset(Strict):
    enabled: bool = False
    at_fill: float = 0.70
    every_min: float | None = None


class IntervalCap(Strict):
    enabled: bool = False
    interval_usd: float | None = None


class HarnessConfig(Strict):
    name: Literal["A", "B", "C", "D", "E"]
    description: str
    continuation_prompt: str = "Continue working on the task."
    gate: Gate = Gate()
    reset: Reset = Reset()
    interval_cap: IntervalCap = IntervalCap()
