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
