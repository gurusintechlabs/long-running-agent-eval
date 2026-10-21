"""t13 (stage 4): filtered search returns k results for every index type, the 1% filter target, and the
knn() SQL table function (brief 4.2-4.4)."""
import json
import statistics
import time

import numpy as np
import pytest

from _support import Server, clustered, exact_topk, stage, upsert_all

KINDS = {"flat": {"type": "flat"}, "hnsw": {"type": "hnsw", "m": 8, "ef_construction": 64},
         "ivf_flat": {"type": "ivf_flat", "nlist": 32}, "ivf_pq": {"type": "ivf_pq", "nlist": 32},
         "qsg": {"type": "qsg", "degree": 16}}
N_SMALL = 5000
N_BIG = 100_000
FILTER_MEDIAN_MAX_S = 0.050


def _payload(i):
    return {"pct": i % 100, "tag": f"t{i % 7}", "flags": ["even" if i % 2 == 0 else "odd", f"m{i % 3}"]}


def _search(srv, name, body):
    r = srv.post(f"/v1/collections/{name}/search", body)
    assert r.status == 200, r
    return r.json()


@pytest.fixture(scope="module")
def kinds(tmp_path_factory):
    srv = Server(tmp_path_factory.mktemp("t13k"))
    try:
        base, queries = clustered(N_SMALL, queries=12, seed=1313)
        for name, idx in KINDS.items():
            srv.put(f"/v1/collections/{name.replace('_', '-')}", {"dim": 96})
            upsert_all(srv, name.replace("_", "-"), base, payload=_payload)
            assert srv.put(f"/v1/collections/{name.replace('_', '-')}/index", idx, timeout=600).status == 200
        yield srv, base, queries
    finally:
        srv.close()


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    srv = Server(tmp_path_factory.mktemp("t13b"))
    try:
        base, queries = clustered(N_BIG, queries=60, seed=1314)
        srv.put("/v1/collections/big", {"dim": 96})
        upsert_all(srv, "big", base, payload=lambda i: {"pct": i % 100, "n": i})
        assert srv.put("/v1/collections/big/index", {"type": "ivf_pq"}, timeout=900).status == 200
        yield srv, base, queries
    finally:
        srv.close()


FILTERS = [  # (filter, predicate over the point id)
    ({"must": [{"key": "pct", "match": {"value": 42}}]}, lambda i: i % 100 == 42),                       # 1%
    ({"must": [{"key": "pct", "range": {"lt": 3}}, {"key": "flags", "match": {"value": "odd"}}]},
     lambda i: i % 100 < 3 and i % 2 == 1),                                                           # 1.5%
    ({"should": [{"key": "tag", "match": {"any": ["t1", "t2"]}}], "must_not": [{"key": "flags", "match": {"value": "m0"}}]},
     lambda i: i % 7 in (1, 2) and i % 3 != 0),                                                        # 19%
    ({"must_not": [{"key": "pct", "range": {"gte": 90}}]}, lambda i: i % 100 < 90),                   # 90%
    ({"must": [{"key": "pct", "match": {"value": 7}}, {"key": "tag", "match": {"value": "t3"}}]},
     lambda i: i % 100 == 7 and i % 7 == 3),                                                           # 0.14%: 7 points
]


@stage(4)
def test_filtered_search_returns_k_results_for_every_index_type(kinds):
    srv, base, queries = kinds
    for name in KINDS:
        coll = name.replace("_", "-")
        for flt, pred in FILTERS:
            ok = [i for i in range(N_SMALL) if pred(i)]
            hits = total = 0
            for q in queries:
                out = _search(srv, coll, {"vector": q.tolist(), "k": 20, "filter": flt, "with_payload": True})
                res = out["results"]
                assert len(res) == min(20, len(ok)), (name, flt, len(res), len(ok))
                assert all(pred(r["id"]) for r in res), (name, flt)
                assert len({r["id"] for r in res}) == len(res)
                truth = {i for i, _ in exact_topk(base[ok], q, 20, ids=ok)}
                hits += len({r["id"] for r in res} & truth)
                total += len(truth)
            assert hits / total >= (1.0 if name == "flat" else 0.85), (name, flt, hits / total)


@stage(4)
def test_explain_reports_the_filter_strategy(kinds):
    srv, base, queries = kinds
    q = queries[0].tolist()
    for name in KINDS:
        coll = name.replace("_", "-")
        assert _search(srv, coll, {"vector": q, "explain": True})["explain"]["filter"] == "none"
        assert _search(srv, coll, {"vector": q, "explain": True, "filter": {}})["explain"]["filter"] == "none"
        for flt, _ in FILTERS:
            ex = _search(srv, coll, {"vector": q, "explain": True, "filter": flt})["explain"]
            assert ex["index"] == name and ex["filter"] in ("pre", "post"), ex
        if name == "flat":
            assert ex["filter"] == "pre" and ex["exact"] is True


@stage(4)
def test_a_filter_matching_1_percent_timing(big):
    srv, base, queries = big
    flt = {"must": [{"key": "pct", "match": {"value": 17}}]}
    ok = list(range(17, N_BIG, 100))
    lat = []
    for q in queries:
        t0 = time.monotonic()
        out = _search(srv, "big", {"vector": q.tolist(), "k": 10, "filter": flt})
        lat.append(time.monotonic() - t0)
        assert len(out["results"]) == 10 and all(r["id"] % 100 == 17 for r in out["results"])
    assert statistics.median(lat) <= FILTER_MEDIAN_MAX_S, f"median {statistics.median(lat) * 1000:.1f} ms"
    q = queries[0]
    got = [r["id"] for r in _search(srv, "big", {"vector": q.tolist(), "k": 10, "filter": flt})["results"]]
    assert len(set(got) & {i for i, _ in exact_topk(base[ok], q, 10, ids=ok)}) >= 8


