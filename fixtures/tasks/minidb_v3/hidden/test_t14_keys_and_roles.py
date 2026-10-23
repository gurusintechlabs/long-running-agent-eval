"""t14 (stage 5): API keys, roles and per-collection grants (brief 5.1, 5.2)."""
import pytest

from _support import Server, expect_error, new_key, server, stage, unique  # noqa: F401

VEC = [1.0, 2.0]


@pytest.fixture(scope="module")
def tenants(tmp_path_factory):
    """Collections a, b and c with points; keys of each role on a only, and a writer on a and b."""
    srv = Server(tmp_path_factory.mktemp("t14"))
    try:
        for name in ("a", "b", "c"):
            assert srv.put(f"/v1/collections/{name}", {"dim": 2}).status == 201
            srv.put(f"/v1/collections/{name}/points", {"points": [{"id": i, "vector": [i, 1], "payload": {"of": name}}
                                                                  for i in range(5)]})
        keys = {"reader": new_key(srv, "reader", ["a"]), "writer": new_key(srv, "writer", ["a", "b"]),
                "admin_a": new_key(srv, "admin", ["a"])}
        yield srv, {k: v["key"] for k, v in keys.items()}, keys
    finally:
        srv.close()


@stage(5)
def test_admin_creates_keys_and_sees_the_secret_once(server):  # noqa: F811
    r = server.post("/v1/keys", {"name": "team-a", "role": "reader", "collections": ["a", "b"]})
    assert r.status == 201, r
    body = r.json()
    assert set(body) == {"id", "key", "name", "role", "collections"}
    assert body["id"].startswith("k_") and len(body["id"]) > 2 and body["key"] and body["key"] != body["id"]
    assert (body["name"], body["role"], sorted(body["collections"])) == ("team-a", "reader", ["a", "b"])
    listed = server.get("/v1/keys").json()["keys"]
    mine = [k for k in listed if k["id"] == body["id"]]
    assert len(mine) == 1 and "key" not in mine[0] and body["key"] not in server.get("/v1/keys").body.decode()
    assert {"id": "admin", "name": "admin", "role": "admin", "collections": ["*"]} in listed
    second = new_key(server, "writer", ["*"])
    assert second["id"] != body["id"] and second["key"] != body["key"]


@stage(5)
def test_invalid_key_requests_are_400(server):  # noqa: F811
    for body in ({}, {"name": "x", "role": "root", "collections": ["a"]}, {"name": "x", "role": "reader"},
                 {"name": "x", "role": "reader", "collections": "a"}, {"name": "", "role": "reader", "collections": []},
                 {"role": "reader", "collections": ["a"]}, {"name": "x", "role": "reader", "collections": ["*", "a"]},
                 {"name": "x", "role": "reader", "collections": ["Bad Name"]}, {"name": 5, "role": "reader", "collections": []}):
        expect_error(server.post("/v1/keys", body), 400)


@stage(5)
def test_revoked_keys_stop_working_at_once_and_admin_cannot_be_revoked(server):  # noqa: F811
    k = new_key(server, "reader", ["*"])
    assert server.get("/v1/collections", key=k["key"]).status == 200
    r = server.delete(f"/v1/keys/{k['id']}")
    assert r.status == 200 and r.json() == {"revoked": True}, r
    expect_error(server.get("/v1/collections", key=k["key"]), 401)
    assert k["id"] not in [x["id"] for x in server.get("/v1/keys").json()["keys"]]
    expect_error(server.delete(f"/v1/keys/{k['id']}"), 404)
    expect_error(server.delete("/v1/keys/admin"), 409)
    assert server.get("/v1/collections").status == 200


@stage(5)
def test_keys_and_grants_survive_a_restart_and_a_crash(server):  # noqa: F811
    server.put("/v1/collections/g", {"dim": 2})
    reader = new_key(server, "reader", ["g"])
    gone = new_key(server, "writer", ["g"])
    server.delete(f"/v1/keys/{gone['id']}")
    for crash in (False, True):
        server.restart(crash=crash)
        assert [c["name"] for c in server.get("/v1/collections", key=reader["key"]).json()["collections"]] == ["g"]
        expect_error(server.put("/v1/collections/g/points", {"points": []}, key=reader["key"]), 403)
        expect_error(server.get("/v1/collections", key=gone["key"]), 401)


