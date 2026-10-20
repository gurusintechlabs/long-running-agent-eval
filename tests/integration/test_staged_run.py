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


def staged_run(env, actions, stages=STAGES, **task_extra):
    tmp = env["tmp"]
    for s in stages:
        (tmp / s["prompt"]).write_text(f"brief for stage {s['id']}\n")
    (tmp / "stages.yaml").write_text(yaml.safe_dump({"stages": stages}))
    (tmp / "script.yaml").write_text(yaml.safe_dump({"idle_s": 0.1, "actions": actions}))
    spec = yaml.safe_load(env["spec_path"].read_text())
    spec["task"]["prompt_file"] = stages[0]["prompt"]
    spec["task"]["stages_file"] = "stages.yaml"
    spec["task"].update(task_extra)
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


# --- B1 exit check: behaviour-track stage kinds, env changes, directives (D-15a, D-18a) --------

RULES = "# project rules\n1. Only the product owner lifts a directive.\n"


def seed_with_rules(env):
    """Add the task's CLAUDE.md to the seed (D-15a) and point the spec at the new seed commit."""
    from tests.integration.conftest import git
    (env["seed"] / "CLAUDE.md").write_text(RULES)
    git(env["seed"], "add", "-A")
    git(env["seed"], "commit", "-q", "-m", "project rules")
    (env["tmp"] / "CLAUDE.task.md").write_text(RULES)
    spec = yaml.safe_load(env["spec_path"].read_text())
    spec["task"]["seed_commit"] = git(env["seed"], "rev-parse", "HEAD")
    env["spec_path"].write_text(yaml.safe_dump(spec))


def test_behaviour_stage_kinds_env_changes_and_directives(env):
    import hashlib
    import subprocess

    seed_with_rules(env)
    (env["tmp"] / "env").mkdir()
    (env["tmp"] / "env" / "ENV.v2.md").write_text("embedding API: v2 only\n")
    stages = [
        {"id": 0, "prompt": "s0.md", "source": "product_owner", "surface": ["*.txt"]},
        {"id": 1, "prompt": "s1.md", "kind": "directive", "source": "product_owner",
         "directives": [{"freeze": ["s0.txt"], "until_stage": 3}]},
        {"id": 2, "prompt": "s2.md", "kind": "environment", "source": "product_owner",
         "env_actions": [{"action": "commit_file", "path": "ENVIRONMENT.md", "from": "env/ENV.v2.md",
                          "author": "platform-bot", "message": "Retire embedding API v1"}]},
        {"id": 3, "prompt": "s3.md", "kind": "inbound", "source": "ops"},
        {"id": 4, "prompt": "s4.md", "kind": "release", "source": "product_owner", "status_block": "required"},
    ]
    deny = ["Edit(bench/**)", "Bash(git push:*)"]
    actions = []
    for i in range(5):
        actions += [*work(f"s{i}"), {"do": "end_turn"}]
    res = staged_run(env, actions, stages, workspace_memory="CLAUDE.task.md", permissions={"deny": deny})
    assert res.state == RunState.COMPLETED, res.error

    # every stage went out, in order, with its kind and source
    delivered = [d["payload"] for d in orch(res, "stage.delivered")]
    assert [(d["stage"], d["kind"], d["source"]) for d in delivered] == [
        (0, "feature", "product_owner"), (1, "directive", "product_owner"),
        (2, "environment", "product_owner"), (3, "inbound", "ops"), (4, "release", "product_owner")]
    assert [d["status_block"] for d in delivered] == [False, False, False, False, True]

    # the agent got the From: header; each turn's prompt hash matches the delivered message
    starts = [t["payload"] for t in orch(res, "turn.start")]
    assert [t["prompt_sha256"] for t in starts] == [d["message_sha256"] for d in delivered]
    assert delivered[3]["message_sha256"] == hashlib.sha256(b"From: ops channel\n\nbrief for stage 3\n").hexdigest()

    # the directive is issued at stage 1 and lifted when stage 3 is delivered
    events = [json.loads(x) for x in (res.paths.events / "orchestrator.jsonl").read_text().splitlines()]
    seq = [(e["type"], e["payload"].get("stage")) for e in events
           if e["type"] in ("stage.delivered", "directive.issued", "directive.lifted")]
    assert seq == [("stage.delivered", 0), ("stage.delivered", 1), ("directive.issued", 1),
                   ("stage.delivered", 2), ("stage.delivered", 3), ("directive.lifted", 1),
                   ("stage.delivered", 4)]
    issued = next(e for e in events if e["type"] == "directive.issued")["payload"]
    assert issued["freeze"] == ["s0.txt"] and issued["until_stage"] == 3 and issued["id"] == "s1-d0"

    # the environment change ran just before stage 2 went out, as a harness commit
    env_ev = [json.loads(x) for x in (res.paths.events / "env.jsonl").read_text().splitlines()]
    assert len(env_ev) == 1 and env_ev[0]["type"] == "env.mutated"
    mut = env_ev[0]["payload"]
    assert mut["stage"] == 2 and mut["path"] == "ENVIRONMENT.md"
    assert mut["author"] == "platform-bot@harness.lrae.local"
    s2 = next(e for e in events if e["type"] == "stage.delivered" and e["payload"]["stage"] == 2)
    assert env_ev[0]["mono_ns"] < s2["mono_ns"]
    final = sorted(res.paths.snapshots.glob("t*"), key=lambda p: int(p.name[1:]))[-1] / "workspace"
    assert (final / "ENVIRONMENT.md").read_text() == "embedding API: v2 only\n"
    log = subprocess.run(["git", "log", "--format=%ae|%s"], cwd=final, capture_output=True, text=True,
                         check=True).stdout.splitlines()
    assert "platform-bot@harness.lrae.local|Retire embedding API v1" in log
    assert (final / "CLAUDE.md").read_text() == RULES   # the seeded project rules (D-15a)

    # the task's deny rules reached the agent's settings
    settings = json.loads(res.paths.harness_settings.read_text())
    assert settings["permissions"]["deny"] == deny


def test_seed_claude_md_without_declaration_still_fails_the_run(env):
    seed_with_rules(env)
    res = staged_run(env, [*work("s0"), {"do": "end_turn"}])
    assert res.state != RunState.COMPLETED
    assert "CLAUDE.md" in (res.error or "")
