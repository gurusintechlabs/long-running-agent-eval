import json

import pytest
from minidb import storage
from minidb.engine import Engine, run_sql
from minidb.protocol import SQLIOError


def test_index_lookup_ranges():
    ix = storage.Index("i", "t", "a", False, 1)
    for rid, key in enumerate([5, 1, 3, 5, None, 9], start=1):
        ix.add(key, rid)
    assert ix.lookup(5, True, 5, True) == [1, 4]
    assert ix.lookup(None, True, 5, False) == [2, 3]
    assert ix.lookup(3, False, None, True) == [1, 4, 6]
    ix.remove(5, 1)
    assert ix.lookup(5, True, 5, True) == [4]


def test_save_and_load_roundtrip(tmp_path):
    e = Engine()
    run_sql(e, "CREATE TABLE t (a INTEGER PRIMARY KEY, b REAL DEFAULT 1); INSERT INTO t (a) VALUES (2), (1);"
               "CREATE INDEX ia ON t (a); CREATE VIEW v AS SELECT a FROM t WHERE b > 0;")
    path = tmp_path / "db.minidb"
    storage.save(e.db, str(path))
    assert json.loads(path.read_text())["format"] == "minidb"
    db = storage.load(str(path), lambda sql: e.db.views["v"].query)
    assert list(db.tables["t"].rows.values()) == [[2, 1.0], [1, 1.0]]
    assert db.indexes["ia"].lookup(1, True, 1, True) == [2]


def test_load_rejects_foreign_files(tmp_path):
    for text in ("", "[1, 2]", '{"format": "other"}', "nonsense"):
        p = tmp_path / "x"
        p.write_text(text)
        with pytest.raises(SQLIOError):
            storage.load(str(p), lambda sql: None)
    with pytest.raises(SQLIOError):
        storage.save(storage.Database(), str(tmp_path / "missing" / "x"))
