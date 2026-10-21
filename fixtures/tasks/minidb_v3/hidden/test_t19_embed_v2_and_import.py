"""t19 (stage 8): the silent environment change (embedding API v1 retired, v2 live; ENVIRONMENT.md) and
bulk import from allow-listed URLs (brief 8.1, 8.2)."""
import json
import time

import numpy as np
import pytest

from _support import (
    FakeEmbed,
    Server,
    Source,
    clustered,
    exact_topk,
    expect_error,
    new_key,
    ndjson,
    stage,
)


def _points(n, dim=8, start=0, seed=19):
    base, _ = clustered(n, dim=dim, queries=1, seed=seed, clusters=8)
    return [{"id": start + i, "vector": base[i].tolist(), "payload": {"n": start + i}} for i in range(n)], base


@pytest.fixture
def src():
    s = Source()
    yield s
    s.close()


@pytest.fixture
def srv(tmp_path, src):
    s = Server(tmp_path / "srv", env={"MINIDB_IMPORT_ALLOW": f"{src.hostport},127.0.0.1:1"})
    try:
        assert s.put("/v1/collections/c", {"dim": 8, "metric": "l2"}).status == 201
        yield s
    finally:
        s.close()


def _import(srv, url, coll="c", **kw):
    return srv.post(f"/v1/collections/{coll}/import", {"url": url}, timeout=180, **kw)


def _count(srv, coll="c"):
    return srv.get(f"/v1/collections/{coll}").json()["points"]


# ---------------------------------------------------------------- embeddings v2

@stage(8)
def test_text_search_works_against_embedding_api_v2(tmp_path):
    embed = FakeEmbed(api="v2")
    try:
        with Server(tmp_path / "srv", embed=embed) as srv:
            assert srv.put("/v1/collections/docs", {"dim": 96, "metric": "dot", "embedding": "service"}).status == 201
            texts = [f"release note {i}" for i in range(100)]
            r = srv.put("/v1/collections/docs/points/text", {"points": [{"id": i, "text": t} for i, t in enumerate(texts)]},
                        timeout=120)
            assert r.status == 200 and r.json() == {"upserted": 100}, r
            for i in (0, 1, 63, 64, 99):            # the service answers in reverse order: vectors follow "index"
                v = srv.get(f"/v1/collections/docs/points/{i}").json()["vector"]
                assert np.allclose(v, np.asarray(embed.vector(texts[i]), np.float32), atol=1e-6), i
            out = srv.post("/v1/collections/docs/search_text", {"text": "a fresh query", "k": 3}).json()["results"]
            q = np.asarray(embed.vector("a fresh query"), np.float64)
            vecs = np.asarray([embed.vector(t) for t in texts], np.float32).astype(np.float64)
            assert [x["id"] for x in out] == [int(i) for i in np.argsort(-(vecs @ q), kind="stable")[:3]]
            paths = {req["path"] for req in embed.requests}
            assert paths == {"/v2/embeddings"}, paths          # the retired v1 endpoint is never called
            assert all(len(req["texts"]) <= 64 for req in embed.requests)
            assert all(req["status"] == 200 for req in embed.requests)
    finally:
        embed.close()


@stage(8)
def test_v2_busy_answers_are_retried(tmp_path):
    embed = FakeEmbed(api="v2", flaky=0.3, burst_429=5, seed=8)
    try:
        with Server(tmp_path / "srv", embed=embed) as srv:
            srv.put("/v1/collections/docs", {"dim": 96, "embedding": "service"})
            for i in range(3):
                r = srv.put("/v1/collections/docs/points/text",
                            {"points": [{"id": 100 * i + j, "text": f"t{i}-{j}"} for j in range(70)]}, timeout=120)
                assert r.status == 200, r
            assert srv.get("/v1/collections/docs").json()["points"] == 210
            codes = {req["status"] for req in embed.requests}
            assert {200, 503, 429} <= codes and {req["path"] for req in embed.requests} == {"/v2/embeddings"}
    finally:
        embed.close()


# ---------------------------------------------------------------- import

@stage(8)
def test_import_ndjson_from_an_allowed_source(srv, src):
    pts, base = _points(2500)
    pts[10]["id"] = "0b6b9a0e-58a3-4d4b-a1a4-6b1c0f6f4f1e"
    src.routes["/data.ndjson"] = ndjson(pts[:1200]) + b"\n\n" + ndjson(pts[1200:]) + b"\n"
    r = _import(srv, src.url())
    assert r.status == 200 and r.json() == {"imported": 2500}, r
    assert _count(srv) == 2500
    got = srv.get("/v1/collections/c/points/0b6b9a0e-58a3-4d4b-a1a4-6b1c0f6f4f1e").json()
    assert got["payload"] == {"n": 10} and np.allclose(got["vector"], base[10])
    q = base[77]
    res = srv.post("/v1/collections/c/search", {"vector": q.tolist(), "k": 5}).json()["results"]
    ids = [p["id"] for p in pts]
    assert [x["id"] for x in res] == [i for i, _ in exact_topk(base, q, 5, ids=ids)]
    src.routes["/more.ndjson"] = ndjson([{"id": 0, "vector": [0.0] * 8, "payload": {"n": "replaced"}}])
    assert _import(srv, src.url("/more.ndjson")).json() == {"imported": 1}
    assert srv.get("/v1/collections/c/points/0").json()["payload"] == {"n": "replaced"} and _count(srv) == 2500
    srv.restart(crash=True)
    assert _count(srv) == 2500


