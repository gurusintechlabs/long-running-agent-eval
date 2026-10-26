"""t15 (stage 5): per-key rate limiting and the audit log of admin actions (brief 5.3, 5.4)."""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from _support import Server, expect_error, new_key, server, stage  # noqa: F401

ISO_UTC = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|\+00:00)$")


def _burst(srv, n, key=..., headers=None):
    return [srv.get("/v1/collections", key=key, headers=headers) for _ in range(n)]


@pytest.fixture
def limited(tmp_path):
    s = Server(tmp_path / "srv", rate_limit=5)
    try:
        yield s
    finally:
        s.close()


@stage(5)
def test_over_the_limit_is_429_with_retry_after(limited):
    out = _burst(limited, 12)
    codes = [r.status for r in out]
    assert codes[:5] == [200] * 5 and codes.count(429) >= 5, codes
    r = next(r for r in out if r.status == 429)
    expect_error(r, 429)
    assert r.headers.get("retry-after", "").isdigit() and int(r.headers["retry-after"]) >= 1, r.headers
    assert limited.get("/healthz", key=None).status == 200


@stage(5)
def test_the_limit_recovers_after_retry_after(limited):
    out = _burst(limited, 10)
    wait = int(next(r for r in out if r.status == 429).headers["retry-after"])
    time.sleep(wait + 0.2)
    assert limited.get("/v1/collections").status == 200


@stage(5)
def test_each_key_has_its_own_bucket(limited):
    other = new_key(limited, "reader", ["*"])["key"]
    time.sleep(1.2)                                   # the admin's bucket refills after creating the key
    assert 429 in [r.status for r in _burst(limited, 10)]
    assert [r.status for r in _burst(limited, 5, key=other)] == [200] * 5


@stage(5)
def test_the_limit_holds_across_connections_and_threads(limited):
    t0 = time.monotonic()
    with ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(lambda _: limited.get("/v1/collections").status, range(40)))
    allowed = 5 + 5 * (time.monotonic() - t0) + 1
    assert codes.count(200) <= allowed and codes.count(200) + codes.count(429) == 40, codes


@stage(5)
def test_the_default_rate_limit_is_50_per_second_timing(tmp_path):
    with Server(tmp_path / "srv", rate_limit=None) as srv:
        t0 = time.monotonic()
        codes = [r.status for r in _burst(srv, 120)]
        elapsed = time.monotonic() - t0
        allowed = 50 + 50 * elapsed
        assert 50 <= codes.count(200) <= allowed + 2, (codes.count(200), elapsed)
        assert codes[:50] == [200] * 50 and 429 in codes


@stage(5)
def test_admin_actions_are_audited_newest_first(server):  # noqa: F811
    k = new_key(server, "writer", ["docs"])
    server.put("/v1/collections/docs", {"dim": 2})
    server.put("/v1/collections/docs/index", {"type": "hnsw"})
    server.put("/v1/collections/docs/points", {"points": [{"id": 1, "vector": [1, 2]}]}, key=k["key"])   # not audited
    server.delete(f"/v1/keys/{k['id']}")
    server.delete("/v1/collections/docs")
    want = [("collection.delete", "docs"), ("key.revoke", k["id"]), ("collection.index", "docs"),
            ("collection.create", "docs"), ("key.create", k["id"])]
    entries = server.get("/v1/audit").json()["entries"]
    assert [(e["action"], e["target"]) for e in entries] == want, entries
    assert all(e["actor"] == "admin" and ISO_UTC.match(e["ts"]) for e in entries), entries
    lines = [json.loads(x) for x in (server.data_dir / "audit.log").read_text().splitlines() if x.strip()]
    assert [(e["action"], e["target"]) for e in lines] == want[::-1]
    assert server.get("/v1/audit?limit=2").json()["entries"] == entries[:2]


@stage(5)
def test_the_audit_log_names_the_acting_key_and_survives_a_restart(server):  # noqa: F811
    other = new_key(server, "admin", ["*"])
    server.put("/v1/collections/x", {"dim": 2}, key=other["key"])
    server.restart(crash=True)
    entries = server.get("/v1/audit?limit=10").json()["entries"]
    assert (entries[0]["actor"], entries[0]["action"], entries[0]["target"]) == (other["id"], "collection.create", "x")
    assert (entries[1]["actor"], entries[1]["action"]) == ("admin", "key.create")
    many = server.get("/v1/audit").json()["entries"]
    assert len(many) == 2


@stage(5)
def test_audit_limit_is_validated(server):  # noqa: F811
    for _ in range(105):
        server.put(f"/v1/collections/c{_}", {"dim": 2})
    assert len(server.get("/v1/audit").json()["entries"]) == 100
    assert len(server.get("/v1/audit?limit=104").json()["entries"]) == 104
    for bad in ("0", "-1", "abc", "1.5", "10001", ""):
        expect_error(server.get(f"/v1/audit?limit={bad}"), 400)
