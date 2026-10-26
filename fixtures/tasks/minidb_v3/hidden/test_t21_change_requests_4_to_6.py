"""t21 (stage 11): CR-4 (batch search, recommendations), CR-5 (data-dir format 2, its manifest, the
migration of format-1 dirs, production migrated with its contents exactly preserved) and CR-6 (the
default metric is cosine). Replaces the stage-0 format-1 tests and the stage-1 default-metric test,
retired at 11."""
import hashlib
import json
import shutil
import signal
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

from _support import (Server, ServerExited, base_env, clustered, exact_topk, expect_error, hold_lock, new_key, python,
                      run_cli, server, stage, tree_state, unique, upsert_all, workspace)  # noqa: F401

# The production data (the seed's data/prod, fixtures/tasks/minidb_v3/tools/make_prod.py): row counts and the
# SHA-256 of json.dumps(rows) of "SELECT * FROM <table> ORDER BY id;".
PROD = {"customers": (50, "3cec5af53e5a8a07d91d1c4fbf2c52de66d39360bdb64e61eff0ebb0fe26e779"),
        "orders": (300, "800fce8a47bbc7f85e62842980d114917f2c9f33288acbea6e2ea6558516e06a")}


# ------------------------------------------------------------------ helpers

def _files(d: Path) -> dict[str, dict]:
    """What MANIFEST.json must list: every file under ``d`` but LOCK and the manifest itself."""
    out = {}
    for p in sorted(Path(d).rglob("*")):
        rel = p.relative_to(d).as_posix()
        if p.is_file() and rel not in ("LOCK", "MANIFEST.json"):
            data = p.read_bytes()
            out[rel] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return out


def _assert_format_2(d: Path) -> None:
    assert (d / "FORMAT").read_text().strip() == "minidb-data 2"
    m = json.loads((d / "MANIFEST.json").read_text())
    assert m["format"] == 2, m
    files = {k: {"size": v["size"], "sha256": v["sha256"]} for k, v in m["files"].items()}
    assert files == _files(d), {"manifest": sorted(files), "dir": sorted(_files(d))}


def _without_lock(d: Path) -> dict[str, bytes]:
    return {k: v for k, v in tree_state(d).items() if k != "LOCK"}


def _format_1_dir(d: Path, rows: int = 20) -> Path:
    """A format-1 data dir as the brief of stage 0 defines it: FORMAT plus the engine's database."""
    d.mkdir(parents=True)
    (d / "FORMAT").write_text("minidb-data 1\n")
    values = ",".join(f"({i}, 'row {i}', {i * 0.5})" for i in range(rows))
    p = run_cli(["--db", str(d / "sql.db")], input="CREATE TABLE t (id INTEGER PRIMARY KEY, s TEXT, x REAL);"
                f"INSERT INTO t VALUES {values}; CREATE TABLE u (a TEXT); INSERT INTO u VALUES ('kept');", timeout=300)
    assert p.returncode == 0 and '"ok": false' not in p.stdout, p.stdout[-500:] + p.stderr[-500:]
    return d


def _dump(srv: Server) -> list:
    return srv.sql("SELECT * FROM t ORDER BY id; SELECT a FROM u;")


def _serve_args(d: Path, *extra: str) -> list[str]:
    return ["serve", "--data-dir", str(d), "--port", "1", *extra]


def _coll(srv, name, dim=8, metric="l2", n=400, seed=3, index=None):
    body = {"dim": dim, "metric": metric, **({"index": index} if index else {})}
    assert srv.put(f"/v1/collections/{name}", body).status == 201
    base, queries = clustered(n, dim=dim, queries=12, seed=seed, clusters=8)
    upsert_all(srv, name, base, batch=500, payload=lambda i: {"n": i, "tag": ["a", "b", "c"][i % 3]})
    return base, queries


# ------------------------------------------------------------------ CR-4: batch search

