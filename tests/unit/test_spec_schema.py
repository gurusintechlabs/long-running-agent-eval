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
