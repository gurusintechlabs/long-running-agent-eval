"""Stage 9: --read-only opens a data dir without the lock and without writing to it."""
import fcntl
import os

import numpy as np
import pytest

from minidb.collection.store import Catalog
from minidb.datadir import DataDir, DataDirError
from minidb.engine import Engine
from tests.server_util import Proc


def _files(d):
    return {p.relative_to(d).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(d.rglob("*")) if p.is_file()}


def test_a_read_only_engine_reads_and_refuses_writes(tmp_path):
    db = str(tmp_path / "sql.db")
    e = Engine(db)
    e.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    e.execute("INSERT INTO t VALUES (1)")
    os.close(e.store.fd)
    before = _files(tmp_path)
    ro = Engine(db, read_only=True)
    assert ro.execute("SELECT COUNT(*) FROM t")["rows"] == [[1]]
    for sql in ("INSERT INTO t VALUES (2)", "DELETE FROM t", "CREATE TABLE u (x INTEGER)", "DROP TABLE t"):
        with pytest.raises(Exception, match="read-only"):
            ro.execute(sql)
    assert ro.execute("SELECT COUNT(*) FROM t")["rows"] == [[1]] and _files(tmp_path) == before


def test_a_read_only_data_dir_takes_no_lock_and_must_exist(tmp_path):
    with pytest.raises(DataDirError):
        DataDir(tmp_path / "missing", read_only=True).open()
    assert not (tmp_path / "missing").exists()
    w = DataDir(tmp_path / "d").open()
    DataDir(tmp_path / "d", read_only=True).open()     # while the writer holds the lock
    w.close()
    with open(tmp_path / "d" / "LOCK", "rb") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_read_only_collections_replay_without_writing(tmp_path):
    cat = Catalog(tmp_path)
    c = cat.create("c", 4, "l2", {"type": "ivf_flat", "nlist": 4})
    c.upsert(list(range(10)), np.eye(10, 4, dtype=np.float32) + 1, [None] * 10)
    c._wal_fd = None                        # a crash: everything is in the log
    with open(c.path / "wal.log", "ab") as fh:
        fh.write(b'{"seq": 99, "op": "u"')   # and a torn tail
    before = _files(tmp_path)
    ro = Catalog(tmp_path, read_only=True)
    assert ro.get("c").count() == 10 and ro.get("c").get(3)["vector"] == [1.0, 1.0, 1.0, 2.0]
    with pytest.raises(PermissionError):
        ro.get("c").upsert([1], np.ones((1, 4), np.float32), [None])
    ro.close()
    assert _files(tmp_path) == before


def test_the_server_answers_409_to_writes_in_read_only_mode(tmp_path):
    w = Proc(tmp_path / "d").wait_ready()
    assert w.request("PUT", "/v1/collections/c", {"dim": 2})[0] == 201
    w.stop()
    ro = Proc(tmp_path / "d", extra=["--read-only"]).wait_ready()
    try:
        status, body, _ = ro.request("PUT", "/v1/collections/x", {"dim": 2})
        assert status == 409 and body["type"] == "https://minidb.dev/problems/read-only"
        assert ro.request("GET", "/v1/collections/c")[0] == 200
        res = ro.request("POST", "/v1/sql", {"sql": "SELECT 1; CREATE TABLE t (x INTEGER);"})[1]["results"]
        assert res[0]["ok"] and res[1]["error"]["type"] == "IOError"
    finally:
        ro.stop()