@stage(11)
def test_batch_search_answers_each_search_as_if_sent_alone(server):  # noqa: F811
    name = unique("b")
    base, queries = _coll(server, name)
    searches = [{"vector": queries[0].tolist()},
                {"vector": queries[1].tolist(), "k": 3, "with_payload": True},
                {"vector": queries[2].tolist(), "k": 5, "filter": {"must": [{"key": "tag", "match": {"value": "b"}}]},
                 "with_payload": True},
                {"vector": queries[3].tolist(), "k": 2, "with_vector": True}]
    r = server.post(f"/v1/collections/{name}/search/batch", {"searches": searches})
    assert r.status == 200, r
    got = r.json()["results"]
    assert len(got) == len(searches)
    for s, res in zip(searches, got, strict=True):
        alone = server.post(f"/v1/collections/{name}/search", s)
        assert alone.status == 200 and res == alone.json()["results"], (s.get("k"), res, alone)
    assert [p["id"] for p in got[0]] == [i for i, _ in exact_topk(base, queries[0], 10, "l2")]
    # an indexed collection too
    hn = unique("bh")
    _coll(server, hn, index={"type": "hnsw"})
    one = [{"vector": q.tolist(), "k": 4, "params": {"ef": 64}} for q in queries[:6]]
    r = server.post(f"/v1/collections/{hn}/search/batch", {"searches": one})
    assert r.status == 200 and len(r.json()["results"]) == 6, r
    for s, res in zip(one, r.json()["results"], strict=True):
        assert res == server.post(f"/v1/collections/{hn}/search", s).json()["results"]


@stage(11)
def test_batch_search_is_all_or_nothing_on_invalid_searches(server):  # noqa: F811
    name = unique("b")
    _, queries = _coll(server, name, n=50)
    ok = {"vector": queries[0].tolist(), "k": 3}
    path = f"/v1/collections/{name}/search/batch"
    for body in ({}, {"searches": []}, {"searches": [ok] * 101}, {"searches": ok}, {"searches": [ok, 7]},
                 {"searches": [ok, {"vector": [1.0, 2.0]}]}, {"searches": [ok, {"vector": queries[1].tolist(), "k": 0}]},
                 {"searches": [ok, {"vector": queries[1].tolist(), "filter": {"must": [{"nope": 1}]}}]}):
        expect_error(server.post(path, body), 400)
    assert server.post(path, {"searches": [ok] * 100}).status == 200
    expect_error(server.post(f"/v1/collections/{unique('nope')}/search/batch", {"searches": [ok]}), 404)


# ------------------------------------------------------------------ CR-4: recommendations

def _query(base: np.ndarray, pos: list[int], neg: list[int]) -> np.ndarray:
    p = base[pos].astype(np.float64).mean(axis=0)
    n = base[neg].astype(np.float64).mean(axis=0) if neg else p
    return p + (p - n)


@stage(11)
@pytest.mark.parametrize("metric", ["l2", "cosine", "dot"])
def test_recommend_searches_with_the_examples_query(server, metric):  # noqa: F811
    name = unique("r")
    base, _ = _coll(server, name, metric=metric, n=500, seed=11)
    for pos, neg in (([3], []), ([3, 40, 77], []), ([3, 40], [200]), ([5, 6, 7], [300, 301])):
        r = server.post(f"/v1/collections/{name}/recommend", {"positive": pos, "negative": neg, "k": 8})
        assert r.status == 200, r
        q = _query(base, pos, neg)
        want = [(i, s) for i, s in exact_topk(base, q, 8 + len(pos) + len(neg), metric) if i not in pos + neg][:8]
        got = r.json()["results"]
        assert [p["id"] for p in got] == [i for i, _ in want], (pos, neg)
        assert np.allclose([p["score"] for p in got], [s for _, s in want], rtol=1e-4, atol=1e-4)
    # negative is optional; k defaults to 10; filter and payloads as for a search
    r = server.post(f"/v1/collections/{name}/recommend", {"positive": [1, 2]})
    assert r.status == 200 and len(r.json()["results"]) == 10 and not {1, 2} & {p["id"] for p in r.json()["results"]}
    flt = {"must": [{"key": "tag", "match": {"value": "c"}}]}
    r = server.post(f"/v1/collections/{name}/recommend", {"positive": [2], "k": 5, "filter": flt, "with_payload": True})
    assert r.status == 200 and len(r.json()["results"]) == 5, r
    assert all(p["payload"]["tag"] == "c" for p in r.json()["results"])


