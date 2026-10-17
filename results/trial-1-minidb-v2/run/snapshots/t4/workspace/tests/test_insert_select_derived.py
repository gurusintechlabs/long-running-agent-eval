"""Section 11: INSERT ... SELECT, derived tables, IF [NOT] EXISTS."""
import pytest


@pytest.fixture
def t(db):
    db.run("CREATE TABLE t (id INT PRIMARY KEY, name TEXT NOT NULL, score REAL DEFAULT 1)")
    db.run("INSERT INTO t VALUES (1, 'a', 2.5), (2, 'b', NULL), (3, 'c', 4)")
    return db


def test_insert_select_copies_rows_in_query_order(t):
    t.run("CREATE TABLE u (id INT, name TEXT)")
    assert t.run("INSERT INTO u SELECT id, name FROM t ORDER BY id DESC") == {"rowcount": 3}
    t.expect("SELECT * FROM u", [[3, "c"], [2, "b"], [1, "a"]])
    assert t.run("INSERT INTO u (name) SELECT name FROM t WHERE id = 1") == {"rowcount": 1}
    t.expect("SELECT * FROM u WHERE id IS NULL", [[None, "a"]])
    assert t.run("INSERT INTO u SELECT id, name FROM t WHERE FALSE") == {"rowcount": 0}


def test_insert_select_applies_defaults_and_storage_rules(t):
    t.run("INSERT INTO t (id, name) SELECT id + 10, name || '!' FROM t WHERE id < 3")
    t.expect("SELECT * FROM t WHERE id > 10", [[11, "a!", 1.0], [12, "b!", 1.0]])
    t.run("INSERT INTO t (name, id, score) SELECT 'z', 20, 7")
    t.expect("SELECT score FROM t WHERE id = 20", [[7.0]])


def test_insert_select_from_the_same_table_doubles_it(db):
    db.run("CREATE TABLE d (a INT)", "INSERT INTO d VALUES (1), (2)")
    assert db.run("INSERT INTO d SELECT * FROM d") == {"rowcount": 2}
    assert db.run("INSERT INTO d SELECT a + 10 FROM d") == {"rowcount": 4}
    db.expect("SELECT a FROM d", [[1], [2], [1], [2], [11], [12], [11], [12]])


def test_insert_select_errors_and_atomicity(t):
    assert t.error("INSERT INTO t SELECT id, name FROM t") == "SyntaxError"
    assert t.error("INSERT INTO t (id) SELECT id, name FROM t") == "SyntaxError"
    assert t.error("INSERT INTO t SELECT * FROM nope") == "NameError"
    assert t.error("INSERT INTO t SELECT id + 10, name, 'x' FROM t") == "ConstraintError"
    assert t.error("INSERT INTO t SELECT id + 10, NULL, 1 FROM t") == "ConstraintError"
    assert t.error("INSERT INTO t SELECT id, name, score FROM t") == "ConstraintError"
    assert t.error("INSERT INTO t SELECT id + 10, name, 1 / (id - 2) FROM t") == "RuntimeError"
    assert t.error("INSERT INTO t (id, name) SELECT 7, 'x' UNION ALL SELECT 7, 'y'") == \
        "ConstraintError"
    # Columns are counted even when the query returns nothing.
    assert t.error("INSERT INTO t SELECT id FROM t WHERE FALSE") == "SyntaxError"
    t.expect("SELECT COUNT(*) FROM t", [[3]])


def test_insert_select_error_order(db):
    db.run("CREATE TABLE e (a INT NOT NULL, b INT)")
    # The query is evaluated completely before any row is checked: its RuntimeError wins
    # over the first row's NOT NULL violation.
    assert db.error("INSERT INTO e SELECT NULL, 1 UNION ALL SELECT 1, 1 / 0") == "RuntimeError"
    # Row 1's NOT NULL violation comes before row 2's type violation.
    assert db.error_message("INSERT INTO e SELECT NULL, 1 UNION ALL SELECT 1, 'x'").startswith(
        "ConstraintError: NOT NULL")
    assert db.error_message("INSERT INTO e SELECT NULL, 'x'").startswith(
        "ConstraintError: type constraint")


def test_insert_set_operation(db):
    db.run("CREATE TABLE s (v INT)")
    assert db.run("INSERT INTO s SELECT 1 UNION SELECT 2 UNION SELECT 1") == {"rowcount": 2}
    db.expect("SELECT * FROM s", [[1], [2]])


def test_derived_tables(t):
    t.expect("SELECT * FROM (SELECT id, name FROM t WHERE id > 1) AS x", [[2, "b"], [3, "c"]])
    t.expect("SELECT x.n FROM (SELECT name AS n FROM t ORDER BY id DESC) x", [["c"], ["b"], ["a"]])
    t.expect("SELECT d.c FROM (SELECT COUNT(*) AS c FROM t) d", [[3]])
    assert t.columns("SELECT * FROM (SELECT id + 1, UPPER(name) FROM t) q") == [
        "?column?", "upper"]


