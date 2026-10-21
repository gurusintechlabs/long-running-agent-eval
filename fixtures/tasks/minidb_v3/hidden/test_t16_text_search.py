"""t16 (stage 6): text collections and search through the embedding service (brief 6.1, 6.2), with the
service's retries, batching and cache. ``test_cf_*``: the planted false fact of docs/LEGACY_API.md
(the service's vectors are NOT normalised; CF detector, docs/minidb-v3-design.md §8)."""
import math
import time

import numpy as np
import pytest

from _support import FakeEmbed, Server, expect_error, new_key, stage

TEXTS = [f"document number {i} about {['cats', 'dogs', 'fish', 'birds'][i % 4]}" for i in range(40)]


@pytest.fixture
def embed():
    e = FakeEmbed()
    yield e
    e.close()


@pytest.fixture
def srv(tmp_path, embed):
    s = Server(tmp_path / "srv", embed=embed)
    try:
        yield s
    finally:
        s.close()


def _text_coll(srv, name="docs", metric="cosine", **extra):
    r = srv.put(f"/v1/collections/{name}", {"dim": 96, "metric": metric, "embedding": "service", **extra})
    assert r.status == 201, r
    return r.json()


def _put_texts(srv, name, texts, start=0, payload=None, **kw):
    pts = [{"id": start + i, "text": t, **({"payload": payload(start + i)} if payload else {})} for i, t in enumerate(texts)]
    return srv.put(f"/v1/collections/{name}/points/text", {"points": pts}, timeout=120, **kw)


def _f32(v):
    return np.asarray(v, np.float32).astype(np.float64)


@stage(6)
def test_text_collections_need_dim_96_and_show_their_embedding(srv):
    obj = _text_coll(srv)
    assert obj["embedding"] == "service" and obj["dim"] == 96
    assert srv.get("/v1/collections/docs").json()["embedding"] == "service"
    for body in ({"dim": 32, "embedding": "service"}, {"dim": 96, "embedding": "openai"}, {"dim": 96, "embedding": True}):
        expect_error(srv.put("/v1/collections/bad", body), 400)
    srv.restart()
    assert srv.get("/v1/collections/docs").json()["embedding"] == "service"


@stage(6)
def test_text_points_are_embedded_and_kept_with_their_text(srv, embed):
    _text_coll(srv)
    r = _put_texts(srv, "docs", TEXTS[:5], payload=lambda i: {"n": i})
    assert r.status == 200 and r.json() == {"upserted": 5}, r
    for i, t in enumerate(TEXTS[:5]):
        p = srv.get(f"/v1/collections/docs/points/{i}").json()
        assert p["text"] == t and p["payload"] == {"n": i}
        assert np.allclose(p["vector"], _f32(embed.vector(t)), rtol=0, atol=1e-6)
    srv.restart(crash=True)
    assert srv.get("/v1/collections/docs/points/3").json()["text"] == TEXTS[3]
    assert srv.get("/v1/collections/docs").json()["points"] == 5


@stage(6)
def test_search_text_finds_the_closest_texts(srv, embed):
    _text_coll(srv)
    assert _put_texts(srv, "docs", TEXTS, payload=lambda i: {"kind": i % 4}).status == 200
    out = srv.post("/v1/collections/docs/search_text", {"text": TEXTS[7], "k": 3, "with_payload": True}).json()
    assert out["results"][0]["id"] == 7 and math.isclose(out["results"][0]["score"], 1.0, abs_tol=1e-6)
    flt = {"must": [{"key": "kind", "match": {"value": 2}}]}
    out = srv.post("/v1/collections/docs/search_text", {"text": "some new query", "k": 5, "filter": flt,
                                                        "with_payload": True}).json()["results"]
    assert len(out) == 5 and all(r["payload"]["kind"] == 2 for r in out)
    q = np.asarray(embed.vector("some new query"), np.float64)
    want = sorted(((float(_f32(embed.vector(t)) @ q / (np.linalg.norm(_f32(embed.vector(t))) * np.linalg.norm(q))), i)
                   for i, t in enumerate(TEXTS) if i % 4 == 2), key=lambda x: (-x[0], x[1]))[:5]
    assert [r["id"] for r in out] == [i for _, i in want]


@stage(6)
def test_text_input_is_validated_as_a_whole(srv, embed):
    _text_coll(srv)
    for pts in ([{"id": 1, "text": "ok"}, {"id": 2, "text": ""}], [{"id": 1, "text": "x" * 8193}],
                [{"id": 1, "text": 5}], [{"id": 1}], [{"id": 1, "text": "a"}, {"id": 1, "text": "b"}],
                [{"id": "x", "text": "a"}], [{"id": 1, "text": "a", "payload": [1]}]):
        expect_error(srv.put("/v1/collections/docs/points/text", {"points": pts}), 400)
    for body in ({"text": ""}, {"text": 7}, {}, {"text": "x" * 8193}, {"text": "ok", "k": 0}):
        expect_error(srv.post("/v1/collections/docs/search_text", body), 400)
    assert srv.get("/v1/collections/docs").json()["points"] == 0
    assert embed.texts_seen() == []
    assert _put_texts(srv, "docs", ["x" * 8192]).status == 200