@stage(5)
def test_a_reader_reads_and_searches_granted_collections(tenants):
    srv, keys, _ = tenants
    k = keys["reader"]
    assert [c["name"] for c in srv.get("/v1/collections", key=k).json()["collections"]] == ["a"]
    assert srv.get("/v1/collections/a", key=k).json()["points"] == 5
    assert srv.get("/v1/collections/a/points/2", key=k).json()["payload"] == {"of": "a"}
    res = srv.post("/v1/collections/a/search", {"vector": VEC, "k": 3, "with_payload": True}, key=k).json()["results"]
    assert len(res) == 3 and all(r["payload"] == {"of": "a"} for r in res)


@stage(5)
def test_a_reader_cannot_write(tenants):
    srv, keys, _ = tenants
    k = keys["reader"]
    expect_error(srv.put("/v1/collections/a/points", {"points": [{"id": 9, "vector": VEC}]}, key=k), 403)
    expect_error(srv.post("/v1/collections/a/points/delete", {"ids": [1]}, key=k), 403)
    assert srv.get("/v1/collections/a").json()["points"] == 5


@stage(5)
def test_a_writer_changes_points_only_in_granted_collections(tenants):
    srv, keys, _ = tenants
    k = keys["writer"]
    for name in ("a", "b"):
        assert srv.put(f"/v1/collections/{name}/points", {"points": [{"id": 50, "vector": VEC}]}, key=k).status == 200
        assert srv.post(f"/v1/collections/{name}/points/delete", {"ids": [50]}, key=k).json() == {"deleted": 1}
    expect_error(srv.put("/v1/collections/c/points", {"points": [{"id": 50, "vector": VEC}]}, key=k), 404)
    assert srv.get("/v1/collections/c").json()["points"] == 5


@stage(5)
def test_only_admins_manage_collections_indexes_and_keys(tenants):
    srv, keys, _ = tenants
    for role in ("reader", "writer"):
        k = keys[role]
        expect_error(srv.put("/v1/collections/a", {"dim": 2}, key=k), 403)
        expect_error(srv.delete("/v1/collections/a", key=k), 403)
        expect_error(srv.put("/v1/collections/a/index", {"type": "flat"}, key=k), 403)
        expect_error(srv.post("/v1/keys", {"name": "x", "role": "reader", "collections": ["a"]}, key=k), 403)
        expect_error(srv.get("/v1/keys", key=k), 403)
        expect_error(srv.delete("/v1/keys/admin", key=k), 403)
        expect_error(srv.get("/v1/audit", key=k), 403)
    assert srv.get("/v1/collections/a").status == 200
    k = keys["admin_a"]                              # an admin key with a grant on a only
    name = unique("n")
    expect_error(srv.put(f"/v1/collections/{name}", {"dim": 2}, key=k), 404)
    assert srv.put("/v1/collections/a/index", {"type": "flat"}, key=k).status == 200
    assert srv.post("/v1/keys", {"name": "made-by-a", "role": "reader", "collections": ["a"]}, key=k).status == 201


