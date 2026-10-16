import json
import os
import subprocess
from pathlib import Path

import pytest

from runner import snapshot
from runner.workdir import RunPaths


def git(cwd, *args, **kw):
    env = dict(os.environ, GIT_AUTHOR_NAME="a", GIT_AUTHOR_EMAIL="a@a", GIT_COMMITTER_NAME="a",
               GIT_COMMITTER_EMAIL="a@a", GIT_AUTHOR_DATE="2026-01-01T00:00:00Z",
               GIT_COMMITTER_DATE="2026-01-01T00:00:00Z")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def run(tmp_path):
    paths = RunPaths.for_run("r1", tmp_path / "work", tmp_path / "repo")
    paths.create()
    ws = paths.workspace
    ws.mkdir()
    git(ws, "init", "-q", "-b", "main")
    (ws / "a.py").write_text("x = 1\n")
    git(ws, "add", "-A")
    git(ws, "commit", "-q", "-m", "c1")
    state = tmp_path / "claude" / "projects" / "enc"
    (state / "memory").mkdir(parents=True)
    (state / "sess.jsonl").write_text("{}\n")
    return paths, state


def refs(repo):
    return git(repo, "for-each-ref")


def test_snapshot_copies_workspace_and_state(run):
    paths, state = run
    info = snapshot.take_snapshot(paths, 1, state_dir=state)
    d = paths.snapshots / "t1"
    assert (d / "workspace" / "a.py").read_text() == "x = 1\n"
    assert (d / "workspace" / ".git").is_dir()
    assert (d / "agent_state" / "sess.jsonl").exists()
    assert info.k == 1


def test_meta_json_fields(run):
    paths, state = run
    snapshot.take_snapshot(paths, 1, state_dir=state, cumulative_cost_usd=0.5)
    meta = json.loads((paths.snapshots / "t1" / "meta.json").read_text())
    head = git(paths.workspace, "rev-parse", "HEAD")
    assert meta["head_sha"] == head and meta["dirty"] is False
    assert meta["head_tree"] == git(paths.workspace, "rev-parse", "HEAD^{tree}")
    assert len(meta["worktree_hash"]) == 64 and meta["file_count"] >= 1
    assert meta["cumulative_cost_usd"] == 0.5 and meta["pause_ms"] >= 0 and meta["k"] == 1


def test_dirty_flag_and_untracked_preserved(run):
    paths, state = run
    (paths.workspace / "new.txt").write_text("uncommitted")
    (paths.workspace / "a.py").write_text("x = 2\n")
    snapshot.take_snapshot(paths, 1, state_dir=state)
    meta = json.loads((paths.snapshots / "t1" / "meta.json").read_text())
    assert meta["dirty"] is True
    assert (paths.snapshots / "t1" / "workspace" / "new.txt").read_text() == "uncommitted"


def test_worktree_hash_changes_with_content_and_ignores_caches(run):
    paths, state = run
    h1 = snapshot.worktree_hash(paths.workspace)
    (paths.workspace / "__pycache__").mkdir()
    (paths.workspace / "__pycache__" / "a.pyc").write_bytes(b"\0\1")
    (paths.workspace / ".pytest_cache").mkdir()
    (paths.workspace / ".pytest_cache" / "v").write_text("x")
    assert snapshot.worktree_hash(paths.workspace) == h1
    (paths.workspace / "a.py").write_text("x = 3\n")
    assert snapshot.worktree_hash(paths.workspace) != h1


def test_worktree_hash_ignores_git_dir(run):
    paths, _ = run
    h1 = snapshot.worktree_hash(paths.workspace)
    git(paths.workspace, "commit", "-q", "--allow-empty", "-m", "empty")
    assert snapshot.worktree_hash(paths.workspace) == h1


def test_mirror_tag_created_and_agent_repo_untouched(run):
    paths, state = run
    before = refs(paths.workspace)
    snapshot.take_snapshot(paths, 1, state_dir=state)
    (paths.workspace / "b.py").write_text("y = 1\n")
    git(paths.workspace, "add", "-A")
    git(paths.workspace, "commit", "-q", "-m", "c2")
    snapshot.take_snapshot(paths, 2, state_dir=state)
    tags = git(paths.mirror, "tag", "-l").split()
    assert tags == ["ckpt/t1", "ckpt/t2"]
    assert git(paths.mirror, "rev-parse", "ckpt/t2") == git(paths.workspace, "rev-parse", "HEAD")
    assert git(paths.mirror, "rev-parse", "ckpt/t1") != git(paths.mirror, "rev-parse", "ckpt/t2")
    assert "ckpt" not in git(paths.workspace, "tag", "-l")
    assert refs(paths.workspace).replace("c2", "") != "" and "ckpt" not in refs(paths.workspace)
    assert git(paths.mirror, "rev-parse", "--is-bare-repository") == "true"
    assert before.split()[0] != ""  # sanity: the repo had refs


def test_mirror_has_full_history_for_blame(run):
    paths, state = run
    snapshot.take_snapshot(paths, 1, state_dir=state)
    assert git(paths.mirror, "rev-list", "--count", "ckpt/t1") == "1"


def test_snapshot_without_state_dir_ok(run):
    paths, _ = run
    snapshot.take_snapshot(paths, 1, state_dir=Path("/nonexistent/state"))
    assert (paths.snapshots / "t1" / "agent_state").is_dir()


def test_pip_freeze_hash_recorded_when_provided(run):
    paths, state = run
    snapshot.take_snapshot(paths, 1, state_dir=state, pip_freeze_text="fastapi==1\n")
    meta = json.loads((paths.snapshots / "t1" / "meta.json").read_text())
    assert len(meta["pip_freeze_hash"]) == 64
    assert (paths.snapshots / "t1" / "pip-freeze.txt").read_text() == "fastapi==1\n"


def test_existing_snapshot_not_overwritten(run):
    paths, state = run
    snapshot.take_snapshot(paths, 1, state_dir=state)
    with pytest.raises(FileExistsError):
        snapshot.take_snapshot(paths, 1, state_dir=state)


def test_pauses_and_resumes_process(run):
    paths, state = run
    calls = []

    class FakeProc:
        def pause(self): calls.append("pause")
        def resume(self): calls.append("resume")

    snapshot.take_snapshot(paths, 1, state_dir=state, proc=FakeProc())
    assert calls == ["pause", "resume"]


def test_resumes_process_even_if_copy_fails(run, monkeypatch):
    paths, state = run
    calls = []

    class FakeProc:
        def pause(self): calls.append("pause")
        def resume(self): calls.append("resume")

    monkeypatch.setattr(snapshot.shutil, "copytree", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    with pytest.raises(OSError):
        snapshot.take_snapshot(paths, 1, state_dir=state, proc=FakeProc())
    assert calls == ["pause", "resume"]
