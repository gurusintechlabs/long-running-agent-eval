"""Section 16: durable storage (--db PATH): restarts, crashes, damaged files."""
import json
import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from minidb import storage as storage_module
from minidb.engine import Engine
from minidb.protocol import DBError
from minidb.storage import MAGIC, Storage
from tests.test_cli import ROOT
from tests.test_transactions import _random_statement


def observable(engine):
    """Everything a restart must preserve (rowids themselves are internal)."""
    db = engine.db
    out = {}
    for name in sorted(db.tables):
        t = db.tables[name]
        rows = t.rows
        out[name] = (
            [(c.name, c.type, c.not_null, c.unique, c.primary_key, c.default) for c in t.columns],
            t.scan(),
            sorted((i.name, i.column, i.unique, i.implicit,
                    sorted(((k, [rows[r] for r in v]) for k, v in i.rids.items()), key=repr))
                   for i in t.indexes),
            {col: sorted(keys, key=repr) for col, keys in t.unique_keys.items()},
            [engine.execute(f"EXPLAIN SELECT * FROM {name} WHERE {c.name} = 1")["rows"]
             for c in t.columns],
        )
    return out, sorted(db.indexes)


def run(engine, statements):
    out = []
    for sql in statements:
        try:
            out.append(engine.execute(sql))
        except DBError as exc:
            out.append(exc.type_name)
    return out


def session(path, script, args=("--db",)):
    """Run python -m minidb --db PATH on a script; return the JSON results."""
    proc = subprocess.run([sys.executable, "-m", "minidb", *args, str(path)], input=script,
                          cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines()]


# ---------------------------------------------------------------- restarts

def test_everything_survives_a_restart(tmp_path):
    path = tmp_path / "db"
    res = session(path, """
        CREATE TABLE emp (id INT PRIMARY KEY, name TEXT NOT NULL DEFAULT 'x' UNIQUE,
                          sal REAL DEFAULT 1.5, ok BOOL);
        CREATE INDEX emp_sal ON emp (sal);
        CREATE INDEX emp_sal2 ON emp (sal);
        CREATE UNIQUE INDEX emp_ok ON emp (ok);
        INSERT INTO emp VALUES (3, 'c', 2, TRUE), (1, 'a', NULL, FALSE), (2, 'b', 0.5, NULL);
        DELETE FROM emp WHERE id = 1;
        INSERT INTO emp (id, name) VALUES (5, 'e');
        UPDATE emp SET sal = sal * 10 WHERE id = 3;
        CREATE TABLE other (v TEXT);
        DROP TABLE other;
        DROP INDEX emp_sal;
    """)
    assert all(r["ok"] for r in res), res
    res = session(path, """
        SELECT * FROM emp;
        EXPLAIN SELECT * FROM emp WHERE sal > 1;
        EXPLAIN SELECT * FROM emp WHERE name = 'a';
        INSERT INTO emp (id, name) VALUES (6, 'f');
        INSERT INTO emp VALUES (7, 'c', 1, FALSE);
        INSERT INTO emp VALUES (8, 'g', 1, TRUE);
        INSERT INTO emp (id) VALUES (9);
        SELECT id FROM emp;
        SELECT * FROM other;
    """)
    assert res[0]["rows"] == [[3, "c", 20.0, True], [2, "b", 0.5, None], [5, "e", 1.5, None]]
    assert res[1]["rows"] == [["SEARCH emp USING INDEX emp_sal2 (sal RANGE)"]]
    assert res[2]["rows"] == [["SEARCH emp USING INDEX emp_name_key (name = ?)"]]
    assert res[3] == {"ok": True, "rowcount": 1}
    assert res[4]["error"]["type"] == "ConstraintError"   # UNIQUE name survived
    assert res[5]["error"]["type"] == "ConstraintError"   # the unique index on ok survived
    assert res[6] == {"ok": True, "rowcount": 1}          # DEFAULT 'x' for name survived
    assert res[7]["rows"] == [[3], [2], [5], [6], [9]]    # new rows after the old ones
    assert res[8]["error"]["type"] == "NameError"


