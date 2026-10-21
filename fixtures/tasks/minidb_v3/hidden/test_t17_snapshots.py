"""t17 (stage 7): collection snapshots (brief 7.1): create, list, download, delete, and restore on the
same or another server, atomically, with roles and the audit log. The archive format is the agent's
own; the tests only require a tar archive that round-trips."""
import io
import json
import re
import tarfile

import numpy as np
import pytest

from _support import (FakeEmbed, Server, clustered, exact_topk, expect_error, new_key, recall_at, stage, unique,
                      upsert_all)

NAME_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,127}")
OCTET = {"Content-Type": "application/octet-stream"}


def _snap(srv, coll, name=None, **kw):
    return srv.post(f"/v1/collections/{coll}/snapshots", {"name": name} if name else {}, **kw)


def _download(srv, coll, name, **kw):
    return srv.get(f"/v1/collections/{coll}/snapshots/{name}", **kw)


def _restore(srv, coll, data, **kw):
    return srv.request("POST", f"/v1/collections/{coll}/snapshots/restore", data=data, headers=OCTET, timeout=300,
                       **kw)


def _fill(srv, name, n=300, dim=8, index=None, metric="l2", seed=7):
    body = {"dim": dim, "metric": metric, **({"index": index} if index else {})}
    assert srv.put(f"/v1/collections/{name}", body).status == 201
    base, queries = clustered(n, dim=dim, queries=10, seed=seed, clusters=8)
    upsert_all(srv, name, base, batch=500, payload=lambda i: {"n": i, "tag": ["a", "b", "c"][i % 3]})
    return base, queries


def _results(srv, coll, queries, **extra):
    out = []
    for q in queries:
        r = srv.post(f"/v1/collections/{coll}/search", {"vector": q.tolist(), "k": 10, "with_payload": True, **extra})
        assert r.status == 200, r
        out.append(r.json()["results"])
    return out


def _info(srv, coll):
    r = srv.get(f"/v1/collections/{coll}")
    assert r.status == 200, r
    return {k: v for k, v in r.json().items() if k != "name"}


@pytest.fixture
def srv(tmp_path):
    s = Server(tmp_path / "srv")
    try:
        yield s
    finally:
        s.close()


@stage(7)
def test_create_list_download_and_delete_snapshots(srv):
    _fill(srv, "c")
    r = _snap(srv, "c", "first")
    assert r.status == 201 and r.json()["name"] == "first", r
    size = r.json()["size"]
    r = _snap(srv, "c")
    assert r.status == 201 and NAME_RE.fullmatch(r.json()["name"]), r
    auto = r.json()["name"]
    expect_error(_snap(srv, "c", "first"), 409)
    for bad in ("../x", "Upper", ".hidden", "-dash", "a" * 129, "a/b", "a b"):
        expect_error(_snap(srv, "c", bad), 400)
    expect_error(_snap(srv, "nope", "x"), 404)
    listed = srv.get("/v1/collections/c/snapshots").json()["snapshots"]
    assert [s["name"] for s in listed] == ["first", auto]
    assert all(set(s) >= {"name", "size", "created"} for s in listed) and listed[0]["size"] == size
    d = _download(srv, "c", "first")
    assert d.status == 200 and d.ctype == "application/octet-stream", d
    assert d.headers.get("content-disposition") == 'attachment; filename="first"', d.headers
    assert len(d.body) == size
    with tarfile.open(fileobj=io.BytesIO(d.body)) as tf:
        assert tf.getmembers()
    expect_error(_download(srv, "c", "missing"), 404)
    r = srv.delete("/v1/collections/c/snapshots/first")
    assert r.status == 200 and r.json() == {"deleted": True}, r
    expect_error(_download(srv, "c", "first"), 404)
    expect_error(srv.delete("/v1/collections/c/snapshots/first"), 404)
    srv.restart()
    assert [s["name"] for s in srv.get("/v1/collections/c/snapshots").json()["snapshots"]] == [auto]
    assert srv.delete("/v1/collections/c").status == 200
    _fill(srv, "c", n=10)
    assert srv.get("/v1/collections/c/snapshots").json()["snapshots"] == []


