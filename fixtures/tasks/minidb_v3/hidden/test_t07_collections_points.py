"""t07 (stage 1): collections and points over REST, validation, durability (brief 1.2, 1.3)."""
import json

import numpy as np

from _support import expect_error, server, shared, stage, unique  # noqa: F401


def _coll(srv, dim=4, metric=None, name=None):
    name = name or unique("c")
    body = {"dim": dim} if metric is None else {"dim": dim, "metric": metric}
    r = srv.put(f"/v1/collections/{name}", body)
    assert r.status == 201, r
    return name


def _core(obj):
    """The stage-1 fields of a collection object (later stages add more)."""
    return {k: obj.get(k) for k in ("name", "dim", "metric", "points")}


def _pts(srv, name, points):
    return srv.put(f"/v1/collections/{name}/points", {"points": points})


@stage(1)
def test_create_get_list_and_delete(shared):  # noqa: F811
    a, b = unique("b"), unique("a")
    r = shared.put(f"/v1/collections/{a}", {"dim": 3, "metric": "dot"})
    assert r.status == 201 and _core(r.json()) == {"name": a, "dim": 3, "metric": "dot", "points": 0}, r
    _coll(shared, 5, "cosine", b)
    assert _core(shared.get(f"/v1/collections/{a}").json()) == {"name": a, "dim": 3, "metric": "dot", "points": 0}
    names = [c["name"] for c in shared.get("/v1/collections").json()["collections"]]
    assert names == sorted(names) and {a, b} <= set(names)
    r = shared.delete(f"/v1/collections/{a}")
    assert r.status == 200 and r.json() == {"deleted": True}
    expect_error(shared.get(f"/v1/collections/{a}"), 404)
    assert a not in [c["name"] for c in shared.get("/v1/collections").json()["collections"]]


@stage(1, 11)
def test_the_default_metric_is_l2(shared):  # noqa: F811
    name = _coll(shared, 2)
    assert shared.get(f"/v1/collections/{name}").json()["metric"] == "l2"


@stage(1)
def test_an_existing_name_is_409(shared):  # noqa: F811
    name = _coll(shared)
    expect_error(shared.put(f"/v1/collections/{name}", {"dim": 4}), 409)


@stage(1)
def test_invalid_names_and_specs_are_400(shared):  # noqa: F811
    for name in ("Abc", "-a", "_a", "a.b", "a" * 65, "a%20b", "%61bc", "%C3%A9t%C3%A9"):
        expect_error(shared.put(f"/v1/collections/{name}", {"dim": 2}), 400)
    assert shared.put(f"/v1/collections/{'a' * 64}", {"dim": 2}).status in (201, 409)
    for body in ({}, {"dim": 0}, {"dim": 4097}, {"dim": "3"}, {"dim": 3.0}, {"dim": True}, {"dim": 3, "metric": "L2"},
                 {"dim": 3, "metric": "euclid"}, {"dim": 3, "metric": None}):
        expect_error(shared.put(f"/v1/collections/{unique('c')}", body), 400)


@stage(1)
def test_unknown_collections_are_404(shared):  # noqa: F811
    name = unique("nope")
    expect_error(shared.get(f"/v1/collections/{name}"), 404)
    expect_error(shared.delete(f"/v1/collections/{name}"), 404)
    expect_error(_pts(shared, name, [{"id": 1, "vector": [1.0]}]), 404)
    expect_error(shared.get(f"/v1/collections/{name}/points/1"), 404)
    expect_error(shared.post(f"/v1/collections/{name}/points/delete", {"ids": [1]}), 404)
    expect_error(shared.post(f"/v1/collections/{name}/search", {"vector": [1.0]}), 404)


@stage(1)
def test_upsert_get_and_replace_points(shared):  # noqa: F811
    name = _coll(shared, 3)
    r = _pts(shared, name, [{"id": 7, "vector": [0.5, 1, -2], "payload": {"a": {"b": [1, "x"]}}}, {"id": 0, "vector": [1, 1, 1]}])
    assert r.status == 200 and r.json() == {"upserted": 2}, r
    p = shared.get(f"/v1/collections/{name}/points/7").json()
    assert p == {"id": 7, "vector": [0.5, 1.0, -2.0], "payload": {"a": {"b": [1, "x"]}}}
    assert shared.get(f"/v1/collections/{name}/points/0").json()["payload"] is None
    assert _pts(shared, name, [{"id": 7, "vector": [3, 2, 1], "payload": None}]).json() == {"upserted": 1}
    assert shared.get(f"/v1/collections/{name}/points/7").json() == {"id": 7, "vector": [3.0, 2.0, 1.0], "payload": None}
    assert shared.get(f"/v1/collections/{name}").json()["points"] == 2
    expect_error(shared.get(f"/v1/collections/{name}/points/8"), 404)


@stage(1)
def test_vectors_are_stored_as_float32(shared):  # noqa: F811
    name = _coll(shared, 2)
    _pts(shared, name, [{"id": 1, "vector": [0.1, 1 / 3]}])
    v = shared.get(f"/v1/collections/{name}/points/1").json()["vector"]
    assert v == np.array([0.1, 1 / 3], dtype=np.float32).astype(float).tolist()


