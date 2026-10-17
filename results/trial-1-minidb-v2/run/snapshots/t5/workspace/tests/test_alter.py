"""Section 17: ALTER TABLE ADD / DROP COLUMN."""
import pytest

from tests.test_storage import session


@pytest.fixture
def t(db):
    db.run("CREATE TABLE t (id INT PRIMARY KEY, a TEXT UNIQUE, b INT, c REAL)")
    db.run("CREATE INDEX t_b ON t (b)", "CREATE INDEX t_c ON t (c)")
    db.run("INSERT INTO t VALUES (1, 'x', 10, 1.5), (2, 'y', 20, NULL), (3, NULL, 10, 0.5)")
    return db


def test_add_column(t):
    assert t.run("ALTER TABLE t ADD COLUMN d BOOLEAN DEFAULT TRUE") == {}
    assert t.run("ALTER TABLE t ADD e TEXT") == {}
    assert t.run("ALTER TABLE t ADD f REAL NOT NULL DEFAULT 2") == {}
    assert t.columns("SELECT * FROM t") == ["id", "a", "b", "c", "d", "e", "f"]
    t.expect("SELECT d, e, f FROM t", [[True, None, 2.0]] * 3)
    t.run("INSERT INTO t (id) VALUES (4)")
    t.expect("SELECT d, e, f FROM t WHERE id = 4", [[True, None, 2.0]])
    assert t.error("INSERT INTO t VALUES (5, 'z', 1, 1.0)") == "SyntaxError"  # 7 columns now
    t.run("INSERT INTO t VALUES (5, 'z', 1, 1.0, FALSE, 'e', 3)")
    t.run("UPDATE t SET e = 'set' WHERE id = 1")
    t.expect("SELECT id, e FROM t WHERE e IS NOT NULL ORDER BY id", [[1, "set"], [5, "e"]])
    t.run("CREATE INDEX t_e ON t (e)")
    t.expect("EXPLAIN SELECT * FROM t WHERE e = 'x'", [["SEARCH t USING INDEX t_e (e = ?)"]])


def test_add_column_errors(t):
    assert t.error("ALTER TABLE nope ADD x INT") == "NameError"
    assert t.error("ALTER TABLE t ADD b TEXT") == "NameError"
    assert t.error("ALTER TABLE t ADD COLUMN B TEXT") == "NameError"
    assert t.error("ALTER TABLE t ADD x INT NOT NULL") == "ConstraintError"
    assert t.error("ALTER TABLE t ADD x INT NOT NULL DEFAULT NULL") == "ConstraintError"
    assert t.error("ALTER TABLE t ADD x INT DEFAULT 'one'") == "ConstraintError"
    assert t.error("ALTER TABLE t ADD x BOOLEAN DEFAULT 1") == "ConstraintError"
    for sql in ("ALTER TABLE t ADD x INT PRIMARY KEY", "ALTER TABLE t ADD x INT UNIQUE",
                "ALTER TABLE t ADD x VARCHAR", "ALTER TABLE t ADD x", "ALTER TABLE t ADD",
                "ALTER TABLE t ADD x INT DEFAULT 1 DEFAULT 2", "ALTER TABLE t RENAME x",
                "ALTER t ADD x INT", "ALTER TABLE t ADD COLUMN select INT"):
        assert t.error(sql) == "SyntaxError", sql
    t.expect("SELECT * FROM t WHERE id = 1", [[1, "x", 10, 1.5]])  # nothing changed


def test_add_not_null_column_to_an_empty_table(db):
    db.run("CREATE TABLE e (a INT)", "ALTER TABLE e ADD b INT NOT NULL")
    assert db.error("INSERT INTO e (a) VALUES (1)") == "ConstraintError"
    db.run("INSERT INTO e VALUES (1, 2)")
    db.expect("SELECT * FROM e", [[1, 2]])


def test_drop_column(t):
    assert t.run("ALTER TABLE t DROP COLUMN b") == {}
    assert t.columns("SELECT * FROM t") == ["id", "a", "c"]
    t.expect("SELECT * FROM t", [[1, "x", 1.5], [2, "y", None], [3, None, 0.5]])
    assert t.error("SELECT b FROM t") == "NameError"
    # Its index is gone, the index on c (now in b's place) still works.
    assert t.error("DROP INDEX t_b") == "NameError"
    t.expect("EXPLAIN SELECT * FROM t WHERE c = 0.5", [["SEARCH t USING INDEX t_c (c = ?)"]])
    t.expect("SELECT id FROM t WHERE c < 1", [[3]])
    t.run("UPDATE t SET c = 9 WHERE id = 1", "INSERT INTO t VALUES (4, 'w', 9.0)")
    t.expect("SELECT id FROM t WHERE c = 9", [[1], [4]])
    # The UNIQUE constraint and implicit index of a are intact.
    assert t.error("INSERT INTO t VALUES (5, 'x', 0)") == "ConstraintError"
    t.expect("EXPLAIN SELECT * FROM t WHERE a = 'x'",
             [["SEARCH t USING INDEX t_a_key (a = ?)"]])
    t.run("CREATE INDEX t_b ON t (c)")  # the name is free again


