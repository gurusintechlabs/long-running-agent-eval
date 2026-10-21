"""Stage 5: keys, grants, rate limiting, the audit log, and their HTTP endpoints."""
import json
import time

import pytest

from minidb.audit import AuditLog
from minidb.auth import InvalidKeyRequest, KeyStore, Principal, parse_key_request
from minidb.server import keys_api
from minidb.server.ratelimit import RateLimiter
from tests.server_util import ADMIN_KEY, Proc


def test_keys_are_checked_by_hash_and_survive_reload(tmp_path):
    ks = KeyStore(tmp_path, "adm")
    assert ks.authenticate("adm") == Principal("admin", "admin", None)
    made = ks.create("t", "reader", ["a"])
    assert made["key"] not in (tmp_path / "keys.json").read_text()
    p = KeyStore(tmp_path, "adm").authenticate(made["key"])
    assert p.role == "reader" and p.sees("a") and not p.sees("b") and not p.allows("write")
    assert ks.revoke(made["id"]) and ks.authenticate(made["key"]) is None and not ks.revoke(made["id"])
    assert ks.authenticate("nope") is None


def test_key_requests_are_validated():
    assert parse_key_request({"name": "n", "role": "writer", "collections": ["b", "a", "a"]}) == ("n", "writer", ["a", "b"])
    for bad in ({"name": "", "role": "reader", "collections": []}, {"name": "n", "role": "x", "collections": []},
                {"name": "n", "role": "reader", "collections": ["*", "a"]}, {"name": "n", "role": "reader"}):
        with pytest.raises(InvalidKeyRequest):
            parse_key_request(bad)


def test_token_bucket():
    rl = RateLimiter(3)
    assert [rl.take("k") for _ in range(3)] == [None, None, None]
    assert rl.take("k") == 1 and rl.take("other") is None
    time.sleep(0.4)
    assert rl.take("k") is None


def test_audit_log_newest_first(tmp_path):
    log = AuditLog(tmp_path)
    log.record("admin", "collection.create", "a")
    log.record("k_1", "key.revoke", "k_2")
    with open(tmp_path / "audit.log", "ab") as fh:
        fh.write(b'{"torn')
    assert [e["target"] for e in log.latest(5)] == ["k_2", "a"] and log.latest(1)[0]["actor"] == "k_1"


def test_keys_and_audit_over_http(tmp_path):
    srv = Proc(tmp_path / "data").wait_ready()
    try:
        status, made, _ = srv.request("POST", "/v1/keys", {"name": "r", "role": "reader", "collections": ["a"]})
        assert status == 201 and made["id"].startswith("k_")
        assert srv.request("GET", "/v1/keys", key=made["key"])[0] == 403
        assert srv.request("GET", "/v1/collections/a", key=made["key"])[0] == 404
        assert srv.request("DELETE", "/v1/keys/admin")[0] == 409
        status, body, _ = srv.request("GET", "/v1/audit?limit=1")
        assert status == 200 and body["entries"][0]["action"] == "key.create"
        assert srv.request("GET", "/v1/audit?limit=0")[0] == 400
        assert keys_api.AUDIT_DEFAULT == 100
        assert ADMIN_KEY not in json.dumps(body)
    finally:
        srv.stop()