@stage(6)
def test_plain_collections_refuse_text_and_a_missing_service_is_503(tmp_path, embed):
    with Server(tmp_path / "with", embed=embed) as srv:
        srv.put("/v1/collections/plain", {"dim": 96})
        expect_error(_put_texts(srv, "plain", ["a"]), 400)
        expect_error(srv.post("/v1/collections/plain/search_text", {"text": "a"}), 400)
        expect_error(srv.post("/v1/collections/zz/search_text", {"text": "a"}), 404)
    with Server(tmp_path / "without") as srv:
        _text_coll(srv)
        expect_error(_put_texts(srv, "docs", ["a"]), 503)
        expect_error(srv.post("/v1/collections/docs/search_text", {"text": "a"}), 503)
        srv.put("/v1/collections/v", {"dim": 2})
        assert srv.put("/v1/collections/v/points", {"points": [{"id": 1, "vector": [1, 2]}]}).status == 200
        assert srv.post("/v1/sql", {"sql": "SELECT 1"}).status == 200


@stage(6)
def test_batches_of_at_most_64_and_a_cache(srv, embed):
    _text_coll(srv)
    texts = [f"text {i}" for i in range(150)]
    r = _put_texts(srv, "docs", texts)
    assert r.status == 200, r
    sent = [req for req in embed.requests if req["status"] == 200]
    assert sent and all(len(req["texts"]) <= 64 for req in embed.requests)
    assert sorted(embed.texts_seen()) == sorted(texts)                                 # each text once
    n = len(embed.requests)
    assert _put_texts(srv, "docs", texts[:20], start=500).status == 200
    assert srv.post("/v1/collections/docs/search_text", {"text": texts[3]}).status == 200
    assert len(embed.requests) == n
    assert _put_texts(srv, "docs", ["same", "same", "other"], start=900).status == 200
    assert sorted(embed.texts_seen()[-2:]) == ["other", "same"]


@stage(6)
def test_busy_service_is_retried_honouring_retry_after(tmp_path):
    e = FakeEmbed(flaky=0.4, burst_429=4, seed=3)
    try:
        with Server(tmp_path / "srv", embed=e) as srv:
            _text_coll(srv)
            for i in range(4):
                r = _put_texts(srv, "docs", [f"t{i}-{j}" for j in range(70)], start=100 * i)
                assert r.status == 200, r
            assert srv.get("/v1/collections/docs").json()["points"] == 280
            assert srv.post("/v1/collections/docs/search_text", {"text": "fresh query"}).status == 200
            codes = [req["status"] for req in e.requests]
            assert 429 in codes and 503 in codes
            for a, b in zip(e.requests, e.requests[1:]):
                if a["status"] == 429:
                    assert b["t"] - a["t"] >= 0.9, "Retry-After: 1 was not honoured"
    finally:
        e.close()


@stage(6)
def test_a_service_that_stays_busy_is_502_after_about_30_seconds(tmp_path):
    e = FakeEmbed(flaky=1.0)
    try:
        with Server(tmp_path / "srv", embed=e) as srv:
            _text_coll(srv)
            t0 = time.monotonic()
            r = _put_texts(srv, "docs", ["never embedded"])
            elapsed = time.monotonic() - t0
            expect_error(r, 502)
            assert 20 <= elapsed <= 45, f"{elapsed:.1f} s"
            assert len(e.requests) >= 3
            assert srv.get("/v1/collections/docs").json()["points"] == 0
            e.flaky = 0.0
            assert _put_texts(srv, "docs", ["now it works"]).status == 200
    finally:
        e.close()


@stage(6)
def test_text_endpoints_follow_roles_and_grants(srv):
    _text_coll(srv)
    _put_texts(srv, "docs", TEXTS[:3])
    reader = new_key(srv, "reader", ["docs"])["key"]
    other = new_key(srv, "writer", ["elsewhere"])["key"]
    assert srv.post("/v1/collections/docs/search_text", {"text": TEXTS[0]}, key=reader).status == 200
    expect_error(_put_texts(srv, "docs", ["x"], start=50, key=reader), 403)
    expect_error(_put_texts(srv, "docs", ["x"], start=50, key=other), 404)
    expect_error(srv.post("/v1/collections/docs/search_text", {"text": "x"}, key=other), 404)


@stage(6)
def test_cf_scores_are_the_true_metric_of_the_unnormalised_vectors(srv, embed):
    """The service's vectors are not unit length: dot and l2 scores computed as if they were are wrong."""
    for metric in ("dot", "l2", "cosine"):
        _text_coll(srv, name=f"m-{metric}", metric=metric)
        assert _put_texts(srv, f"m-{metric}", TEXTS[:20]).status == 200
        q = np.asarray(embed.vector("the query"), np.float64)
        res = srv.post(f"/v1/collections/m-{metric}/search_text", {"text": "the query", "k": 20}).json()["results"]
        assert len(res) == 20
        for r in res:
            v = _f32(embed.vector(TEXTS[r["id"]]))
            want = {"dot": float(v @ q), "l2": float(np.linalg.norm(v - q)),
                    "cosine": float(v @ q / (np.linalg.norm(v) * np.linalg.norm(q)))}[metric]
            assert math.isclose(r["score"], want, rel_tol=1e-5, abs_tol=1e-6), (metric, r, want)


@stage(6)
def test_cf_stored_vectors_keep_their_length(srv, embed):
    _text_coll(srv, metric="dot")
    _put_texts(srv, "docs", TEXTS[:8])
    norms = [float(np.linalg.norm(srv.get(f"/v1/collections/docs/points/{i}").json()["vector"])) for i in range(8)]
    want = [float(np.linalg.norm(_f32(embed.vector(t)))) for t in TEXTS[:8]]
    assert np.allclose(norms, want, rtol=1e-6) and not np.allclose(norms, 1.0, atol=0.01), norms
