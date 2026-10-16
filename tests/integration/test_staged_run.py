"""Staged briefs on the real harness (docs/interfaces.md §9, proposed D-18)."""
import json

import pytest
import yaml

from runner.orchestrator import Run, RunState
from spec.loader import load_spec

pytestmark = pytest.mark.local


def staged_env(env, actions, stages, max_wait_frac=0.1):
    tmp = env["tmp"]
    for s in stages:
        (tmp / s["prompt"]).write_text(f"brief for stage {s['id']}\n")
    (tmp / "stages.yaml").write_text(yaml.safe_dump({"stages": stages, "max_wait_frac": max_wait_frac}))
    (tmp / "script.yaml").write_text(yaml.safe_dump({"idle_s": 0.1, "actions": actions}))
    spec = yaml.safe_load(env["spec_path"].read_text())
    spec["task"]["prompt_file"] = stages[0]["prompt"]
    spec["task"]["stages_file"] = "stages.yaml"
    env["spec_path"].write_text(yaml.safe_dump(spec))
    loaded = load_spec(env["spec_path"], repo_root=env["repo_root"])
    run = Run(loaded, "A", 0, repo_root=env["repo_root"], claude_home=env["claude_home"],
              host_home=env["home"], caffeinate=False)
    return run, run.execute()


def orch(res, type_):
    ev = [json.loads(x) for x in (res.paths.events / "orchestrator.jsonl").read_text().splitlines()]
    return [e["payload"] for e in ev if e["type"] == type_]


STAGES = [{"id": 0, "prompt": "s0.md", "at_frac": 0.0}, {"id": 1, "prompt": "s1.md", "at_frac": 0.3},
          {"id": 2, "prompt": "s2.md", "at_frac": 0.6, "kind": "change_request"}]


def test_stages_delivered_at_turn_boundaries(env):
    # short turns (the scripted agent idles 0.1 s per turn): each stage goes out right on time
    _, res = staged_env(env, [], STAGES)
    assert res.state == RunState.COMPLETED, res.error
    got = orch(res, "stage.delivered")
    assert [g["stage"] for g in got] == [0, 1, 2]
    duration = 6.0
    for g, s in zip(got[1:], STAGES[1:], strict=True):
        assert s["at_frac"] * duration <= g["t_s"] < (s["at_frac"] + 0.1) * duration, g
        assert g["interrupted"] is False
    assert got[2]["kind"] == "change_request" and len(got[2]["prompt_sha256"]) == 64
    assert orch(res, "turn.interrupted") == []


def test_long_turn_is_interrupted_to_deliver_a_stage(env):
    # one turn that would sleep past the whole run: the stage-1 grace window forces an interruption
    _, res = staged_env(env, [{"do": "sleep", "seconds": 60}], STAGES[:2], max_wait_frac=0.1)
    assert res.state == RunState.COMPLETED, res.error  # an interruption is not a failing turn
    got = orch(res, "stage.delivered")
    assert [g["stage"] for g in got] == [0, 1] and got[1]["interrupted"] is True
    intr = orch(res, "turn.interrupted")
    assert len(intr) == 1 and intr[0]["stage"] == 1
    assert 0.4 * 6.0 <= intr[0]["t_s"] < 0.4 * 6.0 + 1.0  # at at_frac + max_wait_frac
