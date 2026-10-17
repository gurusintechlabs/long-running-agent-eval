"""Section 4: UPDATE and DELETE."""
import pytest


@pytest.fixture
def t(db):
    db.run("CREATE TABLE t (a INT, b INT, c TEXT)")
    db.run("INSERT INTO t VALUES (1, 10, 'x'), (2, 20, 'y'), (3, 30, 'z')")
    return db


def test_update_rowcount_and_values(t):
    assert t.run("UPDATE t SET b = b + 1 WHERE a >= 2") == {"rowcount": 2}
    t.expect("SELECT * FROM t", [[1, 10, "x"], [2, 21, "y"], [3, 31, "z"]])
    assert t.run("UPDATE t SET c = c") == {"rowcount": 3}
    assert t.run("UPDATE t SET c = 'q' WHERE a > 99") == {"rowcount": 0}


def test_update_keeps_row_order(t):
    t.run("UPDATE t SET a = 0 WHERE a = 2")
    t.expect("SELECT a FROM t", [[1], [0], [3]])


def test_update_uses_old_row_values(t):
    t.run("UPDATE t SET a = b, b = a WHERE t.a = 1")
    t.expect("SELECT a, b FROM t WHERE c = 'x'", [[10, 1]])


def test_update_errors(t):
    assert t.error("UPDATE nope SET a = 1") == "NameError"
    assert t.error("UPDATE t SET zz = 1") == "NameError"
    assert t.error("UPDATE t SET a = zz") == "NameError"
    assert t.error("UPDATE t SET a = 1 WHERE u.a = 1") == "NameError"
    assert t.error("UPDATE t SET a = 1, a = 2") == "SyntaxError"
    assert t.error("UPDATE t SET t.a = 1") == "SyntaxError"
    assert t.error("UPDATE t AS x SET a = 1") == "SyntaxError"
    assert t.error("UPDATE t x SET a = 1") == "SyntaxError"
    assert t.error("UPDATE t SET a = COUNT(*)") == "SyntaxError"
    assert t.error("UPDATE t SET a = 1 WHERE COUNT(*) > 1") == "SyntaxError"
    assert t.error("UPDATE t SET a = 'x'") == "TypeError"
    assert t.error("UPDATE t SET a = 1 WHERE a") == "TypeError"


def test_update_is_atomic(t):
    assert t.error("UPDATE t SET b = 100 / (a - 3)") == "RuntimeError"
    t.expect("SELECT b FROM t", [[10], [20], [30]])


def test_update_error_order_is_row_by_row(db):
    db.run("CREATE TABLE t (a INT NOT NULL, b INT)")
    db.run("INSERT INTO t VALUES (1, 0), (2, 1)")
    # Row 1's NOT NULL failure comes before row 2's division by zero.
    assert db.error("UPDATE t SET a = NULL, b = 1 / (b - 1)") == "ConstraintError"
    # Within a row: evaluate all values, then type checks, then NOT NULL.
    assert db.error("UPDATE t SET a = NULL, b = 1 / b") == "RuntimeError"
    assert db.error("UPDATE t SET a = NULL, b = 'x'") == "TypeError"
    # Rows not selected by WHERE are never evaluated.
    assert db.run("UPDATE t SET b = 1 / b WHERE b <> 0") == {"rowcount": 1}


def test_delete(t):
    assert t.run("DELETE FROM t WHERE b = 20") == {"rowcount": 1}
    t.expect("SELECT a FROM t", [[1], [3]])
    t.run("INSERT INTO t VALUES (4, 40, 'w')")
    t.expect("SELECT a FROM t", [[1], [3], [4]])
    assert t.run("DELETE FROM t") == {"rowcount": 3}
    t.expect("SELECT * FROM t", [])


def test_delete_errors_and_atomicity(t):
    assert t.error("DELETE FROM nope") == "NameError"
    assert t.error("DELETE FROM t WHERE zz = 1") == "NameError"
    assert t.error("DELETE FROM t WHERE COUNT(*) = 1") == "SyntaxError"
    assert t.error("DELETE FROM t WHERE 10 / (a - 2) > 0") == "RuntimeError"
    assert t.error("DELETE FROM t WHERE a") == "TypeError"
    t.expect("SELECT a FROM t", [[1], [2], [3]])
    assert t.run("DELETE FROM t WHERE t.a = 1 OR c = 'z'") == {"rowcount": 2}