@stage(7)
def test_a_snapshot_restores_on_another_server(tmp_path):
    with Server(tmp_path / "a") as a, Server(tmp_path / "b") as b:
        _, qf = _fill(a, "plain", n=600, dim=16, metric="cosine")
        bh, qh = _fill(a, "graph", n=3000, dim=16, index={"type": "hnsw", "m": 8, "ef_construction": 64}, seed=9)
        a.post("/v1/collections/plain/points/delete", {"ids": [3, 4, 5]})
        a.put("/v1/collections/plain/points", {"points": [{"id": "6f1c1a2e-1b4f-4c55-9a43-0d9f6f1d2b3c",
                                                            "vector": [0.5] * 16, "payload": {"uuid": True}}]})
        archives = {}
        for coll in ("plain", "graph"):
            name = _snap(a, coll).json()["name"]
            archives[coll] = _download(a, coll, name).body
        r = _restore(b, "copy", archives["plain"])
        assert r.status == 200, r
        assert r.json()["name"] == "copy" and _info(b, "copy") == _info(a, "plain")
        assert _results(b, "copy", qf) == _results(a, "plain", qf)
        for pid in (0, 7, "6f1c1a2e-1b4f-4c55-9a43-0d9f6f1d2b3c"):
            assert b.get(f"/v1/collections/copy/points/{pid}").json() == a.get(f"/v1/collections/plain/points/{pid}").json()
        expect_error(b.get("/v1/collections/copy/points/4"), 404)
        assert _restore(b, "graph", archives["graph"]).status == 200
        assert _info(b, "graph") == _info(a, "graph")
        truth = [[i for i, _ in exact_topk(bh, q, 10)] for q in qh]      # an approximate index: same quality
        recall = {s: recall_at([[r["id"] for r in res] for res in _results(srv, "graph", qh)], truth)
                  for s, srv in (("original", a), ("restored", b))}
        assert recall["restored"] >= recall["original"] - 0.05, recall
        b.restart(crash=True)
        assert _info(b, "copy") == _info(a, "plain") and _results(b, "copy", qf[:3]) == _results(a, "plain", qf[:3])


@stage(7)
def test_restore_replaces_the_collection(srv):
    _, q = _fill(srv, "c", n=200)
    snap = _download(srv, "c", _snap(srv, "c").json()["name"]).body
    before = _results(srv, "c", q)
    srv.put("/v1/collections/c/points", {"points": [{"id": 5000 + i, "vector": [9.0] * 8} for i in range(50)]})
    srv.post("/v1/collections/c/points/delete", {"ids": list(range(0, 100))})
    srv.put("/v1/collections/c/index", {"type": "hnsw"})
    r = _restore(srv, "c", snap)
    assert r.status == 200 and r.json()["points"] == 200 and r.json()["index"] == {"type": "flat"}, r
    expect_error(srv.get("/v1/collections/c/points/5003"), 404)
    assert srv.get("/v1/collections/c/points/50").status == 200
    assert _results(srv, "c", q) == before
    srv.restart()
    assert _results(srv, "c", q) == before


