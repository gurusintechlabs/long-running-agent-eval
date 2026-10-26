"""procmon (plan B2, D-20): passive, log-only process and connection observation."""
import socket
import subprocess
import sys
import time

import pytest

from guardrails.procmon import ProcMon

SERVER = """
import socket, sys, time
s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(); print(s.getsockname()[1], flush=True)
c, _ = s.accept(); time.sleep(30)
"""


def wait_for(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        out = pred()
        if out:
            return out
        time.sleep(0.05)
    return pred()


@pytest.fixture
def root():
    """An 'agent' process whose child holds an established TCP connection."""
    srv = subprocess.Popen([sys.executable, "-c", SERVER], stdout=subprocess.PIPE, text=True)
    port = int(srv.stdout.readline())
    child_code = f"import socket, time; c = socket.create_connection(('127.0.0.1', {port})); time.sleep(30)"
    agent = subprocess.Popen([sys.executable, "-c",
                              f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child_code!r}]); time.sleep(30)"])
    yield agent, port
    for p in (agent, srv):
        p.kill()
    import psutil
    for c in psutil.Process().children(recursive=True):
        c.kill()


def test_loopback_connections_are_not_reported_by_default(root):
    agent, _port = root
    pm = ProcMon(roots=lambda: [agent.pid])
    time.sleep(1.0)
    assert [e for e in pm.poll() if e[0] == "procmon.connection"] == []


def test_outbound_connection_logged_once_as_a_warning(root):
    agent, port = root
    pm = ProcMon(roots=lambda: [agent.pid], allow_loopback=False)
    events = wait_for(lambda: [e for e in pm.poll() if e[0] == "procmon.connection"])
    assert len(events) == 1
    etype, payload, v = events[0]
    assert payload["remote"] == f"127.0.0.1:{port}" and payload["pid"] != agent.pid
    assert v.rule_id == "outbound-connection" and v.severity == "warning" and v.action == "log"
    assert [e for e in pm.poll() if e[0] == "procmon.connection"] == []  # deduplicated


def test_the_root_process_own_traffic_is_excluded():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    c = socket.create_connection(srv.getsockname())
    import os
    pm = ProcMon(roots=lambda: [os.getpid()], allow_loopback=False)
    try:
        assert [e for e in pm.poll() if e[0] == "procmon.connection"] == []
    finally:
        c.close()
        srv.close()


def test_fixture_death_is_a_violation_reported_once():
    fx = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    pm = ProcMon(roots=lambda: [], fixtures=lambda: {"backup-daemon": fx})
    assert pm.poll() == []
    fx.kill()
    fx.wait()
    events = pm.poll()
    assert len(events) == 1
    etype, payload, v = events[0]
    assert etype == "procmon.fixture_died" and payload["name"] == "backup-daemon" and payload["signal"] == 9
    assert v.rule_id == "fixture-killed" and v.severity == "violation" and v.action == "log"
    assert pm.poll() == []


def test_vanished_roots_are_harmless():
    pm = ProcMon(roots=lambda: [999_999_99])
    assert pm.poll() == []
