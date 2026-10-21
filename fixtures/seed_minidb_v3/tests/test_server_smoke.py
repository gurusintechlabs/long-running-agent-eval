"""Smoke tests for the HTTP server stub: it starts, answers /healthz, and stops."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ADMIN_KEY = "smoke-test-admin-key"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(tmp_path):
    port = free_port()
    env = {**os.environ, "MINIDB_ADMIN_KEY": ADMIN_KEY}
    proc = subprocess.Popen([sys.executable, "-m", "minidb", "serve", "--data-dir", str(tmp_path / "data"),
                             "--port", str(port)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(url + "/healthz", timeout=1)
            break
        except OSError:
            time.sleep(0.05)
    yield url
    proc.terminate()
    proc.wait(timeout=10)


def test_healthz(server):
    with urllib.request.urlopen(server + "/healthz", timeout=5) as r:
        assert r.status == 200 and json.loads(r.read()) == {"status": "ok"}


def test_unknown_path_is_404(server):
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(urllib.request.Request(server + "/nope", headers={"Authorization": f"Bearer {ADMIN_KEY}"}),
                               timeout=5)
    assert e.value.code == 404
