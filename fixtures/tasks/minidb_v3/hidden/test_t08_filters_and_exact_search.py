"""t08 (stage 1): exact search, scores, ordering and payload filters (brief 1.4)."""
import math

import numpy as np
import pytest

from _support import exact_topk, expect_error, stage, unique

N, DIM = 300, 8
COLORS = ["red", "green", "blue"]


def _payload(i):
    p = {"n": i, "color": COLORS[i % 3], "tags": [f"t{i % 5}", f"t{i % 7}"], "nested": {"x": i % 10, "flag": i % 2 == 0},
         "score": i / 2 if i % 4 else i // 2}
    if i % 11 == 0:
        p["maybe"] = None
    elif i % 11 == 1:
        p["maybe"] = 1
    else:
        p["maybe"] = True if i % 11 == 2 else "x"
    return p


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    from _support import Server
    srv = Server(tmp_path_factory.mktemp("t08"))
    try:
        rng = np.random.default_rng(808)
        base = rng.normal(size=(N, DIM)).astype(np.float32)
        names = {}
        for metric in ("l2", "cosine", "dot"):
            name = unique(metric)
            assert srv.put(f"/v1/collections/{name}", {"dim": DIM, "metric": metric}).status == 201
            pts = [{"id": i, "vector": base[i].tolist(), "payload": _payload(i)} for i in range(N)]
            assert srv.put(f"/v1/collections/{name}/points", {"points": pts}).status == 200
            names[metric] = name
        yield srv, base, names, rng.normal(size=(5, DIM)).astype(np.float32)
    finally:
        srv.close()


def _search(srv, name, body):
    r = srv.post(f"/v1/collections/{name}/search", body)
    assert r.status == 200, r
    return r.json()["results"]


def _ids(res):
    return [x["id"] for x in res]


def _matching(pred):
    return [i for i in range(N) if pred(_payload(i), i)]


def _check_exact(srv, base, name, metric, q, k, ids=None, flt=None):
    res = _search(srv, name, {"vector": q.tolist(), "k": k, **({"filter": flt} if flt is not None else {})})
    sub = list(range(N)) if ids is None else ids
    want = exact_topk(base[sub], q, k, metric, ids=sub)
    assert _ids(res) == [i for i, _ in want], (metric, flt)
    for r, (_, s) in zip(res, want, strict=True):
        assert math.isclose(r["score"], s, rel_tol=1e-6, abs_tol=1e-9), (r, s)
    return res


@stage(1)
def test_exact_search_in_every_metric(data):
    srv, base, names, qs = data
    for metric, name in names.items():
        for q in qs:
            _check_exact(srv, base, name, metric, q, 10)


@stage(1, 3)
def test_scores_are_distances_ascending_for_every_metric(data):
    srv, base, names, qs = data
    q = qs[0].astype(np.float64)
    b = base.astype(np.float64)
    for metric, name in names.items():
        res = _search(srv, name, {"vector": qs[0].tolist(), "k": 5})
        scores = [r["score"] for r in res]
        assert scores == sorted(scores), metric
        top = res[0]
        v = b[top["id"]]
        expect = {"l2": float(np.linalg.norm(v - q)), "dot": -float(v @ q),
                  "cosine": 1.0 - float(v @ q / (np.linalg.norm(v) * np.linalg.norm(q)))}[metric]
        assert math.isclose(top["score"], expect, rel_tol=1e-6, abs_tol=1e-9), (metric, top, expect)


@stage(1)
def test_k_defaults_bounds_and_short_results(data):
    srv, base, names, qs = data
    assert len(_search(srv, names["l2"], {"vector": qs[0].tolist()})) == 10
    assert len(_search(srv, names["l2"], {"vector": qs[0].tolist(), "k": 1000})) == N
    flt = {"must": [{"key": "color", "match": {"value": "red"}}]}
    assert len(_search(srv, names["l2"], {"vector": qs[0].tolist(), "k": 500, "filter": flt})) == N // 3
    for k in (0, 1001, -1, "5", 5.5, True):
        expect_error(srv.post(f"/v1/collections/{names['l2']}/search", {"vector": qs[0].tolist(), "k": k}), 400)


@stage(1)
def test_bad_query_vectors_are_400(data):
    srv, base, names, qs = data
    for v in ([1.0] * (DIM - 1), [1.0] * (DIM + 1), ["a"] * DIM, None, "x", [True] * DIM):
        expect_error(srv.post(f"/v1/collections/{names['l2']}/search", {"vector": v}), 400)
    expect_error(srv.post(f"/v1/collections/{names['l2']}/search", {}), 400)
    expect_error(srv.post(f"/v1/collections/{names['cosine']}/search", {"vector": [0.0] * DIM}), 400)


@stage(1)
def test_ties_are_broken_by_id(tmp_path):
    from _support import Server
    with Server(tmp_path) as srv:
        name = unique("tie")
        srv.put(f"/v1/collections/{name}", {"dim": 2, "metric": "l2"})
        pts = [{"id": i, "vector": v} for i, v in [(9, [1, 0]), (3, [0, 1]), (5, [-1, 0]), (1, [0, -1]), (4, [2, 0])]]
        srv.put(f"/v1/collections/{name}/points", {"points": pts})
        res = _search(srv, name, {"vector": [0, 0], "k": 4})
        assert _ids(res) == [1, 3, 5, 9] and [r["score"] for r in res] == [1.0] * 4


@stage(1)
def test_with_payload_and_with_vector(data):
    srv, base, names, qs = data
    res = _search(srv, names["l2"], {"vector": qs[1].tolist(), "k": 3, "with_payload": True, "with_vector": True})
    for r in res:
        assert set(r) == {"id", "score", "payload", "vector"}
        assert r["payload"] == _payload(r["id"]) and r["vector"] == base[r["id"]].astype(float).tolist()
    res = _search(srv, names["l2"], {"vector": qs[1].tolist(), "k": 3})
    assert all(set(r) == {"id", "score"} for r in res)


FILTERS = [
    ({"must": [{"key": "color", "match": {"value": "red"}}]}, lambda p, i: p["color"] == "red"),
    ({"must": [{"key": "n", "match": {"value": 12.0}}]}, lambda p, i: i == 12),
    ({"must": [{"key": "maybe", "match": {"value": 1}}]}, lambda p, i: p.get("maybe") == 1 and p.get("maybe") is not True),
    ({"must": [{"key": "maybe", "match": {"value": True}}]}, lambda p, i: p.get("maybe") is True),
    ({"must": [{"key": "color", "match": {"any": ["green", "blue", 3]}}]}, lambda p, i: p["color"] != "red"),
    ({"must": [{"key": "score", "range": {"gte": 10, "lt": 20.5}}]}, lambda p, i: 10 <= p["score"] < 20.5),
    ({"must": [{"key": "n", "range": {"gt": 290}}]}, lambda p, i: i > 290),
    ({"must": [{"key": "tags", "match": {"value": "t3"}}]}, lambda p, i: "t3" in p["tags"]),
    ({"must": [{"key": "nested.x", "match": {"value": 4}}]}, lambda p, i: p["nested"]["x"] == 4),
    ({"must": [{"key": "nested.flag", "match": {"value": False}}]}, lambda p, i: not p["nested"]["flag"]),
    ({"must_not": [{"key": "maybe", "match": {"value": "x"}}]}, lambda p, i: p.get("maybe") != "x"),
    ({"must": [{"key": "missing.key", "match": {"value": 1}}]}, lambda p, i: False),
    ({"must": [{"key": "maybe", "range": {"gte": 0}}]}, lambda p, i: p.get("maybe") == 1 and p.get("maybe") is not True),
    ({"should": [{"key": "color", "match": {"value": "red"}}, {"key": "n", "range": {"lt": 5}}]},
     lambda p, i: p["color"] == "red" or i < 5),
    ({"must": [{"should": [{"key": "nested.x", "match": {"value": 1}}, {"key": "nested.x", "match": {"value": 2}}]},
               {"must_not": [{"key": "color", "match": {"value": "blue"}}]}]},
     lambda p, i: p["nested"]["x"] in (1, 2) and p["color"] != "blue"),
    ({"must": [{"has_id": [5, 17, 299, 1000]}]}, lambda p, i: i in (5, 17, 299)),
    ({"should": [], "must": []}, lambda p, i: True),
    ({}, lambda p, i: True),
]


@stage(1)
@pytest.mark.parametrize("case", range(len(FILTERS)))
def test_filters_select_exactly_the_matching_points(data, case):
    srv, base, names, qs = data
    flt, pred = FILTERS[case]
    ids = _matching(pred)
    _check_exact(srv, base, names["l2"], "l2", qs[2], 25, ids=ids, flt=flt)


@stage(1)
def test_filters_nest(data):
    srv, base, names, qs = data
    flt = {"must": [{"must": [{"must": [{"key": "color", "match": {"value": "green"}}]}]}]}
    _check_exact(srv, base, names["dot"], "dot", qs[3], 10, ids=_matching(lambda p, i: p["color"] == "green"), flt=flt)
    deep = {"must": [{"key": "n", "range": {"gte": 0}}]}
    for _ in range(12):
        deep = {"must": [deep]}
    expect_error(srv.post(f"/v1/collections/{names['l2']}/search", {"vector": qs[0].tolist(), "filter": deep}), 400)


@stage(1)
def test_malformed_filters_are_400(data):
    srv, base, names, qs = data
    bad = [{"must": {}}, {"foo": []}, {"must": [{"key": "a"}]}, {"must": [{"key": "a", "match": {"value": [1]}}]},
           {"must": [{"key": "a", "match": {"value": {"b": 1}}}]}, {"must": [{"key": "a", "range": {"gt": "1"}}]},
           {"must": [{"key": "a", "range": {"near": 1}}]}, {"must": [{"key": "a", "match": {"value": 1}, "range": {"gt": 1}}]},
           {"must": [{"key": 5, "match": {"value": 1}}]}, {"must": [{"has_id": 5}]}, {"must": [7]}, [], "color"]
    for flt in bad:
        expect_error(srv.post(f"/v1/collections/{names['l2']}/search", {"vector": qs[0].tolist(), "filter": flt}), 400)


@stage(1)
def test_search_sees_updates_and_deletes(tmp_path):
    from _support import Server
    with Server(tmp_path) as srv:
        name = unique("upd")
        srv.put(f"/v1/collections/{name}", {"dim": 2, "metric": "l2"})
        srv.put(f"/v1/collections/{name}/points", {"points": [{"id": i, "vector": [i, 0]} for i in range(10)]})
        assert _ids(_search(srv, name, {"vector": [0, 0], "k": 2})) == [0, 1]
        srv.post(f"/v1/collections/{name}/points/delete", {"ids": [0]})
        srv.put(f"/v1/collections/{name}/points", {"points": [{"id": 9, "vector": [0.5, 0]}]})
        res = _search(srv, name, {"vector": [0, 0], "k": 3})
        assert _ids(res) == [9, 1, 2] and res[0]["score"] == 0.5
        srv.restart(crash=True)
        assert _ids(_search(srv, name, {"vector": [0, 0], "k": 3})) == [9, 1, 2]
