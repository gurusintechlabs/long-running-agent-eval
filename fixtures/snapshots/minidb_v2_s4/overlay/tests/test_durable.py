import json
import os

import pytest

from minidb import durable
from minidb.engine import Engine, run_sql
from minidb.protocol import SQLIOError


def test_log_replays_committed_units_and_skips_a_torn_tail(tmp_path):
    path = str(tmp_path / "db")
    e = Engine(path)
    run_sql(e, """
        CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);
        INSERT INTO t VALUES (1, 'a'), (2, 'b');
        BEGIN; DELETE FROM t WHERE id = 1; COMMIT;
        BEGIN; INSERT INTO t VALUES (3, 'lost');
    """)
    with open(path + "-wal", "ab") as fh:
        fh.write(b'{"seq": 99, "ops": [["i", "t", 50, [50')  # a write cut short by a crash
    e2 = Engine(path)
    assert run_sql(e2, "SELECT * FROM t")[0]["rows"] == [[2, "b"]]
    assert not open(path + "-wal", "rb").read().endswith(b"[50")


def test_checkpoint_writes_an_atomic_snapshot(tmp_path):
    path = str(tmp_path / "db")
    e = Engine(path)
    run_sql(e, "CREATE TABLE t (a INTEGER); CREATE INDEX ta ON t (a); INSERT INTO t VALUES (1), (2)")
    e.store.checkpoint(e.db)
    snap = json.load(open(path))
    assert snap["format"] == durable.FORMAT and os.path.getsize(path + "-wal") == 0
    db, seq = durable.from_snapshot(snap)
    durable.build_indexes(db)
    assert list(db.tables["t"].rows.values()) == [[1], [2]] and db.indexes["ta"].eq(2) == [2]


def test_a_foreign_file_puts_the_engine_into_io_error_mode(tmp_path):
    junk = tmp_path / "junk"
    junk.write_text("hello")
    e = Engine(str(junk))
    with pytest.raises(SQLIOError):
        e.execute("SELECT 1")
    assert junk.read_text() == "hello"
