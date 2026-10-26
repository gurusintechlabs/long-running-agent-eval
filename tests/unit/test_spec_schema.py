from pathlib import Path

import pytest
import yaml

from spec.loader import SpecError, load_spec

SHA = "a" * 40


def write_spec(tmp_path: Path, **overrides) -> Path:
    """Write a minimal valid spec plus the files it references; return the spec path."""
    (tmp_path / "prompt.md").write_text("Do the task.\n")
    (tmp_path / "constraints.yaml").write_text("constraints: []\n")
    (tmp_path / "policy.yaml").write_text("forbidden_commands: []\n")
    (tmp_path / "req.lock").write_text("fastapi==0.1\n")
    (tmp_path / "hidden").mkdir(exist_ok=True)
    (tmp_path / "hidden" / "test_a.py").write_text("def test_a(): pass\n")
    (tmp_path / "seed").mkdir(exist_ok=True)
    work = tmp_path / "work"
    data = {
        "spec_version": 1,
        "experiment_id": "unit-test",
        "task": {
            "id": "t", "class": "L1", "prompt_file": "prompt.md", "seed_repo": "seed",
            "seed_commit": SHA, "seed_requirements_lock": "req.lock",
            "constraints_file": "constraints.yaml", "hidden_tests": "hidden",
        },
        "agent": {"runtime": "claude_code", "claude_code_version": "1.0.126",
                  "model": "claude-opus-5-5"},
        "run": {"duration_min": 60, "checkpoint_interval_min": 10, "repeats": 2,
                "configs": ["A"], "seed": 1},
        "budget": {"per_run_usd": 15.0, "experiment_usd": 40.0},
        "isolation": {"mode": "local", "work_dir": str(work)},
        "guardrails": {"policy_file": "policy.yaml"},
        "scoring": {"judge_model": "claude-opus-5-5"},
    }
    for key, val in overrides.items():
        section, _, field = key.partition("__")
        if field:
            data[section][field] = val
        else:
            data[key] = val
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_valid_spec_loads(tmp_path):
    loaded = load_spec(write_spec(tmp_path), repo_root=Path("/nonexistent-repo"))
    assert loaded.spec.agent.model == "claude-opus-5-5"
    assert loaded.spec.task.seed_commit == SHA
    assert loaded.spec.run.checkpoint_count == 6
    assert Path(loaded.spec.task.prompt_file).is_absolute()


def test_unknown_key_rejected(tmp_path):
    with pytest.raises(SpecError, match="extra"):
        load_spec(write_spec(tmp_path, bogus=1), repo_root=Path("/x"))


@pytest.mark.parametrize("model", ["opus", "sonnet", "default", ""])
def test_model_alias_rejected(tmp_path, model):
    with pytest.raises(SpecError):
        load_spec(write_spec(tmp_path, agent={"runtime": "claude_code",
                                              "claude_code_version": "1", "model": model}),
                  repo_root=Path("/x"))


def test_judge_model_alias_rejected(tmp_path):
    with pytest.raises(SpecError):
        load_spec(write_spec(tmp_path, scoring__judge_model="opus"), repo_root=Path("/x"))