@stage(1)
def test_a_batch_is_validated_as_a_whole(shared):  # noqa: F811
    name = _coll(shared, 2, "cosine")
    good = {"id": 1, "vector": [1, 0]}
    bad_points = [{"id": 2, "vector": [1, 0, 0]}, {"id": -1, "vector": [1, 0]}, {"id": 2 ** 63, "vector": [1, 0]},
                  {"id": 1.5, "vector": [1, 0]}, {"id": True, "vector": [1, 0]}, {"id": "7", "vector": [1, 0]},
                  {"id": 2, "vector": [1, "x"]}, {"id": 2, "vector": [0, 0]}, {"id": 2, "vector": [1, 0], "payload": [1]},
                  {"id": 2, "vector": [1, 0], "payload": "x"}, {"id": 2, "vector": [1, 0], "payload": {"s": "x" * 70_000}},
                  {"id": 1, "vector": [0, 1]}, {"vector": [1, 0]}, {"id": 2}]
    for bad in bad_points:
        expect_error(_pts(shared, name, [good, bad]), 400)
    r = shared.request("PUT", f"/v1/collections/{name}/points",
                       data=b'{"points": [{"id": 1, "vector": [1, 0]}, {"id": 2, "vector": [1e400, 0]}]}')
    expect_error(r, 400)
    expect_error(_pts(shared, name, [{"id": i, "vector": [1, i]} for i in range(1001)]), 400)
    for body in ({}, {"points": {}}, {"points": [1]}):
        expect_error(shared.put(f"/v1/collections/{name}/points", body), 400)
    assert shared.get(f"/v1/collections/{name}").json()["points"] == 0
    expect_error(shared.get(f"/v1/collections/{name}/points/1"), 404)
    assert _pts(shared, name, [good, {"id": 2, "vector": [1, 0], "payload": {"s": "x" * 60_000}}]).status == 200


@stage(1)
def test_upsert_bodies_up_to_8_mib_are_accepted(shared):  # noqa: F811
    name = _coll(shared, 96)
    rng = np.random.default_rng(3)
    pts = [{"id": i, "vector": rng.normal(size=96).tolist(), "payload": {"i": i}} for i in range(1000)]
    body = json.dumps({"points": pts}).encode()
    assert 1 << 20 < len(body) < 8 << 20
    r = shared.request("PUT", f"/v1/collections/{name}/points", data=body)
    assert r.status == 200 and r.json() == {"upserted": 1000}, r
    r = shared.declared_body("PUT", f"/v1/collections/{name}/points", (8 << 20) + 1)
    assert r.status == 413 and r.elapsed < 5, r
    r = shared.declared_body("POST", f"/v1/collections/{name}/search", len(body))   # 1 MiB everywhere else
    assert r.status == 413 and r.elapsed < 5, r


@stage(1)
def test_delete_points_counts_what_was_deleted(shared):  # noqa: F811
    name = _coll(shared, 2)
    _pts(shared, name, [{"id": i, "vector": [i, 1]} for i in range(5)])
    r = shared.post(f"/v1/collections/{name}/points/delete", {"ids": [1, 3, 99, 1]})
    assert r.status == 200 and r.json() == {"deleted": 2}, r
    assert shared.get(f"/v1/collections/{name}").json()["points"] == 3
    expect_error(shared.get(f"/v1/collections/{name}/points/3"), 404)
    for body in ({}, {"ids": 1}, {"ids": [-1]}, {"ids": ["x"]}):
        expect_error(shared.post(f"/v1/collections/{name}/points/delete", body), 400)


@stage(1)
def test_large_ids_and_path_ids(shared):  # noqa: F811
    name = _coll(shared, 1)
    big = 2 ** 63 - 1
    assert _pts(shared, name, [{"id": big, "vector": [1]}]).status == 200
    assert shared.get(f"/v1/collections/{name}/points/{big}").json()["id"] == big
    for bad in ("-1", "1.0", "abc", str(2 ** 63)):
        assert shared.get(f"/v1/collections/{name}/points/{bad}").status in (400, 404)


@stage(1)
def test_collections_and_points_survive_restart_and_crash(server):  # noqa: F811
    a = _coll(server, 2, "dot")
    _pts(server, a, [{"id": i, "vector": [i, -i], "payload": {"i": i}} for i in range(50)])
    server.post(f"/v1/collections/{a}/points/delete", {"ids": [0, 1]})
    _pts(server, a, [{"id": 2, "vector": [9, 9], "payload": {"new": True}}])
    gone = _coll(server, 3)
    server.delete(f"/v1/collections/{gone}")
    server.restart(crash=True)
    assert _core(server.get(f"/v1/collections/{a}").json()) == {"name": a, "dim": 2, "metric": "dot", "points": 48}
    assert server.get(f"/v1/collections/{a}/points/2").json() == {"id": 2, "vector": [9.0, 9.0], "payload": {"new": True}}
    expect_error(server.get(f"/v1/collections/{a}/points/1"), 404)
    expect_error(server.get(f"/v1/collections/{gone}"), 404)
    server.restart()
    assert server.get(f"/v1/collections/{a}").json()["points"] == 48
    assert server.put(f"/v1/collections/{gone}", {"dim": 5}).status == 201      # the name is free again