def test_drop_unique_column_drops_its_implicit_index_and_constraint(t):
    t.run("CREATE INDEX t_a2 ON t (a)", "ALTER TABLE t DROP a")
    assert t.error("DROP INDEX t_a2") == "NameError"
    t.run("CREATE INDEX t_a_key ON t (b)")
    t.run("ALTER TABLE t ADD a TEXT", "INSERT INTO t VALUES (9, 1, 1.0, 'x'), (8, 1, 1.0, 'x')")
    t.expect("SELECT COUNT(*) FROM t WHERE a = 'x'", [[2]])


def test_drop_column_errors(t):
    assert t.error("ALTER TABLE nope DROP a") == "NameError"
    assert t.error("ALTER TABLE t DROP nope") == "NameError"
    assert t.error("ALTER TABLE t DROP COLUMN id") == "ConstraintError"
    t.run("CREATE TABLE one (x INT)")
    assert t.error("ALTER TABLE one DROP x") == "ConstraintError"
    assert t.error("ALTER TABLE t DROP") == "SyntaxError"
    assert t.error("ALTER TABLE t DROP COLUMN a, b") == "SyntaxError"
    t.expect("SELECT * FROM t WHERE id = 1", [[1, "x", 10, 1.5]])


def test_add_then_drop_and_reuse_a_name(t):
    t.run("ALTER TABLE t ADD d INT DEFAULT 5", "ALTER TABLE t DROP d", "ALTER TABLE t ADD d TEXT")
    t.expect("SELECT d FROM t", [[None]] * 3)


def test_alter_in_transactions(t):
    t.run("BEGIN", "ALTER TABLE t ADD d INT DEFAULT 1", "ALTER TABLE t DROP b",
          "INSERT INTO t VALUES (4, 'q', 2.0, 7)")
    t.expect("SELECT * FROM t WHERE id = 4", [[4, "q", 2.0, 7]])
    t.run("ROLLBACK")
    assert t.columns("SELECT * FROM t") == ["id", "a", "b", "c"]
    t.expect("SELECT id FROM t WHERE b = 10", [[1], [3]])
    t.expect("EXPLAIN SELECT * FROM t WHERE b = 10", [["SEARCH t USING INDEX t_b (b = ?)"]])
    t.run("BEGIN", "ALTER TABLE t DROP c", "COMMIT")
    assert t.columns("SELECT * FROM t") == ["id", "a", "b"]
    # A failing ALTER inside a transaction changes nothing and the transaction goes on.
    t.run("BEGIN")
    assert t.error("ALTER TABLE t ADD z INT NOT NULL") == "ConstraintError"
    t.run("ALTER TABLE t ADD z INT DEFAULT 3", "COMMIT")
    t.expect("SELECT z FROM t", [[3]] * 3)


def test_alter_is_durable(tmp_path):
    path = tmp_path / "db"
    session(path, """
        CREATE TABLE t (id INT PRIMARY KEY, a TEXT UNIQUE, b INT, c REAL);
        CREATE INDEX t_c ON t (c);
        INSERT INTO t VALUES (1, 'x', 10, 1.5), (2, 'y', 20, NULL);
        ALTER TABLE t ADD COLUMN d BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE t DROP COLUMN a;
        BEGIN; ALTER TABLE t DROP COLUMN b; ROLLBACK;
        BEGIN; ALTER TABLE t ADD e TEXT DEFAULT 'e'; COMMIT;
    """)
    res = session(path, """
        SELECT * FROM t;
        EXPLAIN SELECT * FROM t WHERE c = 1.5;
        INSERT INTO t (id, c) VALUES (3, 2.5);
        SELECT * FROM t WHERE c > 2;
        INSERT INTO t (id, d) VALUES (4, NULL);
    """)
    assert res[0]["columns"] == ["id", "b", "c", "d", "e"]
    assert res[0]["rows"] == [[1, 10, 1.5, False, "e"], [2, 20, None, False, "e"]]
    assert res[1]["rows"] == [["SEARCH t USING INDEX t_c (c = ?)"]]
    assert res[3]["rows"] == [[3, None, 2.5, False, "e"]]
    assert res[4]["error"]["type"] == "ConstraintError"
