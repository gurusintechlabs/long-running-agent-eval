"""A server process for the tests: ``python -m minidb serve`` on a free port, with its own data dir."""
from __future__ import annotations

import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADMIN_KEY = "test-admin-key"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Proc:
    def __init__(self, data_dir: Path, *, key: str | None = ADMIN_KEY, extra: list[str] | None = None,
                 env: dict[str, str] | None = None) -> None:
        self.data_dir = Path(data_dir)
        self.key = key
        self.port = free_port()
        e = {k: v for k, v in os.environ.items() if k != "MINIDB_ADMIN_KEY"}
        if key is not None:
            e["MINIDB_ADMIN_KEY"] = key
        e.update(env or {})
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "minidb", "serve", "--data-dir", str(self.data_dir), "--port", str(self.port),
             *(extra or [])], cwd=ROOT, env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def wait_ready(self, timeout: float = 20) -> Proc:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited with {self.proc.returncode}: {self.proc.stderr.read()!r}")
            try:
                if self.request("GET", "/healthz", key=None)[0] == 200:
                    return self
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("server not ready")

    def request(self, method: str, path: str, body=None, *, key: str | None | type = ..., raw: bytes | None = None,
                headers: dict | None = None):
        h = dict(headers or {})
        k = self.key if key is ... else key
        if k is not None:
            h["Authorization"] = f"Bearer {k}"
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        try:
            conn.request(method, path, body=data, headers=h)
            r = conn.getresponse()
            payload = r.read()
            return r.status, (json.loads(payload) if payload else None), dict(r.getheaders())
        finally:
            conn.close()

    def sql(self, text: str) -> list[dict]:
        status, body, _ = self.request("POST", "/v1/sql", {"sql": text})
        assert status == 200, body
        return body["results"]

    def stop(self, sig=signal.SIGTERM) -> int:
        if self.proc.poll() is None:
            self.proc.send_signal(sig)
        try:
            return self.proc.wait(timeout=10)
        finally:
            for f in (self.proc.stdout, self.proc.stderr):
                f.close()

    def kill(self) -> None:
        self.proc.kill()
        self.proc.wait(timeout=10)
        for f in (self.proc.stdout, self.proc.stderr):
            f.close()
