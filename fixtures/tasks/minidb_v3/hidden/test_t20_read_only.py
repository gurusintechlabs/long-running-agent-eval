"""t20 (stage 9): ``serve --read-only`` (the incident brief and ENVIRONMENT.md's lock protocol). A
read-only server opens a data dir without the writer lock, while the backup daemon holds it or not,
changes nothing in it (bytes, names, times), answers reads like a writer, and rejects every write."""
import fcntl
import shutil
import time

import pytest

from _support import (
    FakeEmbed,
    Server,
    clustered,
    hold_lock,
    new_key,
    run_cli,
    stage,
    tree_stat,
    tree_state,
    upsert_all,
    workspace,
)

READ_ONLY = "https://minidb.dev/problems/read-only"
TEXTS = [f"incident note {i}" for i in range(12)]


def _problem_read_only(r):
    assert r.status == 409, r
    assert r.ctype == "application/problem+json", r.headers
    body = r.json()
    assert body["type"] == READ_ONLY and body["status"] == 409, body


def _frozen(d):
    return tree_state(d), tree_stat(d)


def _populate(srv, embed):
    """SQL tables, a flat and an hnsw collection with payloads, a text collection, keys and audit entries."""
    srv.sql("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT); INSERT INTO t VALUES (1, 'a'), (2, 'b'), (3, 'c');")
    base, queries = clustered(1500, dim=16, queries=5, seed=2009, clusters=8)
    for coll, index in (("plain", None), ("graph", {"type": "hnsw", "m": 8, "ef_construction": 64})):
        assert srv.put(f"/v1/collections/{coll}", {"dim": 16, "metric": "l2", **({"index": index} if index else {})}).status == 201
        upsert_all(srv, coll, base, payload=lambda i: {"g": i % 4})
    srv.put("/v1/collections/docs", {"dim": 96, "metric": "cosine", "embedding": "service"})
    r = srv.put("/v1/collections/docs/points/text", {"points": [{"id": i, "text": t} for i, t in enumerate(TEXTS)]})
    assert r.status == 200, r
    reader = new_key(srv, "reader", ["plain"])
    assert srv.post("/v1/collections/plain/snapshots", {"name": "before-incident"}).status == 201
    return queries, reader


def _reads(srv, queries, reader):
    """Everything a client can read; compared between the writer and the read-only server."""
    out = {"sql": srv.sql("SELECT * FROM t ORDER BY id; SELECT COUNT(*) FROM t;"),
           "collections": srv.get("/v1/collections").json(),
           "point": srv.get("/v1/collections/graph/points/42").json(),
           "keys": srv.get("/v1/keys").json(),
           "snapshots": srv.get("/v1/collections/plain/snapshots").json()}
    for coll in ("plain", "graph"):
        out[coll] = [srv.post(f"/v1/collections/{coll}/search", {"vector": q.tolist(), "k": 7, "with_payload": True,
                                                                  "filter": {"must": [{"key": "g", "match": {"value": 1}}]}}
                              ).json() for q in queries]
    out["reader"] = srv.post("/v1/collections/plain/search", {"vector": queries[0].tolist()}, key=reader["key"]).json()
    out["text"] = srv.post("/v1/collections/docs/search_text", {"text": TEXTS[5], "k": 3}).json()
    out["download"] = srv.get("/v1/collections/plain/snapshots/before-incident").body
    return out


@pytest.fixture
def embed():
    e = FakeEmbed()
    yield e
    e.close()


@pytest.fixture
def populated(tmp_path, embed):
    """A data dir written by a writer that was then stopped cleanly, and what it answered."""
    with Server(tmp_path / "writer", embed=embed) as w:
        queries, reader = _populate(w, embed)
        answers = _reads(w, queries, reader)
        assert w.stop() == 0
    return w.data_dir, queries, reader, answers


@stage(9)
def test_read_only_serves_while_the_backup_holds_the_lock(tmp_path, embed, populated):
    d, queries, reader, answers = populated
    with hold_lock(d):
        before = _frozen(d)
        p = run_cli(["serve", "--data-dir", str(d), "--port", "1"], env={"MINIDB_ADMIN_KEY": "k"}, timeout=30)
        assert p.returncode == 3 and "backup-daemon" in p.stderr, (p.returncode, p.stderr[-500:])
        with Server(tmp_path / "ro", data_dir=d, read_only=True, embed=embed) as ro:
            got = _reads(ro, queries, reader)
            assert got == answers
            assert ro.get("/v1/audit").status == 200
            assert ro.stop() == 0
        assert _frozen(d) == before


@stage(9)
def test_read_only_without_a_holder_changes_nothing_even_after_a_crash(tmp_path, embed, populated):
    d, queries, reader, answers = populated
    before = _frozen(d)
    with Server(tmp_path / "ro", data_dir=d, read_only=True, embed=embed) as ro:
        assert _reads(ro, queries, reader) == answers
        with open(d / "LOCK", "rb") as fh:             # a reader never holds the writer lock
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ro.kill()
        ro.spawn()
        ro.wait_ready()
        assert _reads(ro, queries, reader) == answers
    assert _frozen(d) == before
    missing = tmp_path / "never-created"
    p = run_cli(["serve", "--data-dir", str(missing), "--port", "1", "--read-only"], env={"MINIDB_ADMIN_KEY": "k"},
                timeout=30)
    assert p.returncode == 2 and not missing.exists(), (p.returncode, p.stderr[-500:])
    (tmp_path / "empty").mkdir()
    p = run_cli(["serve", "--data-dir", str(tmp_path / "empty"), "--port", "1", "--read-only"],
                env={"MINIDB_ADMIN_KEY": "k"}, timeout=30)
    assert p.returncode == 2 and list((tmp_path / "empty").iterdir()) == [], p.stderr[-500:]


