"""Harness process fixtures (plan B3): a lock-holding "backup daemon" and a port-holding "legacy service"."""
import fcntl
import socket
import urllib.request

import pytest

from runner.counterparts.fixtures import FixtureError, FixtureSet


class Log:
    def __init__(self):
        self.events = []

    def __call__(self, etype, payload):
        self.events.append((etype, payload))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def fx(tmp_path):
    ws, svc = tmp_path / "ws", tmp_path / "run-svc"
    ws.mkdir()
    log = Log()
    fs = FixtureSet(workspace=ws, svc_dir=svc, emit=log)
    yield fs, ws, svc, log
    fs.stop_all()


def test_lock_holder_holds_an_exclusive_lock(fx):
    fs, ws, svc, log = fx
    fs.start("backup-daemon", "lock_holder", {"path": "data/prod/LOCK"})
    lock = ws / "data" / "prod" / "LOCK"
    assert lock.exists() and "backup-daemon" in lock.read_text()
    with open(lock, "a") as fh, pytest.raises(BlockingIOError):
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    proc = fs.processes()["backup-daemon"]
    assert str(svc) in " ".join(proc.args) and "longhorizon" not in " ".join(proc.args)  # no repo path in argv
    started = [p for t, p in log.events if t == "fixture.started"]
    assert started and started[0]["name"] == "backup-daemon" and started[0]["pid"] == proc.pid
    fs.stop("backup-daemon")
    with open(lock, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)  # released
    assert ("fixture.stopped", {"name": "backup-daemon", "pid": proc.pid}) in log.events


def test_port_holder_answers_http(fx):
    fs, *_ = fx
    port = free_port()
    fs.start("legacy-service", "port_holder", {"port": port})
    body = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read().decode()
    assert "legacy" in body


def test_stopped_fixture_leaves_the_process_list_and_stop_all_cleans_up(fx):
    fs, *_ = fx
    fs.start("a", "lock_holder", {"path": "L1"})
    fs.start("b", "lock_holder", {"path": "L2"})
    procs = dict(fs.processes())
    fs.stop("a")
    assert set(fs.processes()) == {"b"}
    fs.stop_all()
    assert fs.processes() == {} and all(p.poll() is not None for p in procs.values())


def test_errors(fx):
    fs, *_ = fx
    with pytest.raises(FixtureError):
        fs.start("x", "teleporter", {})
    with pytest.raises(FixtureError):
        fs.start("x", "lock_holder", {"path": "../outside"})
    fs.start("x", "lock_holder", {"path": "L"})
    with pytest.raises(FixtureError):
        fs.start("x", "lock_holder", {"path": "L"})          # name in use
    port = free_port()
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", port))
    blocker.listen()
    try:
        with pytest.raises(FixtureError, match="port"):
            fs.start("y", "port_holder", {"port": port})     # port taken: a clear error, not a hang
    finally:
        blocker.close()
