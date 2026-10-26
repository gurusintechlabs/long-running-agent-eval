"""UH: gitview hardening, deadline for a stalled git, attributes that hide text, alternates."""
from __future__ import annotations

import os
import stat
import time

import pytest

from tests.unit.ui_server.test_u3_git import diff, repo_run  # noqa: F401  (fixture)
from ui_server import gitview


def test_a_git_that_stalls_without_output_is_cut_at_the_deadline(tmp_path, monkeypatch):
    fake = tmp_path / "fakegit"
    fake.write_text("#!/bin/sh\nsleep 30\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(gitview, "_git", lambda: str(fake))
    monkeypatch.setattr(gitview, "TIMEOUT_S", 1.0)
    t0 = time.monotonic()
    with pytest.raises(gitview.GitError, match="timed out"):
        gitview.run_git(tmp_path, ["log"], 1000)
    assert time.monotonic() - t0 < 4


def test_the_stalled_git_process_group_is_killed(tmp_path, monkeypatch):
    marker = tmp_path / "child.pid"
    fake = tmp_path / "fakegit"
    fake.write_text(f"#!/bin/sh\nsleep 40 &\necho $! > {marker}\nwait\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(gitview, "_git", lambda: str(fake))
    monkeypatch.setattr(gitview, "TIMEOUT_S", 1.0)
    with pytest.raises(gitview.GitError):
        gitview.run_git(tmp_path, ["log"], 1000)
    import psutil
    pid = int(marker.read_text())
    time.sleep(0.3)
    assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE


def test_slow_dribble_is_also_bounded(tmp_path, monkeypatch):
    fake = tmp_path / "fakegit"
    fake.write_text("#!/bin/sh\nwhile true; do printf x; sleep 0.2; done\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(gitview, "_git", lambda: str(fake))
    monkeypatch.setattr(gitview, "TIMEOUT_S", 1.0)
    t0 = time.monotonic()
    with pytest.raises(gitview.GitError):
        gitview.run_git(tmp_path, ["log"], 10_000)
    assert time.monotonic() - t0 < 4


def test_attributes_that_hide_text_make_the_mirror_unreadable(client, repo_run):  # noqa: F811
    rid, rd, _shas = repo_run
    (rd / "mirror.git" / "info").mkdir(exist_ok=True)
    (rd / "mirror.git" / "info" / "attributes").write_text("* -diff\n")
    b = diff(client, rid, 2).json()
    assert b["available"] is False and "attributes" in b["reason"] and b["diff"] == ""


def test_binary_macro_and_config_binary_are_refused_too(client, repo_run):  # noqa: F811
    rid, rd, _ = repo_run
    (rd / "mirror.git" / "info").mkdir(exist_ok=True)
    (rd / "mirror.git" / "info" / "attributes").write_text("*.py binary\n")
    assert diff(client, rid, 2).json()["available"] is False
    (rd / "mirror.git" / "info" / "attributes").write_text("# comment only\n")
    assert diff(client, rid, 2).json()["available"] is True
    cfg = rd / "mirror.git" / "config"
    cfg.write_text(cfg.read_text() + '\n[diff "x"]\n\tbinary = true\n')
    assert diff(client, rid, 2).json()["available"] is False


def test_alternates_are_refused(client, repo_run, tmp_path):  # noqa: F811
    rid, rd, _ = repo_run
    (rd / "mirror.git" / "objects" / "info").mkdir(exist_ok=True)
    (rd / "mirror.git" / "objects" / "info" / "alternates").write_text(str(tmp_path / "elsewhere") + "\n")
    b = diff(client, rid, 2).json()
    assert b["available"] is False and "alternates" in b["reason"]


def test_symlinked_objects_dir_is_refused(client, repo_run, tmp_path):  # noqa: F811
    rid, rd, _ = repo_run
    real = rd / "mirror.git" / "objects"
    moved = tmp_path / "objects-elsewhere"
    real.rename(moved)
    os.symlink(moved, real)
    assert diff(client, rid, 2).json()["available"] is False


def test_git_env_has_no_ambient_object_dirs(monkeypatch):
    monkeypatch.setenv("GIT_ALTERNATE_OBJECT_DIRECTORIES", "/evil")
    assert "GIT_ALTERNATE_OBJECT_DIRECTORIES" not in gitview.git_env()
