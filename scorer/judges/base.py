"""Shared machinery of the behaviour judges (plan B5b, docs/behavior-design.md §8).

Every judge:
- is a template in ``scorer/judges/prompts/<name>.md`` whose first line names it
  (``<!-- lrae-judge: <name> v<N> -->``); the prompts are hashed into ``spec_hash`` when the judges
  are on;
- wraps everything the agent wrote as untrusted data (as X(t) does);
- asks for one strict JSON object, validated against the judge's schema, with one retry. A failure
  gives ``None`` (never zero);
- caches raw outputs by ``sha256(prompt + model)`` in ``runs/<id>/scorer/judge-cache/``, so
  re-scoring spends nothing;
- reports its spend as ``cost_usd``, which is never part of S(t).

The runner is the X judge's ``JudgeRunner`` (``(prompt, model) -> CLI stdout``):
``ClaudeJudgeRunner`` for real runs, or the deterministic ``FakeBehaviorJudge`` / ``RecordedJudge``
for tests and scripted runs.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from pathlib import Path

import yaml

from scorer.metrics.x_judge import JudgeOutputError, _clip, _untrusted

PROMPTS = Path(__file__).resolve().parent / "prompts"
BUNDLE = "{{BUNDLE}}"
_HEADER = re.compile(r"<!--\s*lrae-judge:\s*([a-z_]+)\s+v(\d+)\s*-->")
_FENCE = re.compile(r"^\s*```(?:json|JSON)?\s*\n(.*?)\n?\s*```\s*$", re.DOTALL)

__all__ = ["JudgeOutputError", "clip", "untrusted", "prompt_path", "judge_name", "build_prompt", "run_judge",
           "FakeBehaviorJudge", "RecordedJudge", "CLEAN"]

clip = _clip
untrusted = _untrusted


def prompt_path(name: str) -> Path:
    return PROMPTS / f"{name}.md"


def judge_name(prompt: str) -> str | None:
    m = _HEADER.search(prompt[:400])
    return m.group(1) if m else None


def build_prompt(name: str, bundle: str) -> str:
    return prompt_path(name).read_text(encoding="utf-8").replace(BUNDLE, bundle)


def parse_envelope(stdout: str) -> tuple[dict, float]:
    """``(inner JSON object, cost_usd)`` from ``claude -p --output-format json`` stdout."""
    try:
        env = json.loads(stdout)
    except (json.JSONDecodeError, TypeError) as e:
        raise JudgeOutputError(f"stdout is not JSON: {e}") from e
    if isinstance(env, list):
        env = next((m for m in reversed(env) if isinstance(m, dict) and m.get("type") == "result"), {})
    if not isinstance(env, dict):
        raise JudgeOutputError("stdout JSON is not an object")
    cost = env.get("total_cost_usd")
    cost = float(cost) if isinstance(cost, (int, float)) else 0.0
    try:
        if env.get("is_error"):
            raise JudgeOutputError(f"CLI reported an error: {str(env.get('result'))[:200]}")
        text = env.get("result")
        if not isinstance(text, str):
            raise JudgeOutputError("no string 'result' field")
        m = _FENCE.match(text)
        try:
            data = json.loads(m.group(1) if m else text)
        except json.JSONDecodeError as e:
            raise JudgeOutputError(f"result is not strict JSON: {e}") from e
        if not isinstance(data, dict):
            raise JudgeOutputError("result is not a JSON object")
        return data, cost
    except JudgeOutputError as e:
        e.cost_usd = cost  # type: ignore[attr-defined]
        raise


def run_judge(name: str, bundle: str, *, validate: Callable[[dict], dict], model: str, runner,
              cache_dir: Path) -> dict:
    """``{"name", "result": dict | None, "cached", "attempts", "cost_usd", "error"?}``."""
    prompt = build_prompt(name, bundle)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256((prompt + "\0" + model).encode()).hexdigest()
    path = cache_dir / f"{name}-{key}.json"
    rec: dict = {"name": name, "result": None, "cached": False, "attempts": 0, "cost_usd": 0.0}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))["raw_stdout"]
        rec.update(result=validate(parse_envelope(raw)[0]), cached=True)
        return rec
    except (OSError, ValueError, KeyError, TypeError, JudgeOutputError):
        pass
    error = ""
    for attempt in (1, 2):
        rec["attempts"] = attempt
        try:
            raw = runner(prompt, model)
            data, cost = parse_envelope(raw)
            rec["cost_usd"] += cost
            rec["result"] = validate(data)
        except JudgeOutputError as e:
            rec["cost_usd"] += getattr(e, "cost_usd", 0.0)
            error = str(e)
            continue
        except Exception as e:  # runner crashed or timed out
            error = f"{type(e).__name__}: {e}"
            continue
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"judge": name, "model": model, "raw_stdout": raw}, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
        return rec
    rec["error"] = error[:500]
    return rec


# --- deterministic runners -----------------------------------------------------------------------

CLEAN = {
    "goal_observer": {"inferred_goals": [], "fidelity": 1.0, "drift": [], "priority_inversions": []},
    "manipulation": {"tactics": []},
    "prose_claims": {"misstatements": []},
}


def _envelope(result: dict) -> str:
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": json.dumps(result),
                       "total_cost_usd": 0})


class FakeBehaviorJudge:
    """Deterministic runner for scripted runs: every behaviour judge answers "nothing found"."""

    def __call__(self, prompt: str, model: str) -> str:
        name = judge_name(prompt)
        if name not in CLEAN:
            raise JudgeOutputError(f"unknown judge prompt {name!r}")
        return _envelope(CLEAN[name])


class RecordedJudge(FakeBehaviorJudge):
    """Recorded judge answers for canaries (``scoring.behavior.judge_fixtures``): a YAML list of
    ``{judge, when_contains, result}``. The first entry for the judge whose ``when_contains`` occurs in
    the prompt answers; otherwise the clean answer."""

    def __init__(self, fixture: Path):
        self.rules = yaml.safe_load(Path(fixture).read_text()) or []

    def __call__(self, prompt: str, model: str) -> str:
        name = judge_name(prompt)
        for r in self.rules:
            if r["judge"] == name and r["when_contains"] in prompt:
                return _envelope(r["result"])
        return super().__call__(prompt, model)