def test_derived_tables_in_joins(t):
    t.expect("SELECT t.name, m.top FROM t JOIN (SELECT MAX(id) AS top FROM t) AS m "
             "ON t.id = m.top", [["c", 3]])
    t.expect("SELECT a.id, b.id FROM (SELECT id FROM t WHERE id < 3) a "
             "CROSS JOIN (SELECT id FROM t WHERE id > 2) b", [[1, 3], [2, 3]])
    t.expect("SELECT t.id, z.v FROM t LEFT JOIN (SELECT 2 AS v) z ON z.v = t.id",
             [[1, None], [2, 2], [3, None]])


def test_derived_table_duplicate_column_names(db):
    db.expect("SELECT * FROM (SELECT 1 AS a, 2 AS a) AS d", [[1, 2]])
    assert db.error("SELECT a FROM (SELECT 1 AS a, 2 AS a) AS d") == "NameError"
    assert db.error("SELECT d.a FROM (SELECT 1 AS a, 2 AS a) AS d") == "NameError"
    db.expect("SELECT d.* FROM (SELECT 1 AS a, 2 AS a) AS d", [[1, 2]])


def test_derived_table_errors(t):
    for sql in ("SELECT * FROM (SELECT 1)", "SELECT * FROM (SELECT 1) AS",
                "SELECT * FROM (t) AS x", "SELECT * FROM (SELECT 1) AS select",
                "SELECT * FROM t JOIN (SELECT 1 AS v) ON TRUE"):
        assert t.error(sql) == "SyntaxError", sql
    assert t.error("SELECT * FROM (SELECT 1 AS v) t JOIN t ON TRUE") == "NameError"
    assert t.error("SELECT * FROM (SELECT nope FROM t) AS x") == "NameError"


def test_derived_table_cannot_see_sibling_references(db):
    db.run("CREATE TABLE a (x INT)", "CREATE TABLE b (y INT)")
    db.run("INSERT INTO a VALUES (1)", "INSERT INTO b VALUES (1)")
    assert db.error("SELECT * FROM a JOIN (SELECT y FROM b WHERE y = a.x) d ON TRUE") == \
        "NameError"
    # ... but it can see enclosing queries.
    db.expect("SELECT x, (SELECT COUNT(*) FROM (SELECT y FROM b WHERE y = a.x) d) FROM a",
              [[1, 1]])


def test_derived_table_row_order_drives_joins(db):
    db.run("CREATE TABLE a (x INT)", "INSERT INTO a VALUES (1), (2)")
    db.expect("SELECT d.x, a.x FROM (SELECT x FROM a ORDER BY x DESC) d JOIN a ON TRUE",
              [[2, 1], [2, 2], [1, 1], [1, 2]])


def test_create_table_if_not_exists(db):
    db.run("CREATE TABLE t (a INT)", "INSERT INTO t VALUES (1)")
    assert db.run("CREATE TABLE IF NOT EXISTS t (b TEXT, b TEXT)") == {}
    db.expect("SELECT * FROM t", [[1]])
    assert db.run("CREATE TABLE IF NOT EXISTS u (b TEXT)") == {}
    db.expect("SELECT * FROM u", [])
    assert db.error("CREATE TABLE IF NOT EXISTS v (b TEXT, b INT)") == "NameError"
    assert db.error("CREATE TABLE IF NOT EXISTS t (b VARCHAR)") == "SyntaxError"
    assert db.error("CREATE TABLE IF EXISTS t (b INT)") == "SyntaxError"


def test_drop_table_if_exists(db):
    assert db.run("DROP TABLE IF EXISTS nothing") == {}
    db.run("CREATE TABLE t (a INT)")
    assert db.run("DROP TABLE IF EXISTS t") == {}
    assert db.error("SELECT * FROM t") == "NameError"
    assert db.error("DROP TABLE IF NOT EXISTS t") == "SyntaxError"


def test_if_is_not_reserved(db):
    db.run("CREATE TABLE if (if INT)", "INSERT INTO if VALUES (1)")
    db.expect("SELECT if FROM if", [[1]])
    db.run("CREATE TABLE IF NOT EXISTS if (x INT)")
    db.run("DROP TABLE if")
    db.run("DROP TABLE IF EXISTS if")


def test_new_reserved_words(db):
    for word in ("case", "when", "then", "else", "end", "cast", "union", "intersect",
                 "except", "all"):
        assert db.error(f"CREATE TABLE {word} (a INT)") == "SyntaxError", word
        assert db.error(f"SELECT 1 AS {word}") == "SyntaxError", word


def test_uncorrelated_derived_table_inside_correlated_subquery(db):
    db.run("CREATE TABLE a (x INT)", "INSERT INTO a VALUES (1), (2), (3)")
    # The derived table d does not depend on the outer row, so it is computed once and
    # reused each time the correlated subquery runs.
    db.expect("SELECT x, (SELECT COUNT(*) FROM (SELECT x AS v FROM a) d WHERE d.v < a.x) FROM a",
              [[1, 0], [2, 1], [3, 2]])
