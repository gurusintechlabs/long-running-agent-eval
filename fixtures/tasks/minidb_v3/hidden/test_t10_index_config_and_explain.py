"""t10 (stage 2): index objects, PUT .../index, search params, explain, and hnsw correctness (brief 2.1, 2.2)."""
import math

import numpy as np
import pytest

from _support import Server, clustered, expect_error, server, shared, stage, unique, upsert_all  # noqa: F401

HNSW_DEFAULTS = {"type": "hnsw", "m": 16, "ef_construction": 200}


def _stage2(explain):
    """The stage-2 fields of an explain object (later stages add more)."""
    return {k: explain.get(k) for k in ("index", "exact", "ef", "candidates")}


def _search(srv, name, body):
    r = srv.post(f"/v1/collections/{name}/search", body)
    assert r.status == 200, r
    return r.json()


@pytest.fixture(scope="module")
def small(tmp_path_factory):
    """A 3,000-point hnsw collection with payloads."""
    srv = Server(tmp_path_factory.mktemp("t10"))
    try:
        base, queries = clustered(3000, queries=40, seed=1010)
        srv.put("/v1/collections/small", {"dim": base.shape[1], "index": {"type": "hnsw", "m": 8, "ef_construction": 64}})
        upsert_all(srv, "small", base, payload=lambda i: {"parity": i % 2, "bucket": i % 10})
        yield srv, base, queries
    finally:
        srv.close()


@stage(2)
def test_the_default_index_is_flat_and_the_object_shows_it(shared):  # noqa: F811
    name = unique("c")
    r = shared.put(f"/v1/collections/{name}", {"dim": 4})
    assert r.status == 201 and r.json()["index"] == {"type": "flat"}, r
    assert shared.get(f"/v1/collections/{name}").json()["index"] == {"type": "flat"}
    listed = {c["name"]: c for c in shared.get("/v1/collections").json()["collections"]}
    assert listed[name]["index"] == {"type": "flat"}


@stage(2)
def test_hnsw_defaults_are_filled_in(shared):  # noqa: F811
    name = unique("c")
    r = shared.put(f"/v1/collections/{name}", {"dim": 4, "index": {"type": "hnsw"}})
    assert r.status == 201 and r.json()["index"] == HNSW_DEFAULTS, r
    name = unique("c")
    r = shared.put(f"/v1/collections/{name}", {"dim": 4, "index": {"type": "hnsw", "m": 4, "ef_construction": 1000}})
    assert r.json()["index"] == {"type": "hnsw", "m": 4, "ef_construction": 1000}


@stage(2)
def test_invalid_index_objects_are_400(shared):  # noqa: F811
    bad = [{"type": "nope"}, {}, {"type": "hnsw", "m": 3}, {"type": "hnsw", "m": 65}, {"type": "hnsw", "m": "16"},
           {"type": "hnsw", "ef_construction": 15}, {"type": "hnsw", "ef_construction": 1001},
           {"type": "hnsw", "m": 16.5}, "hnsw", [], 5]
    for idx in bad:
        expect_error(shared.put(f"/v1/collections/{unique('c')}", {"dim": 4, "index": idx}), 400)
    name = unique("c")
    shared.put(f"/v1/collections/{name}", {"dim": 4})
    for idx in bad:
        expect_error(shared.put(f"/v1/collections/{name}/index", idx), 400)
    expect_error(shared.put(f"/v1/collections/{unique('nope')}/index", {"type": "flat"}), 404)


@stage(2)
def test_put_index_switches_the_index_of_a_populated_collection(server):  # noqa: F811
    base, queries = clustered(1500, queries=10, seed=99)
    server.put("/v1/collections/sw", {"dim": base.shape[1]})
    upsert_all(server, "sw", base)
    q = queries[0].tolist()
    exact = _search(server, "sw", {"vector": q, "k": 10, "explain": True})
    assert _stage2(exact["explain"]) == {"index": "flat", "exact": True, "ef": None, "candidates": 1500}
    r = server.put("/v1/collections/sw/index", {"type": "hnsw", "m": 8})
    assert r.status == 200 and r.json()["index"] == {"type": "hnsw", "m": 8, "ef_construction": 200}
    assert r.json()["points"] == 1500 and r.json()["name"] == "sw"
    approx = _search(server, "sw", {"vector": q, "k": 10, "explain": True, "params": {"ef": 100}})
    assert approx["explain"]["index"] == "hnsw" and approx["explain"]["ef"] == 100
    assert len({x["id"] for x in approx["results"]} & {x["id"] for x in exact["results"]}) >= 8
    server.restart(crash=True)
    assert server.get("/v1/collections/sw").json()["index"]["type"] == "hnsw"
    assert _search(server, "sw", {"vector": q, "k": 10, "explain": True})["explain"]["index"] == "hnsw"
    assert server.put("/v1/collections/sw/index", {"type": "flat"}).json()["index"] == {"type": "flat"}
    assert _search(server, "sw", {"vector": q, "k": 10})["results"] == exact["results"]