@stage(5)
def test_an_ungranted_collection_looks_exactly_like_a_missing_one(tenants):
    srv, keys, _ = tenants
    k = keys["reader"]
    # Reads are within the reader's role, so only the grant rule applies: 404. A write is also outside the role:
    # the brief does not order the two rules, so 403 and 404 are both fine as long as an ungranted collection
    # and a missing one answer the same (no existence leak; RFC 9110 15.5.4).
    for path, method, body in (("/v1/collections/{}", "GET", None), ("/v1/collections/{}/points/1", "GET", None),
                               ("/v1/collections/{}/search", "POST", {"vector": VEC}),
                               ("/v1/collections/{}/points", "PUT", {"points": []})):
        hidden = srv.request(method, path.format("b"), body, key=k)
        missing = srv.request(method, path.format("zz-missing"), body, key=k)
        status = hidden.status if method == "PUT" and hidden.status in (403, 404) else 404
        expect_error(hidden, status)
        expect_error(missing, status)
        hb, mb = hidden.json(), missing.json()
        if isinstance(hb, dict) and isinstance(mb, dict):
            assert {x: v for x, v in hb.items() if x != "instance"} == {x: v for x, v in mb.items() if x != "instance"}
    names = [c["name"] for c in srv.get("/v1/collections", key=keys["writer"]).json()["collections"]]
    assert names == ["a", "b"]


@stage(5)
def test_a_star_grant_covers_future_collections(tenants):
    srv, _, _ = tenants
    k = new_key(srv, "reader", ["*"])["key"]
    name = unique("later")
    srv.put(f"/v1/collections/{name}", {"dim": 2})
    srv.put(f"/v1/collections/{name}/points", {"points": [{"id": 1, "vector": VEC}]})
    assert srv.get(f"/v1/collections/{name}", key=k).json()["points"] == 1
    assert name in [c["name"] for c in srv.get("/v1/collections", key=k).json()["collections"]]
    named = new_key(srv, "reader", ["later-by-name"])["key"]
    expect_error(srv.get("/v1/collections/later-by-name", key=named), 404)
    srv.put("/v1/collections/later-by-name", {"dim": 2})
    assert srv.get("/v1/collections/later-by-name", key=named).status == 200


@stage(5)
def test_sql_and_knn_are_admin_only_and_respect_grants(tenants):
    srv, keys, _ = tenants
    for role in ("reader", "writer"):
        expect_error(srv.post("/v1/sql", {"sql": "SELECT 1"}, key=keys[role]), 403)
        expect_error(srv.post("/v1/sql", {"sql": "SELECT * FROM knn('a', VECTOR '[1, 2]', 3)"}, key=keys[role]), 403)
    k = keys["admin_a"]
    (ok,) = srv.sql("SELECT id FROM knn('a', VECTOR '[1, 2]', 3)", key=k)
    assert ok["ok"] is True and len(ok["rows"]) == 3
    (bad,) = srv.sql("SELECT id FROM knn('b', VECTOR '[1, 2]', 3)", key=k)
    (missing,) = srv.sql("SELECT id FROM knn('zz-missing', VECTOR '[1, 2]', 3)", key=k)
    assert bad["ok"] is False and bad["error"]["type"] == missing["error"]["type"] == "NameError", bad
    (full,) = srv.sql("SELECT id FROM knn('b', VECTOR '[1, 2]', 3)")
    assert full["ok"] is True


@stage(5)
def test_every_endpoint_needs_a_valid_key(tenants):
    srv, keys, info = tenants
    calls = [("GET", "/v1/collections", None), ("PUT", "/v1/collections/zz", {"dim": 2}), ("GET", "/v1/collections/a", None),
             ("DELETE", "/v1/collections/a", None), ("PUT", "/v1/collections/a/index", {"type": "flat"}),
             ("PUT", "/v1/collections/a/points", {"points": []}), ("GET", "/v1/collections/a/points/1", None),
             ("POST", "/v1/collections/a/points/delete", {"ids": []}), ("POST", "/v1/collections/a/search", {"vector": VEC}),
             ("POST", "/v1/sql", {"sql": "SELECT 1"}), ("POST", "/v1/keys", {"name": "x", "role": "admin", "collections": ["*"]}),
             ("GET", "/v1/keys", None), ("DELETE", f"/v1/keys/{info['reader']['id']}", None), ("GET", "/v1/audit", None)]
    for key in (None, "nope", info["reader"]["id"], "Bearer"):
        for method, path, body in calls:
            expect_error(srv.request(method, path, body, key=key), 401)
    assert srv.get("/v1/collections/a").json()["points"] >= 5
    assert srv.get("/v1/collections", key=keys["reader"]).status == 200