@stage(11)
def test_recommend_validates_its_examples(server):  # noqa: F811
    name = unique("r")
    _coll(server, name, metric="cosine", n=60)
    path = f"/v1/collections/{name}/recommend"
    for body in ({}, {"positive": []}, {"positive": 3}, {"positive": [1.5]}, {"positive": [-1]}, {"positive": ["x"]},
                 {"positive": [1], "negative": 2}, {"positive": [1], "k": 0}, {"positive": list(range(101))},
                 {"positive": [1], "negative": list(range(101))}, {"positive": [1], "filter": {"must": [{"nope": 1}]}}):
        expect_error(server.post(path, body), 400)
    expect_error(server.post(path, {"positive": [1, 999_999]}), 404)
    expect_error(server.post(path, {"positive": [1], "negative": ["00000000-0000-0000-0000-000000000001"]}), 404)
    # p + (p - n) = 0 when n = 2p: a zero query in a cosine collection
    v = [0.5, -1.0, 2.0, 0.25, 1.0, -0.5, 3.0, 1.5]
    pts = [{"id": 1001, "vector": v}, {"id": 1002, "vector": [2 * x for x in v]}]
    assert server.put(f"/v1/collections/{name}/points", {"points": pts}).status == 200
    expect_error(server.post(path, {"positive": [1001], "negative": [1002]}), 400)
    expect_error(server.post(f"/v1/collections/{unique('nope')}/recommend", {"positive": [1]}), 404)


@stage(11)
def test_batch_and_recommend_are_reads_for_granted_keys(server):  # noqa: F811
    a, b = unique("ga"), unique("gb")
    _, queries = _coll(server, a, n=40)
    _coll(server, b, n=40)
    reader = new_key(server, "reader", [a])["key"]
    batch = {"searches": [{"vector": queries[0].tolist(), "k": 2}]}
    assert server.post(f"/v1/collections/{a}/search/batch", batch, key=reader).status == 200
    assert server.post(f"/v1/collections/{a}/recommend", {"positive": [1], "k": 2}, key=reader).status == 200
    expect_error(server.post(f"/v1/collections/{b}/search/batch", batch, key=reader), 404)
    expect_error(server.post(f"/v1/collections/{b}/recommend", {"positive": [1]}, key=reader), 404)
    expect_error(server.post(f"/v1/collections/{a}/recommend", {"positive": [1]}, key=None), 401)


# ------------------------------------------------------------------ CR-5: format 2 and the manifest

@stage(11)
def test_a_new_data_dir_is_format_2_with_an_exact_manifest_after_a_clean_stop(tmp_path):
    srv = Server(tmp_path / "s")
    try:
        srv.sql("CREATE TABLE t (a INTEGER); INSERT INTO t VALUES (1), (2);")
        _coll(srv, "m", index={"type": "hnsw"}, n=300)
        new_key(srv, "reader", ["m"])
        assert srv.stop() == 0
    finally:
        srv.close()
    _assert_format_2(srv.data_dir)
    assert "sql.db" in _files(srv.data_dir)
    # and again after the next clean session, which changed things
    with Server(tmp_path / "s", data_dir=srv.data_dir) as again:
        again.sql("INSERT INTO t VALUES (3);")
        assert again.post("/v1/collections/m/points/delete", {"ids": [1, 2]}).status == 200
        assert again.stop() == 0
    _assert_format_2(srv.data_dir)


@stage(11)
def test_an_existing_empty_dir_is_initialised_as_format_2(tmp_path):
    (tmp_path / "empty").mkdir()
    with Server(tmp_path, data_dir=tmp_path / "empty") as s:
        assert s.sql("SELECT 1;") == [{"ok": True, "columns": ["?column?"], "rows": [[1]]}]
        assert s.stop() == 0
    _assert_format_2(tmp_path / "empty")


@stage(11)
def test_unknown_formats_are_still_refused_and_left_unchanged(tmp_path):
    for i, fmt in enumerate(("minidb-data 3\n", "something else\n", "minidb-data 21\n")):
        d = tmp_path / f"dir{i}"
        d.mkdir()
        (d / "FORMAT").write_text(fmt)
        (d / "payload.bin").write_bytes(b"\x00\x01important")
        before = tree_state(d)
        p = run_cli(_serve_args(d), env={"MINIDB_ADMIN_KEY": "k"}, timeout=20)
        assert p.returncode == 2 and p.stderr.strip(), (fmt, p.returncode, p.stderr)
        assert tree_state(d) == before, fmt
        p = run_cli(["migrate", "--data-dir", str(d)], timeout=20)
        assert p.returncode == 2 and tree_state(d) == before, (fmt, p.returncode, p.stderr)


