"""Section 5: column types, DEFAULT, NOT NULL, UNIQUE, PRIMARY KEY."""
import pytest

from minidb.catalog import Column, Table
from minidb.protocol import ConstraintError


def test_storage_type_rules(db):
    db.run("CREATE TABLE t (i INT, r REAL, s TEXT, b BOOLEAN)")
    db.run("INSERT INTO t VALUES (1, 3, 'x', TRUE), (NULL, NULL, NULL, NULL)")
    db.expect("SELECT * FROM t", [[1, 3.0, "x", True], [None, None, None, None]])
    for bad in ("(1.5, 1, 'x', TRUE)", "('5', 1, 'x', TRUE)", "(TRUE, 1, 'x', TRUE)",
                "(1, 'x', 'x', TRUE)", "(1, TRUE, 'x', TRUE)", "(1, 1, 1, TRUE)",
                "(1, 1, 'x', 1)", "(1, 1, 'x', 'true')"):
        assert db.error(f"INSERT INTO t VALUES {bad}") == "TypeError", bad
    db.run("UPDATE t SET r = 7 WHERE i = 1")
    db.expect("SELECT r FROM t WHERE i = 1", [[7.0]])


def test_defaults(db):
    db.run("CREATE TABLE t (id INT, a INT DEFAULT -5, b REAL DEFAULT 2, c TEXT DEFAULT 'it''s',"
           " d BOOLEAN DEFAULT FALSE, e INT DEFAULT NULL, f REAL DEFAULT -0.5)")
    db.run("INSERT INTO t (id) VALUES (1)")
    db.expect("SELECT * FROM t", [[1, -5, 2.0, "it's", False, None, -0.5]])


@pytest.mark.parametrize("coldef", ["a INT DEFAULT 'x'", "a INT DEFAULT 1.5",
                                    "a TEXT DEFAULT 1", "a BOOLEAN DEFAULT 0"])
def test_default_type_mismatch(db, coldef):
    assert db.error(f"CREATE TABLE t ({coldef})") == "TypeError"
    assert db.error("SELECT * FROM t") == "NameError"


@pytest.mark.parametrize("coldef", ["a INT DEFAULT +1", "a INT DEFAULT (1)",
                                    "a INT DEFAULT -'x'", "a INT DEFAULT abs(1)",
                                    "a INT UNIQUE UNIQUE", "a INT DEFAULT 1 DEFAULT 2",
                                    "a INT PRIMARY KEY PRIMARY KEY", "a INT NULL"])
def test_bad_column_definitions(db, coldef):
    assert db.error(f"CREATE TABLE t ({coldef})") == "SyntaxError"


def test_constraint_clauses_in_any_order(db):
    db.run("CREATE TABLE t (a INT DEFAULT 1 UNIQUE NOT NULL, b TEXT NOT NULL PRIMARY KEY)")
    db.run("INSERT INTO t (b) VALUES ('x')")
    db.expect("SELECT * FROM t", [[1, "x"]])


def test_not_null(db):
    db.run("CREATE TABLE t (a INT NOT NULL, b INT NOT NULL DEFAULT 0, c INT NOT NULL DEFAULT NULL)")
    assert db.error("INSERT INTO t VALUES (NULL, 1, 1)") == "ConstraintError"
    assert db.error("INSERT INTO t (b, c) VALUES (1, 1)") == "ConstraintError"
    assert db.error("INSERT INTO t (a) VALUES (1)") == "ConstraintError"  # c defaults to NULL
    db.run("INSERT INTO t (a, c) VALUES (1, 2)")
    assert db.error("UPDATE t SET b = NULL") == "ConstraintError"
    db.expect("SELECT * FROM t", [[1, 0, 2]])


def test_unique_allows_many_nulls(db):
    db.run("CREATE TABLE t (a INT UNIQUE)")
    db.run("INSERT INTO t VALUES (NULL), (NULL), (1)")
    assert db.error("INSERT INTO t VALUES (1)") == "ConstraintError"
    assert db.error("INSERT INTO t VALUES (2), (2)") == "ConstraintError"
    db.expect("SELECT * FROM t", [[None], [None], [1]])
    db.run("INSERT INTO t VALUES (2)")


def test_unique_real_column_compares_by_value(db):
    db.run("CREATE TABLE t (r REAL UNIQUE)")
    db.run("INSERT INTO t VALUES (1)")
    assert db.error("INSERT INTO t VALUES (1.0)") == "ConstraintError"


def test_primary_key(db):
    db.run("CREATE TABLE t (id INT PRIMARY KEY, v TEXT)")
    db.run("INSERT INTO t VALUES (1, 'a'), (2, 'b'), (3, 'c')")
    assert db.error("INSERT INTO t VALUES (NULL, 'x')") == "ConstraintError"
    assert db.error("INSERT INTO t (v) VALUES ('x')") == "ConstraintError"
    assert db.error("INSERT INTO t VALUES (1, 'x')") == "ConstraintError"
    assert db.error("UPDATE t SET id = 1 WHERE id = 2") == "ConstraintError"
    assert db.error("UPDATE t SET id = 5") == "ConstraintError"
    # Checked against the final state: shifting every key succeeds.
    assert db.run("UPDATE t SET id = id + 1") == {"rowcount": 3}
    db.expect("SELECT * FROM t", [[2, "a"], [3, "b"], [4, "c"]])
    db.run("UPDATE t SET id = 5 - id")
    db.expect("SELECT id FROM t", [[3], [2], [1]])


def test_unique_after_delete_and_update(db):
    db.run("CREATE TABLE t (a INT UNIQUE, b INT)")
    db.run("INSERT INTO t VALUES (1, 1), (2, 2)")
    db.run("DELETE FROM t WHERE a = 1")
    db.run("INSERT INTO t VALUES (1, 3)")
    db.run("UPDATE t SET a = NULL WHERE a = 2")
    db.run("INSERT INTO t VALUES (2, 4)")
    db.run("UPDATE t SET b = 0")  # unchanged unique column
    db.expect("SELECT * FROM t", [[None, 0], [1, 0], [2, 0]])
    assert db.error("UPDATE t SET a = 1 WHERE b = 0") == "ConstraintError"
    db.expect("SELECT a FROM t", [[None], [1], [2]])


def test_unique_checked_after_all_rows(db):
    db.run("CREATE TABLE t (a INT UNIQUE, b INT NOT NULL)")
    db.run("INSERT INTO t VALUES (1, 1)")
    # The duplicate in row 1 is only reported after every row passed its other checks.
    assert db.error("INSERT INTO t VALUES (1, 1), (2, NULL)") == "ConstraintError"
    assert db.error("INSERT INTO t VALUES (1, 1), (2, 'x')") == "TypeError"
    assert db.error("INSERT INTO t VALUES (1, 1), (2, 1 / 0)") == "RuntimeError"


def test_table_constraint_checks_directly():
    table = Table("t", [Column("a", "INTEGER", unique=True)])
    table.insert_rows([(1,), (None,)])
    with pytest.raises(ConstraintError):
        table.insert_rows([(2,), (1,)])
    assert table.rows == [(1,), (None,)]
    table.update_rows([(0, (2,)), (1, (1,))])
    assert table.rows == [(2,), (1,)]
    table.delete_rows({0})
    table.insert_rows([(2,)])
    assert table.rows == [(1,), (2,)]
