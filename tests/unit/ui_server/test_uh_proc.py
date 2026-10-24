"""UH-3/UH-4: harness process detection on macOS launch styles, and a manifest cannot point the UI at
an unrelated process. All decoys are real sleeper processes; nothing here starts an lrae run."""
from __future__ import annotations

import signal
import time

import psutil
import pytest

from tests.unit.ui_server import control_support as cs
from tests.unit.ui_server.test_control import good_nonce, launch, rig  # noqa: F401  (fixtures)
from ui_server import control_core as cc
from ui_server import harness_proc

MAC_PY = "/Library/Frameworks/Python.framework/Versions/3.13/Resources/Python.app/Contents/MacOS/Python"


@pytest.fixture
def kills(monkeypatch):
    calls = []
    real = cc.os.kill

    def spy(pid, sig):
        calls.append((pid, sig))
        return real(pid, sig)

    monkeypatch.setattr(cc.os, "kill", spy)
    return calls


@pytest.mark.parametrize("argv,ok", [
    ([MAC_PY, "-m", "runner.cli", "--repo-root", "/r", "run", "s.yaml"], True),
    ([MAC_PY, "./probe/lrae", "run", "x.yaml"], True),                       # console script, relative path
    ([MAC_PY, "/venv/bin/lrae", "--repo-root", "/r", "resume", "rid", "--from", "t2"], True),
    ([MAC_PY, "/repo/runner/cli.py", "run", "s.yaml", "--config", "A"], True),
    (["Python", "-u", "-m", "runner.cli", "run", "s.yaml"], True),
    (["/usr/bin/python3.13", "-X", "dev", "-m", "runner.cli", "run", "s.yaml"], True),
    (["lrae", "run", "s.yaml"], True),
    ([MAC_PY, "-m", "runner.cli", "validate", "s.yaml"], False),
    ([MAC_PY, "-m", "runner.cli", "ui"], False),
    ([MAC_PY, "-c", "run lrae"], False),
    ([MAC_PY, "/tmp/other.py", "lrae", "run"], False),
    ([MAC_PY, "-m", "pytest", "run"], False),
    ([MAC_PY, "-m", "runner.cli", "run"], False),                             # no spec
])
def test_matcher(argv, ok):
    assert cc._argv_is_harness(argv) is ok


@pytest.mark.parametrize("style", ["module", "script", "clipy"])
def test_real_decoy_of_every_launch_style_is_recognised(tmp_path, style):
    p = cs.spawn_lookalike(tmp_path, "x.yaml", repo=tmp_path, style=style)
    try:
        time.sleep(0.4)
        assert cc._argv_is_harness(psutil.Process(p.pid).cmdline()), psutil.Process(p.pid).cmdline()
        assert cc.harness_state(p.pid) == "alive"
    finally:
        p.kill()
        p.wait()


@pytest.mark.parametrize("style", ["module", "script", "clipy"])
def test_terminal_launched_run_without_manifest_blocks_launch(rig, style):  # noqa: F811
    """No manifest yet (pre-flight) and none needed: the command line alone makes it visible."""
    p = cs.spawn_lookalike(rig.r["tmp"], str(rig.spec), repo=rig.r["repo"], style=style)
    try:
        time.sleep(0.4)
        r = launch(rig, good_nonce(rig))
        assert r.status_code == 409 and r.json()["detail"]["code"] == "run_active", r.text
        assert rig.spawner.calls == []
    finally:
        p.kill()
        p.wait()


@pytest.mark.parametrize("style", ["module", "script", "clipy"])
def test_stop_works_for_every_launch_style(rig, kills, style):  # noqa: F811
    p = cs.spawn_lookalike(rig.r["tmp"], str(rig.spec), repo=rig.r["repo"], style=style)
    try:
        time.sleep(0.4)
        cs.write_manifest(rig.r["runs"], "live", harness_pid=p.pid, start_epoch=time.time(),
                          spec_path=str(rig.spec))
        r = rig.c.post("/api/runs/live/stop")
        assert r.status_code == 200, r.text
        assert kills == [(p.pid, signal.SIGINT)]
        p.wait(timeout=10)
    finally:
        p.kill()
        p.wait()