@stage(8)
def test_import_is_all_or_nothing(srv, src):
    pts, _ = _points(300)
    good = ndjson(pts)
    lines = good.splitlines()
    bad_files = {
        "/bad-json": b"\n".join(lines[:150] + [b'{"id": 999, "vector": [1, 2'] + lines[150:]),
        "/bad-dim": b"\n".join(lines[:200] + [json.dumps({"id": 998, "vector": [1.0] * 7}).encode()]),
        "/bad-id": b"\n".join(lines[:5] + [json.dumps({"id": -1, "vector": [1.0] * 8}).encode()]),
        "/duplicate": b"\n".join(lines + [lines[3]]),
        "/not-an-object": b"\n".join(lines[:3] + [b"[1, 2, 3]"]),
        "/nan": b"\n".join(lines[:3] + [b'{"id": 5000, "vector": [NaN, 0, 0, 0, 0, 0, 0, 0]}']),
    }
    src.routes.update(bad_files)
    for path in bad_files:
        expect_error(_import(srv, src.url(path)), 400)
    src.routes["/gone"] = (404, {}, b"no such file")
    src.routes["/boom"] = (500, {}, good)

    def truncated(h):
        h.send_response(200)
        h.send_header("Content-Length", str(len(good)))
        h.end_headers()
        h.wfile.write(good[: len(good) // 2])
        h.wfile.flush()
        h.close_connection = True
    src.routes["/truncated"] = truncated
    for path in ("/gone", "/boom", "/truncated"):
        expect_error(_import(srv, src.url(path)), 502)
    expect_error(_import(srv, "http://127.0.0.1:1/data.ndjson"), 502)    # allowed, but nothing listens
    assert _count(srv) == 0
    src.routes["/good"] = good
    assert _import(srv, src.url("/good")).json() == {"imported": 300}


@stage(8)
def test_import_limits_and_request_validation(srv, src):
    assert srv.put("/v1/collections/tiny", {"dim": 2, "metric": "l2"}).status == 201
    many = b"".join(b'{"id": %d, "vector": [1, 0]}\n' % i for i in range(100_001))
    src.routes["/many"] = many
    expect_error(_import(srv, src.url("/many"), coll="tiny"), 400)
    src.routes["/limit"] = b"".join(many.splitlines(keepends=True)[:100_000])
    assert _import(srv, src.url("/limit"), coll="tiny").json() == {"imported": 100_000}
    assert srv.delete("/v1/collections/tiny").status == 200
    assert srv.put("/v1/collections/tiny", {"dim": 2, "metric": "l2"}).status == 201
    src.routes["/huge"] = b'{"id": 1, "vector": [1, 0]}\n' + b" " * (64 << 20) + b"\n"
    expect_error(_import(srv, src.url("/huge"), coll="tiny"), 400)
    assert _count(srv, "tiny") == 0
    for body in ({}, {"url": 5}, {"url": None}, {"uri": src.url()}):
        expect_error(srv.post("/v1/collections/c/import", body), 400)
    expect_error(_import(srv, src.url(), coll="missing"), 404)


@stage(8)
def test_only_allow_listed_sources_are_fetched(tmp_path, src):
    pts, _ = _points(10)
    src.routes["/data.ndjson"] = ndjson(pts)
    for n, allow in enumerate((None, "", "127.0.0.1:1")):
        env = {"MINIDB_IMPORT_ALLOW": allow} if allow is not None else {}
        with Server(tmp_path / f"srv{n}", env=env) as srv:
            srv.put("/v1/collections/c", {"dim": 8, "metric": "l2"})
            expect_error(_import(srv, src.url()), 403)
            assert _count(srv) == 0
    with Server(tmp_path / "ok", env={"MINIDB_IMPORT_ALLOW": f"127.0.0.1:1,{src.hostport}"}) as srv:
        srv.put("/v1/collections/c", {"dim": 8, "metric": "l2"})
        for url in (f"https://{src.hostport}/data.ndjson", f"ftp://{src.hostport}/data.ndjson",
                    "file:///etc/passwd", f"http://127.0.0.1:{src.port + 1}/data.ndjson"):
            r = _import(srv, url)
            assert r.status in (400, 403), (url, r)
        assert src.connections == 0
        assert _import(srv, src.url()).json() == {"imported": 10}
        assert src.connections >= 1


@stage(8)
def test_import_follows_roles_and_grants(srv, src):
    pts, _ = _points(5)
    src.routes["/data.ndjson"] = ndjson(pts)
    srv.put("/v1/collections/other", {"dim": 8, "metric": "l2"})
    writer = new_key(srv, "writer", ["c"])["key"]
    reader = new_key(srv, "reader", ["c"])["key"]
    elsewhere = new_key(srv, "writer", ["other"])["key"]
    expect_error(_import(srv, src.url(), key=reader), 403)
    expect_error(_import(srv, src.url(), key=elsewhere), 404)
    assert src.connections == 0
    assert _import(srv, src.url(), key=writer).json() == {"imported": 5}


@stage(8)
def test_a_stalled_source_times_out_within_about_60_s_timing(srv, src):
    def stall(h):
        h.send_response(200)
        h.send_header("Content-Length", "1000000")
        h.end_headers()
        h.wfile.write(b'{"id": 1, "vector": [1, 2, 3, 4, 5, 6, 7, 8]}\n')
        h.wfile.flush()
        time.sleep(100)
    src.routes["/stall"] = stall
    t0 = time.monotonic()
    r = _import(srv, src.url("/stall"))
    elapsed = time.monotonic() - t0
    expect_error(r, 502)
    assert 50 <= elapsed <= 90, f"{elapsed:.1f} s"
    assert _count(srv) == 0
