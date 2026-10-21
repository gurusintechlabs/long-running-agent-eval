"""Black-box harness for the minidb v3 acceptance tests. Never imports the code under test.

Environment (set by the scorer, scorer.yaml):
  LRAE_WORKSPACE  absolute path of a temp copy of the repo under test (cwd of every server process)
  LRAE_PYTHON     interpreter for ``python -m minidb`` (the scorer venv: stdlib, numpy, pytest)
  LRAE_STAGE      the stage in force (docs/interfaces.md §9); unset = the final stage

* ``stage(introduced, retired=None)``: a test is active for ``introduced <= LRAE_STAGE < retired``.
* ``Server``: one ``python -m minidb serve`` process with its own data dir, port, admin key and log
  file (stdout and stderr), started with a scrubbed environment. ``Server.request`` never raises on an
  HTTP error status.
* ``FakeEmbed``: a deterministic stand-in for the shared embedding service (API v1 or v2, optional
  503s and 429s), counting requests. Its vectors are NOT normalised.
* ``clustered`` / ``exact_topk``: the hidden datasets (same family as ``bench/``, different seeds).

Conftest files are disabled (``--noconftest``): tests import the fixtures they use from here.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import random
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import numpy as np
import pytest

FINAL_STAGE = 13
READY_TIMEOUT_S = 20
HIDDEN_SEED = 51_017          # the visible bench/ uses another seed
DIM = 96


# ------------------------------------------------------------------ stages

def current_stage() -> int:
    raw = os.environ.get("LRAE_STAGE", "").strip()
    return int(raw) if raw else FINAL_STAGE


def stage(introduced: int, retired: int | None = None):
    """Active for ``introduced <= stage < retired`` (``retired=None``: forever)."""
    if not 0 <= introduced <= FINAL_STAGE or (retired is not None and not introduced < retired <= FINAL_STAGE):
        raise ValueError(f"bad stage window [{introduced}, {retired})")
    s = current_stage()
    active = introduced <= s and (retired is None or s < retired)
    mark = pytest.mark.skipif(not active, reason=f"stage window [{introduced}, {retired}) inactive at stage {s}")

    def deco(fn):
        fn = mark(fn)
        fn.lrae_stage = (introduced, retired)
        return fn
    return deco


def at_least(s: int) -> bool:
    return current_stage() >= s


# ------------------------------------------------------------------ processes

def workspace() -> Path:
    return Path(os.environ.get("LRAE_WORKSPACE", ".")).resolve()


def python() -> str:
    return os.environ.get("LRAE_PYTHON") or sys.executable


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def base_env(home: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {"PATH": f"{Path(python()).parent}:/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(home),
           "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
    env.update(extra or {})
    return env


def run_cli(args: list[str], *, env: dict[str, str] | None = None, timeout: float = 60,
            input: str | None = None) -> subprocess.CompletedProcess:
    """``python -m minidb <args>`` in the workspace (scrubbed env plus ``env``)."""
    home = Path(tempfile.mkdtemp(prefix="minidb-cli-home-"))
    return subprocess.run([python(), "-m", "minidb", *args], cwd=workspace(), env=base_env(home, env),
                          capture_output=True, text=True, timeout=timeout, input=input)


class Response:
    def __init__(self, status: int, headers: dict[str, str], body: bytes) -> None:
        self.status, self.headers, self.body = status, headers, body

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))

    @property
    def ctype(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    def __repr__(self) -> str:
        return f"<Response {self.status} {self.body[:300]!r}>"


class RawReply:
    """What came back on a raw connection: the bytes, whether the server closed it, and when."""

    def __init__(self, data: bytes, closed: bool, elapsed: float) -> None:
        self.data, self.closed, self.elapsed = data, closed, elapsed

    @property
    def status(self) -> int | None:
        line = self.data.split(b"\r\n", 1)[0].split()
        return int(line[1]) if len(line) >= 2 and line[0].startswith(b"HTTP/") and line[1].isdigit() else None

    def __repr__(self) -> str:
        return f"<RawReply closed={self.closed} after {self.elapsed:.1f}s {self.data[:200]!r}>"


class ServerExited(RuntimeError):
    pass


class Server:
    """One server process. ``start=False`` builds it without starting (for start-up tests)."""

    def __init__(self, root: Path, *, data_dir: Path | None = None, read_only: bool = False,
                 admin_key: str | None = None, env: dict[str, str] | None = None, embed: FakeEmbed | None = None,
                 rate_limit: int | None = 100_000, start: bool = True) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.data_dir = Path(data_dir) if data_dir else self.root / "data"
        self.read_only = read_only
        self.admin_key = admin_key if admin_key is not None else "adm-" + secrets.token_hex(16)
        self.extra_env = dict(env or {})
        self.embed = embed
        self.rate_limit = rate_limit
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self.n = 0
        self.log_path = self.root / "server.log"
        if start:
            self.start()

    # -- lifecycle
    def env(self) -> dict[str, str]:
        e = {"MINIDB_ADMIN_KEY": self.admin_key}
        if self.rate_limit is not None:
            e["MINIDB_RATE_LIMIT"] = str(self.rate_limit)
        if self.embed is not None:
            e.update(EMBED_URL=self.embed.url, EMBED_API_KEY=self.embed.key)
        e.update(self.extra_env)
        return {k: v for k, v in e.items() if v is not None}

    def command(self) -> list[str]:
        cmd = [python(), "-m", "minidb", "serve", "--data-dir", str(self.data_dir), "--port", str(self.port)]
        return cmd + (["--read-only"] if self.read_only else [])

    def spawn(self) -> subprocess.Popen:
        self.port = free_port()
        self.n += 1
        home = self.root / "home"
        home.mkdir(exist_ok=True)
        fh = open(self.log_path, "ab")
        fh.write(f"\n=== start {self.n} ===\n".encode())
        fh.flush()
        self.proc = subprocess.Popen(self.command(), cwd=workspace(), env=base_env(home, self.env()), stdout=fh,
                                     stderr=subprocess.STDOUT, start_new_session=True)
        fh.close()
        return self.proc

    def start(self, timeout: float = READY_TIMEOUT_S) -> Server:
        self.spawn()
        self.wait_ready(timeout)
        return self

    def wait_ready(self, timeout: float = READY_TIMEOUT_S) -> float:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if self.proc.poll() is not None:
                raise ServerExited(f"server exited with {self.proc.returncode}: {self.log()[-1500:]}")
            try:
                if self.request("GET", "/healthz", key=None, timeout=1).status == 200:
                    return time.monotonic() - t0
            except OSError:
                pass
            time.sleep(0.05)
        raise ServerExited(f"server not ready after {timeout}s: {self.log()[-1500:]}")

    def kill(self) -> None:
        """SIGKILL (a crash)."""
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait(timeout=10)

    def stop(self, timeout: float = 10) -> int | None:
        """SIGTERM, then SIGKILL after ``timeout``. Returns the exit status of the SIGTERM path."""
        if not self.proc or self.proc.poll() is not None:
            return self.proc.returncode if self.proc else None
        self.proc.send_signal(signal.SIGTERM)
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.kill()
            return None

    def restart(self, *, crash: bool = False) -> float:
        """Stop (or SIGKILL) and start again on the same data dir. Returns seconds until ready."""
        self.kill() if crash else self.stop()
        self.spawn()
        return self.wait_ready()

    def close(self) -> None:
        self.stop(timeout=5)
        if self.proc:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)   # stray children
            except (ProcessLookupError, PermissionError):
                pass

    def log(self) -> str:
        try:
            return self.log_path.read_text(errors="replace")
        except OSError:
            return ""

    # -- HTTP
    def request(self, method: str, path: str, body: Any = None, *, key: str | None | type = ...,
                headers: dict[str, str] | None = None, data: bytes | None = None, timeout: float = 60) -> Response:
        """``key=...`` (default): the admin key; ``key=None``: no Authorization header."""
        h = {}
        k = self.admin_key if key is ... else key
        if k is not None:
            h["Authorization"] = f"Bearer {k}"
        if body is not None and data is None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            conn.request(method, path, body=data, headers=h)
            r = conn.getresponse()
            return Response(r.status, {k.lower(): v for k, v in r.getheaders()}, r.read())
        finally:
            conn.close()

    def get(self, path: str, **kw) -> Response:
        return self.request("GET", path, **kw)

    def post(self, path: str, body: Any = None, **kw) -> Response:
        return self.request("POST", path, body if body is not None else {}, **kw)

    def put(self, path: str, body: Any = None, **kw) -> Response:
        return self.request("PUT", path, body if body is not None else {}, **kw)

    def delete(self, path: str, **kw) -> Response:
        return self.request("DELETE", path, **kw)

    def sql(self, sql: str, **kw) -> list[dict]:
        r = self.post("/v1/sql", {"sql": sql}, **kw)
        assert r.status == 200, r
        return r.json()["results"]

    def declared_body(self, method: str, path: str, length: int, *, key: str | None | type = ...,
                      timeout: float = 10) -> RawReply:
        """Headers announcing a body of ``length`` bytes, and no body: the size check must not wait."""
        k = self.admin_key if key is ... else key
        auth = f"Authorization: Bearer {k}\r\n" if k is not None else ""
        return self.raw(f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n{auth}Content-Type: application/json\r\n"
                        f"Content-Length: {length}\r\nConnection: close\r\n\r\n".encode(), timeout=timeout)

    def raw(self, data: bytes, *, timeout: float = 15, then_wait: float = 0.0) -> RawReply:
        """Send raw bytes on a fresh connection; read until the server closes it or ``timeout``."""
        t0 = time.monotonic()
        s = socket.create_connection(("127.0.0.1", self.port), timeout=timeout)
        try:
            s.sendall(data)
            if then_wait:
                time.sleep(then_wait)
            buf = b""
            closed = False
            while True:
                left = timeout - (time.monotonic() - t0)
                if left <= 0:
                    break
                s.settimeout(left)
                try:
                    chunk = s.recv(65536)
                except TimeoutError:
                    break
                except OSError:
                    closed = True
                    break
                if not chunk:
                    closed = True
                    break
                buf += chunk
            return RawReply(buf, closed, time.monotonic() - t0)
        finally:
            s.close()

    def __enter__(self) -> Server:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


@pytest.fixture
def server(tmp_path):
    s = Server(tmp_path / "srv")
    yield s
    s.close()


@pytest.fixture(scope="module")
def shared(tmp_path_factory):
    """One server per test module (tests use their own table / collection names)."""
    s = Server(tmp_path_factory.mktemp("shared"))
    yield s
    s.close()


def cli_results(script: str, *, db: Path | None = None) -> list[dict]:
    """The result objects ``python -m minidb [--db PATH]`` prints for ``script``."""
    p = run_cli(["--db", str(db)] if db else [], input=script, timeout=120)
    assert p.returncode == 0, p.stderr[-2000:]
    return [json.loads(line) for line in p.stdout.splitlines() if line.strip()]


def tree_state(path: Path) -> dict[str, bytes]:
    """Every file under ``path`` with its bytes (to show that nothing changed)."""
    path = Path(path)
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in sorted(path.rglob("*")) if p.is_file()}


def unique(prefix: str = "t") -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


# ------------------------------------------------------------------ fake embedding service

class FakeEmbed:
    """API ``v1``: ``POST /v1/embed {"texts"}`` -> ``{"embeddings"}``. API ``v2``: ``POST /v2/embeddings
    {"input"}`` + ``X-Api-Version: 2`` -> ``{"data": [{"index", "embedding"}]}`` (v1 is then 410).
    ``flaky``: share of requests answered 503; ``burst_429``: every n-th request answered 429 with
    ``Retry-After: 1``. Max 64 texts per request (else 400)."""

    def __init__(self, *, api: str = "v1", dim: int = DIM, flaky: float = 0.0, burst_429: int = 0, seed: int = 1):
        self.api, self.dim, self.flaky, self.burst_429 = api, dim, flaky, burst_429
        self.key = "emb-" + secrets.token_hex(12)
        self.rng = random.Random(seed)
        self.requests: list[dict] = []
        self.lock = threading.Lock()
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                outer._serve(self)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def vector(self, text: str) -> list[float]:
        r = random.Random(int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big"))
        scale = 0.5 + r.random() * 3.0                      # never unit length
        return [round(r.gauss(0.0, 1.0) * scale, 6) for _ in range(self.dim)]

    def texts_seen(self) -> list[str]:
        return [t for r in self.requests if r["status"] == 200 for t in r["texts"]]

    def _reply(self, h, code, obj, headers=None):
        data = json.dumps(obj).encode()
        h.send_response(code)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            h.send_header(k, v)
        h.end_headers()
        h.wfile.write(data)

    def _serve(self, h) -> None:
        body = h.rfile.read(int(h.headers.get("Content-Length") or 0))
        try:
            obj = json.loads(body or b"{}")
        except ValueError:
            obj = {}
        texts = obj.get("texts") if h.path == "/v1/embed" else obj.get("input")
        with self.lock:
            n = len(self.requests) + 1
            fault = None
            if self.burst_429 and n % self.burst_429 == 0:
                fault = 429
            elif self.flaky and self.rng.random() < self.flaky:
                fault = 503
            rec = {"path": h.path, "texts": list(texts or []), "status": None, "auth": h.headers.get("Authorization")}
            self.requests.append(rec)

        def done(code, payload, headers=None):
            rec["status"] = code
            self._reply(h, code, payload, headers)
        if h.headers.get("Authorization") != f"Bearer {self.key}":
            return done(401, {"error": "invalid key"})
        if h.path == "/v1/embed" and self.api == "v2":
            return done(410, {"error": "v1 is retired; use POST /v2/embeddings with X-Api-Version: 2"})
        if h.path not in ("/v1/embed", "/v2/embeddings") or (h.path == "/v2/embeddings" and self.api == "v1"):
            return done(404, {"error": "not found"})
        if h.path == "/v2/embeddings" and h.headers.get("X-Api-Version") != "2":
            return done(400, {"error": "X-Api-Version: 2 is required"})
        if not isinstance(texts, list) or not texts or len(texts) > 64 or not all(isinstance(t, str) for t in texts):
            return done(400, {"error": "1 to 64 texts required"})
        if fault == 429:
            return done(429, {"error": "rate limited"}, {"Retry-After": "1"})
        if fault == 503:
            return done(503, {"error": "busy"})
        if h.path == "/v1/embed":
            return done(200, {"model": "fake-embed-1", "embeddings": [self.vector(t) for t in texts]})
        data = [{"index": i, "embedding": self.vector(t)} for i, t in enumerate(texts)]
        return done(200, {"model": "fake-embed-2", "data": list(reversed(data))})   # order is not guaranteed

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


# ------------------------------------------------------------------ datasets

def clustered(n: int, *, dim: int = DIM, queries: int = 200, seed: int = HIDDEN_SEED,
              clusters: int = 64) -> tuple[np.ndarray, np.ndarray]:
    """``(base [n, dim], queries [queries, dim])`` float32, around ``clusters`` random centres."""
    rng = np.random.default_rng(seed)
    centres = rng.normal(0.0, 1.0, (clusters, dim)).astype(np.float32)
    spread = rng.uniform(0.15, 0.45, clusters).astype(np.float32)
    which = rng.integers(0, clusters, n + queries)
    pts = centres[which] + rng.normal(0.0, 1.0, (n + queries, dim)).astype(np.float32) * spread[which, None]
    return pts[:n].astype(np.float32), pts[n:].astype(np.float32)


def scores(base: np.ndarray, q: np.ndarray, metric: str, *, cr1: bool | None = None) -> np.ndarray:
    """The score of every base point for query ``q`` (stage 1 semantics before CR-1, else CR-1)."""
    after = at_least(3) if cr1 is None else cr1
    b, qq = base.astype(np.float64), np.asarray(q, dtype=np.float64)
    if metric == "l2":
        return np.sqrt(((b - qq) ** 2).sum(1))
    if metric == "cosine":
        cos = (b @ qq) / (np.linalg.norm(b, axis=1) * np.linalg.norm(qq))
        return cos if after else 1.0 - cos
    dot = b @ qq
    return dot if after else -dot


def descending(metric: str, *, cr1: bool | None = None) -> bool:
    after = at_least(3) if cr1 is None else cr1
    return after and metric in ("cosine", "dot")


def exact_topk(base: np.ndarray, q: np.ndarray, k: int, metric: str = "l2", *, ids=None,
               cr1: bool | None = None) -> list[tuple[int, float]]:
    """Exact top-``k`` ``(id, score)`` with the server's ordering rules (ties by id ascending)."""
    s = scores(base, q, metric, cr1=cr1)
    ids = list(range(len(base))) if ids is None else list(ids)
    order = sorted(range(len(ids)), key=lambda i: ((-s[i]) if descending(metric, cr1=cr1) else s[i], ids[i]))
    return [(ids[i], float(s[i])) for i in order[:k]]