@stage(7)
def test_a_bad_archive_changes_nothing(srv):
    _, q = _fill(srv, "c", n=200)
    good = _download(srv, "c", _snap(srv, "c").json()["name"]).body
    before, info = _results(srv, "c", q), _info(srv, "c")

    def tar(members):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            for name, data in members:
                ti = tarfile.TarInfo(name)
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
        return buf.getvalue()
    with tarfile.open(fileobj=io.BytesIO(good)) as tf:
        names = [m.name for m in tf.getmembers() if m.isfile()]
        garbled = tar([(n, b"\x00garbage" * 50) for n in names])
    for bad in (b"", b"not a tar archive at all", good[: len(good) // 2], tar([]), garbled,
                tar([("README", b"hello")]), json.dumps({"points": []}).encode()):
        expect_error(_restore(srv, "c", bad), 400)
        assert _info(srv, "c") == info and _results(srv, "c", q[:3]) == before[:3]
        expect_error(_restore(srv, "fresh", bad), 400)
        expect_error(srv.get("/v1/collections/fresh"), 404)
    assert [c["name"] for c in srv.get("/v1/collections").json()["collections"]] == ["c"]
    srv.restart()
    assert _results(srv, "c", q) == before


@stage(7)
def test_restore_bodies_up_to_256_mib(srv):
    base, q = _fill(srv, "big", n=6000, dim=96)          # an archive larger than the 1 MiB JSON limit
    snap = _download(srv, "big", _snap(srv, "big").json()["name"]).body
    assert len(snap) > (1 << 20)
    assert _restore(srv, "big2", snap).status == 200
    assert _info(srv, "big2") == _info(srv, "big")
    r = srv.declared_body("POST", "/v1/collections/big2/snapshots/restore", (256 << 20) + 1)
    assert r.status == 413, r
    assert _results(srv, "big2", q[:2]) == _results(srv, "big", q[:2])


@stage(7)
def test_snapshot_roles_grants_and_audit(srv):
    _fill(srv, "c", n=20)
    _fill(srv, "other", n=5)
    writer = new_key(srv, "writer", ["c"])["key"]
    reader = new_key(srv, "reader", ["c", "other"])["key"]
    stranger = new_key(srv, "admin", ["other"])["key"]
    r = _snap(srv, "c", "w1", key=writer)
    assert r.status == 201, r
    assert srv.get("/v1/collections/c/snapshots", key=writer).status == 200
    data = _download(srv, "c", "w1", key=writer)
    assert data.status == 200
    expect_error(_restore(srv, "c", data.body, key=writer), 403)
    expect_error(srv.delete("/v1/collections/c/snapshots/w1", key=writer), 403)
    expect_error(_snap(srv, "c", "r1", key=reader), 403)
    expect_error(srv.get("/v1/collections/c/snapshots", key=reader), 403)
    expect_error(_download(srv, "c", "w1", key=reader), 403)
    for r in (_snap(srv, "c", "s1", key=stranger), srv.get("/v1/collections/c/snapshots", key=stranger),
              _download(srv, "c", "w1", key=stranger), _restore(srv, "c", data.body, key=stranger)):
        expect_error(r, 404)
    assert _restore(srv, "c", data.body).status == 200
    entries = srv.get("/v1/audit").json()["entries"]
    assert entries[0]["action"] == "snapshot.restore" and entries[0]["target"] == "c" and entries[0]["actor"] == "admin"
    assert sum(e["action"] == "snapshot.restore" for e in entries) == 1


@stage(7)
def test_text_collections_keep_their_texts_through_a_snapshot(tmp_path):
    embed = FakeEmbed()
    try:
        with Server(tmp_path / "a", embed=embed) as a, Server(tmp_path / "b", embed=embed) as b:
            assert a.put("/v1/collections/docs", {"dim": 96, "metric": "cosine", "embedding": "service"}).status == 201
            texts = [f"note {i} on {unique('topic')}" for i in range(30)]
            r = a.put("/v1/collections/docs/points/text", {"points": [{"id": i, "text": t} for i, t in enumerate(texts)]})
            assert r.status == 200, r
            arch = _download(a, "docs", _snap(a, "docs").json()["name"]).body
            assert _restore(b, "docs", arch).status == 200
            assert _info(b, "docs") == _info(a, "docs") and _info(b, "docs")["embedding"] == "service"
            assert b.get("/v1/collections/docs/points/4").json()["text"] == texts[4]
            n = len(embed.requests)
            out = b.post("/v1/collections/docs/search_text", {"text": texts[11], "k": 1}).json()["results"]
            assert out[0]["id"] == 11 and len(embed.requests) == n + 1
            v = np.asarray(b.get("/v1/collections/docs/points/11").json()["vector"])
            assert np.allclose(v, np.asarray(embed.vector(texts[11]), np.float32), atol=1e-6)
    finally:
        embed.close()
