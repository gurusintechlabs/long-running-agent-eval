"""Assorted edge cases across sections."""


def test_text_compares_by_code_point(db):
    assert db.one("SELECT 'é' > 'z'") is True
    assert db.one("SELECT 'Z' < 'a'") is True
    assert db.one("SELECT 'ab' < 'abc'") is True


def test_like_treats_regex_metacharacters_literally(db):
    assert db.one("SELECT 'a+b(c)' LIKE 'a+b(_)'") is True
    assert db.one("SELECT 'a\\b' LIKE 'a\\_'") is True  # no escape character
    assert db.one("SELECT 'a_' LIKE 'a\\_'") is False
    assert db.one("SELECT 'a\\b' LIKE 'a_b'") is True
    assert db.one("SELECT '[x]' LIKE '[%]'") is True
    assert db.one("SELECT '50%' LIKE '50%'") is True
    assert db.one("SELECT 'é' LIKE '_'") is True


def test_not_binds_looser_than_is_null(db):
    assert db.one("SELECT NOT NULL IS NULL") is False
    assert db.one("SELECT NOT 1 IN (2, 3)") is True


def test_order_by_booleans_and_nulls(db):
    db.run("CREATE TABLE t (b BOOLEAN, k INT)")
    db.run("INSERT INTO t VALUES (TRUE, 1), (NULL, 2), (FALSE, 3), (TRUE, 4)")
    db.expect("SELECT k FROM t ORDER BY b, k DESC", [[2], [3], [4], [1]])
    db.expect("SELECT k FROM t ORDER BY b DESC, k", [[1], [4], [3], [2]])


def test_left_join_anti_join(db):
    db.run("CREATE TABLE a (id INT)", "CREATE TABLE b (aid INT)")
    db.run("INSERT INTO a VALUES (1), (2), (3)", "INSERT INTO b VALUES (2)")
    db.expect("SELECT a.id FROM a LEFT JOIN b ON b.aid = a.id WHERE b.aid IS NULL",
              [[1], [3]])


def test_join_with_empty_side(db):
    db.run("CREATE TABLE a (id INT)", "CREATE TABLE b (id INT)")
    db.run("INSERT INTO a VALUES (1)")
    db.expect("SELECT * FROM a CROSS JOIN b", [])
    db.expect("SELECT * FROM a LEFT JOIN b ON a.id = b.id", [[1, None]])
    db.expect("SELECT * FROM b LEFT JOIN a ON a.id = b.id", [])


def test_where_runs_after_join_on(db):
    db.run("CREATE TABLE a (x INT)", "CREATE TABLE b (y INT)")
    db.run("INSERT INTO a VALUES (0), (1)", "INSERT INTO b VALUES (1)")
    # The ON condition removes the x = 0 row before WHERE could divide by zero.
    db.expect("SELECT x FROM a JOIN b ON a.x = b.y WHERE 1 / x = 1", [[1]])


def test_count_star_vs_count_column_over_left_join(db):
    db.run("CREATE TABLE a (id INT)", "CREATE TABLE b (aid INT)")
    db.run("INSERT INTO a VALUES (1), (2)", "INSERT INTO b VALUES (1), (1)")
    db.expect("SELECT a.id, COUNT(*), COUNT(b.aid) FROM a LEFT JOIN b ON b.aid = a.id "
              "GROUP BY a.id", [[1, 2, 2], [2, 1, 0]])


def test_group_by_boolean_and_null_keys(db):
    db.run("CREATE TABLE t (b BOOLEAN, i INT)")
    db.run("INSERT INTO t VALUES (TRUE, 1), (NULL, 1), (FALSE, 0), (TRUE, 1), (NULL, 0)")
    db.expect("SELECT b, COUNT(*) FROM t GROUP BY b", [[True, 2], [None, 2], [False, 1]])
    # TRUE and 1 are different values, so grouping by both keeps them apart.
    db.expect("SELECT COUNT(*) FROM t GROUP BY b, i", [[2], [1], [1], [1]])


def test_select_list_errors_reported_on_rows_only(db):
    db.run("CREATE TABLE t (a INT, s TEXT)")
    db.expect("SELECT a / 0, s + 1, -s FROM t", [])
    db.run("INSERT INTO t VALUES (1, 'x')")
    assert db.error("SELECT a / 0 FROM t") == "RuntimeError"
    assert db.error("SELECT s + 1 FROM t") == "TypeError"


def test_reserved_words_cannot_be_names(db):
    db.run("CREATE TABLE t (a INT)")
    for sql in ("CREATE TABLE u (key INT)", "CREATE TABLE index (a INT)",
                "SELECT 1 AS order", "SELECT * FROM t AS left"):
        assert db.error(sql) == "SyntaxError", sql
    db.expect("SELECT 1 AS count, 2 AS text", [[1, 2]])


def test_real_subtraction(db):
    db.expect("SELECT 2.5 - 1, 1 - 0.25, 3 - 1", [[1.5, 0.75, 2]])
    assert db.error("SELECT -1" + "0" * 308 + ".0 - 1" + "0" * 308 + ".0") == "RuntimeError"


def test_delete_matching_nothing(db):
    db.run("CREATE TABLE t (a INT UNIQUE)", "INSERT INTO t VALUES (1)")
    assert db.run("DELETE FROM t WHERE a > 5") == {"rowcount": 0}
    assert db.error("INSERT INTO t VALUES (1)") == "ConstraintError"


def test_unsupported_statements(db):
    for sql in ("BEGIN", "EXPLAIN UPDATE t SET a = 1", "ALTER TABLE t ADD COLUMN b INT",
                "frobnicate", "42", "CREATE INDEX i ON t a", ""):
        assert db.error(sql) == "SyntaxError", sql
