"""Section 15: BEGIN / COMMIT / ROLLBACK."""
import random

import pytest

from minidb.engine import Engine
from minidb.journal import Journal
from minidb.protocol import DBError


def state(engine):
    """Everything a transaction must restore: schemas, rows in order, every index's contents,
    unique-key sets, and plans."""
    db = engine.db
    out = {}
    for name in sorted(db.tables):
        t = db.tables[name]
        out[name] = (
            [(c.name, c.type, c.not_null, c.unique, c.primary_key, c.default) for c in t.columns],
            t.scan_items(),
            sorted((i.name, i.column, i.unique, i.implicit,
                    sorted(((k, list(v)) for k, v in i.rids.items()), key=repr),
                    list(i.sorted_keys())) for i in t.indexes),
            {col: sorted(keys, key=repr) for col, keys in t.unique_keys.items()},
            [engine.execute(f"EXPLAIN SELECT * FROM {name} WHERE {c.name} = 1")["rows"]
             for c in t.columns],
        )
    return out, sorted(db.indexes)


@pytest.fixture
def t(db):
    db.run("CREATE TABLE t (id INT PRIMARY KEY, s TEXT UNIQUE, n INT)")
    db.run("CREATE INDEX t_n ON t (n)")
    db.run("INSERT INTO t VALUES (1, 'a', 10), (2, 'b', 20), (3, 'c', 30)")
    return db


def test_commit_and_rollback(t):
    assert t.run("BEGIN") == {}
    t.run("INSERT INTO t VALUES (4, 'd', 40)", "DELETE FROM t WHERE id = 1",
          "UPDATE t SET n = 0 WHERE id = 2")
    t.expect("SELECT id, n FROM t", [[2, 0], [3, 30], [4, 40]])
    assert t.run("ROLLBACK") == {}
    t.expect("SELECT id, n FROM t", [[1, 10], [2, 20], [3, 30]])
    t.run("BEGIN TRANSACTION", "INSERT INTO t VALUES (5, 'e', 50)", "COMMIT TRANSACTION")
    t.expect("SELECT id FROM t", [[1], [2], [3], [5]])
    t.run("begin", "DELETE FROM t", "rollback transaction")
    t.expect("SELECT COUNT(*) FROM t", [[4]])


def test_rollback_restores_row_order_and_new_rows_go_last(t):
    t.run("BEGIN", "DELETE FROM t WHERE id = 1", "DELETE FROM t WHERE id = 2",
          "INSERT INTO t VALUES (9, 'z', 90)", "ROLLBACK")
    t.expect("SELECT id FROM t", [[1], [2], [3]])
    t.run("INSERT INTO t VALUES (7, 'x', 70)")
    t.expect("SELECT id FROM t", [[1], [2], [3], [7]])
    t.expect("SELECT id FROM t WHERE n >= 10", [[1], [2], [3], [7]])


def test_rollback_restores_constraints(t):
    t.run("BEGIN", "DELETE FROM t WHERE id = 1", "INSERT INTO t VALUES (8, 'h', 1)", "ROLLBACK")
    assert t.error("INSERT INTO t VALUES (1, 'q', 0)") == "ConstraintError"
    t.run("INSERT INTO t VALUES (8, 'h', 1)")  # the rolled-back insert left nothing behind


def test_rollback_of_schema_changes(t):
    before = state(t.engine)
    t.run("BEGIN")
    t.run("CREATE TABLE u (a INT PRIMARY KEY)", "INSERT INTO u VALUES (1)",
          "DROP INDEX t_n", "CREATE UNIQUE INDEX t_n2 ON t (n)", "ALTER TABLE t ADD COLUMN f REAL",
          "ALTER TABLE t DROP COLUMN s", "CREATE INDEX t_f ON t (f)", "DROP TABLE t")
    assert t.error("SELECT * FROM t") == "NameError"
    t.run("CREATE TABLE t (other TEXT)")
    t.run("ROLLBACK")
    assert state(t.engine) == before
    assert t.error("SELECT * FROM u") == "NameError"
    assert t.error("INSERT INTO t VALUES (4, 'a', 1)") == "ConstraintError"  # UNIQUE s is back


def test_transaction_errors_leave_the_state_unchanged(t):
    for sql in ("COMMIT", "ROLLBACK", "COMMIT TRANSACTION"):
        assert t.error(sql) == "TransactionError"
    t.run("BEGIN", "INSERT INTO t VALUES (4, 'd', 40)")
    assert t.error("BEGIN") == "TransactionError"
    t.expect("SELECT COUNT(*) FROM t", [[4]])  # still inside the same transaction
    t.run("ROLLBACK")
    t.expect("SELECT COUNT(*) FROM t", [[3]])
    for sql in ("BEGIN WORK", "COMMIT 1", "ROLLBACK TO x", "BEGIN TRANSACTION t"):
        assert t.error(sql) == "SyntaxError", sql
    t.run("CREATE TABLE transaction (transaction INT)")  # TRANSACTION is not reserved