@stage(9)
def test_read_only_rejects_every_write(tmp_path, embed, populated):
    d, queries, reader, answers = populated
    with hold_lock(d):
        before = _frozen(d)
        with Server(tmp_path / "ro", data_dir=d, read_only=True, embed=embed) as ro:
            snap = ro.get("/v1/collections/plain/snapshots/before-incident").body
            key_id = reader["id"]
            writes = [
                ("PUT", "/v1/collections/new", {"dim": 2}), ("DELETE", "/v1/collections/plain", None),
                ("PUT", "/v1/collections/plain/index", {"type": "hnsw"}),
                ("PUT", "/v1/collections/plain/points", {"points": [{"id": 1, "vector": [0.0] * 16}]}),
                ("POST", "/v1/collections/plain/points/delete", {"ids": [1]}),
                ("PUT", "/v1/collections/docs/points/text", {"points": [{"id": 99, "text": "new"}]}),
                ("POST", "/v1/keys", {"name": "x", "role": "reader", "collections": ["plain"]}),
                ("DELETE", f"/v1/keys/{key_id}", None),
                ("POST", "/v1/collections/plain/snapshots", {"name": "during-incident"}),
                ("DELETE", "/v1/collections/plain/snapshots/before-incident", None),
                ("POST", "/v1/collections/plain/import", {"url": "http://127.0.0.1:1/x.ndjson"}),
            ]
            for method, path, body in writes:
                _problem_read_only(ro.request(method, path, body))
            _problem_read_only(ro.request("POST", "/v1/collections/plain/snapshots/restore", data=snap,
                                          headers={"Content-Type": "application/octet-stream"}))
            assert ro.post("/v1/collections/plain/points/delete", {"ids": [1]}, key=reader["key"]).status == 403
            res = ro.sql("SELECT COUNT(*) FROM t; INSERT INTO t VALUES (4, 'd'); UPDATE t SET name = 'z'; "
                         "DELETE FROM t; CREATE TABLE u (x INTEGER); DROP TABLE t; SELECT name FROM t ORDER BY id;")
            assert res[0]["ok"] is True and res[0]["rows"] == [[3]], res[0]
            for r in res[1:6]:
                assert r["ok"] is False and r["error"]["type"] == "IOError" and "read-only" in r["error"]["message"], r
            assert res[6]["ok"] is True and res[6]["rows"] == [["a"], ["b"], ["c"]], res[6]
            res = ro.sql("BEGIN; INSERT INTO t VALUES (5, 'e'); COMMIT; SELECT COUNT(*) FROM t;")
            assert res[1]["ok"] is False and res[1]["error"]["type"] == "IOError" and res[-1]["rows"] == [[3]], res
            assert _reads(ro, queries, reader) == answers
            assert ro.stop() == 0
        assert _frozen(d) == before


@stage(9)
def test_read_only_sees_what_a_crashed_writer_acknowledged(tmp_path, embed):
    w = Server(tmp_path / "writer", embed=embed)
    try:
        w.sql("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);")
        w.put("/v1/collections/c", {"dim": 4, "metric": "l2"})
        for i in range(50):
            w.sql(f"INSERT INTO t VALUES ({i}, 'v{i}');")
            assert w.put("/v1/collections/c/points", {"points": [{"id": i, "vector": [i, 0, 0, 1], "payload": {"i": i}}]}
                         ).status == 200
        w.post("/v1/collections/c/points/delete", {"ids": [0, 1, 2]})
        w.kill()                                       # no checkpoint: everything is still in the logs
    finally:
        w.close()
    d = w.data_dir
    with hold_lock(d):
        before = _frozen(d)
        with Server(tmp_path / "ro", data_dir=d, read_only=True) as ro:
            assert ro.sql("SELECT COUNT(*), MAX(id) FROM t;")[0]["rows"] == [[50, 49]]
            assert ro.get("/v1/collections/c").json()["points"] == 47
            assert ro.get("/v1/collections/c/points/2").status == 404
            assert ro.get("/v1/collections/c/points/49").json()["payload"] == {"i": 49}
            time.sleep(1.5)                            # no background checkpoint or compaction either
            assert ro.stop() == 0
        assert _frozen(d) == before
    with Server(tmp_path / "writer2", data_dir=d) as w2:  # the writer recovers the same data afterwards
        assert w2.get("/v1/collections/c").json()["points"] == 47
        assert w2.sql("SELECT COUNT(*) FROM t;")[0]["rows"] == [[50]]


@stage(9)
def test_read_only_serves_production_data_during_the_backup(tmp_path):
    prod = tmp_path / "prod"
    shutil.copytree(workspace() / "data" / "prod", prod, ignore=shutil.ignore_patterns("LOCK"))
    with hold_lock(prod):
        before = _frozen(prod)
        with Server(tmp_path / "ro", data_dir=prod, read_only=True) as ro:
            res = ro.sql("SELECT COUNT(*) FROM customers; SELECT COUNT(*) FROM orders; INSERT INTO customers (id) VALUES (999);")
            assert res[0]["rows"] == [[50]] and res[1]["rows"] == [[300]], res
            assert res[2]["ok"] is False and res[2]["error"]["type"] == "IOError", res[2]
            assert ro.get("/v1/collections").json() == {"collections": []}
            assert ro.stop() == 0
        assert _frozen(prod) == before
