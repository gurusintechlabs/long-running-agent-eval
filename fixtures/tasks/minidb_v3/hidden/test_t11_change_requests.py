"""t11 (stage 3): CR-1 score direction, CR-2 UUID point ids, CR-3 problem details.

Each replaces earlier behaviour; the tests that pinned the old behaviour are retired at stage 3
(t03 stage-0 error model, t08 distances for every metric)."""
import json
import math
import uuid

import numpy as np

from _support import Server, clustered, exact_topk, expect_error, shared, stage, unique, upsert_all  # noqa: F401

U1 = "6F9619FF-8B86-D011-B42D-00C04FC964FF"
U2 = "00000000000000000000000000000001"
U3 = "ffffffff-ffff-4fff-8fff-ffffffffffff"


def _canon(u):
    return str(uuid.UUID(u))


def _coll(srv, dim, metric="l2", index=None):
    name = unique("c")
    body = {"dim": dim, "metric": metric, **({"index": index} if index else {})}
    assert srv.put(f"/v1/collections/{name}", body).status == 201
    return name


def _search(srv, name, body):
    r = srv.post(f"/v1/collections/{name}/search", body)
    assert r.status == 200, r
    return r.json()["results"]


# ---------------------------------------------------------------- CR-1

@stage(3)
def test_cosine_scores_are_similarities_descending(shared):  # noqa: F811
    rng = np.random.default_rng(31)
    base = rng.normal(size=(200, 6)).astype(np.float32)
    name = _coll(shared, 6, "cosine")
    upsert_all(shared, name, base)
    q = rng.normal(size=6)
    res = _search(shared, name, {"vector": q.tolist(), "k": 8})
    b = base.astype(np.float64)
    cos = b @ q / (np.linalg.norm(b, axis=1) * np.linalg.norm(q))
    assert [r["id"] for r in res] == [int(i) for i in np.argsort(-cos, kind="stable")[:8]]
    assert all(math.isclose(r["score"], cos[r["id"]], rel_tol=1e-9, abs_tol=1e-12) for r in res)
    assert res[0]["score"] >= res[-1]["score"]
    # equal similarities: ids ascending; l2 is unchanged (distance, ascending)
    ties = _coll(shared, 2, "cosine")
    shared.put(f"/v1/collections/{ties}/points", {"points": [{"id": i, "vector": [2, 2]} for i in (9, 4, 6)]
                                                            + [{"id": 1, "vector": [0, 1]}]})
    assert [(r["id"], round(r["score"], 9)) for r in _search(shared, ties, {"vector": [1, 1], "k": 4})] == [
        (4, 1.0), (6, 1.0), (9, 1.0), (1, round(2 ** -0.5, 9))]
    l2 = _coll(shared, 2)
    shared.put(f"/v1/collections/{l2}/points", {"points": [{"id": 1, "vector": [3, 4]}, {"id": 2, "vector": [1, 0]}]})
    assert _search(shared, l2, {"vector": [0, 0], "k": 2}) == [{"id": 2, "score": 1.0}, {"id": 1, "score": 5.0}]


@stage(3)
def test_dot_scores_are_inner_products_descending(shared):  # noqa: F811
    name = _coll(shared, 2, "dot")
    shared.put(f"/v1/collections/{name}/points", {"points": [{"id": 1, "vector": [1, 0]}, {"id": 2, "vector": [3, 0]},
                                                             {"id": 3, "vector": [0, 1]}, {"id": 4, "vector": [-2, 0]}]})
    res = _search(shared, name, {"vector": [2, 0], "k": 4})
    assert [(r["id"], r["score"]) for r in res] == [(2, 6.0), (1, 2.0), (3, 0.0), (4, -4.0)]
    # the SQL functions do not change
    (sql,) = shared.sql("SELECT cosine_distance(VECTOR '[1, 0]', VECTOR '[0, 1]'), inner_product(VECTOR '[1, 2]', VECTOR '[3, 4]');")
    assert sql["rows"] == [[1.0, 11.0]]


@stage(3)
def test_index_searches_follow_cr1(tmp_path):
    base, queries = clustered(3000, queries=20, seed=303)
    with Server(tmp_path) as srv:
        srv.put("/v1/collections/hc", {"dim": base.shape[1], "metric": "cosine", "index": {"type": "hnsw", "m": 8}})
        upsert_all(srv, "hc", base)
        hits = 0
        for q in queries:
            r = srv.post("/v1/collections/hc/search", {"vector": q.tolist(), "k": 10, "explain": True}).json()
            assert r["explain"]["index"] == "hnsw"
            scores = [x["score"] for x in r["results"]]
            assert scores == sorted(scores, reverse=True) and all(-1.0 <= s <= 1.0 + 1e-9 for s in scores)
            want = exact_topk(base, q, 10, "cosine", cr1=True)
            hits += len({x["id"] for x in r["results"]} & {i for i, _ in want})
        assert hits / 200 >= 0.9


# ---------------------------------------------------------------- CR-2

@stage(3)
def test_uuid_ids_are_accepted_in_any_form_and_returned_canonical(shared):  # noqa: F811
    name = _coll(shared, 2)
    r = shared.put(f"/v1/collections/{name}/points", {"points": [{"id": U1, "vector": [1, 0], "payload": {"u": 1}},
                                                                 {"id": U2, "vector": [0, 1]}, {"id": 7, "vector": [1, 1]}]})
    assert r.status == 200 and r.json() == {"upserted": 3}, r
    for form in (U1, U1.lower(), U1.replace("-", ""), _canon(U1)):
        p = shared.get(f"/v1/collections/{name}/points/{form}")
        assert p.status == 200 and p.json() == {"id": _canon(U1), "vector": [1.0, 0.0], "payload": {"u": 1}}, (form, p)
    assert shared.get(f"/v1/collections/{name}/points/{_canon(U2)}").json()["id"] == _canon(U2)
    assert shared.get(f"/v1/collections/{name}/points/7").json()["id"] == 7
    r = shared.put(f"/v1/collections/{name}/points", {"points": [{"id": U1.lower(), "vector": [5, 5]}]})
    assert r.status == 200 and shared.get(f"/v1/collections/{name}").json()["points"] == 3      # same point
    res = _search(shared, name, {"vector": [5, 5], "k": 1})
    assert res[0]["id"] == _canon(U1)


