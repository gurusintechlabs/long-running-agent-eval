import pytest
import yaml

from runner.stages import StageError, StageScheduler, load_stages
from spec.loader import SpecError, load_spec


def write_plan(tmp_path, stages, **extra):
    for s in stages:
        if "prompt" in s:
            (tmp_path / s["prompt"]).write_text(f"brief {s['id']}\n")
    (tmp_path / "stages.yaml").write_text(yaml.safe_dump({"stages": stages, **extra}))
    return tmp_path / "stages.yaml"


PLAN = [{"id": 0, "prompt": "s0.md"}, {"id": 1, "prompt": "s1.md"},
        {"id": 2, "prompt": "s2.md", "kind": "change_request"}]


def test_load(tmp_path):
    plan = load_stages(write_plan(tmp_path, PLAN))
    assert [s.id for s in plan.stages] == [0, 1, 2]
    assert plan.stages[2].kind == "change_request" and plan.stages[1].text == "brief 1\n"


@pytest.mark.parametrize("bad", [
    [PLAN[0], {"id": 2, "prompt": "s1.md"}],                         # ids not sequential
    [PLAN[0], {"id": 1, "prompt": "s1.md", "kind": "surprise"}],     # unknown kind
    [PLAN[0], {"id": 1, "prompt": "s1.md", "at_frac": 0.3}],         # no clock: times are not a key
    [PLAN[0], {"id": 1}],                                            # no prompt
])
def test_invalid_plans(tmp_path, bad):
    with pytest.raises(StageError):
        load_stages(write_plan(tmp_path, bad))


def test_unknown_top_level_key(tmp_path):
    with pytest.raises(StageError):
        load_stages(write_plan(tmp_path, PLAN, max_wait_frac=0.1))


def test_missing_prompt_file(tmp_path):
    path = write_plan(tmp_path, PLAN)
    (tmp_path / "s2.md").unlink()
    with pytest.raises(StageError):
        load_stages(path)


def test_scheduler_hands_out_stages_in_order_then_none(tmp_path):
    sch = StageScheduler(load_stages(write_plan(tmp_path, PLAN)))
    assert sch.active() == 0
    s = sch.next()
    assert s.id == 1
    sch.mark_delivered(s)
    assert sch.next().id == 2 and sch.active() == 1
    sch.mark_delivered(sch.next())
    assert sch.next() is None and sch.active() == 2


def test_resume_keeps_delivered(tmp_path):
    sch = StageScheduler(load_stages(write_plan(tmp_path, PLAN)), delivered={0, 1})
    assert sch.next().id == 2


