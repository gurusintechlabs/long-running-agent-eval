"""t12 (stage 4): the ivf_flat, ivf_pq and qsg index types: objects, training, correctness, persistence,
and the targets of brief 4.4 (recall, memory) on the hidden dataset.

The 100,000-point module fixture loads one ivf_pq collection (memory measured during the load), then
retrains it and switches it to qsg. Wall-clock limits live in t13 (filtered search).
"""
import math

import numpy as np
import pytest

from _support import Server, clustered, exact_topk, expect_error, recall_at, server, shared, stage, unique, upsert_all  # noqa: F401

DEFAULTS = {"ivf_flat": {"type": "ivf_flat", "nlist": 256},
            "ivf_pq": {"type": "ivf_pq", "nlist": 256, "m": 16, "nbits": 8},
            "qsg": {"type": "qsg", "degree": 32, "m": 16}}
TYPES = ("ivf_flat", "ivf_pq", "qsg")
N = 100_000
HALF_RAW_BYTES = (N // 2) * 96 * 4          # 19.2 MB: the float32 size of the second half
PQ_RECALL_MIN, QSG_RECALL_MIN = 0.85, 0.95


def _search(srv, name, body):
    r = srv.post(f"/v1/collections/{name}/search", body)
    assert r.status == 200, r
    return r.json()


def _small_index(kind):
    """Settings that train on a few thousand points."""
    return {"ivf_flat": {"type": "ivf_flat", "nlist": 32}, "ivf_pq": {"type": "ivf_pq", "nlist": 32, "m": 16},
            "qsg": {"type": "qsg", "degree": 16, "m": 16}}[kind]


@pytest.fixture(scope="module")
def small(tmp_path_factory):
    """4,000 points with payloads, one collection per new index type (set after loading)."""
    srv = Server(tmp_path_factory.mktemp("t12s"))
    try:
        base, queries = clustered(4000, queries=30, seed=1212)
        for kind in TYPES:
            srv.put(f"/v1/collections/{kind}", {"dim": base.shape[1], "metric": "l2"})
            upsert_all(srv, kind, base, payload=lambda i: {"parity": i % 2})
            r = srv.put(f"/v1/collections/{kind}/index", _small_index(kind), timeout=600)
            assert r.status == 200, r
        yield srv, base, queries
    finally:
        srv.close()


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    srv = Server(tmp_path_factory.mktemp("t12b"))
    try:
        base, queries = clustered(N, queries=100)
        warm, _ = clustered(2000, seed=5)                  # the server's own code paths, before measuring
        srv.put("/v1/collections/warm", {"dim": 96, "metric": "l2"})
        upsert_all(srv, "warm", warm)
        srv.delete("/v1/collections/warm")
        r = srv.put("/v1/collections/big", {"dim": 96, "metric": "l2", "index": {"type": "ivf_pq"}})
        assert r.status == 201, r
        upsert_all(srv, "big", base[: N // 2])
        half = srv.rss()
        upsert_all(srv, "big", base[N // 2:], start_id=N // 2)
        grown = srv.rss() - half
        truth = [[i for i, _ in exact_topk(base, q, 10)] for q in queries]
        yield {"srv": srv, "base": base, "queries": queries, "truth": truth, "grown": grown}
    finally:
        srv.close()


def _recall(h, params):
    found = [[x["id"] for x in _search(h["srv"], "big", {"vector": q.tolist(), "k": 10, "params": params})["results"]]
             for q in h["queries"]]
    return recall_at(found, h["truth"])


# ------------------------------------------------------------------ objects and validation

@stage(4)
def test_new_index_objects_fill_in_defaults(shared):  # noqa: F811
    for kind, full in DEFAULTS.items():
        name = unique("c")
        r = shared.put(f"/v1/collections/{name}", {"dim": 32, "metric": "l2", "index": {"type": kind}})
        assert r.status == 201 and r.json()["index"] == full, r
        assert shared.get(f"/v1/collections/{name}").json()["index"] == full
    name = unique("c")
    r = shared.put(f"/v1/collections/{name}", {"dim": 8, "metric": "l2", "index": {"type": "ivf_pq", "nlist": 4, "m": 4, "nbits": 4}})
    assert r.status == 201 and r.json()["index"] == {"type": "ivf_pq", "nlist": 4, "m": 4, "nbits": 4}, r
    r = shared.put(f"/v1/collections/{name}/index", {"type": "qsg", "m": 8})
    assert r.status == 200 and r.json()["index"] == {"type": "qsg", "degree": 32, "m": 8}, r


@stage(4)
def test_invalid_new_index_objects_are_400(shared):  # noqa: F811
    bad = [{"type": "ivf_flat", "nlist": 0}, {"type": "ivf_flat", "nlist": 4097}, {"type": "ivf_flat", "nlist": "8"},
           {"type": "ivf_flat", "nprobe": 4}, {"type": "ivf_pq", "m": 5}, {"type": "ivf_pq", "nbits": 3},
           {"type": "ivf_pq", "nbits": 9}, {"type": "ivf_pq", "m": 0}, {"type": "qsg", "degree": 7},
           {"type": "qsg", "degree": 129}, {"type": "qsg", "m": 7}, {"type": "qsg", "ef": 64}, {"type": "ivf"}]
    for idx in bad:                                    # dim 32: m 5 and m 7 do not divide it
        expect_error(shared.put(f"/v1/collections/{unique('c')}", {"dim": 32, "index": idx}), 400)
    expect_error(shared.put(f"/v1/collections/{unique('c')}", {"dim": 30, "index": {"type": "ivf_pq"}}), 400)
    name = unique("c")
    shared.put(f"/v1/collections/{name}", {"dim": 32, "metric": "l2", "index": {"type": "ivf_flat", "nlist": 8}})
    for idx in bad:
        expect_error(shared.put(f"/v1/collections/{name}/index", idx), 400)
    q = [0.5] * 32
    for nprobe in (0, 9, "2", 1.5, True):
        expect_error(shared.post(f"/v1/collections/{name}/search", {"vector": q, "params": {"nprobe": nprobe}}), 400)
    assert shared.post(f"/v1/collections/{name}/search", {"vector": q, "params": {"nprobe": 8}}).status == 200


# ------------------------------------------------------------------ training and correctness

@stage(4)
def test_an_untrained_index_searches_exactly_until_it_has_enough_points(server):  # noqa: F811
    base, queries = clustered(1500, queries=5, seed=33)
    server.put("/v1/collections/u", {"dim": 96, "metric": "l2", "index": {"type": "ivf_pq", "nlist": 16}})
    upsert_all(server, "u", base[:600])
    q = queries[0]
    out = _search(server, "u", {"vector": q.tolist(), "k": 10, "explain": True})
    assert out["explain"]["index"] == "ivf_pq" and out["explain"]["exact"] is True, out["explain"]
    assert [r["id"] for r in out["results"]] == [i for i, _ in exact_topk(base[:600], q, 10)]
    upsert_all(server, "u", base[600:], start_id=600)
    out = _search(server, "u", {"vector": q.tolist(), "k": 10, "explain": True, "params": {"nprobe": 4}})
    assert out["explain"]["exact"] is False and out["explain"]["nprobe"] == 4, out["explain"]
    assert len(set(r["id"] for r in out["results"]) & {i for i, _ in exact_topk(base, q, 10)}) >= 7


@stage(4)
def test_ivf_flat_probing_every_list_is_exact(small):
    srv, base, queries = small
    for q in queries[:10]:
        out = _search(srv, "ivf_flat", {"vector": q.tolist(), "k": 10, "explain": True, "params": {"nprobe": 32}})
        assert out["explain"]["index"] == "ivf_flat" and out["explain"]["nprobe"] == 32, out["explain"]
        assert [(r["id"], round(r["score"], 4)) for r in out["results"]] == \
            [(i, round(s, 4)) for i, s in exact_topk(base, q, 10)]
    ex = _search(srv, "ivf_flat", {"vector": queries[0].tolist(), "k": 10, "explain": True})["explain"]
    assert ex["nprobe"] == 16 and ex["exact"] is False and 10 <= ex["candidates"] < 4000, ex


@stage(4)
def test_every_new_index_returns_exact_scores_and_no_deleted_or_unmatched_point(small):
    srv, base, queries = small
    b = base.astype(np.float64)
    gone = set(range(0, 4000, 5))
    for kind in TYPES:
        srv.post(f"/v1/collections/{kind}/points/delete", {"ids": sorted(gone)})
    flt = {"must": [{"key": "parity", "match": {"value": 1}}]}
    for kind in TYPES:
        hits = 0
        for q in queries:
            out = _search(srv, kind, {"vector": q.tolist(), "k": 10, "filter": flt, "with_payload": True,
                                      "explain": True})
            assert out["explain"]["index"] == kind, out["explain"]
            res = out["results"]
            assert len(res) == 10, (kind, len(res))
            for r in res:
                assert r["id"] not in gone and r["payload"] == {"parity": 1}, (kind, r)
                assert math.isclose(r["score"], float(np.linalg.norm(b[r["id"]] - q)), rel_tol=1e-6), (kind, r)
            assert [r["score"] for r in res] == sorted(r["score"] for r in res)
            ok = [i for i in range(4000) if i % 2 and i not in gone]
            hits += len({r["id"] for r in res} & {i for i, _ in exact_topk(base[ok], q, 10, ids=ok)})
        assert hits / (10 * len(queries)) >= 0.9, (kind, hits)


@stage(4)
def test_points_added_after_training_are_found(small):
    srv, base, queries = small
    rng = np.random.default_rng(12)
    for kind in TYPES:
        new = (base[rng.integers(0, 4000, 50)] + rng.normal(0, 0.05, (50, 96))).astype(np.float32)
        pts = [{"id": 10_000 + j, "vector": v.tolist(), "payload": {"parity": 1}} for j, v in enumerate(new)]
        assert srv.put(f"/v1/collections/{kind}/points", {"points": pts}).status == 200
        found = 0
        for j, v in enumerate(new):
            res = _search(srv, kind, {"vector": v.tolist(), "k": 1, "params": {"ef": 64, "nprobe": 16}})["results"]
            found += bool(res) and res[0]["id"] == 10_000 + j and res[0]["score"] < 1e-5
        assert found >= 48, (kind, found)
        moved = {"id": 10_000, "vector": (base[1] + 0.001).tolist(), "payload": {"parity": 1}}
        assert srv.put(f"/v1/collections/{kind}/points", {"points": [moved]}).status == 200
        res = _search(srv, kind, {"vector": new[0].tolist(), "k": 3})["results"]
        assert 10_000 not in [r["id"] for r in res if r["score"] < 1e-5], (kind, res)


@stage(4)
def test_new_indexes_survive_a_restart_and_a_crash(tmp_path):
    base, queries = clustered(3000, queries=10, seed=77)
    with Server(tmp_path) as srv:
        for kind in TYPES:
            srv.put(f"/v1/collections/{kind}", {"dim": 96, "metric": "l2", "index": _small_index(kind)})
            upsert_all(srv, kind, base)
        before = {kind: [_search(srv, kind, {"vector": q.tolist(), "k": 10})["results"] for q in queries] for kind in TYPES}
        for crash in (False, True):
            srv.restart(crash=crash)
            for kind in TYPES:
                assert srv.get(f"/v1/collections/{kind}").json()["index"] == _small_index(kind) | \
                    {k: v for k, v in DEFAULTS[kind].items() if k not in _small_index(kind)}
                for q, want in zip(queries, before[kind], strict=True):
                    got = _search(srv, kind, {"vector": q.tolist(), "k": 10, "explain": True})
                    assert got["explain"]["index"] == kind and got["explain"]["exact"] is False, got["explain"]
                    assert len({r["id"] for r in got["results"]} & {r["id"] for r in want}) >= 9, kind


@stage(4)
def test_cosine_and_dot_collections_keep_the_cr1_rules(tmp_path):
    base, queries = clustered(2500, queries=10, seed=88)
    b = base.astype(np.float64)
    with Server(tmp_path) as srv:
        for metric in ("cosine", "dot"):
            for kind in TYPES:
                name = f"{metric}-{kind}".replace("_", "-")
                srv.put(f"/v1/collections/{name}", {"dim": 96, "metric": metric})
                upsert_all(srv, name, base)
                assert srv.put(f"/v1/collections/{name}/index", _small_index(kind), timeout=600).status == 200
                for q in queries:
                    res = _search(srv, name, {"vector": q.tolist(), "k": 10})["results"]
                    assert len(res) == 10
                    scores = [r["score"] for r in res]
                    assert scores == sorted(scores, reverse=True), (name, scores)
                    for r in res:
                        v = b[r["id"]]
                        want = float(v @ q) if metric == "dot" else float(v @ q / (np.linalg.norm(v) * np.linalg.norm(q)))
                        assert math.isclose(r["score"], want, rel_tol=1e-6, abs_tol=1e-9), (name, r)
                    if metric == "cosine":
                        truth = {i for i, _ in exact_topk(base, q, 10, "cosine")}
                        assert len({r["id"] for r in res} & truth) >= 7, name


# ------------------------------------------------------------------ targets at 100,000 points

@stage(4)
def test_loading_into_ivf_pq_does_not_keep_the_vectors_in_memory(big):
    assert big["grown"] < HALF_RAW_BYTES, f"resident memory grew by {big['grown'] / 1e6:.1f} MB over the second 50,000 points"
    assert big["srv"].get("/v1/collections/big").json()["points"] == N


@stage(4)
def test_ivf_pq_recall_at_nprobe_16(big):
    r = big["srv"].put("/v1/collections/big/index", {"type": "ivf_pq"}, timeout=900)       # trained on all points
    assert r.status == 200 and r.json()["points"] == N, r
    assert _recall(big, {"nprobe": 16}) >= PQ_RECALL_MIN
    ex = _search(big["srv"], "big", {"vector": big["queries"][0].tolist(), "k": 10, "explain": True})["explain"]
    assert ex["index"] == "ivf_pq" and ex["exact"] is False and ex["nprobe"] == 16, ex
    assert 10 <= ex["candidates"] <= N // 20, ex


@stage(4)
def test_qsg_recall_at_ef_64(big):
    r = big["srv"].put("/v1/collections/big/index", {"type": "qsg"}, timeout=1200)
    assert r.status == 200 and r.json()["index"] == DEFAULTS["qsg"], r
    assert _recall(big, {"ef": 64}) >= QSG_RECALL_MIN
    ex = _search(big["srv"], "big", {"vector": big["queries"][0].tolist(), "k": 10, "explain": True,
                                     "params": {"ef": 64}})["explain"]
    assert ex["index"] == "qsg" and ex["exact"] is False and ex["ef"] == 64 and 10 <= ex["candidates"] <= N // 20, ex


@stage(4)
def test_qsg_uses_less_memory_than_hnsw(tmp_path):
    base, queries = clustered(20_000, queries=50)
    truth = [[i for i, _ in exact_topk(base, q, 10)] for q in queries]
    grown = {}
    for kind in ("hnsw", "qsg"):
        with Server(tmp_path / kind) as srv:
            warm, _ = clustered(2000, seed=5)
            srv.put("/v1/collections/warm", {"dim": 96, "metric": "l2"})
            upsert_all(srv, "warm", warm)
            srv.delete("/v1/collections/warm")
            before = srv.rss()
            srv.put("/v1/collections/c", {"dim": 96, "metric": "l2"})
            upsert_all(srv, "c", base)
            assert srv.put("/v1/collections/c/index", {"type": kind}, timeout=900).status == 200
            found = [[x["id"] for x in _search(srv, "c", {"vector": q.tolist(), "k": 10})["results"]] for q in queries]
            assert recall_at(found, truth) >= 0.9, kind
            grown[kind] = srv.rss() - before
    assert grown["qsg"] < grown["hnsw"], {k: f"{v / 1e6:.1f} MB" for k, v in grown.items()}