@stage(2)
def test_ef_is_validated_and_raised_to_k(small):
    srv, base, queries = small
    q = queries[0].tolist()
    for ef in (0, 2001, "64", 1.5, True):
        expect_error(srv.post("/v1/collections/small/search", {"vector": q, "params": {"ef": ef}}), 400)
    expect_error(srv.post("/v1/collections/small/search", {"vector": q, "params": 5}), 400)
    out = _search(srv, "small", {"vector": q, "k": 30, "params": {"ef": 5}, "explain": True})
    assert out["explain"]["ef"] == 30 and len(out["results"]) == 30
    out = _search(srv, "small", {"vector": q, "k": 10, "explain": True})
    assert out["explain"]["ef"] == 64 and out["explain"]["exact"] is False


@stage(2)
def test_flat_ignores_ef(shared):  # noqa: F811
    name = unique("c")
    shared.put(f"/v1/collections/{name}", {"dim": 2})
    shared.put(f"/v1/collections/{name}/points", {"points": [{"id": i, "vector": [i, 0]} for i in range(30)]})
    out = _search(shared, name, {"vector": [0, 0], "k": 5, "params": {"ef": 1}, "explain": True})
    assert [r["id"] for r in out["results"]] == [0, 1, 2, 3, 4]
    assert _stage2(out["explain"]) == {"index": "flat", "exact": True, "ef": None, "candidates": 30}
    assert "explain" not in _search(shared, name, {"vector": [0, 0]})


@stage(2)
def test_hnsw_never_returns_deleted_or_unmatched_points(small):
    srv, base, queries = small
    deleted = list(range(0, 3000, 3))
    for i in range(0, len(deleted), 500):
        srv.post("/v1/collections/small/points/delete", {"ids": deleted[i:i + 500]})
    gone = set(deleted)
    flt = {"must": [{"key": "parity", "match": {"value": 1}}]}
    b = base.astype(np.float64)
    for q in queries:
        out = _search(srv, "small", {"vector": q.tolist(), "k": 20, "filter": flt, "with_payload": True, "explain": True})
        assert out.get("explain", {}).get("index") == "hnsw", out.get("explain")
        res = out["results"]
        assert res, "no results"
        for r in res:
            assert r["id"] not in gone and r["payload"]["parity"] == 1, r
            assert math.isclose(r["score"], float(np.linalg.norm(b[r["id"]] - q)), rel_tol=1e-6)
        assert [r["score"] for r in res] == sorted(r["score"] for r in res)


@stage(2)
def test_hnsw_follows_updates(small):
    srv, base, queries = small
    q = queries[5]
    target = [int(i) for i in range(1, 3000, 3)][:5]          # live points, moved next to the query
    pts = [{"id": t, "vector": (q + 0.0001 * (j + 1)).tolist(), "payload": {"parity": 7}} for j, t in enumerate(target)]
    assert srv.put("/v1/collections/small/points", {"points": pts}).status == 200
    out = _search(srv, "small", {"vector": q.tolist(), "k": 5, "with_payload": True, "explain": True})
    assert out.get("explain", {}).get("index") == "hnsw", out.get("explain")
    res = out["results"]
    assert [r["id"] for r in res] == target
    assert all(r["payload"] == {"parity": 7} for r in res)


@stage(2)
def test_an_index_set_on_an_empty_collection_is_maintained(server):  # noqa: F811
    server.put("/v1/collections/e", {"dim": 3, "index": {"type": "hnsw", "m": 4, "ef_construction": 16}})
    assert _search(server, "e", {"vector": [1, 0, 0]})["results"] == []
    rng = np.random.default_rng(5)
    vecs = rng.normal(size=(300, 3)).astype(np.float32)
    for i in range(0, 300, 7):
        chunk = [{"id": j, "vector": vecs[j].tolist()} for j in range(i, min(i + 7, 300))]
        assert server.put("/v1/collections/e/points", {"points": chunk}).status == 200
    assert server.get("/v1/collections/e").json()["points"] == 300
    b = vecs.astype(np.float64)
    hits = 0
    for q in rng.normal(size=(20, 3)):
        res = _search(server, "e", {"vector": q.tolist(), "k": 10, "explain": True})
        assert res["explain"]["index"] == "hnsw"
        ids = [r["id"] for r in res["results"]]
        assert len(ids) == len(set(ids)) == 10 and set(ids) <= set(range(300))
        hits += len(set(ids) & set(np.argsort(np.linalg.norm(b - q, axis=1), kind="stable")[:10].tolist()))
    assert hits / 200 >= 0.9
