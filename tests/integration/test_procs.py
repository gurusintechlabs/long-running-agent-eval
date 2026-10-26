import os
import subprocess
import sys
import time

import psutil
import pytest

from runner import procs

pytestmark = pytest.mark.local

TICKER = "while true; do date +%s%N >> ticks; sleep 0.05; done"


def wait_for(cond, timeout=5.0, step=0.05):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return False


def size(p):
    return p.stat().st_size if p.exists() else 0


def test_group_freeze_and_resume(tmp_path):
    mp = procs.spawn(["sh", "-c", TICKER], cwd=tmp_path, env={"PATH": "/usr/bin:/bin"})
    try:
        ticks = tmp_path / "ticks"
        assert wait_for(lambda: size(ticks) > 40)
        mp.pause()
        time.sleep(0.3)
        frozen = size(ticks)
        time.sleep(0.5)
        assert size(ticks) == frozen, "process kept running while paused"
        mp.resume()
        assert wait_for(lambda: size(ticks) > frozen + 40)
    finally:
        mp.kill()
    assert not mp.alive()


def test_spawned_process_is_group_leader(tmp_path):
    mp = procs.spawn(["sleep", "30"], cwd=tmp_path, env={"PATH": "/usr/bin:/bin"})
    try:
        assert os.getpgid(mp.pid) == mp.pid != os.getpgid(os.getpid())
    finally:
        mp.kill()


def test_terminate_escalates_to_kill_after_grace(tmp_path):
    script = "trap '' TERM; while true; do sleep 0.1; done"
    mp = procs.spawn(["sh", "-c", script], cwd=tmp_path, env={"PATH": "/usr/bin:/bin"})
    time.sleep(0.3)
    t0 = time.time()
    mp.terminate(grace_s=0.5)
    assert not mp.alive()
    assert 0.4 < time.time() - t0 < 3


def test_terminate_graceful_exit_is_fast(tmp_path):
    mp = procs.spawn(["sleep", "30"], cwd=tmp_path, env={"PATH": "/usr/bin:/bin"})
    t0 = time.time()
    mp.terminate(grace_s=5)
    assert not mp.alive() and time.time() - t0 < 2


def test_kill_takes_down_whole_group(tmp_path):
    mp = procs.spawn(["sh", "-c", "sleep 60 & sleep 60 & wait"], cwd=tmp_path,
                     env={"PATH": "/usr/bin:/bin"})
    assert wait_for(lambda: len(psutil.Process(mp.pid).children()) >= 2)
    kids = psutil.Process(mp.pid).children()
    mp.kill()
    assert wait_for(lambda: not any(k.is_running() and k.status() != "zombie" for k in kids))


SPAWNER = """
import subprocess, sys
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
open("child.pid", "w").write(str(child.pid))
"""


def test_orphan_sweep_kills_escaped_background_process(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run([sys.executable, "-c", SPAWNER], cwd=work, check=True)  # parent exits, child lives in its own session
    pid = int((work / "child.pid").read_text())
    assert psutil.pid_exists(pid)
    killed = procs.sweep(work)
    assert pid in killed
    assert wait_for(lambda: not psutil.pid_exists(pid) or psutil.Process(pid).status() == "zombie")


def test_sweep_ignores_unrelated_and_own_processes(tmp_path):
    work, other = tmp_path / "work", tmp_path / "other"
    work.mkdir()
    other.mkdir()
    bystander = subprocess.Popen(["sleep", "30"], cwd=other)
    try:
        assert procs.sweep(work) == []
        assert bystander.poll() is None
    finally:
        bystander.kill()
        bystander.wait()


def test_sweep_never_kills_caller(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # restored afterwards: later tests in this worker use relative paths
    assert os.getpid() not in procs.sweep(tmp_path)


def test_pause_includes_escaped_descendants_under_workdir(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    mp = procs.spawn(["sh", "-c", "python3 -c \"import subprocess,sys,time;"
                      "subprocess.Popen(['sh','-c','while true; do date >> esc; sleep 0.05; done'],"
                      "start_new_session=True); time.sleep(60)\""], cwd=work,
                     env={"PATH": "/usr/bin:/bin:/usr/local/bin"}, sweep_root=work)
    try:
        esc = work / "esc"
        assert wait_for(lambda: size(esc) > 40)
        mp.pause()
        time.sleep(0.3)
        frozen = size(esc)
        time.sleep(0.5)
        assert size(esc) == frozen, "escaped child kept running during pause"
        mp.resume()
        assert wait_for(lambda: size(esc) > frozen + 40)
    finally:
        mp.kill()
        procs.sweep(work)


def make_zombie(tmp_path):
    """A managed process that has exited but has not been reaped (the harness has not polled it)."""
    mp = procs.spawn(["true"], cwd=tmp_path, env={"PATH": "/usr/bin:/bin"})
    assert wait_for(lambda: psutil.Process(mp.pid).status() == psutil.STATUS_ZOMBIE), "never became a zombie"
    return mp


def test_pause_resume_on_an_exited_unreaped_process_do_not_raise(tmp_path):
    # macOS answers EPERM when signalling the group of a zombie; a checkpoint that lands between
    # turns used to crash the whole run with PermissionError (seen intermittently under load).
    mp = make_zombie(tmp_path)
    mp.pause()
    mp.resume()
    mp.kill()
    assert not mp.alive()


def test_terminate_on_an_exited_unreaped_process_does_not_raise(tmp_path):
    mp = make_zombie(tmp_path)
    mp.terminate(grace_s=1)
    assert not mp.alive()