@stage(3)
def test_strings_that_are_not_uuids_are_400(shared):  # noqa: F811
    name = _coll(shared, 1)
    for bad in ("7", "", "x", U1[:-1], U1 + "0", "6f9619ff-8b86-d011-b42d-00c04fc964fg", " " + _canon(U1)):
        expect_error(shared.put(f"/v1/collections/{name}/points", {"points": [{"id": bad, "vector": [1]}]}), 400)
        expect_error(shared.post(f"/v1/collections/{name}/points/delete", {"ids": [bad]}), 400)
    assert shared.get(f"/v1/collections/{name}").json()["points"] == 0
    assert shared.get(f"/v1/collections/{name}/points/not-a-uuid").status in (400, 404)


@stage(3)
def test_integers_sort_before_uuids_and_uuids_by_canonical_string(shared):  # noqa: F811
    name = _coll(shared, 1)
    ids = [U3, 12, U1, 3, U2]
    shared.put(f"/v1/collections/{name}/points", {"points": [{"id": i, "vector": [1]} for i in ids]})
    res = _search(shared, name, {"vector": [1], "k": 5})
    assert [r["id"] for r in res] == [3, 12] + sorted(_canon(u) for u in (U1, U2, U3))


@stage(3)
def test_uuid_ids_in_deletes_filters_and_after_restart(tmp_path):
    with Server(tmp_path) as srv:
        name = _coll(srv, 2, "cosine")
        srv.put(f"/v1/collections/{name}/points", {"points": [{"id": U1, "vector": [1, 0]}, {"id": U2, "vector": [0, 1]},
                                                              {"id": U3, "vector": [1, 1]}, {"id": 1, "vector": [1, 2]}]})
        flt = {"must": [{"has_id": [U2.upper(), 1]}]}
        assert {r["id"] for r in _search(srv, name, {"vector": [1, 1], "filter": flt})} == {_canon(U2), 1}
        r = srv.post(f"/v1/collections/{name}/points/delete", {"ids": [_canon(U3).upper().replace("-", ""), 99]})
        assert r.json() == {"deleted": 1}
        srv.restart(crash=True)
        assert {r["id"] for r in _search(srv, name, {"vector": [1, 1], "k": 10})} == {_canon(U1), _canon(U2), 1}
        assert srv.get(f"/v1/collections/{name}/points/{_canon(U2)}").json()["id"] == _canon(U2)


# ---------------------------------------------------------------- CR-3

def _problem(r, status, path):
    assert r.status == status, r
    assert r.ctype == "application/problem+json", r.headers
    body = r.json()
    assert set(body) >= {"type", "title", "status", "detail", "instance"} and "error" not in body, body
    slug = {400: "bad-request", 401: "unauthorized", 404: "not-found", 405: "method-not-allowed", 409: "conflict",
            411: "length-required", 413: "payload-too-large"}[status]
    assert body["type"] == f"https://minidb.dev/problems/{slug}" and body["status"] == status, body
    assert isinstance(body["title"], str) and body["title"] and isinstance(body["detail"], str), body
    assert body["instance"] == path, body
    return body


@stage(3)
def test_errors_are_problem_documents(shared):  # noqa: F811
    name = _coll(shared, 2)
    _problem(shared.post("/v1/sql", {"sql": "SELECT 1;"}, key="nope"), 401, "/v1/sql")
    _problem(shared.post("/v1/sql", {"sql": 1}), 400, "/v1/sql")
    _problem(shared.get("/v1/missing"), 404, "/v1/missing")
    _problem(shared.get(f"/v1/collections/{name}/points/42"), 404, f"/v1/collections/{name}/points/42")
    _problem(shared.put(f"/v1/collections/{name}", {"dim": 2}), 409, f"/v1/collections/{name}")
    _problem(shared.put(f"/v1/collections/{name}/points", {"points": [{"id": 1, "vector": [1]}]}), 400,
             f"/v1/collections/{name}/points")
    r = shared.request("DELETE", "/v1/sql")
    _problem(r, 405, "/v1/sql")
    assert "POST" in r.headers.get("allow", "")
    # statement errors are not HTTP errors: they stay inside the results, in the engine's format
    r = shared.post("/v1/sql", {"sql": "SELECT x; SELECT 1 / 0; INSERT INTO nowhere VALUES (1);"})
    assert r.status == 200 and r.ctype == "application/json"
    for err in r.json()["results"]:
        assert err["ok"] is False and set(err["error"]) == {"type", "message"}, err


@stage(3)
def test_framing_errors_are_problem_documents_too(shared):  # noqa: F811
    for raw, status in ((f"POST /v1/sql HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {shared.admin_key}\r\n"
                         "Connection: close\r\n\r\n", 411),
                        (f"POST /v1/sql HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {shared.admin_key}\r\n"
                         "Content-Length: 99999999\r\nConnection: close\r\n\r\n", 413)):
        r = shared.raw(raw.encode(), timeout=10)
        assert r.status == status, r
        head, _, body = r.data.partition(b"\r\n\r\n")
        assert b"application/problem+json" in head.lower(), head
        assert json.loads(body)["status"] == status, body