def _spec(tmp_path, stages_file, prompt="s0.md"):
    from tests.integration.conftest import git
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "main")
    (seed / "a.py").write_text("x = 1\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "seed")
    for name in ("constraints.yaml", "policy.yaml", "req.lock"):
        (tmp_path / name).write_text("{}\n" if name.endswith("yaml") else "")
    (tmp_path / "hidden").mkdir()
    spec = {"spec_version": 1, "experiment_id": "staged",
            "task": {"id": "t", "class": "L3", "prompt_file": prompt, "seed_repo": "seed",
                     "seed_commit": git(seed, "rev-parse", "HEAD"), "seed_requirements_lock": "req.lock",
                     "constraints_file": "constraints.yaml", "hidden_tests": "hidden",
                     "stages_file": stages_file},
            "agent": {"runtime": "scripted", "claude_code_version": "n/a", "script": "s0.md"},
            "run": {"duration_min": 1, "checkpoint_interval_min": 0.5, "repeats": 1, "configs": ["A"]},
            "budget": {"per_run_usd": 1, "experiment_usd": 1},
            "isolation": {"work_dir": str(tmp_path / "work")},
            "guardrails": {"policy_file": "policy.yaml"}, "scoring": {"judge_model": "claude-opus-5-5"}}
    (tmp_path / "spec.yaml").write_text(yaml.safe_dump(spec))
    return tmp_path / "spec.yaml"


def test_spec_hash_covers_stage_prompts(tmp_path):
    write_plan(tmp_path, PLAN)
    path = _spec(tmp_path, "stages.yaml")
    repo = tmp_path / "repo"
    repo.mkdir()
    h1 = load_spec(path, repo_root=repo).spec_hash
    (tmp_path / "s2.md").write_text("changed brief\n")
    assert load_spec(path, repo_root=repo).spec_hash != h1


def test_prompt_file_must_be_stage_zero(tmp_path):
    write_plan(tmp_path, PLAN)
    path = _spec(tmp_path, "stages.yaml", prompt="s1.md")
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(SpecError):
        load_spec(path, repo_root=repo)


# --- behaviour-track stage fields (D-18a, docs/behavior-design.md §5.1) ----------------------

def write_env_source(tmp_path, rel="env/ENV.v2.md", text="v2 docs\n"):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return rel


def rich_plan(tmp_path):
    src = write_env_source(tmp_path)
    return [
        {"id": 0, "prompt": "s0.md", "source": "product_owner", "surface": ["minidb/**"]},
        {"id": 1, "prompt": "s1.md", "kind": "directive", "source": "product_owner",
         "directives": [{"freeze": ["minidb/index/**"], "until_stage": 3}, {"stop": "the CSV exporter"}]},
        {"id": 2, "prompt": "s2.md", "env_actions": [
            {"action": "commit_file", "path": "ENVIRONMENT.md", "from": src, "author": "platform-bot",
             "message": "Update environment"}]},
        {"id": 3, "prompt": "s3.md", "kind": "inbound", "source": "ops"},
        {"id": 4, "prompt": "s4.md", "kind": "release", "status_block": "required"},
    ]


def test_rich_fields_load(tmp_path):
    plan = load_stages(write_plan(tmp_path, rich_plan(tmp_path)))
    s0, s1, s2, s3, s4 = plan.stages
    assert s0.source == "product_owner" and s0.surface == ("minidb/**",)
    assert s1.kind == "directive" and len(s1.directives) == 2
    assert s1.directives[0].freeze == ("minidb/index/**",) and s1.directives[0].until_stage == 3
    assert s1.directives[1].stop == "the CSV exporter" and s1.directives[1].until_stage is None
    assert s1.directives[0].id == "s1-d0" and s1.directives[1].id == "s1-d1"
    act = s2.env_actions[0]
    assert act.action == "commit_file" and act.params["path"] == "ENVIRONMENT.md"
    assert act.source_file == (tmp_path / "env/ENV.v2.md").resolve()
    assert s3.kind == "inbound" and s3.source == "ops"
    assert s4.kind == "release" and s4.status_block is True
    assert s0.status_block is False and s2.source is None and s2.directives == () and s3.env_actions == ()


def test_message_header_names_the_source_only_when_declared(tmp_path):
    plan = load_stages(write_plan(tmp_path, rich_plan(tmp_path)))
    assert plan.stages[0].message() == "From: product owner\n\nbrief 0\n"
    assert plan.stages[3].message() == "From: ops channel\n\nbrief 3\n"
    assert plan.stages[2].message() == "brief 2\n"  # no source: the text is sent unchanged (v2 tasks)
    assert plan.stages[0].message("assembled\n") == "From: product owner\n\nassembled\n"


def test_directive_lifecycle(tmp_path):
    plan = load_stages(write_plan(tmp_path, rich_plan(tmp_path)))
    assert [d.id for d in plan.directives_issued_at(1)] == ["s1-d0", "s1-d1"]
    assert [d.id for d in plan.directives_lifted_at(3)] == ["s1-d0"]
    assert plan.directives_lifted_at(4) == [] and plan.directives_issued_at(2) == []


@pytest.mark.parametrize("patch", [
    {"source": "ceo"},                                                          # unknown source
    {"directives": [{"freeze": ["a/**"], "stop": "x"}]},                        # both freeze and stop
    {"directives": [{"until_stage": 2}]},                                       # neither
    {"directives": [{"freeze": ["a/**"], "until_stage": 1}]},                   # lifted at its own stage
    {"directives": [{"freeze": ["a/**"], "until_stage": 9}]},                   # no such stage
    {"directives": [{"freeze": [], "until_stage": 2}]},                         # empty freeze
    {"surface": "minidb/**"},                                                   # not a list
    {"status_block": "maybe"},
    {"env_actions": [{"action": "launch_missiles"}]},                           # unknown action
    {"env_actions": [{"action": "counterpart_mode", "service": "embed", "mode": "v2"}]},  # mode must be a mapping
    {"env_actions": [{"action": "counterpart_mode", "service": "dns", "mode": {"api": "v2"}}]},
    {"env_actions": [{"action": "start_process", "name": "x", "fixture": "teleporter"}]},
    {"env_actions": [{"action": "start_process", "name": "Bad Name", "fixture": "lock_holder",
                      "params": {"path": "L"}}]},
    {"env_actions": [{"action": "stop_process"}]},
    {"env_actions": [{"action": "commit_file", "path": "E.md", "author": "bot"}]},         # no 'from'
    {"env_actions": [{"action": "commit_file", "path": "E.md", "from": "env/missing.md", "author": "bot"}]},
    {"env_actions": [{"action": "commit_file", "path": "../E.md", "from": "env/ENV.v2.md", "author": "bot"}]},
    {"env_actions": [{"action": "commit_file", "path": "/tmp/E.md", "from": "env/ENV.v2.md", "author": "bot"}]},
    {"env_actions": [{"action": "commit_file", "path": "E.md", "from": "env/ENV.v2.md", "author": "Bad Name!"}]},
    {"env_actions": [{"action": "commit_file", "path": "E.md", "from": "env/ENV.v2.md", "author": "bot",
                      "surprise": 1}]},
])
def test_invalid_rich_fields(tmp_path, patch):
    write_env_source(tmp_path)
    plan = [PLAN[0], {"id": 1, "prompt": "s1.md", **patch}, {"id": 2, "prompt": "s2.md"}]
    with pytest.raises(StageError):
        load_stages(write_plan(tmp_path, plan))


def test_spec_hash_covers_env_action_sources(tmp_path):
    write_plan(tmp_path, rich_plan(tmp_path))
    path = _spec(tmp_path, "stages.yaml")
    repo = tmp_path / "repo"
    repo.mkdir()
    h1 = load_spec(path, repo_root=repo).spec_hash
    (tmp_path / "env/ENV.v2.md").write_text("v2 docs, edited\n")
    assert load_spec(path, repo_root=repo).spec_hash != h1


def test_counterpart_and_process_actions_load(tmp_path):
    plan = [PLAN[0], {"id": 1, "prompt": "s1.md", "env_actions": [
        {"action": "counterpart_mode", "service": "embed", "mode": {"api": "v2", "flaky": 0.3}},
        {"action": "start_process", "name": "backup-daemon", "fixture": "lock_holder",
         "params": {"path": "data/prod/LOCK"}},
        {"action": "stop_process", "name": "backup-daemon"}]}, {"id": 2, "prompt": "s2.md"}]
    acts = load_stages(write_plan(tmp_path, plan)).stages[1].env_actions
    assert [a.action for a in acts] == ["counterpart_mode", "start_process", "stop_process"]
    assert acts[0].params == {"service": "embed", "mode": {"api": "v2", "flaky": 0.3}}
    assert acts[1].params["fixture"] == "lock_holder" and acts[1].source_file is None
