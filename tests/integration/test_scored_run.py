"""Phase 3 task 5: the asynchronous scorer queue inside a real (scripted) run, and its throughput."""
import json
import os

import pytest

from runner.orchestrator import Run, RunState
from spec.loader import load_spec

from .pilot_support import CORE, REPO, make_pilot_spec, scorer_passes, scorer_venv  # noqa: F401

pytestmark = pytest.mark.local

DT_S, K = 20.0, 3
# Scoring must keep up with the checkpoints: each one scored within dt/2 (the design margin). Under
# parallel test workers the machine is shared with other scripted runs, so only the hard limit
# applies there: within dt, i.e. the scorer queue never falls behind.
SCORE_LIMIT_S = DT_S if os.environ.get("PYTEST_XDIST_WORKER") else DT_S / 2


@pytest.mark.slow
def test_checkpoints_are_scored_during_the_run(tmp_path, scorer_venv):  # noqa: F811
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (tmp_path / "claude").mkdir()
    loaded = load_spec(make_pilot_spec(tmp_path, dt_s=DT_S, k=K), repo_root=repo_root)
    run = Run(loaded, "A", 0, repo_root=repo_root, claude_home=tmp_path / "claude",
              host_home=tmp_path / "home", caffeinate=False, score=True)
    res = run.execute()
    assert res.state == RunState.COMPLETED, res.error
    passes = scorer_passes(res.paths.art)
    assert sorted(passes) == list(range(1, K + 1))
    for k, p in passes.items():
        assert set(CORE) <= set(p["metrics"]), k
        assert all(p["metrics"][m] is not None for m in CORE), (k, p["metrics"])
        assert p["done"]["duration_s"] < SCORE_LIMIT_S, f"t{k} scoring took {p['done']['duration_s']}s"
    assert passes[3]["metrics"]["P"] == 1.0  # the reference solution is complete at t3
    assert passes[1]["metrics"]["P"] == 0.0
    # the route lands at t2 without its test (t3): endpoint-needs-test fires, once
    hazards = [h for p in passes.values() for h in p["hazards"]]
    assert [(h["dimension"], h["k"]) for h in hazards] == [("context", 2)]
    orch = [json.loads(x) for x in (res.paths.events / "orchestrator.jsonl").read_text().splitlines()]
    finished = [e["payload"] for e in orch if e["type"] == "scorer.finished"]
    assert [f["k"] for f in finished] == [1, 2, 3] and all(f["returncode"] == 0 for f in finished)


def test_killed_canary_has_a_safety_hazard(tmp_path, scorer_venv):  # noqa: F811
    """The kill snapshot is scored and the violation that caused it is a safety hazard. (Once
    missed: violation times used the PREPARING-time manifest origin, checkpoints the run.clock one.)"""
    import yaml
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (tmp_path / "claude").mkdir()
    spec_path = make_pilot_spec(tmp_path, dt_s=DT_S, k=K)
    spec = yaml.safe_load(spec_path.read_text())
    spec["agent"]["script"] = str(REPO / "fixtures" / "scripted" / "canary_forbidden.yaml")
    spec_path.write_text(yaml.safe_dump(spec))
    run = Run(load_spec(spec_path, repo_root=repo_root), "A", 0, repo_root=repo_root,
              claude_home=tmp_path / "claude", host_home=tmp_path / "home", caffeinate=False, score=True)
    res = run.execute()
    assert res.state == RunState.KILLED
    passes = scorer_passes(res.paths.art)
    hz = [h for p in passes.values() for h in p["hazards"]]
    assert [(h["dimension"], h["rule"]) for h in hz] == [("safety", "rm-rf-root")]
    assert hz[0]["t_attributed_s"] <= hz[0]["t_detected_s"]
