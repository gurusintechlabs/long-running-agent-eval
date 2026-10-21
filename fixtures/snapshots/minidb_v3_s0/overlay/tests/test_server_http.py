"""The HTTP server (stage 0): startup, keys, /v1/sql, errors, limits, shutdown."""
import fcntl
import os
import signal
import socket
import threading

import pytest

from minidb.server import api, app, errors, handler
from tests.server_util import ADMIN_KEY, Proc


@pytest.fixture
def srv(tmp_path):
    p = Proc(tmp_path / "data").wait_ready()
    yield p
    p.stop()


def test_healthz_needs_no_key(srv):
    assert srv.request("GET", "/healthz", key=None)[:2] == (200, {"status": "ok"})


def test_missing_admin_key_exits_2(tmp_path):
    p = Proc(tmp_path / "d", key="")
    assert p.proc.wait(timeout=10) == 2
    assert b"MINIDB_ADMIN_KEY" in p.proc.stderr.read()
    p.stop()


def test_wrong_or_missing_key_is_401(srv):
    for key in (None, "nope", ADMIN_KEY + "x"):
        status, body, _ = srv.request("POST", "/v1/sql", {"sql": "SELECT 1;"}, key=key)
        assert status == 401 and body["error"]["type"] == "Unauthorized"


def test_sql_results_match_the_protocol(srv):
    res = srv.sql("CREATE TABLE t (a INTEGER); INSERT INTO t VALUES (1), (2); SELECT SUM(a) FROM t; SELECT nope;")
    assert res[:3] == [{"ok": True}, {"ok": True, "rowcount": 2}, {"ok": True, "columns": ["sum"], "rows": [[3]]}]
    assert res[3]["ok"] is False and res[3]["error"]["type"] == "NameError"


def test_open_transaction_is_rolled_back_at_the_end_of_the_request(srv):
    srv.sql("CREATE TABLE t (a INTEGER);")
    srv.sql("BEGIN; INSERT INTO t VALUES (1);")
    assert srv.sql("SELECT COUNT(*) FROM t;")[0]["rows"] == [[0]]


def test_errors(srv):
    assert srv.request("GET", "/nope")[0] == 404
    status, body, headers = srv.request("GET", "/v1/sql")
    assert status == 405 and headers["Allow"] == "POST" and body["error"]["type"] == "MethodNotAllowed"
    assert srv.request("POST", "/v1/sql", raw=b"{nope")[0] == 400
    assert srv.request("POST", "/v1/sql", {"sql": 3})[0] == 400


def _raw(port: int, data: bytes, timeout: float = 15) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
        s.sendall(data)
        out = b""
        while chunk := s.recv(65536):
            out += chunk
        return out


def test_length_required_and_payload_too_large(srv):
    head = f"POST /v1/sql HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {ADMIN_KEY}\r\nConnection: close\r\n"
    assert _raw(srv.port, (head + "\r\n").encode()).startswith(b"HTTP/1.1 411")
    assert _raw(srv.port, (head + f"Content-Length: {handler.MAX_BODY + 1}\r\n\r\n").encode()).startswith(b"HTTP/1.1 413")


def test_stalled_body_is_dropped(srv):
    head = f"POST /v1/sql HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {ADMIN_KEY}\r\nContent-Length: 50\r\n\r\n{{"
    out = _raw(srv.port, head.encode(), timeout=handler.BODY_DEADLINE_S + 5)
    assert out == b""          # closed without an answer once the deadline passed


def test_data_survives_a_crash(tmp_path):
    p = Proc(tmp_path / "data").wait_ready()
    p.sql("CREATE TABLE t (a INTEGER); INSERT INTO t VALUES (7);")
    p.kill()
    p = Proc(tmp_path / "data").wait_ready()
    assert p.sql("SELECT a FROM t;")[0]["rows"] == [[7]]
    assert p.stop() == 0


def test_busy_lock_exits_3(tmp_path):
    d = tmp_path / "data"
    p = Proc(d).wait_ready()
    assert p.stop() == 0
    fd = os.open(d / "LOCK", os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.ftruncate(fd, 0)
        os.write(fd, b"backup-daemon pid 1\n")
        q = Proc(d)
        assert q.proc.wait(timeout=10) == 3
        assert b"backup-daemon pid 1" in q.proc.stderr.read()
        q.stop()
    finally:
        os.close(fd)


def test_sigterm_finishes_requests_in_flight(srv):
    rows = ",".join(f"({i})" for i in range(800))
    srv.sql(f"CREATE TABLE s (x INTEGER); INSERT INTO s VALUES {rows};")
    out = {}
    th = threading.Thread(target=lambda: out.setdefault(
        "r", srv.sql("SELECT COUNT(*) FROM s a CROSS JOIN s b WHERE a.x < b.x;")))
    th.start()
    threading.Event().wait(0.2)
    srv.proc.send_signal(signal.SIGTERM)
    th.join(20)
    assert out["r"][0]["rows"] == [[800 * 799 // 2]]
    assert srv.proc.wait(timeout=10) == 0


def test_router_matches_exactly():
    r = api.router()
    assert r.match("POST", "/v1/sql")[1] == {}
    for path in ("/v1/sql/", "/V1/sql", "/v1/%73ql"):
        with pytest.raises(errors.ApiError) as e:
            r.match("POST", path)
        assert e.value.status == 404
    with pytest.raises(errors.ApiError) as e:
        r.match("GET", "/v1/sql")
    assert e.value.status == 405 and e.value.headers == {"Allow": "POST"}


def test_parse_json_rejects_non_json_constants_and_deep_nesting():
    assert handler.parse_json(b'{"a": [1, 2.5]}') == {"a": [1, 2.5]}
    for raw in (b"NaN", b'{"a": Infinity}', b"[" * 100_000, b"\xff"):
        with pytest.raises(errors.ApiError):
            handler.parse_json(raw)


def test_error_body_hides_internal_messages():
    assert errors.error_body(500, "KeyError: /secret/path", "/x")[1] == {
        "error": {"type": "InternalError", "message": errors.INTERNAL_MESSAGE}}


def test_app_main_usage(tmp_path, monkeypatch):
    monkeypatch.delenv("MINIDB_ADMIN_KEY", raising=False)
    assert app.main(["--data-dir", str(tmp_path / "d"), "--port", "1"]) == 2