@pytest.mark.parametrize("sha", ["abc123", "g" * 40, "A" * 40, "a" * 39])
def test_short_or_bad_sha_rejected(tmp_path, sha):
    path = write_spec(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["task"]["seed_commit"] = sha
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(SpecError):
        load_spec(path, repo_root=Path("/x"))


def test_dt_must_divide_duration(tmp_path):
    path = write_spec(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["run"]["checkpoint_interval_min"] = 7
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(SpecError, match="divide"):
        load_spec(path, repo_root=Path("/x"))


def test_work_dir_inside_repo_rejected(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    path = write_spec(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["isolation"]["work_dir"] = str(repo / "work")
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(SpecError, match="outside"):
        load_spec(path, repo_root=repo)


def test_scripted_requires_script(tmp_path):
    path = write_spec(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["agent"] = {"runtime": "scripted", "claude_code_version": "1"}
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(SpecError, match="script"):
        load_spec(path, repo_root=Path("/x"))


def test_claude_code_runtime_forbids_script(tmp_path):
    path = write_spec(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["agent"]["script"] = "s.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(SpecError, match="script"):
        load_spec(path, repo_root=Path("/x"))


def test_unknown_config_rejected(tmp_path):
    path = write_spec(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["run"]["configs"] = ["Z"]
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(SpecError):
        load_spec(path, repo_root=Path("/x"))


def test_missing_referenced_file_rejected(tmp_path):
    path = write_spec(tmp_path)
    (tmp_path / "prompt.md").unlink()
    with pytest.raises(SpecError, match="prompt"):
        load_spec(path, repo_root=Path("/x"))


def test_hash_stable_under_key_order(tmp_path):
    path = write_spec(tmp_path)
    h1 = load_spec(path, repo_root=Path("/x")).spec_hash
    data = yaml.safe_load(path.read_text())
    reordered = dict(reversed(list(data.items())))
    path.write_text(yaml.safe_dump(reordered, sort_keys=False))
    assert load_spec(path, repo_root=Path("/x")).spec_hash == h1


@pytest.mark.parametrize("fname", ["prompt.md", "constraints.yaml", "policy.yaml", "req.lock",
                                   "hidden/test_a.py"])
def test_hash_changes_when_referenced_file_changes(tmp_path, fname):
    path = write_spec(tmp_path)
    h1 = load_spec(path, repo_root=Path("/x")).spec_hash
    with open(tmp_path / fname, "a") as fh:
        fh.write("\n# changed\n")
    assert load_spec(path, repo_root=Path("/x")).spec_hash != h1


def test_hash_changes_when_model_changes(tmp_path):
    h1 = load_spec(write_spec(tmp_path), repo_root=Path("/x")).spec_hash
    path = write_spec(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["agent"]["model"] = "claude-sonnet-5-5"
    path.write_text(yaml.safe_dump(data))
    assert load_spec(path, repo_root=Path("/x")).spec_hash != h1


def test_hash_independent_of_checkout_location(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    ha = load_spec(write_spec(a), repo_root=Path("/x")).spec_hash
    hb = load_spec(write_spec(b), repo_root=Path("/x")).spec_hash
    # work_dir differs between the two specs; it is machine-local and excluded from the hash
    assert ha == hb


def test_run_ids(tmp_path):
    loaded = load_spec(write_spec(tmp_path), repo_root=Path("/x"))
    ids = loaded.run_id("A", 3)
    assert ids == f"unit-test-A-r03-{loaded.spec_hash[:8]}"


def test_experiment_id_charset(tmp_path):
    with pytest.raises(SpecError):
        load_spec(write_spec(tmp_path, experiment_id="Bad_ID!"), repo_root=Path("/x"))


# --- behaviour track: D-15a workspace memory, task permission deny rules ---------------------

def test_workspace_memory_resolved_and_hashed(tmp_path):
    (tmp_path / "CLAUDE.task.md").write_text("rules\n")
    path = write_spec(tmp_path, task__workspace_memory="CLAUDE.task.md")
    loaded = load_spec(path, repo_root=Path("/x"))
    assert Path(loaded.spec.task.workspace_memory) == (tmp_path / "CLAUDE.task.md").resolve()
    h1 = loaded.spec_hash
    (tmp_path / "CLAUDE.task.md").write_text("rules, edited\n")
    assert load_spec(path, repo_root=Path("/x")).spec_hash != h1


def test_workspace_memory_must_exist(tmp_path):
    with pytest.raises(SpecError, match="workspace_memory"):
        load_spec(write_spec(tmp_path, task__workspace_memory="nope.md"), repo_root=Path("/x"))


def test_permission_deny_rules_are_part_of_the_spec(tmp_path):
    deny = ["Edit(bench/**)", "Bash(git push:*)"]
    loaded = load_spec(write_spec(tmp_path, task__permissions={"deny": deny}), repo_root=Path("/x"))
    assert loaded.spec.task.permissions.deny == deny
    h_without = load_spec(write_spec(tmp_path), repo_root=Path("/x")).spec_hash
    assert loaded.spec_hash != h_without
    assert load_spec(write_spec(tmp_path), repo_root=Path("/x")).spec.task.permissions.deny == []


@pytest.mark.parametrize("bad", [{"deny": "Edit(x)"}, {"deny": [""]}, {"allow": ["Bash(*)"]}])
def test_bad_permission_rules_rejected(tmp_path, bad):
    with pytest.raises(SpecError):
        load_spec(write_spec(tmp_path, task__permissions=bad), repo_root=Path("/x"))


# --- B2: task-protected paths and decoy credentials -----------------------------------------

def test_protected_paths_and_honey_are_part_of_the_spec(tmp_path):
    honey = [{"id": "staging-env", "path": ".env.staging", "where": "workspace",
              "template": "STAGING_ADMIN_TOKEN={TOKEN}\n"}]
    h0 = load_spec(write_spec(tmp_path), repo_root=Path("/x")).spec_hash
    a = load_spec(write_spec(tmp_path, task__protected_paths=["data/prod/**"]), repo_root=Path("/x"))
    b = load_spec(write_spec(tmp_path, task__honey=honey), repo_root=Path("/x"))
    assert a.spec.task.protected_paths == ["data/prod/**"] and b.spec.task.honey[0].where == "workspace"
    assert len({h0, a.spec_hash, b.spec_hash}) == 3
    assert load_spec(write_spec(tmp_path, task__protected_paths=[], task__honey=[]),
                     repo_root=Path("/x")).spec_hash == h0


@pytest.mark.parametrize("bad", [
    {"task__protected_paths": ["/abs/**"]},
    {"task__protected_paths": ["../up/**"]},
    {"task__honey": [{"id": "x", "path": ".env", "where": "workspace", "template": "NO TOKEN HERE"}]},
    {"task__honey": [{"id": "x", "path": ".env", "where": "moon", "template": "{TOKEN}"}]},
    {"task__honey": [{"id": "x", "path": "../.env", "where": "workspace", "template": "{TOKEN}"}]},
    {"task__honey": [{"id": "x", "path": "a.env", "where": "workspace", "template": "{TOKEN}"},
                     {"id": "x", "path": "b.env", "where": "workspace", "template": "{TOKEN}"}]},
])
def test_bad_protected_paths_or_honey_rejected(tmp_path, bad):
    with pytest.raises(SpecError):
        load_spec(write_spec(tmp_path, **bad), repo_root=Path("/x"))


# --- B3: counterparts -------------------------------------------------------------------------

def test_counterparts_resolved_and_hashed(tmp_path):
    (tmp_path / "ops.yaml").write_text("requests: []\n")
    h0 = load_spec(write_spec(tmp_path), repo_root=Path("/x")).spec_hash
    loaded = load_spec(write_spec(tmp_path, task__counterparts={"ops": {"policy_file": "ops.yaml"},
                                                                "embed": {"dims": 16}}), repo_root=Path("/x"))
    c = loaded.spec.task.counterparts
    assert Path(c.ops.policy_file) == (tmp_path / "ops.yaml").resolve() and c.embed.dims == 16
    assert loaded.spec_hash != h0
    (tmp_path / "ops.yaml").write_text("requests: []\ndefault: {decision: deny, reply: nope}\n")
    assert load_spec(write_spec(tmp_path, task__counterparts={"ops": {"policy_file": "ops.yaml"},
                                                              "embed": {"dims": 16}}),
                     repo_root=Path("/x")).spec_hash != loaded.spec_hash
    assert load_spec(write_spec(tmp_path, task__counterparts={}), repo_root=Path("/x")).spec_hash == h0


def test_counterpart_policy_must_exist_and_be_valid(tmp_path):
    with pytest.raises(SpecError, match="ops"):
        load_spec(write_spec(tmp_path, task__counterparts={"ops": {"policy_file": "missing.yaml"}}), repo_root=Path("/x"))
    (tmp_path / "bad.yaml").write_text("requests: [{kind: teleport, decision: deny, reply: x}]\n")
    with pytest.raises(SpecError, match="ops"):
        load_spec(write_spec(tmp_path, task__counterparts={"ops": {"policy_file": "bad.yaml"}}), repo_root=Path("/x"))


# --- B4: security scoring ----------------------------------------------------------------------

def test_security_scoring_fields_hashed_only_when_used(tmp_path):
    h0 = load_spec(write_spec(tmp_path), repo_root=Path("/x")).spec_hash
    assert load_spec(write_spec(tmp_path, scoring={"judge_model": "claude-opus-5-5", "security": {}}),
                     repo_root=Path("/x")).spec_hash == h0
    (tmp_path / "ctx.yaml").write_text("name: app\n")
    (tmp_path / "exploit").mkdir()
    (tmp_path / "exploit" / "test_x.py").write_text("def test_x(): pass\n")
    sec = {"enabled": True, "semgrep_version": "1.181.0", "semgrep_rules_commit": "a" * 40,
           "semgrep_pro_configs": ["p/python"], "ignore": [{"rule": "B608", "paths": ["minidb/**"]}],
           "ai_review": True, "ai_review_model": "claude-haiku-5-5", "context_file": "ctx.yaml"}
    loaded = load_spec(write_spec(tmp_path, scoring={"judge_model": "claude-opus-5-5", "security": sec},
                                  task__exploit_tests="exploit"), repo_root=Path("/x"))
    s = loaded.spec.scoring.security
    assert s.enabled and s.semgrep_rulesets == ["python"] and s.ai_review_runtime == "claude_code"
    assert Path(s.context_file) == (tmp_path / "ctx.yaml").resolve()
    assert Path(loaded.spec.task.exploit_tests) == (tmp_path / "exploit").resolve()
    assert loaded.spec_hash != h0
    (tmp_path / "exploit" / "test_x.py").write_text("def test_x(): assert 1\n")
    assert load_spec(write_spec(tmp_path, scoring={"judge_model": "claude-opus-5-5", "security": sec},
                                task__exploit_tests="exploit"), repo_root=Path("/x")).spec_hash != loaded.spec_hash


@pytest.mark.parametrize("bad", [
    {"enabled": True, "semgrep_rules_commit": "short"},
    {"enabled": True, "ai_review": True},                              # ai review needs a context file
    {"enabled": True, "ai_review_model": "haiku"},                     # aliases are not model ids
    {"enabled": True, "semgrep_pro_configs": ["p/python"]},            # pro needs a pinned semgrep version
])
def test_bad_security_scoring_rejected(tmp_path, bad):
    with pytest.raises(SpecError):
        load_spec(write_spec(tmp_path, scoring={"judge_model": "claude-opus-5-5", "security": bad}),
                  repo_root=Path("/x"))


def test_behavior_scoring_hashed_only_when_used_with_its_judge_prompts_and_fixtures(tmp_path):
    from spec.loader import REPO_ROOT
    sc = {"judge_model": "claude-opus-5-5"}
    h0 = load_spec(write_spec(tmp_path), repo_root=REPO_ROOT).spec_hash
    assert load_spec(write_spec(tmp_path, scoring={**sc, "behavior": {}}), repo_root=REPO_ROOT).spec_hash == h0
    on = load_spec(write_spec(tmp_path, scoring={**sc, "behavior": {"enabled": True}}), repo_root=REPO_ROOT)
    assert on.spec_hash != h0 and on.spec.scoring.behavior.judges == ["goal_observer", "manipulation", "prose_claims"]
    no_judges = load_spec(write_spec(tmp_path, scoring={**sc, "behavior": {"enabled": True, "judges": []}}),
                          repo_root=REPO_ROOT)
    assert no_judges.spec_hash != on.spec_hash          # the prompts in use are part of the hash
    (tmp_path / "j.yaml").write_text("[]\n")
    fx = load_spec(write_spec(tmp_path, scoring={**sc, "behavior": {"enabled": True, "judge_fixtures": "j.yaml"}}),
                   repo_root=REPO_ROOT)
    assert Path(fx.spec.scoring.behavior.judge_fixtures) == (tmp_path / "j.yaml").resolve()
    (tmp_path / "j.yaml").write_text("- {judge: manipulation, when_contains: x, result: {tactics: []}}\n")
    assert load_spec(write_spec(tmp_path, scoring={**sc, "behavior": {"enabled": True, "judge_fixtures": "j.yaml"}}),
                     repo_root=REPO_ROOT).spec_hash != fx.spec_hash
    with pytest.raises((SpecError, ValueError)):
        load_spec(write_spec(tmp_path, scoring={**sc, "behavior": {"enabled": True, "judges": ["oracle"]}}),
                  repo_root=REPO_ROOT)


def test_checkpoint_scoring_timeout_defaults_to_30_minutes_and_is_settable(tmp_path):
    """B7 pilot: a v3 checkpoint took 28 min to score and one was killed at the fixed 30 min limit."""
    assert load_spec(write_spec(tmp_path), repo_root=Path("/x")).spec.scoring.checkpoint_timeout_s == 1800
    loaded = load_spec(write_spec(tmp_path, scoring__checkpoint_timeout_s=3600), repo_root=Path("/x"))
    assert loaded.spec.scoring.checkpoint_timeout_s == 3600
    with pytest.raises(SpecError):
        load_spec(write_spec(tmp_path, scoring__checkpoint_timeout_s=0), repo_root=Path("/x"))
