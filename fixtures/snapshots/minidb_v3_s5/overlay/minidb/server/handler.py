"""HTTP/1.1 request handling: framing, limits, authentication, routing and error responses.

Order of checks for every request: ``GET /healthz`` needs nothing; everything else first needs a
valid key (401), then a token from the key's rate limit (429), then a known path and method (404,
405), then the route's access policy (a collection the key has no grant on is 404, exactly as a
missing one; a role too low is 403), then a well-formed body (411, 413, 400).
A request that is refused before its body is read closes the connection, so leftover body bytes are
never parsed as a next request. Bodies are read against a deadline (``BODY_DEADLINE_S``).
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs

from minidb.auth import Principal
from minidb.server.errors import ApiError, error_body

log = logging.getLogger("minidb.server")

MAX_BODY = 1 << 20            # 1 MiB
BODY_DEADLINE_S = 8.0         # a client that stops mid-body is dropped well within 10 s
IDLE_TIMEOUT_S = 10.0
BODY_METHODS = ("POST", "PUT", "PATCH")


@dataclass
class Request:
    method: str
    path: str
    params: dict[str, str]
    headers: Any
    service: Any
    raw: bytes = b""
    principal: Principal | None = None
    query: dict[str, str] = field(default_factory=dict)
    _json: Any = field(default=None, repr=False)
    _parsed: bool = False

    def json(self) -> Any:
        if not self._parsed:
            self._json = parse_json(self.raw)
            self._parsed = True
        return self._json

    def object(self) -> dict:
        body = self.json()
        if not isinstance(body, dict):
            raise ApiError(400, "the request body must be a JSON object")
        return body


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not valid JSON")


def parse_json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise ApiError(400, "the request body is not valid JSON") from None


# Access policies of routes: "any" (every valid key), "admin", or ("collection", "read" | "write" |
# "admin") for routes with a {name} parameter.
Policy = Any


def authorize(principal: Principal, policy: Policy, params: dict[str, str]) -> None:
    if policy == "any":
        return
    if policy == "admin":
        if principal.role != "admin":
            raise ApiError(403, "this endpoint needs an admin key")
        return
    _, action = policy
    if not principal.sees(params.get("name", "")):
        raise ApiError(404, "no such collection")
    if not principal.allows(action):
        raise ApiError(403, f"this key's role ({principal.role}) does not allow this request")


@dataclass
class Route:
    pattern: re.Pattern
    methods: dict[str, Callable[[Request], tuple[int, Any]]]
    max_body: dict[str, int] = field(default_factory=dict)
    policy: dict[str, Policy] = field(default_factory=dict)


class Router:
    def __init__(self) -> None:
        self.routes: list[Route] = []

    def add(self, template: str, method: str, fn: Callable, *, policy: Policy, max_body: int = MAX_BODY) -> None:
        """``template``: a path with ``{name}`` segments (each matches one non-empty segment)."""
        rx = re.compile("^" + re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>[^/]+)", re.escape(template)) + "$")
        for r in self.routes:
            if r.pattern.pattern == rx.pattern:
                break
        else:
            r = Route(rx, {})
            self.routes.append(r)
        r.methods[method] = fn
        r.max_body[method] = max_body
        r.policy[method] = policy

    def match(self, method: str, path: str) -> tuple[Route, dict[str, str]]:
        allowed: set[str] = set()
        for r in self.routes:
            m = r.pattern.match(path)
            if m is None:
                continue
            if method in r.methods:
                return r, m.groupdict()
            allowed |= set(r.methods)
        if allowed:
            raise ApiError(405, f"method {method} is not allowed on this path",
                           headers={"Allow": ", ".join(sorted(allowed))})
        raise ApiError(404, "no such endpoint")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "minidb/0.2"
    sys_version = ""
    timeout = IDLE_TIMEOUT_S

    # ------------------------------------------------------------ framing

    def handle_one_request(self) -> None:
        try:
            self.raw_requestline = self.rfile.readline(65537)
            if len(self.raw_requestline) > 65536:
                self.requestline, self.request_version, self.command = "", "", ""
                self.send_error(400, "request line too long")
                return
            if not self.raw_requestline:
                self.close_connection = True
                return
            if not self.parse_request():
                return
            self._dispatch()
            self.wfile.flush()
        except (TimeoutError, ConnectionError):
            self.close_connection = True

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """Malformed requests detected by ``http.server`` (bad request line, headers, version)."""
        self.close_connection = True
        self._send_error(ApiError(400 if code != 500 else 500, message or "malformed request"))

    def log_message(self, fmt: str, *args) -> None:  # http.server's own access log: unused
        pass

    # ------------------------------------------------------------ dispatch

    def _dispatch(self) -> None:
        srv = self.server
        t0 = time.monotonic()
        srv.request_started()
        status = 0
        method, path = self.command, self.path.split("?", 1)[0]
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        try:
            if srv.stopping:
                self.close_connection = True
            try:
                if method == "GET" and path == "/healthz":
                    status, obj = 200, {"status": "ok"}
                else:
                    principal = self._authenticate()
                    wait = srv.limiter.take(principal.id)
                    if wait is not None:
                        self.close_connection = True
                        raise ApiError(429, "rate limit exceeded for this key", headers={"Retry-After": str(wait)})
                    route, params = srv.router.match(method, path)
                    authorize(principal, route.policy[method], params)
                    raw = self._read_body(route.max_body.get(method, MAX_BODY))
                    req = Request(method, path, params, self.headers, srv.service, raw, principal,
                                  {k: v[-1] for k, v in parse_qs(query, keep_blank_values=True).items()})
                    status, obj = route.methods[method](req)
            except ApiError as e:
                status = e.status
                self._send_error(e)
                return
            except (TimeoutError, ConnectionError):   # the client stalled or vanished mid-body
                self.close_connection = True
                return
            except Exception:  # noqa: BLE001 - a bug: log it, answer a generic 500
                status = 500
                log.error("unhandled error on %s %s\n%s", method, path, traceback.format_exc())
                self._send_error(ApiError(500, "internal error"))
                return
            self._send_json(status, obj)
        finally:
            srv.request_finished()
            log.info("%s %s %d %.1fms", method, path[:200], status, (time.monotonic() - t0) * 1000)

    def _authenticate(self) -> Principal:
        header = self.headers.get("Authorization") or ""
        scheme, _, key = header.partition(" ")
        key = key.strip()
        principal = self.server.service.keys.authenticate(key) if scheme.lower() == "bearer" and key else None
        if principal is None:
            self.close_connection = True
            raise ApiError(401, "a valid API key is required (Authorization: Bearer <key>)")
        return principal

    def _read_body(self, limit: int) -> bytes:
        method = self.command
        te = self.headers.get("Transfer-Encoding")
        cl = self.headers.get("Content-Length")
        if te is not None and te.strip().lower() != "identity":
            self.close_connection = True
            raise ApiError(411, "chunked bodies are not supported; send Content-Length")
        if cl is None:
            if method in BODY_METHODS:
                self.close_connection = True
                raise ApiError(411, "Content-Length is required")
            return b""
        cl = cl.strip()
        if not cl.isdigit():
            self.close_connection = True
            raise ApiError(400, "invalid Content-Length")
        n = int(cl)
        if n > limit:
            self.close_connection = True
            raise ApiError(413, f"the request body is larger than {limit} bytes")
        return self._read_exact(n)

    def _read_exact(self, n: int) -> bytes:
        deadline = time.monotonic() + BODY_DEADLINE_S
        chunks, got = [], 0
        sock = self.connection
        try:
            while got < n:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                sock.settimeout(remaining)
                chunk = self.rfile.read1(min(n - got, 1 << 16))
                if not chunk:
                    raise ConnectionError("client closed the connection mid-body")
                chunks.append(chunk)
                got += len(chunk)
        finally:
            sock.settimeout(IDLE_TIMEOUT_S)
        return b"".join(chunks)

    # ------------------------------------------------------------ responses

    def _send_error(self, e: ApiError) -> None:
        ctype, body = error_body(e.status, e.message, (getattr(self, "path", "") or "").split("?", 1)[0])
        self._send_json(e.status, body, ctype=ctype, headers=e.headers)

    def _send_json(self, status: int, obj: Any, *, ctype: str = "application/json",
                   headers: dict[str, str] | None = None) -> None:
        # ASCII escapes: any string (even a lone surrogate from a client's \ud800) encodes safely
        data = json.dumps(obj, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")
        self.send_response_only(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if self.close_connection or self.server.stopping:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)


def configure_logging() -> None:
    """Access lines and errors to stderr. Never request headers or bodies (they carry keys and data)."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(message)s")
