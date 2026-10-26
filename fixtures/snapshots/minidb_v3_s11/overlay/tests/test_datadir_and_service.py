"""Data dirs, the writer lock, and the service behind the HTTP API."""
import fcntl
import json
import os
import threading

import pytest

from minidb.datadir import FORMAT_LINE, DataDir, DataDirError, LockBusy, check_format, listing
from minidb.locks import RWLock
from minidb.service import Service


def test_a_missing_dir_is_initialised(tmp_path):
    d = DataDir(tmp_path / "new").open()
    try:
        assert (tmp_path / "new" / "FORMAT").read_text() == FORMAT_LINE + "\n"
        assert check_format(tmp_path / "new") == 2
    finally:
        d.close()


def test_other_formats_are_refused_untouched(tmp_path):
    (tmp_path / "FORMAT").write_text("minidb-data 3\n")
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


def _format_1(path):
    path.mkdir()
    (path / "FORMAT").write_text("minidb-data 1\n")
    (path / "sql.db").write_bytes(b"db")
    (path / "collections").mkdir()
    (path / "collections" / "x.bin").write_bytes(b"\x00" * 10)
    return path


def _manifest(path):
    return json.loads((path / "MANIFEST.json").read_text())


def test_a_clean_close_seals_an_exact_manifest(tmp_path):
    d = DataDir(tmp_path / "d").open()
    assert _manifest(tmp_path / "d")["state"] == "open"
    (tmp_path / "d" / "data.bin").write_bytes(b"abc")
    d.seal()
    d.close()
    m = _manifest(tmp_path / "d")
    assert m["state"] == "closed" and m["files"] == listing(tmp_path / "d")
    assert set(m["files"]) == {"FORMAT", "data.bin"}


def test_a_mismatch_refuses_a_writer_untouched_and_is_reported_read_only(tmp_path, capsys):
    d = DataDir(tmp_path).open()
    (tmp_path / "data.bin").write_bytes(b"abc")
    d.seal()
    d.close()
    (tmp_path / "data.bin").write_bytes(b"abd")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.name != "LOCK"}
    with pytest.raises(DataDirError, match="data.bin"):
        DataDir(tmp_path).open()
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.name != "LOCK"} == before
    DataDir(tmp_path, read_only=True).open()
    assert "data.bin" in capsys.readouterr().err


def test_an_unclean_close_is_not_a_mismatch(tmp_path):
    d = DataDir(tmp_path).open()
    (tmp_path / "data.bin").write_bytes(b"abc")
    d.close()                                  # no seal: as after a crash
    DataDir(tmp_path).open().close()


def test_a_writer_migrates_format_1_and_keeps_every_file(tmp_path):
    src = _format_1(tmp_path / "d")
    before = listing(src)
    d = DataDir(src).open()
    d.seal()
    d.close()
    after = listing(src)
    assert (src / "FORMAT").read_text() == "minidb-data 2\n"
    assert {k: v for k, v in after.items() if k != "FORMAT"} == {k: v for k, v in before.items() if k != "FORMAT"}


def test_migrate_only_and_its_errors(tmp_path):
    src = _format_1(tmp_path / "d")
    assert DataDir(src).migrate() is True
    m = _manifest(src)
    assert m["state"] == "closed" and m["files"] == listing(src)
    assert DataDir(src).migrate() is False
    with pytest.raises(DataDirError):
        DataDir(tmp_path / "missing").migrate()
    held = DataDir(_format_1(tmp_path / "e")).open()
    try:
        with pytest.raises(LockBusy):
            DataDir(tmp_path / "e").migrate()
    finally:
        held.close()


def test_a_crash_between_the_two_renames_leaves_format_1(tmp_path, monkeypatch):
    from minidb import datadir
    src = _format_1(tmp_path / "d")
    real = datadir._write_atomic

    def crash(path, text):
        if path.name == "FORMAT":
            raise KeyboardInterrupt("crash")
        real(path, text)
    monkeypatch.setattr(datadir, "_write_atomic", crash)
    with pytest.raises(KeyboardInterrupt):
        DataDir(src).migrate()
    monkeypatch.undo()
    assert check_format(src) == 1
    assert DataDir(src).migrate() is True and _manifest(src)["files"] == listing(src)