def upsert_all(srv: Server, coll: str, base: np.ndarray, *, batch: int = 1000, payload=None, start_id: int = 0,
               key=...) -> None:
    for i in range(0, len(base), batch):
        pts = [{"id": start_id + j, "vector": base[j].tolist(),
                **({"payload": payload(start_id + j)} if payload else {})} for j in range(i, min(i + batch, len(base)))]
        r = srv.put(f"/v1/collections/{coll}/points", {"points": pts}, key=key, timeout=600)
        assert r.status == 200, r


def recall_at(found: list[list], truth: list[list]) -> float:
    hits = sum(len(set(f) & set(t)) for f, t in zip(found, truth, strict=True))
    return hits / sum(len(t) for t in truth)


def error_kind(r: Response) -> str | None:
    """The error kind of a response in the format of the active stage: the stage-0 ``error.type`` before
    CR-3, the problem slug from stage 3 on."""
    try:
        body = r.json()
    except ValueError:
        return None
    if at_least(3):
        t = body.get("type", "") if isinstance(body, dict) else ""
        return t.rsplit("/", 1)[-1] if t.startswith("https://minidb.dev/problems/") else None
    err = body.get("error") if isinstance(body, dict) else None
    return err.get("type") if isinstance(err, dict) else None


SLUG = {400: "bad-request", 401: "unauthorized", 403: "forbidden", 404: "not-found", 405: "method-not-allowed",
        409: "conflict", 411: "length-required", 413: "payload-too-large", 429: "too-many-requests",
        500: "internal-error", 502: "bad-gateway", 503: "unavailable"}
TYPE = {400: "BadRequest", 401: "Unauthorized", 403: "Forbidden", 404: "NotFound", 405: "MethodNotAllowed",
        409: "Conflict", 411: "LengthRequired", 413: "PayloadTooLarge", 500: "InternalError"}


def expect_error(r: Response, status: int) -> None:
    """``r`` is an error of ``status`` in the active stage's error format."""
    assert r.status == status, r
    if at_least(3):
        assert r.ctype == "application/problem+json", r.headers
        body = r.json()
        assert body["status"] == status and error_kind(r) == SLUG[status], body
        assert {"type", "title", "status", "detail", "instance"} <= set(body), body
    else:
        assert error_kind(r) == TYPE[status], r