def test_resume_decoy_must_name_this_run(rig, kills):  # noqa: F811
    p = cs.spawn_lookalike(rig.r["tmp"], "other-run", "--from", "t1", repo=rig.r["repo"], verb="resume")
    try:
        time.sleep(0.4)
        cs.write_manifest(rig.r["runs"], "live", harness_pid=p.pid, start_epoch=time.time())
        assert rig.c.post("/api/runs/live/stop").status_code == 409          # resume of another run
        cs.write_manifest(rig.r["runs"], "other-run", harness_pid=p.pid, start_epoch=time.time())
        assert rig.c.post("/api/runs/other-run/stop").status_code == 200
        assert kills == [(p.pid, signal.SIGINT)]
        p.wait(timeout=10)
    finally:
        p.kill()
        p.wait()


# -- tampered manifests ----------------------------------------------------------------------------

def _tampered(rig, p, **manifest):  # noqa: F811
    cs.write_manifest(rig.r["runs"], "victim", harness_pid=p.pid, **manifest)


@pytest.mark.parametrize("what", ["other_repo", "other_spec", "no_start_epoch", "no_spec_path", "string_start",
                                  "other_config", "norepo_outside"])
def test_unrelated_harness_looking_process_is_never_signalled(rig, kills, what):  # noqa: F811
    tmp, repo = rig.r["tmp"], rig.r["repo"]
    kw = dict(start_epoch=time.time(), spec_path=str(rig.spec))
    if what == "other_repo":
        p = cs.spawn_lookalike(tmp, str(rig.spec), repo=tmp / "somewhere-else")
    elif what == "other_spec":
        p = cs.spawn_lookalike(tmp, str(tmp / "unrelated.yaml"), repo=repo)
    elif what == "other_config":
        p = cs.spawn_lookalike(tmp, str(rig.spec), "--config", "Z", repo=repo)
    elif what == "norepo_outside":
        p = cs.spawn_lookalike(tmp, str(rig.spec), style="norepo")      # cwd is outside the repo
    else:
        p = cs.spawn_lookalike(tmp, str(rig.spec), repo=repo)
        if what == "no_start_epoch":
            kw["start_epoch"] = None
        elif what == "no_spec_path":
            kw.pop("spec_path")
        else:
            kw["start_epoch"] = "0"
    try:
        time.sleep(0.4)
        _tampered(rig, p, **kw)
        r = rig.c.post("/api/runs/victim/stop")
        assert r.status_code == 409 and r.json()["detail"]["code"] == "not_a_live_harness", r.text
        r = rig.c.post("/api/runs/victim/kill", json={"confirm": "victim"})
        assert r.status_code == 409
        assert kills == [] and cs.alive(p.pid)
        assert rig.spawner.calls == []
    finally:
        p.kill()
        p.wait()


def test_the_verified_process_is_signalled_only_with_a_matching_manifest(rig, kills):  # noqa: F811
    p = cs.spawn_lookalike(rig.r["tmp"], str(rig.spec), "--config", "A", "--repeat", "0", repo=rig.r["repo"])
    try:
        time.sleep(0.4)
        cs.write_manifest(rig.r["runs"], "ok-run", harness_pid=p.pid, start_epoch=time.time(),
                          spec_path=str(rig.spec), config="A", repeat=0)
        assert rig.c.post("/api/runs/ok-run/stop").status_code == 200
        assert kills == [(p.pid, signal.SIGINT)]
        p.wait(timeout=10)
    finally:
        p.kill()
        p.wait()


def test_verify_fails_closed_without_a_repo(tmp_path):
    assert cc.verify_harness(12345, {"harness_pid": 12345, "start_epoch": 1.0}) is None
    assert harness_proc.verify(True, {}, tmp_path) is None
