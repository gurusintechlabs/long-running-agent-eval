"""Environment mutator (docs/behavior-design.md §5.1, D-18a): harness changes made between turns."""
import os
import subprocess

import pytest

from runner.envmut import EnvMutationError, EnvMutator, harness_identity, is_harness_email
from runner.stages import EnvAction


def git(repo, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "agent", "GIT_AUTHOR_EMAIL": "agent@lrae.local",
           "GIT_COMMITTER_NAME": "agent", "GIT_COMMITTER_EMAIL": "agent@lrae.local"}
    return subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def ws(tmp_path):
    w = tmp_path / "ws"
    w.mkdir()
    git(w, "init", "-q", "-b", "main")
    (w / "ENVIRONMENT.md").write_text("v1 docs\n")
    (w / "app.py").write_text("x = 1\n")
    git(w, "add", "-A")
    git(w, "commit", "-q", "-m", "seed")
    return w


@pytest.fixture
def src(tmp_path):
    p = tmp_path / "task" / "ENV.v2.md"
    p.parent.mkdir()
    p.write_text("v2 docs\n")
    return p


def action(src, **over):
    params = {"path": "ENVIRONMENT.md", "author": "platform-bot", "message": "Update environment docs"}
    params.update(over)
    return EnvAction("commit_file", params, src)


def test_harness_identity():
    name, email = harness_identity("platform-bot")
    assert name == "platform-bot" and email == "platform-bot@harness.lrae.local"
    assert is_harness_email(email) and not is_harness_email("agent@lrae.local")
    assert not is_harness_email("x@harness.lrae.local.evil.com")


def test_commit_file_commits_only_that_path_as_the_named_author(ws, src):
    (ws / "app.py").write_text("x = 2\n")            # agent's unstaged edit
    (ws / "new.py").write_text("y = 1\n")
    git(ws, "add", "new.py")                         # agent's staged, uncommitted file
    ev = EnvMutator(ws).apply(action(src))
    assert ev["action"] == "commit_file" and ev["path"] == "ENVIRONMENT.md"
    assert ev["clobbered_local_change"] is False
    assert (ws / "ENVIRONMENT.md").read_text() == "v2 docs\n"
    assert git(ws, "log", "-1", "--format=%an <%ae>|%s") == \
        "platform-bot <platform-bot@harness.lrae.local>|Update environment docs"
    assert git(ws, "show", "--name-only", "--format=", "HEAD") == "ENVIRONMENT.md"
    assert ev["sha"] == git(ws, "rev-parse", "HEAD")
    # the agent's work is untouched: still staged / still modified, nothing lost
    assert git(ws, "diff", "--cached", "--name-only") == "new.py"
    assert git(ws, "diff", "--name-only") == "app.py"
    assert (ws / "app.py").read_text() == "x = 2\n"


def test_commit_file_reports_a_clobbered_local_edit(ws, src):
    (ws / "ENVIRONMENT.md").write_text("agent's local notes\n")
    ev = EnvMutator(ws).apply(action(src))
    assert ev["clobbered_local_change"] is True
    assert (ws / "ENVIRONMENT.md").read_text() == "v2 docs\n"


def test_commit_file_creates_new_files_and_dirs(ws, src):
    ev = EnvMutator(ws).apply(action(src, path="docs/ops/RUNBOOK.md"))
    assert (ws / "docs/ops/RUNBOOK.md").read_text() == "v2 docs\n"
    assert git(ws, "show", "--name-only", "--format=", "HEAD") == "docs/ops/RUNBOOK.md"
    assert ev["clobbered_local_change"] is False


def test_agent_hooks_never_run_in_the_harness(ws, src, tmp_path):
    marker = tmp_path / "hook-ran"
    hook = f"#!/bin/sh\ntouch {marker}\n"
    for d in (ws / ".git" / "hooks", ws / "myhooks"):
        d.mkdir(exist_ok=True)
        for name in ("pre-commit", "commit-msg", "post-commit", "prepare-commit-msg"):
            (d / name).write_text(hook)
            (d / name).chmod(0o755)
    git(ws, "config", "--local", "core.hooksPath", str(ws / "myhooks"))
    EnvMutator(ws).apply(action(src))
    assert not marker.exists()


def test_refuses_to_write_through_a_symlink(ws, src, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("keep\n")
    (ws / "ENVIRONMENT.md").unlink()
    (ws / "ENVIRONMENT.md").symlink_to(outside)
    with pytest.raises(EnvMutationError, match="symlink"):
        EnvMutator(ws).apply(action(src))
    assert outside.read_text() == "keep\n"


def test_unimplemented_action_raises(ws, src):
    with pytest.raises(EnvMutationError):
        EnvMutator(ws).apply(EnvAction("counterpart_mode", {"service": "embed", "mode": "v2"}, None))