def test_failing_statements_do_not_spoil_the_transaction(t):
    t.run("BEGIN", "INSERT INTO t VALUES (4, 'd', 40)")
    assert t.error("INSERT INTO t VALUES (5, 'e', 50), (1, 'x', 0)") == "ConstraintError"
    assert t.error("UPDATE t SET n = DIV(1, n - 20)") == "RuntimeError"
    assert t.error("SELECT nope FROM t") == "NameError"
    assert t.error("ALTER TABLE t ADD COLUMN z INT NOT NULL") == "ConstraintError"
    t.run("INSERT INTO t VALUES (5, 'e', 50)", "COMMIT")
    t.expect("SELECT id FROM t", [[1], [2], [3], [4], [5]])


def test_reads_inside_a_transaction_see_its_changes(t):
    t.run("BEGIN", "UPDATE t SET n = n + 1", "CREATE INDEX t_s2 ON t (s)")
    t.expect("SELECT SUM(n) FROM t", [[63]])
    t.expect("EXPLAIN SELECT * FROM t WHERE n = 11", [["SEARCH t USING INDEX t_n (n = ?)"]])
    t.expect("SELECT id FROM t WHERE n = 11", [[1]])
    t.run("ROLLBACK")
    t.expect("SELECT id FROM t WHERE n = 11", [])


# ---------------------------------------------------------------- randomized

def _random_statement(r):
    k = r.random()
    key = r.randint(0, 30)
    val = r.choice(["NULL", str(r.randint(0, 5))])
    if k < 0.3:
        return f"INSERT INTO t VALUES ({key}, '{r.choice('abcdefgh')}{key}', {val})"
    if k < 0.45:
        return f"UPDATE t SET n = {val} WHERE id % {r.randint(2, 4)} = {r.randint(0, 1)}"
    if k < 0.55:
        return f"UPDATE t SET id = id + {r.randint(1, 3)} WHERE n = {r.randint(0, 5)}"
    if k < 0.7:
        return f"DELETE FROM t WHERE n = {r.randint(0, 5)} OR id = {key}"
    if k < 0.75:
        return r.choice(["CREATE INDEX t_extra ON t (n)", "DROP INDEX t_extra",
                         "CREATE UNIQUE INDEX t_u ON t (n)", "DROP INDEX t_u"])
    if k < 0.8:
        return r.choice(["ALTER TABLE t ADD COLUMN x INT DEFAULT 7", "ALTER TABLE t DROP COLUMN x",
                         "ALTER TABLE t DROP COLUMN s", "ALTER TABLE t ADD COLUMN s TEXT"])
    if k < 0.85:
        return r.choice(["CREATE TABLE u (a INT UNIQUE)", "DROP TABLE u",
                         "INSERT INTO u VALUES (1), (2)", "DELETE FROM u WHERE a = 1"])
    return f"INSERT INTO t SELECT id + 100, s || 'x', n FROM t WHERE n = {r.randint(0, 5)}"


def _run_all(engine, statements):
    out = []
    for sql in statements:
        try:
            out.append(engine.execute(sql))
        except DBError as exc:
            out.append(exc.type_name)
    return out


def _fresh(seed):
    r = random.Random(seed)
    engine = Engine()
    engine.execute("CREATE TABLE t (id INT PRIMARY KEY, s TEXT UNIQUE, n INT)")
    engine.execute("CREATE INDEX t_n ON t (n)")
    _run_all(engine, [_random_statement(r) for _ in range(15)])
    return r, engine


@pytest.mark.parametrize("seed", range(80))
def test_rollback_restores_everything(seed):
    r, engine = _fresh(seed)
    before = state(engine)
    statements = [_random_statement(r) for _ in range(r.randint(1, 12))]
    engine.execute("BEGIN")
    _run_all(engine, statements)
    engine.execute("ROLLBACK")
    assert state(engine) == before, statements


@pytest.mark.parametrize("seed", range(80))
def test_commit_equals_running_without_a_transaction(seed):
    r, engine = _fresh(seed)
    _, twin = _fresh(seed)
    statements = [_random_statement(r) for _ in range(r.randint(1, 12))]
    engine.execute("BEGIN")
    results = _run_all(engine, statements)
    engine.execute("COMMIT")
    assert results == _run_all(twin, statements)
    assert state(engine) == state(twin)


def test_journal_directly():
    journal = Journal()
    log = []
    journal.record(lambda: log.append("undo 1"), ["op", 1])
    mark = journal.mark()
    journal.record(lambda: log.append("undo 2"), None)
    journal.record(lambda: log.append("undo 3"), ["op", 3])
    assert journal.redo_since(0) == [["op", 1], ["op", 3]]
    journal.undo_to(mark)
    assert log == ["undo 3", "undo 2"] and journal.redo_since(0) == [["op", 1]]
