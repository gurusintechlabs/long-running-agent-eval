"""Scripted pilot on the real seed, task, hidden tests and scorer (no spend), for Phases 3-4."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
CORE = ("P", "R", "D", "C", "W", "X", "S")


def make_pilot_spec(tmp: Path, *, dt_s: float, k: int, repeats: int = 1) -> Path:
    """The scripted pilot spec with absolute paths, a temp work dir and a script for this dt."""
    spec = yaml.safe_load((REPO / "spec" / "examples" / "pilot-scripted.yaml").read_text())
    base = REPO / "spec" / "examples"
    for key in ("prompt_file", "seed_repo", "seed_requirements_lock", "constraints_file", "hidden_tests"):
        spec["task"][key] = str((base / spec["task"][key]).resolve())
    spec["guardrails"]["policy_file"] = str((base / spec["guardrails"]["policy_file"]).resolve())
    script = tmp / "pilot_agent.yaml"
    out = subprocess.run([sys.executable, str(REPO / "fixtures" / "scripted" / "build_pilot_script.py"),
                          str(dt_s), str(k)], capture_output=True, text=True, check=True).stdout
    script.write_text(out)
    spec["agent"]["script"] = str(script)
    spec["run"].update(duration_min=dt_s * k / 60, checkpoint_interval_min=dt_s / 60, repeats=repeats)
    spec["isolation"]["work_dir"] = str(tmp / "home" / "lrae-work")
    path = tmp / "pilot.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False))
    return path


@pytest.fixture(scope="session")
def scorer_venv():
    from scorer.venv import install_scorer
    return install_scorer(REPO, REPO / "fixtures" / "seed_export_service" / "requirements.lock")


def scorer_passes(art: Path) -> dict[int, dict]:
    """Last ok scoring pass per checkpoint: {k: {"metrics": {name: value}, "hazards": [...], "done": {...}}}."""
    events = [json.loads(x) for x in (art / "events" / "scorer.jsonl").read_text().splitlines()]
    by_pass: dict[str, dict] = {}
    for e in events:
        p = e["payload"]
        cur = by_pass.setdefault(p.get("pass_id"), {"metrics": {}, "hazards": [], "done": None})
        if e["type"] == "scorer.metric":
            cur["metrics"][p["name"]] = p["value"]
        elif e["type"] == "scorer.hazard":
            cur["hazards"].append(p)
        elif e["type"] == "scorer.done":
            cur["done"] = p
    out = {}
    for cur in by_pass.values():
        if cur["done"] and cur["done"].get("ok"):
            out[cur["done"]["k"]] = cur
    return out
