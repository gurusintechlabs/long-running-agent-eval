import os
import subprocess
from pathlib import Path

import pytest
import yaml


def git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="s", GIT_AUTHOR_EMAIL="s@s", GIT_COMMITTER_NAME="s",
               GIT_COMMITTER_EMAIL="s@s", GIT_AUTHOR_DATE="2026-01-01T00:00:00Z",
               GIT_COMMITTER_DATE="2026-01-01T00:00:00Z")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True,
                          text=True).stdout.strip()


DT_S = 1.5          # checkpoint interval in tests
DURATION_S = 6.0    # 4 checkpoints


def make_script(path: Path, extra=()):
    """Scripted agent: one visible change in the middle of each checkpoint interval."""
    actions = []
    for k in range(1, 5):
        at = (k - 0.5) * DT_S
        actions.append({"at": at, "do": "write_file", "path": f"step{k}.txt", "content": f"step {k}\n"})
        actions.append({"at": at + 0.05, "do": "git_commit", "message": f"step {k}"})
        actions.append({"at": at + 0.1, "do": "emit_otel", "event": "claude_code.api_request",
                        "attrs": {"cost_usd": 0.01, "input_tokens": 100, "model": "scripted"}})
    actions.extend(extra)
    path.write_text(yaml.safe_dump({"idle_s": 0.1, "actions": actions}))


@pytest.fixture
def env(tmp_path):
    """A throwaway 'repo root', claude home, home, seed repo and spec for scripted runs."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    claude_home = tmp_path / "claude"
    claude_home.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "main")
    (seed / "app.py").write_text("print('seed')\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "seed")
    sha = git(seed, "rev-parse", "HEAD")
    (tmp_path / "prompt.md").write_text("Do the task.\n")
    (tmp_path / "constraints.yaml").write_text("constraints: []\n")
    (tmp_path / "policy.yaml").write_text("forbidden_commands: []\n")
    (tmp_path / "req.lock").write_text("")
    (tmp_path / "hidden").mkdir()
    (tmp_path / "hidden" / "t.py").write_text("x=1\n")
    make_script(tmp_path / "script.yaml")
    spec = {
        "spec_version": 1, "experiment_id": "orch-test",
        "task": {"id": "t", "class": "L1", "prompt_file": "prompt.md", "seed_repo": "seed",
                 "seed_commit": sha, "seed_requirements_lock": "req.lock",
                 "constraints_file": "constraints.yaml", "hidden_tests": "hidden"},
        "agent": {"runtime": "scripted", "claude_code_version": "n/a", "script": "script.yaml"},
        "run": {"duration_min": DURATION_S / 60, "checkpoint_interval_min": DT_S / 60, "repeats": 2,
                "configs": ["A"], "seed": 1},
        "budget": {"per_run_usd": 15.0, "experiment_usd": 40.0},
        "isolation": {"mode": "local", "work_dir": str(home / "lrae-work")},
        "telemetry": {"export_interval_ms": 200},
        "guardrails": {"policy_file": "policy.yaml"},
        "scoring": {"judge_model": "claude-opus-5-5"},
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec))
    return dict(tmp=tmp_path, repo_root=repo_root, claude_home=claude_home, home=home,
                spec_path=spec_path, seed=seed, sha=sha)
