import os
import subprocess

import pytest

from runner import workdir
from runner.memory import MemoryError_


def git(cwd, *args, env=None):
    e = dict(os.environ, GIT_AUTHOR_NAME="s", GIT_AUTHOR_EMAIL="s@s", GIT_COMMITTER_NAME="s",
             GIT_COMMITTER_EMAIL="s@s", **(env or {}))
    return subprocess.run(["git", *args], cwd=cwd, env=e, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def seed(tmp_path):
    repo = tmp_path / "seed"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "a.py").write_text("print(1)\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed")
    return repo, git(repo, "rev-parse", "HEAD")


def test_run_paths_layout(tmp_path):
    p = workdir.RunPaths.for_run("r1", work_dir=tmp_path / "w", repo_root=tmp_path / "repo")
    assert p.work == tmp_path / "w" / "r1"
    assert p.workspace == p.work / "workspace" and p.tmp == p.work / "tmp" and p.venv == p.work / "venv"
    assert p.art == tmp_path / "repo" / "runs" / "r1"
    assert p.events == p.art / "events" and p.snapshots == p.art / "snapshots"
    assert p.mirror == p.art / "mirror.git"
    assert p.art not in p.work.parents and p.work not in p.art.parents


def test_two_runs_never_share_dirs(tmp_path):
    a = workdir.RunPaths.for_run("r1", tmp_path / "w", tmp_path / "repo")
    b = workdir.RunPaths.for_run("r2", tmp_path / "w", tmp_path / "repo")
    assert not {a.work, a.art} & {b.work, b.art}


def test_create_refuses_existing_run_dir(tmp_path):
    p = workdir.RunPaths.for_run("r1", tmp_path / "w", tmp_path / "repo")
    p.create()
    assert p.workspace.parent.is_dir() and p.tmp.is_dir() and p.events.is_dir()
    with pytest.raises(FileExistsError):
        p.create()


def test_clone_seed_pins_commit_and_sets_identity(tmp_path, seed):
    repo, sha = seed
    ws = tmp_path / "ws"
    workdir.clone_seed(repo, sha, ws)
    assert git(ws, "rev-parse", "HEAD") == sha
    assert git(ws, "config", "--local", "user.email") == "agent@lrae.local"
    assert git(ws, "config", "--local", "user.name") == "agent"
    assert (ws / "a.py").exists()


def test_clone_seed_has_no_remote_link_back(tmp_path, seed):
    repo, sha = seed
    ws = tmp_path / "ws"
    workdir.clone_seed(repo, sha, ws)
    assert git(ws, "remote").strip() == ""  # agent cannot push/fetch from the source fixture


def test_clone_seed_wrong_commit_fails(tmp_path, seed):
    repo, _ = seed
    with pytest.raises(workdir.WorkdirError):
        workdir.clone_seed(repo, "b" * 40, tmp_path / "ws")


def test_clone_seed_rejects_memory_files(tmp_path, seed):
    repo, _ = seed
    (repo / "CLAUDE.md").write_text("x")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "bad")
    sha = git(repo, "rev-parse", "HEAD")
    with pytest.raises(MemoryError_):
        workdir.clone_seed(repo, sha, tmp_path / "ws")