def test_uncommitted_and_failed_changes_are_gone(tmp_path):
    path = tmp_path / "db"
    session(path, """
        CREATE TABLE t (id INT PRIMARY KEY);
        INSERT INTO t VALUES (1);
        BEGIN; INSERT INTO t VALUES (2); COMMIT;
        BEGIN; INSERT INTO t VALUES (3); ROLLBACK;
        INSERT INTO t VALUES (4), (1);
        UPDATE t SET id = DIV(id, 0);
        BEGIN; INSERT INTO t VALUES (5); DELETE FROM t WHERE id = 1;
    """)  # the input ends inside a transaction: it is rolled back
    res = session(path, "SELECT id FROM t; COMMIT;")
    assert res[0]["rows"] == [[1], [2]]
    assert res[1]["error"]["type"] == "TransactionError"


def test_new_database_file_is_created(tmp_path):
    path = tmp_path / "fresh.db"
    assert session(path, "SELECT 1")[0]["rows"] == [[1]]
    assert path.exists()
    assert {p.name for p in tmp_path.iterdir()} <= {"fresh.db", "fresh.db-wal"}
    assert session(path, "CREATE TABLE t (a INT)") == [{"ok": True}]


def test_without_db_nothing_is_written(tmp_path):
    proc = subprocess.run([sys.executable, "-m", "minidb"], input="CREATE TABLE t (a INT);",
                          cwd=tmp_path, text=True, capture_output=True, timeout=60,
                          env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert proc.stdout.strip() == '{"ok": true}'
    assert list(tmp_path.iterdir()) == []


def test_bad_command_line(tmp_path):
    proc = subprocess.run([sys.executable, "-m", "minidb", "--frobnicate"], input="", cwd=ROOT,
                          text=True, capture_output=True, timeout=60)
    assert proc.returncode != 0 and "usage" in proc.stderr


# ---------------------------------------------------------------- crashes

def _kill_after(path, statements, extra_unanswered=""):
    """Send statements one at a time, wait for each answer, optionally send more without
    waiting, then SIGKILL the process."""
    proc = subprocess.Popen([sys.executable, "-m", "minidb", "--db", str(path)], cwd=ROOT,
                            text=True, encoding="utf-8", stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    answers = []
    try:
        for sql in statements:
            proc.stdin.write(sql + ";\n")
            proc.stdin.flush()
            answers.append(json.loads(proc.stdout.readline()))
        if extra_unanswered:
            proc.stdin.write(extra_unanswered)
            proc.stdin.flush()
    finally:
        proc.send_signal(signal.SIGKILL)
        proc.wait()
    return answers


def test_answered_statements_survive_sigkill(tmp_path):
    path = tmp_path / "db"
    answers = _kill_after(path, [
        "CREATE TABLE t (id INT PRIMARY KEY, v TEXT)",
        "INSERT INTO t VALUES (1, 'a'), (2, 'b')",
        "BEGIN", "UPDATE t SET v = 'z'", "COMMIT",
        "BEGIN", "DELETE FROM t", "INSERT INTO t VALUES (3, 'c')",  # never committed
    ])
    assert all(a["ok"] for a in answers)
    assert session(path, "SELECT * FROM t")[0]["rows"] == [[1, "z"], [2, "z"]]


def test_sigkill_during_a_large_statement_is_all_or_nothing(tmp_path):
    path = tmp_path / "db"
    big = "INSERT INTO t VALUES " + ", ".join(f"({i})" for i in range(100, 60100)) + ";\n"
    _kill_after(path, ["CREATE TABLE t (id INT PRIMARY KEY)", "INSERT INTO t VALUES (1)"],
                extra_unanswered=big)
    count = session(path, "SELECT COUNT(*) FROM t")[0]["rows"][0][0]
    assert count in (1, 60001)


def test_torn_log_records_are_ignored(tmp_path):
    path = str(tmp_path / "db")
    engine = Engine(path)
    run(engine, ["CREATE TABLE t (a INT)", "INSERT INTO t VALUES (1)", "INSERT INTO t VALUES (2)"])
    engine.close()
    wal = Path(path + "-wal")
    data = wal.read_bytes()
    last = data.rstrip(b"\n").rfind(b"\n") + 1
    for damaged in (data[:-1], data[:last + 10], data[:last] + b"garbage\n",
                    data[:last] + data[last:].replace(b"2", b"3")):
        wal.write_bytes(damaged)
        engine = Engine(path)
        assert engine.execute("SELECT a FROM t")["rows"] == [[1]]
        engine.execute("INSERT INTO t VALUES (5)")  # appended after the cut-off point
        engine.close()
        assert Engine(path).execute("SELECT a FROM t")["rows"] == [[1], [5]]
        wal.write_bytes(data)


# ---------------------------------------------------------------- checkpoints

def test_checkpoints_and_crash_between_snapshot_and_log_truncation(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_module, "_MIN_LOG_BYTES", 2000)
    path = str(tmp_path / "db")
    engine = Engine(path)
    engine.execute("CREATE TABLE t (id INT PRIMARY KEY, v INT)")
    for i in range(300):
        engine.execute(f"INSERT INTO t VALUES ({i}, {i % 7})")
        if i % 3 == 0:
            engine.execute(f"UPDATE t SET v = v + 1 WHERE id = {i // 2}")
    assert os.path.getsize(path) > len(MAGIC) + 100            # snapshots were written
    assert os.path.getsize(path + "-wal") <= 2 * os.path.getsize(path) + 2000
    expected = engine.execute("SELECT * FROM t")["rows"]
    # Crash right after a snapshot replaced PATH but before the log was emptied:
    log_before = Path(path + "-wal").read_bytes()
    engine.storage._write_snapshot(engine.db)
    engine.close()
    Path(path + "-wal").write_bytes(log_before)
    assert Engine(path).execute("SELECT * FROM t")["rows"] == expected  # nothing applied twice


# ---------------------------------------------------------------- unusable files

def test_a_file_that_is_not_a_database(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_bytes(b"hello, I am not a database\n")
    res = session(path, "SELECT 1; CREATE TABLE t (a INT); INSERT INTO t VALUES (1)")
    assert [r["error"]["type"] for r in res] == ["IOError"] * 3
    assert path.read_bytes() == b"hello, I am not a database\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["notes.txt"]


def test_a_damaged_snapshot(tmp_path):
    path = tmp_path / "db"
    path.write_bytes(MAGIC + b'{"seq": 0, "tables": [{"name": 1}]}')
    assert session(path, "SELECT 1")[0]["error"]["type"] == "IOError"


@pytest.mark.parametrize("where", ["missing_dir/db", "."])
def test_unusable_paths(tmp_path, where):
    path = tmp_path / where
    res = session(path, "SELECT 1; SELECT 2")
    assert [r["error"]["type"] for r in res] == ["IOError", "IOError"]
    assert not (tmp_path / "missing_dir").exists()


# ---------------------------------------------------------------- randomized restarts

@pytest.mark.parametrize("seed", range(40))
def test_random_sessions_with_restarts(tmp_path, seed):
    r = random.Random(seed)
    path = str(tmp_path / "db")
    durable = Engine(path)
    reference = Engine()
    for sql in ("CREATE TABLE t (id INT PRIMARY KEY, s TEXT UNIQUE, n INT)",
                "CREATE INDEX t_n ON t (n)"):
        durable.execute(sql)
        reference.execute(sql)
    in_transaction = False
    for _ in range(60):
        k = r.random()
        if k < 0.08 and not in_transaction:
            sql = "BEGIN"
            in_transaction = True
        elif k < 0.16 and in_transaction:
            sql = r.choice(["COMMIT", "ROLLBACK"])
            in_transaction = False
        else:
            sql = _random_statement(r)
        assert run(durable, [sql]) == run(reference, [sql])
        if r.random() < 0.1:  # "crash" and restart: an open transaction is lost
            durable.storage.close()
            durable = Engine(path)
            if in_transaction:
                reference.execute("ROLLBACK")
                in_transaction = False
            assert observable(durable) == observable(reference)
    durable.storage.close()
    if in_transaction:
        reference.execute("ROLLBACK")
    assert observable(Engine(path)) == observable(reference)


def test_storage_directly(tmp_path):
    store = Storage(str(tmp_path / "x"))
    engine = Engine()
    store.open(engine.db)
    store.append([["create_table", "t", [["a", "INTEGER", False, False, False, None]]]])
    store.append([["insert", "t", [[0, [1]], [1, [2]]]]])
    store.close()
    reopened = Engine(str(tmp_path / "x"))
    assert reopened.execute("SELECT * FROM t")["rows"] == [[1], [2]]


class _FailingLog:
    """Stands in for the log file: every write fails as on a full disk."""

    def __init__(self, real):
        self.real = real

    def write(self, data):
        raise OSError(28, "No space left on device")

    def fileno(self):
        return self.real.fileno()

    def close(self):
        self.real.close()


def test_a_failed_log_write_is_an_io_error_and_leaves_no_trace(tmp_path):
    path = str(tmp_path / "db")
    engine = Engine(path)
    engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
    engine.execute("INSERT INTO t VALUES (1)")
    real = engine.storage._log
    engine.storage._log = _FailingLog(real)
    with pytest.raises(DBError) as info:
        engine.execute("INSERT INTO t VALUES (2)")
    assert info.value.type_name == "IOError"
    assert engine.execute("SELECT id FROM t")["rows"] == [[1]]  # undone in memory too
    # A COMMIT that cannot be written leaves the transaction open and unchanged.
    engine.execute("BEGIN")
    engine.execute("INSERT INTO t VALUES (3)")
    with pytest.raises(DBError) as info:
        engine.execute("COMMIT")
    assert info.value.type_name == "IOError"
    assert engine.execute("SELECT id FROM t")["rows"] == [[1], [3]]
    engine.storage._log = real  # the disk has space again
    engine.execute("COMMIT")
    engine.execute("INSERT INTO t VALUES (4)")
    engine.close()
    assert Engine(path).execute("SELECT id FROM t")["rows"] == [[1], [3], [4]]


@pytest.mark.parametrize("seed", range(6))
def test_sigkill_at_random_moments(tmp_path, seed):
    """Groups of 5 rows (5 * g ... 5 * g + 4) are written atomically, alternately as one
    INSERT and as a committed transaction; rows are padded so that the log is checkpointed
    many times. After a kill at a random moment, the table must hold exactly the first k
    groups, k at least the number of groups whose answers were read."""
    import threading
    r = random.Random(seed)
    path = tmp_path / "db"
    session(path, "CREATE TABLE t (id INT PRIMARY KEY, pad TEXT)")
    proc = subprocess.Popen([sys.executable, "-m", "minidb", "--db", str(path)], cwd=ROOT,
                            text=True, encoding="utf-8", stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pad = "x" * 400
    answered_groups = 0
    lines_per_group = []

    def writer():
        try:
            for g in range(100000):
                rows = ", ".join(f"({5 * g + i}, '{pad}')" for i in range(5))
                if g % 2:
                    proc.stdin.write(f"INSERT INTO t VALUES {rows};\n")
                    lines_per_group.append(1)
                else:
                    proc.stdin.write(f"BEGIN; INSERT INTO t VALUES {rows}; COMMIT;\n")
                    lines_per_group.append(3)
        except (BrokenPipeError, ValueError, OSError):
            pass

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    deadline = time.time() + r.uniform(0.3, 1.5)
    answers = 0
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        assert json.loads(line)["ok"]
        answers += 1
    proc.send_signal(signal.SIGKILL)
    proc.wait()
    thread.join(timeout=5)
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        try:
            stream.close()
        except OSError:  # unflushed input for the dead process
            pass
    seen = 0
    for n in lines_per_group:
        if seen + n > answers:
            break
        seen += n
        answered_groups += 1
    ids = [row[0] for row in session(path, "SELECT id FROM t")[0]["rows"]]
    assert len(ids) % 5 == 0 and ids == list(range(len(ids)))
    assert len(ids) // 5 >= answered_groups
    assert answered_groups > 0