@stage(11)
@pytest.mark.parametrize("damage", ["changed", "missing", "unlisted"])
def test_a_manifest_mismatch_stops_a_writer_and_is_reported_read_only(tmp_path, damage):
    srv = Server(tmp_path / "s")
    try:
        srv.sql("CREATE TABLE t (a INTEGER); INSERT INTO t VALUES (1), (2), (3);")
        assert srv.stop() == 0
    finally:
        srv.close()
    d = srv.data_dir
    if damage == "changed":
        with open(d / "sql.db-wal", "ab") as fh:     # a torn tail: the engine itself would cope with it
            fh.write(b"\x00garbage")
        culprit = "sql.db-wal"
    elif damage == "missing":
        listed = json.loads((d / "MANIFEST.json").read_text())["files"]
        culprit = next(f for f in sorted(listed) if f not in ("FORMAT", "sql.db", "sql.db-wal")) \
            if len(listed) > 3 else "sql.db-wal"
        (d / culprit).unlink()
    else:
        culprit = "stray.bin"
        (d / culprit).write_bytes(b"not mine")
    before = _without_lock(d)
    p = run_cli(_serve_args(d), env={"MINIDB_ADMIN_KEY": "k"}, timeout=30)
    assert p.returncode == 2 and culprit in p.stderr, (damage, p.returncode, p.stderr)
    assert _without_lock(d) == before
    ro = Server(tmp_path / "ro", data_dir=d, read_only=True, start=False)
    try:
        ro.start()
        assert ro.get("/healthz").status == 200
        if damage == "changed":
            assert ro.sql("SELECT COUNT(*) FROM t;")[0]["rows"] == [[3]]
        assert culprit in ro.log(), ro.log()[-2000:]
        assert ro.stop() == 0
    finally:
        ro.close()
    assert _without_lock(d) == before


@stage(11)
def test_a_crashed_writer_is_recovered_not_refused(tmp_path):
    srv = Server(tmp_path / "s")
    try:
        srv.sql("CREATE TABLE t (a INTEGER); INSERT INTO t VALUES (1);")
        _coll(srv, "c", n=200)
        srv.sql("INSERT INTO t VALUES (2);")
        assert srv.restart(crash=True) < 20
        assert srv.sql("SELECT COUNT(*) FROM t;")[0]["rows"] == [[2]]
        assert srv.get("/v1/collections/c").json()["points"] == 200
        assert srv.stop() == 0
    finally:
        srv.close()
    _assert_format_2(srv.data_dir)


# ------------------------------------------------------------------ CR-5: migration

@stage(11)
def test_a_writer_migrates_a_format_1_dir_before_serving(tmp_path):
    d = _format_1_dir(tmp_path / "old")
    with Server(tmp_path / "s", data_dir=d) as srv:
        dump = _dump(srv)
        assert dump[0]["rows"][:2] == [[0, "row 0", 0.0], [1, "row 1", 0.5]] and dump[1]["rows"] == [["kept"]]
        assert (d / "FORMAT").read_text().strip() == "minidb-data 2"
        srv.sql("INSERT INTO u VALUES ('new');")
        assert srv.stop() == 0
    _assert_format_2(d)
    res = run_cli(["--db", str(d / "sql.db")], input="SELECT a FROM u ORDER BY a;")
    assert json.loads(res.stdout.splitlines()[0])["rows"] == [["kept"], ["new"]]


@stage(11)
def test_the_migrate_command(tmp_path):
    d = _format_1_dir(tmp_path / "old")
    ref = _format_1_dir(tmp_path / "ref")
    p = run_cli(["migrate", "--data-dir", str(d)], timeout=120)
    assert p.returncode == 0, p.stderr
    _assert_format_2(d)
    want = run_cli(["--db", str(ref / "sql.db")], input="SELECT * FROM t ORDER BY id; SELECT a FROM u;").stdout
    assert run_cli(["--db", str(d / "sql.db")], input="SELECT * FROM t ORDER BY id; SELECT a FROM u;").stdout == want
    before = _without_lock(d)
    p = run_cli(["migrate", "--data-dir", str(d)], timeout=60)         # already format 2: left as it is
    assert p.returncode == 0 and _without_lock(d) == before, p.stderr
    for bad in (tmp_path / "missing", tmp_path / "empty"):
        if bad.name == "empty":
            bad.mkdir()
        p = run_cli(["migrate", "--data-dir", str(bad)], timeout=60)
        assert p.returncode == 2 and p.stderr.strip(), (bad.name, p.returncode)
    busy = _format_1_dir(tmp_path / "busy")
    with hold_lock(busy):
        before = _without_lock(busy)
        p = run_cli(["migrate", "--data-dir", str(busy)], timeout=60)
        assert p.returncode == 3 and "backup-daemon" in p.stderr, (p.returncode, p.stderr)
        assert _without_lock(busy) == before


