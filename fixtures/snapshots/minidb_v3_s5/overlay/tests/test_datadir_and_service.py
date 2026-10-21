"""Data dirs, the writer lock, and the service behind the HTTP API."""
import fcntl
import os
import threading

import pytest

from minidb.datadir import FORMAT_LINE, DataDir, DataDirError, LockBusy, check_format
from minidb.locks import RWLock
from minidb.service import Service


def test_a_missing_dir_is_initialised(tmp_path):
    d = DataDir(tmp_path / "new").open()
    try:
        assert (tmp_path / "new" / "FORMAT").read_text() == FORMAT_LINE + "\n"
        assert check_format(tmp_path / "new")
    finally:
        d.close()


def test_other_formats_are_refused_untouched(tmp_path):
    (tmp_path / "FORMAT").write_text("minidb-data 2\n")
    with pytest.raises(DataDirError):
        DataDir(tmp_path).open()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["FORMAT"]
    other = tmp_path / "other"
    other.mkdir()
    (other / "x").write_text("x")
    with pytest.raises(DataDirError):
        DataDir(other).open()
    assert sorted(p.name for p in other.iterdir()) == ["x"]


def test_busy_lock_names_the_holder(tmp_path):
    first = DataDir(tmp_path).open()
    try:
        with pytest.raises(LockBusy) as e:
            DataDir(tmp_path).open()
        assert f"pid {os.getpid()}" in e.value.holder
    finally:
        first.close()
    DataDir(tmp_path).open().close()       # free again


def test_lock_is_a_flock_on_LOCK(tmp_path):
    d = DataDir(tmp_path).open()
    fd = os.open(tmp_path / "LOCK", os.O_RDWR)
    try:
        with pytest.raises(BlockingIOError):
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(fd)
        d.close()


def test_service_runs_sql_durably(tmp_path):
    d = DataDir(tmp_path).open()
    s = Service(d, "k")
    assert s.run_sql("CREATE TABLE t (a INTEGER); INSERT INTO t VALUES (1);")[1] == {"ok": True, "rowcount": 1}
    s.close()
    s2 = Service(d, "k")
    assert s2.run_sql("SELECT a FROM t;") == [{"ok": True, "columns": ["a"], "rows": [[1]]}]
    s2.close()
    d.close()


def test_rwlock_excludes_writers_from_readers():
    lock, events = RWLock(), []

    def writer():
        with lock.write():
            events.append("w")
    with lock.read():
        th = threading.Thread(target=writer)
        th.start()
        th.join(0.2)
        assert events == []          # the writer waits for the reader
    th.join(2)
    assert events == ["w"]
