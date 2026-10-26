"""t09 (stage 2): the hnsw index on the hidden dataset: recall, latency, build time, restart (brief 2.3).

One server and one 20,000-point collection for the module. Wall-clock limits are in tests named
*timing* (deselected in per-commit scoring, rerun once at checkpoints). The restart test runs last.
"""
import math
import statistics
import time

import pytest

from _support import Server, clustered, exact_topk, recall_at, stage, upsert_all

N = 20_000
QUERIES = 200
RECALL_MIN = 0.95
LATENCY_MEDIAN_MAX_S = 0.015
UPSERT_MAX_S = 60.0


@pytest.fixture(scope="module")
def hnsw(tmp_path_factory):
    srv = Server(tmp_path_factory.mktemp("t09"))
    try:
        base, queries = clustered(N, queries=QUERIES)
        r = srv.put("/v1/collections/hidden", {"dim": base.shape[1], "metric": "l2", "index": {"type": "hnsw"}})
        assert r.status == 201, r
        assert r.json().get("index", {}).get("type") == "hnsw", r
        t0 = time.monotonic()
        upsert_all(srv, "hidden", base)
        upsert_s = time.monotonic() - t0
        truth = [[i for i, _ in exact_topk(base, q, 10)] for q in queries]
        yield {"srv": srv, "base": base, "queries": queries, "truth": truth, "upsert_s": upsert_s}
    finally:
        srv.close()


def _search(srv, q, **extra):
    r = srv.post("/v1/collections/hidden/search", {"vector": q.tolist(), "k": 10, **extra})
    assert r.status == 200, r
    return r.json()


def _recall(h):
    found = [[x["id"] for x in _search(h["srv"], q, params={"ef": 64})["results"]] for q in h["queries"]]
    return recall_at(found, h["truth"])


@stage(2)
def test_upserting_20k_points_into_hnsw_timing(hnsw):
    assert hnsw["upsert_s"] <= UPSERT_MAX_S, f"{hnsw['upsert_s']:.1f} s"
    assert hnsw["srv"].get("/v1/collections/hidden").json()["points"] == N


@stage(2)
def test_recall_at_10_with_ef_64(hnsw):
    assert _recall(hnsw) >= RECALL_MIN


@stage(2)
def test_search_latency_median_timing(hnsw):
    srv, lat = hnsw["srv"], []
    for q in hnsw["queries"]:
        t0 = time.monotonic()
        _search(srv, q, params={"ef": 64})
        lat.append(time.monotonic() - t0)
    assert statistics.median(lat) <= LATENCY_MEDIAN_MAX_S, f"median {statistics.median(lat) * 1000:.1f} ms"


@stage(2)
def test_an_index_search_scores_few_points_exactly(hnsw):
    for q in hnsw["queries"][:20]:
        ex = _search(hnsw["srv"], q, params={"ef": 64}, explain=True)["explain"]
        assert ex["index"] == "hnsw" and ex["exact"] is False and ex["ef"] == 64, ex
        assert 10 <= ex["candidates"] <= N // 10, ex


@stage(2)
def test_returned_scores_are_exact(hnsw):
    base = hnsw["base"].astype("float64")
    for q in hnsw["queries"][:20]:
        res = _search(hnsw["srv"], q)["results"]
        assert len(res) == 10
        scores = [r["score"] for r in res]
        assert scores == sorted(scores)
        for r in res:
            assert math.isclose(r["score"], float(((base[r["id"]] - q) ** 2).sum() ** 0.5), rel_tol=1e-6)


@stage(2)
def test_a_cosine_hnsw_collection_reaches_the_recall_target(tmp_path):
    base, queries = clustered(5000, queries=100, seed=77)
    with Server(tmp_path) as srv:
        r = srv.put("/v1/collections/cos", {"dim": base.shape[1], "metric": "cosine", "index": {"type": "hnsw", "m": 12}})
        assert r.status == 201 and r.json().get("index", {}).get("type") == "hnsw", r
        upsert_all(srv, "cos", base)
        found, truth = [], []
        for q in queries:
            r = srv.post("/v1/collections/cos/search", {"vector": q.tolist(), "k": 10, "params": {"ef": 64}})
            found.append([x["id"] for x in r.json()["results"]])
            truth.append([i for i, _ in exact_topk(base, q, 10, "cosine")])
        assert recall_at(found, truth) >= RECALL_MIN


@stage(2)
def test_a_clean_restart_does_not_rebuild_the_graph_timing(hnsw):
    srv = hnsw["srv"]
    ready_s = srv.restart()
    assert ready_s <= max(3.0, 0.25 * hnsw["upsert_s"]), f"ready after {ready_s:.1f} s (upsert took {hnsw['upsert_s']:.1f} s)"
    assert srv.get("/v1/collections/hidden").json()["index"]["type"] == "hnsw"
    assert _recall(hnsw) >= RECALL_MIN