# ------------------------------------------------------------------ knn() in SQL

def _vec_sql(q):
    return "VECTOR '" + json.dumps([float(x) for x in q]) + "'"


def _knn(srv, sql):
    (res,) = srv.sql(sql)
    assert res.get("ok") is True, res
    return res


@stage(4)
def test_knn_returns_the_rows_of_the_search_endpoint(kinds):
    srv, base, queries = kinds
    for name in ("flat", "hnsw", "ivf_pq", "qsg"):
        coll = name.replace("_", "-")
        for q in queries[:4]:
            res = _knn(srv, f"SELECT id, score, payload FROM knn('{coll}', {_vec_sql(q)}, 15)")
            assert [c.lower() for c in res["columns"]] == ["id", "score", "payload"]
            want = _search(srv, coll, {"vector": [float(x) for x in q], "k": 15, "with_payload": True})["results"]
            assert [r[0] for r in res["rows"]] == [w["id"] for w in want], name
            for row, w in zip(res["rows"], want, strict=True):
                assert abs(row[1] - w["score"]) <= 1e-9 * max(1.0, abs(w["score"])), (name, row, w)
                assert json.loads(row[2]) == w["payload"]


@stage(4)
def test_knn_can_be_joined_filtered_grouped_and_ordered(kinds):
    srv, base, queries = kinds
    q = queries[1]
    srv.sql("CREATE TABLE t13_tags (pid INTEGER PRIMARY KEY, label TEXT)")
    want = _search(srv, "flat", {"vector": [float(x) for x in q], "k": 30})["results"]
    ids = [w["id"] for w in want]
    srv.sql("INSERT INTO t13_tags VALUES " + ", ".join(f"({i}, 'L{i % 3}')" for i in ids[::2]))
    res = _knn(srv, f"SELECT k.id, t.label FROM knn('flat', {_vec_sql(q)}, 30) AS k JOIN t13_tags t ON t.pid = k.id "
                    "ORDER BY k.score, k.id")
    assert [r[0] for r in res["rows"]] == ids[::2] and all(r[1] == f"L{r[0] % 3}" for r in res["rows"])
    cut = want[9]["score"]
    res = _knn(srv, f"SELECT id FROM knn('flat', {_vec_sql(q)}, 30) WHERE score <= {cut!r} ORDER BY id DESC")
    assert [r[0] for r in res["rows"]] == sorted(ids[:10], reverse=True)
    res = _knn(srv, f"SELECT COUNT(*), MIN(score) FROM knn('flat', {_vec_sql(q)}, 30)")
    assert res["rows"][0][0] == 30 and abs(res["rows"][0][1] - want[0]["score"]) < 1e-9


@stage(4)
def test_knn_errors(kinds):
    srv, base, queries = kinds
    q = _vec_sql(queries[0])
    (res,) = srv.sql(f"SELECT * FROM knn('no-such-collection', {q}, 5)")
    assert res["ok"] is False and res["error"]["type"] == "NameError", res
    for bad in (f"knn('flat', '[1, 2]', 5)", f"knn('flat', VECTOR '[1, 2]', 5)", f"knn(42, {q}, 5)",
                f"knn('flat', {q}, 0)", f"knn('flat', {q}, 1001)", f"knn('flat', {q}, 'five')"):
        (res,) = srv.sql(f"SELECT * FROM {bad}")
        assert res["ok"] is False and res["error"]["type"] == "TypeError", (bad, res)
    out = srv.sql(f"SELECT 1; SELECT * FROM knn('nope', {q}, 1); SELECT 2")         # processing continues
    assert [r["ok"] for r in out] == [True, False, True]


@stage(4)
def test_knn_follows_upserts_and_deletes(tmp_path):
    with Server(tmp_path) as srv:
        srv.put("/v1/collections/k", {"dim": 2, "metric": "cosine"})
        srv.put("/v1/collections/k/points", {"points": [{"id": i, "vector": [1, i / 10], "payload": {"i": i}} for i in range(5)]})
        rows = _knn(srv, "SELECT id, score FROM knn('k', VECTOR '[1, 0]', 3)")["rows"]
        assert [r[0] for r in rows] == [0, 1, 2] and rows[0][1] > rows[1][1] > rows[2][1]       # CR-1
        srv.post("/v1/collections/k/points/delete", {"ids": [0]})
        srv.put("/v1/collections/k/points", {"points": [{"id": "6a2f41a3-c54c-fce8-32d2-0324e1c32e22", "vector": [2, 0]}]})
        rows = _knn(srv, "SELECT id, payload FROM knn('k', VECTOR '[1, 0]', 2)")["rows"]
        assert [r[0] for r in rows] == ["6a2f41a3-c54c-fce8-32d2-0324e1c32e22", 1], rows
        assert rows[0][1] is None and json.loads(rows[1][1]) == {"i": 1}
        assert np.isfinite([r[0] for r in _knn(srv, "SELECT score FROM knn('k', VECTOR '[0, 1]', 4)")["rows"]]).all()
