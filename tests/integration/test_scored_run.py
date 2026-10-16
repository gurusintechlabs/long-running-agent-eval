"""Phase 3 task 5: the asynchronous scorer queue inside a real (scripted) run, and its throughput."""
import json

import pytest

from runner.orchestrator import Run, RunState
from spec.loader import load_spec

from .pilot_support import CORE, make_pilot_spec, scorer_passes, scorer_venv  # noqa: F401

pytestmark = pytest.mark.local

DT_S, K = 20.0, 3


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
        assert p["done"]["duration_s"] < DT_S / 2, f"t{k} scoring took {p['done']['duration_s']}s"
    assert passes[3]["metrics"]["P"] == 1.0  # the reference solution is complete at t3
    assert passes[1]["metrics"]["P"] == 0.0
    # the route lands at t2 without its test (t3): endpoint-needs-test fires, once
    hazards = [h for p in passes.values() for h in p["hazards"]]
    assert [(h["dimension"], h["k"]) for h in hazards] == [("context", 2)]
    orch = [json.loads(x) for x in (res.paths.events / "orchestrator.jsonl").read_text().splitlines()]
    finished = [e["payload"] for e in orch if e["type"] == "scorer.finished"]
    assert [f["k"] for f in finished] == [1, 2, 3] and all(f["returncode"] == 0 for f in finished)
