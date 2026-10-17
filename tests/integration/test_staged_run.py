"""One turn per piece of work, next stage on done (docs/interfaces.md §9, D-4, D-18).

The scripted agent ends a turn with ``end_turn`` the way the real agent ends one when it considers
its work finished. Nothing waits for a clock and nobody is told to "keep working".
"""
import json

import pytest
import yaml

from runner.orchestrator import Run, RunState
from spec.loader import load_spec

pytestmark = pytest.mark.local

STAGES = [{"id": 0, "prompt": "s0.md"}, {"id": 1, "prompt": "s1.md"},
          {"id": 2, "prompt": "s2.md", "kind": "change_request"}]


def staged_run(env, actions, stages=STAGES):
    tmp = env["tmp"]
    for s in stages:
        (tmp / s["prompt"]).write_text(f"brief for stage {s['id']}\n")
    (tmp / "stages.yaml").write_text(yaml.safe_dump({"stages": stages}))
    (tmp / "script.yaml").write_text(yaml.safe_dump({"idle_s": 0.1, "actions": actions}))
    spec = yaml.safe_load(env["spec_path"].read_text())
    spec["task"]["prompt_file"] = stages[0]["prompt"]
    spec["task"]["stages_file"] = "stages.yaml"
    env["spec_path"].write_text(yaml.safe_dump(spec))
    run = Run(load_spec(env["spec_path"], repo_root=env["repo_root"]), "A", 0, repo_root=env["repo_root"],
              claude_home=env["claude_home"], host_home=env["home"], caffeinate=False)
    return run.execute()


def orch(res, type_):
    ev = [json.loads(x) for x in (res.paths.events / "orchestrator.jsonl").read_text().splitlines()]
    return [e for e in ev if e["type"] == type_]


def work(name):
    return [{"do": "write_file", "path": f"{name}.txt", "content": name},
            {"do": "git_commit", "message": name}]


def test_next_stage_follows_each_finished_turn_and_the_run_ends_when_done(env):
    res = staged_run(env, [*work("s0"), {"do": "end_turn"}, *work("s1"), {"do": "end_turn"},
                           *work("s2"), {"do": "end_turn"}])
    assert res.state == RunState.COMPLETED, res.error
    delivered = orch(res, "stage.delivered")
    assert [d["payload"]["stage"] for d in delivered] == [0, 1, 2]
    ends = orch(res, "turn.end")
    assert len(ends) == 3 and all(e["payload"]["returncode"] == 0 for e in ends)
    # each stage goes out right after the previous turn ended: no waiting
    for prev_end, nxt in zip(ends, delivered[1:], strict=False):
        assert 0 <= (nxt["mono_ns"] - prev_end["mono_ns"]) / 1e9 < 1.0
    done = orch(res, "run.done")
    assert len(done) == 1 and done[0]["payload"]["stages"] == [0, 1, 2]
    assert done[0]["payload"]["t_s"] < 6.0  # finished well before the 6 s deadline
    manifest = json.loads(res.paths.manifest.read_text())
    assert manifest["end"]["end_reason"] == "task_done"
    final = json.loads(sorted(res.paths.snapshots.glob("t*/meta.json"))[-1].read_text())
    assert final["final"] == "complete"
    assert (res.paths.snapshots / f"t{final['k']}" / "workspace" / "s2.txt").exists()


def test_unstaged_task_ends_after_its_one_finished_turn(env):
    (env["tmp"] / "script.yaml").write_text(yaml.safe_dump({"actions": [*work("only"), {"do": "end_turn"}]}))
    run = Run(load_spec(env["spec_path"], repo_root=env["repo_root"]), "A", 0, repo_root=env["repo_root"],
              claude_home=env["claude_home"], host_home=env["home"], caffeinate=False)
    res = run.execute()
    assert res.state == RunState.COMPLETED, res.error
    assert len(orch(res, "turn.end")) == 1 and len(orch(res, "run.done")) == 1


def test_deadline_still_ends_a_run_that_is_not_done(env):
    res = staged_run(env, [*work("s0"), {"do": "sleep", "seconds": 60}])
    assert res.state == RunState.COMPLETED, res.error
    assert [d["payload"]["stage"] for d in orch(res, "stage.delivered")] == [0]
    assert orch(res, "run.done") == []
    assert json.loads(res.paths.manifest.read_text())["end"]["end_reason"] == "deadline"


def test_a_failed_turn_is_resumed_with_the_recovery_prompt_not_the_next_stage(env):
    res = staged_run(env, [*work("s0a"), {"do": "fail_turn"}, *work("s0b"), {"do": "end_turn"},
                           *work("s1"), {"do": "end_turn"}, *work("s2"), {"do": "end_turn"}])
    assert res.state == RunState.COMPLETED, res.error
    ends = [e["payload"]["returncode"] for e in orch(res, "turn.end")]
    assert ends == [1, 0, 0, 0]
    delivered = orch(res, "stage.delivered")
    starts = orch(res, "turn.start")
    # stage 1 goes out only after the turn that finished stage 0, i.e. at the third turn start
    assert [d["payload"]["stage"] for d in delivered] == [0, 1, 2]
    assert delivered[1]["seq"] > starts[1]["seq"]
