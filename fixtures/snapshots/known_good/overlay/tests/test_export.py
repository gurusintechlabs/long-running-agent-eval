import csv
import io

import pytest
from fastapi.testclient import TestClient

from app import audit
from app.config import Settings
from app.main import create_app
from app.ratelimit import RateLimiter

HEADER = ["id", "title", "slug", "description", "quantity", "created_at"]


@pytest.fixture()
def xclient():
    settings = Settings(db_path=":memory:", export_rate_limit=3, export_rate_window_s=3600)
    with TestClient(create_app(settings=settings)) as c:
        yield c


def _rows(resp):
    return list(csv.reader(io.StringIO(resp.text, newline="")))


def _add(client, headers, n, prefix="item"):
    for i in range(n):
        assert client.post("/items", json={"title": f"{prefix} {i}"}, headers=headers).status_code == 201


def _export_audit(user_id=None):
    return [e for e in audit.list_entries(user_id=user_id, limit=1000) if e["action"] == "export.csv"]


def test_export_requires_api_key(xclient):
    assert xclient.get("/export").status_code == 401
    assert xclient.get("/export", headers={"X-API-Key": "nope"}).status_code == 401
    assert _export_audit() == []


def test_export_csv_header_and_rows(xclient, alice):
    xclient.post("/items", json={"title": "Blue Widget", "description": "d", "quantity": 4}, headers=alice)
    xclient.post("/items", json={"title": "Plain"}, headers=alice)
    r = xclient.get("/export", headers=alice)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    rows = _rows(r)
    assert rows[0] == HEADER
    assert rows[1][1:5] == ["Blue Widget", "blue-widget", "d", "4"]
    assert rows[2][1:5] == ["Plain", "plain", "", "1"]
    assert r.headers["x-total-count"] == "2"


def test_export_pagination(xclient, alice):
    _add(xclient, alice, 5)
    page = _rows(xclient.get("/export?limit=2&offset=2", headers=alice))
    assert [r[1] for r in page[1:]] == ["item 2", "item 3"]
    assert len(_rows(xclient.get("/export?offset=99", headers=alice))) == 1
    assert len(_rows(xclient.get("/export?limit=0", headers=alice))) == 2


def test_export_only_own_items(xclient, alice, bob):
    _add(xclient, alice, 2, "a")
    _add(xclient, bob, 1, "b")
    assert [r[1] for r in _rows(xclient.get("/export", headers=bob))[1:]] == ["b 0"]


def test_export_escapes_special_characters(xclient, alice):
    title = 'say "hi", ok'
    desc = "line1\nline2"
    xclient.post("/items", json={"title": title, "description": desc}, headers=alice)
    rows = _rows(xclient.get("/export", headers=alice))
    assert rows[1][1] == title and rows[1][3] == desc


def test_export_invalid_params_422_not_counted(xclient, alice):
    assert xclient.get("/export?limit=abc", headers=alice).status_code == 422
    assert xclient.get("/export?offset=x", headers=alice).status_code == 422
    assert _export_audit() == []
    for _ in range(3):
        assert xclient.get("/export", headers=alice).status_code == 200


def test_export_rate_limit_per_user(xclient, alice, bob):
    for _ in range(3):
        assert xclient.get("/export", headers=alice).status_code == 200
    r = xclient.get("/export", headers=alice)
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) >= 1
    assert xclient.get("/export", headers=bob).status_code == 200
    assert xclient.get("/items", headers=alice).status_code == 200
    assert len(_export_audit(user_id=1)) == 3


def test_export_audit_entry_per_success(xclient, alice):
    xclient.get("/export", headers=alice)
    xclient.get("/export?limit=1", headers=alice)
    entries = _export_audit(user_id=1)
    assert len(entries) == 2 and all(e["user_id"] == 1 for e in entries)


def test_rate_limiter_window_resets():
    now = [0.0]
    rl = RateLimiter(2, 10, clock=lambda: now[0])
    assert rl.hit(1)[0] and rl.hit(1)[0]
    allowed, retry = rl.hit(1)
    assert not allowed and retry == 10
    assert rl.hit(2)[0]
    now[0] = 10.0
    assert rl.hit(1)[0]
