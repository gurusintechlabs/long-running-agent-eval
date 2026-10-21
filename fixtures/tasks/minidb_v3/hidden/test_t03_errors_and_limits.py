"""t03 (stage 0): paths, methods, framing limits and the error model (brief 0.2, 0.3)."""
import http.client
import json
import threading

from _support import error_kind, expect_error, shared, stage, unique  # noqa: F401

MIB = 1_048_576


def _head(srv, method, path, extra=""):
    return (f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {srv.admin_key}\r\n"
            f"{extra}Connection: close\r\n\r\n").encode()


@stage(0)
def test_an_unknown_path_is_404(shared):  # noqa: F811
    for path in ("/nope", "/v1", "/v1/sqlx", "/v2/sql"):
        expect_error(shared.get(path), 404)
        expect_error(shared.post(path, {"sql": "SELECT 1;"}), 404)


@stage(0)
def test_paths_are_matched_exactly(shared):  # noqa: F811
    for path in ("/v1/sql/", "/V1/sql", "/v1/SQL", "/v1/%73ql", "/v1//sql", "/v1/./sql"):
        expect_error(shared.post(path, {"sql": "SELECT 1;"}), 404)


@stage(0)
def test_a_wrong_method_is_405_with_allow(shared):  # noqa: F811
    for method in ("GET", "DELETE", "PUT", "PATCH"):
        r = shared.request(method, "/v1/sql", {"sql": "SELECT 1;"} if method in ("PUT", "PATCH") else None)
        expect_error(r, 405)
        assert "POST" in [m.strip() for m in r.headers.get("allow", "").split(",")], r.headers


@stage(0)
def test_a_body_without_content_length_is_411(shared):  # noqa: F811
    r = shared.raw(_head(shared, "POST", "/v1/sql"), timeout=10)
    assert r.status == 411, r
    r = shared.raw(_head(shared, "POST", "/v1/sql", "Transfer-Encoding: chunked\r\n") + b"5\r\n{\"a\":\r\n0\r\n\r\n",
                   timeout=10)
    assert r.status in (411, 400), r


@stage(0)
def test_a_body_over_1_mib_is_413_without_reading_it(shared):  # noqa: F811
    r = shared.raw(_head(shared, "POST", "/v1/sql", f"Content-Length: {MIB + 1}\r\n") + b'{"sql": "', timeout=10)
    assert r.status == 413 and r.elapsed < 5, r
    body = r.data.split(b"\r\n\r\n", 1)[1]
    assert error_kind_ok(body, 413)
    r = shared.raw(_head(shared, "POST", "/v1/sql", "Content-Length: 50000000000\r\n"), timeout=10)
    assert r.status == 413, r


def error_kind_ok(body: bytes, status: int) -> bool:
    try:
        obj = json.loads(body)
    except ValueError:
        return False
    return isinstance(obj, dict) and bool(obj)


@stage(0)
def test_a_body_of_exactly_1_mib_is_accepted(shared):  # noqa: F811
    prefix = b'{"sql": "SELECT 41 + 1;'
    body = prefix + b" " * (MIB - len(prefix) - 2) + b'"}'
    assert len(body) == MIB
    r = shared.request("POST", "/v1/sql", data=body, headers={"Content-Type": "application/json"})
    assert r.status == 200 and r.json()["results"][0]["rows"] == [[42]], r


@stage(0)
def test_invalid_json_is_400(shared):  # noqa: F811
    for data in (b"", b"{", b'{"sql": "SELECT 1;"', b"\xff\xfe", b'{"sql": NaN}', b"[" * 50_000 + b"]" * 50_000):
        expect_error(shared.request("POST", "/v1/sql", data=data), 400)


@stage(0)
def test_a_stalled_body_does_not_hold_a_worker_timing(shared):  # noqa: F811
    stalled = {}

    def stall():
        stalled["r"] = shared.raw(_head(shared, "POST", "/v1/sql", "Content-Length: 100\r\n") + b'{"sql": "SE',
                                  timeout=14)
    threads = [threading.Thread(target=stall) for _ in range(4)]
    for t in threads:
        t.start()
    assert shared.sql("SELECT 1;")[0]["ok"] is True        # other clients are served meanwhile
    for t in threads:
        t.join(20)
    r = stalled["r"]
    assert r.closed and r.elapsed <= 11.5, r
    assert r.status in (None, 400, 408), r


@stage(0)
def test_keep_alive_connections_serve_several_requests(shared):  # noqa: F811
    conn = http.client.HTTPConnection("127.0.0.1", shared.port, timeout=10)
    try:
        for i in range(3):
            conn.request("POST", "/v1/sql", body=json.dumps({"sql": f"SELECT {i};"}),
                         headers={"Authorization": f"Bearer {shared.admin_key}"})
            r = conn.getresponse()
            assert r.status == 200 and json.loads(r.read())["results"][0]["rows"] == [[i]]
    finally:
        conn.close()


@stage(0)
def test_responses_are_json_with_a_length(shared):  # noqa: F811
    rs = [shared.post("/v1/sql", {"sql": "SELECT 1;"}), shared.get("/nope"), shared.get("/healthz", key=None)]
    assert [r.status for r in rs] == [200, 404, 200], rs
    for r in rs:
        assert r.ctype in ("application/json", "application/problem+json"), r.headers
        assert int(r.headers["content-length"]) == len(r.body)
        json.loads(r.body)


@stage(0, 3)
def test_error_bodies_follow_the_stage_0_error_model(shared):  # noqa: F811
    cases = [(shared.post("/v1/sql", {"sql": "SELECT 1;"}, key="bad"), 401, "Unauthorized"),
             (shared.get("/missing"), 404, "NotFound"),
             (shared.get("/v1/sql"), 405, "MethodNotAllowed"),
             (shared.post("/v1/sql", {"q": 1}), 400, "BadRequest")]
    for r, status, typ in cases:
        assert r.status == status and r.ctype == "application/json", r
        body = r.json()
        assert set(body) == {"error"} and set(body["error"]) == {"type", "message"}, body
        assert body["error"]["type"] == typ and isinstance(body["error"]["message"], str) and body["error"]["message"]


@stage(0)
def test_errors_do_not_leak_paths_or_keys(shared):  # noqa: F811
    t = unique()
    bodies = [shared.post("/v1/sql", {"sql": 1}).body, shared.request("POST", "/v1/sql", data=b"{").body,
              shared.get(f"/{t}").body, shared.post("/v1/sql", {"sql": "x"}, key="wrong-key-123").body]
    for b in bodies:
        text = b.decode("utf-8", "replace")
        assert str(shared.data_dir) not in text and str(shared.root) not in text
        assert shared.admin_key not in text and "wrong-key-123" not in text
        assert "Traceback" not in text and 'File "' not in text
    assert error_kind(shared.get(f"/{t}")) is not None
