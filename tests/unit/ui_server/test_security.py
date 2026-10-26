"""UI-1 (local only), UI-2 (token), UI-8 (read-only db), response headers."""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from tests.unit.ui_server.conftest import BASE, PORT, TOKEN
from ui_server.app import create_app


def test_no_token_is_401(settings):
    with TestClient(create_app(settings), base_url=BASE) as c:
        assert c.get("/api/runs").status_code == 401
        assert c.get("/api/health").status_code == 401


def test_wrong_token_is_401(settings):
    with TestClient(create_app(settings), base_url=BASE) as c:
        assert c.get("/api/runs", headers={"X-LRAE-Token": "nope"}).status_code == 401
        assert c.get("/api/runs", headers={"X-LRAE-Token": TOKEN + "x"}).status_code == 401


def test_bearer_token_is_accepted(settings):
    with TestClient(create_app(settings), base_url=BASE) as c:
        assert c.get("/api/health", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200


def test_token_in_query_string_is_not_accepted(settings):
    with TestClient(create_app(settings), base_url=BASE) as c:
        assert c.get(f"/api/health?token={TOKEN}").status_code == 401


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1:9999", "localhost.evil.example:8765",
                                  "127.0.0.1.evil.example:8765", ""])
def test_foreign_host_header_is_403(client, host):
    r = client.get("/api/health", headers={"Host": host})
    assert r.status_code in (400, 403)


@pytest.mark.parametrize("host", [f"127.0.0.1:{PORT}", f"localhost:{PORT}", f"[::1]:{PORT}"])
def test_loopback_hosts_are_allowed(client, host):
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


def test_host_check_applies_to_static_pages_too(settings):
    with TestClient(create_app(settings), base_url=BASE) as c:
        assert c.get("/", headers={"Host": "evil.example"}).status_code in (400, 403)
        assert c.get("/").status_code == 200  # the page itself needs no token (it carries none)


@pytest.mark.parametrize("method", ["get", "post"])
def test_foreign_origin_is_403(client, method):
    r = getattr(client, method)("/api/health" if method == "get" else "/api/ingest",
                                headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_own_origin_is_fine(client):
    assert client.get("/api/health", headers={"Origin": BASE}).status_code == 200


def test_no_cors_headers(client):
    r = client.get("/api/health", headers={"Origin": BASE})
    assert not any(h.lower().startswith("access-control-") for h in r.headers)
    pre = client.options("/api/ingest", headers={"Origin": "https://evil.example",
                                                 "Access-Control-Request-Method": "POST"})
    assert pre.status_code in (403, 405)
    assert "access-control-allow-origin" not in {h.lower() for h in pre.headers}


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-eval" not in csp and "script-src 'self'" in csp
    page = client.get("/", headers={})
    assert "content-security-policy" in page.headers


def test_post_needs_token(settings):
    with TestClient(create_app(settings), base_url=BASE) as c:
        assert c.post("/api/ingest").status_code == 401


def test_store_is_opened_read_only(settings, two_runs):
    from ui_server.store import open_ro
    con = open_ro(settings.runs_dir / "metrics.sqlite")
    assert con is not None
    assert con.execute("select count(*) from runs").fetchone()[0] == 1
    with pytest.raises(sqlite3.OperationalError):
        con.execute("delete from runs")
    with pytest.raises(sqlite3.OperationalError):
        con.execute("create table x(a)")
    con.close()


def test_open_ro_missing_db_is_none(tmp_path):
    from ui_server.store import open_ro
    assert open_ro(tmp_path / "nope.sqlite") is None


def test_server_never_writes_to_run_dirs(client, two_runs, settings):
    def snapshot():
        return sorted((str(p.relative_to(settings.runs_dir)), p.stat().st_mtime_ns, p.stat().st_size)
                      for p in settings.runs_dir.rglob("*") if p.is_file())
    before = snapshot()
    for rid in two_runs:
        for path in ("", "/checkpoints"):
            assert client.get(f"/api/runs/{rid}{path}").status_code == 200
    client.get("/api/runs")
    client.get("/api/experiments")
    client.get("/api/ingest/status")
    assert snapshot() == before