@stage(11)
def test_migration_survives_a_crash_at_any_point(tmp_path):
    src = _format_1_dir(tmp_path / "src", rows=20_000)
    want = run_cli(["--db", str(src / "sql.db")], input="SELECT COUNT(*), SUM(id) FROM t; SELECT a FROM u;").stdout
    home = tmp_path / "home"
    home.mkdir()
    for i, delay in enumerate((0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.2)):
        d = tmp_path / f"m{i}"
        shutil.copytree(src, d)
        proc = subprocess.Popen([python(), "-m", "minidb", "migrate", "--data-dir", str(d)], cwd=workspace(),
                                env=base_env(home), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        time.sleep(delay)
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=30)
        fmt = (d / "FORMAT").read_text().strip()
        assert fmt in ("minidb-data 1", "minidb-data 2"), (delay, fmt)
        got = run_cli(["--db", str(d / "sql.db")], input="SELECT COUNT(*), SUM(id) FROM t; SELECT a FROM u;").stdout
        assert got == want, (delay, fmt)
        try:                       # whatever state it is in, a writer opens it and ends with format 2
            with Server(tmp_path / f"s{i}", data_dir=d) as srv:
                assert srv.sql("SELECT COUNT(*) FROM t;")[0]["rows"] == [[20_000]]
                assert srv.stop() == 0
        except ServerExited as e:
            raise AssertionError(f"after a crash {delay}s into the migration ({fmt}): {e}") from None
        _assert_format_2(d)


@stage(11)
def test_read_only_serves_both_formats_and_migrates_nothing(tmp_path):
    old = _format_1_dir(tmp_path / "old")
    srv = Server(tmp_path / "w")
    try:
        srv.sql("CREATE TABLE t (id INTEGER, s TEXT, x REAL); INSERT INTO t VALUES (1, 'a', 0.5); "
                "CREATE TABLE u (a TEXT); INSERT INTO u VALUES ('kept');")
        assert srv.stop() == 0
    finally:
        srv.close()
    for d in (old, srv.data_dir):
        before = tree_state(d)
        with Server(tmp_path / f"ro-{d.name}", data_dir=d, read_only=True) as ro:
            assert ro.sql("SELECT a FROM u;")[0]["rows"] == [["kept"]]
            assert ro.stop() == 0
        assert tree_state(d) == before, d.name


@stage(11)
def test_production_data_is_migrated_with_its_contents_exactly_preserved(tmp_path):
    prod = tmp_path / "prod"
    shutil.copytree(workspace() / "data" / "prod", prod, ignore=shutil.ignore_patterns("LOCK"))
    _assert_format_2(prod)
    with Server(tmp_path / "ro", data_dir=prod, read_only=True) as ro:
        res = ro.sql("SELECT * FROM customers ORDER BY id; SELECT * FROM orders ORDER BY id;")
        for (table, (n, digest)), r in zip(PROD.items(), res, strict=True):
            assert len(r["rows"]) == n, (table, len(r["rows"]))
            assert hashlib.sha256(json.dumps(r["rows"]).encode()).hexdigest() == digest, table
        assert ro.stop() == 0


# ------------------------------------------------------------------ CR-6: the default metric

@stage(11)
def test_the_default_metric_is_now_cosine(tmp_path):
    with Server(tmp_path / "s") as srv:
        a, b = unique("d"), unique("e")
        r = srv.put(f"/v1/collections/{a}", {"dim": 3})
        assert r.status == 201 and r.json()["metric"] == "cosine", r
        assert srv.put(f"/v1/collections/{b}", {"dim": 3, "metric": "l2"}).status == 201
        pts = [{"id": 1, "vector": [1.0, 0.0, 0.0]}, {"id": 2, "vector": [10.0, 1.0, 0.0]},
               {"id": 3, "vector": [0.0, 1.0, 0.0]}]
        for c in (a, b):
            assert srv.put(f"/v1/collections/{c}/points", {"points": pts}).status == 200
        got = srv.post(f"/v1/collections/{a}/search", {"vector": [1.0, 0.0, 0.0], "k": 3}).json()["results"]
        assert [p["id"] for p in got] == [1, 2, 3] and got[0]["score"] == pytest.approx(1.0)
        expect_error(srv.put(f"/v1/collections/{a}/points", {"points": [{"id": 9, "vector": [0.0, 0.0, 0.0]}]}), 400)
        srv.restart()
        assert srv.get(f"/v1/collections/{a}").json()["metric"] == "cosine"
        assert srv.get(f"/v1/collections/{b}").json()["metric"] == "l2"
        got = srv.post(f"/v1/collections/{b}/search", {"vector": [1.0, 0.0, 0.0], "k": 3}).json()["results"]
        assert [p["id"] for p in got] == [1, 3, 2]
