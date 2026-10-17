"""Section 3: ORDER BY, LIMIT/OFFSET, DISTINCT, scalar functions."""
import pytest


@pytest.fixture
def people(db):
    db.run("CREATE TABLE p (name TEXT, age INT, score REAL)")
    db.run("INSERT INTO p VALUES ('ann', 30, 1.5), ('bob', NULL, 2.5), ('cid', 25, NULL), "
           "('dan', 30, 0.5), ('eve', 25, 2.5)")
    return db


def test_order_by_asc_desc_and_nulls(people):
    # NULL sorts as if larger than any value: last ascending, first descending.
    people.expect("SELECT name FROM p ORDER BY age",
                  [["cid"], ["eve"], ["ann"], ["dan"], ["bob"]])
    people.expect("SELECT name FROM p ORDER BY age DESC",
                  [["bob"], ["ann"], ["dan"], ["cid"], ["eve"]])
    people.expect("SELECT name FROM p ORDER BY age DESC, score ASC",
                  [["bob"], ["dan"], ["ann"], ["eve"], ["cid"]])


def test_nulls_first_and_last(people):
    people.expect("SELECT name FROM p ORDER BY age NULLS FIRST",
                  [["bob"], ["cid"], ["eve"], ["ann"], ["dan"]])
    people.expect("SELECT name FROM p ORDER BY age ASC NULLS LAST",
                  [["cid"], ["eve"], ["ann"], ["dan"], ["bob"]])
    people.expect("SELECT name FROM p ORDER BY age DESC NULLS LAST",
                  [["ann"], ["dan"], ["cid"], ["eve"], ["bob"]])
    people.expect("SELECT name FROM p ORDER BY age DESC NULLS FIRST, score nulls first",
                  [["bob"], ["dan"], ["ann"], ["cid"], ["eve"]])
    people.expect("SELECT name, score FROM p ORDER BY 2 NULLS FIRST, 1 DESC LIMIT 2",
                  [["cid", None], ["dan", 0.5]])
    people.expect("SELECT DISTINCT age FROM p ORDER BY age NULLS FIRST", [[None], [25], [30]])
    people.expect("SELECT (SELECT name FROM p ORDER BY score DESC NULLS LAST LIMIT 1)",
                  [["bob"]])
    people.expect("SELECT * FROM (SELECT age FROM p ORDER BY age LIMIT 1) d", [[25]])


def test_nulls_first_last_syntax(people):
    for sql in ("SELECT name FROM p ORDER BY age NULLS", "SELECT name FROM p ORDER BY age NULLS 1",
                "SELECT name FROM p ORDER BY age NULLS FIRST DESC",
                "SELECT name FROM p ORDER BY age NULLS FIRST LAST",
                "SELECT name FROM p ORDER BY age FIRST"):
        assert people.error(sql) == "SyntaxError", sql
    # NULLS, FIRST and LAST are not reserved.
    people.run("CREATE TABLE w (nulls INT, first INT, last INT)")
    people.run("INSERT INTO w VALUES (NULL, 1, 2), (3, 4, 5)")
    people.expect("SELECT nulls, first AS last FROM w ORDER BY nulls NULLS FIRST, last",
                  [[None, 1], [3, 4]])
    people.expect("SELECT last FROM w ORDER BY nulls", [[5], [2]])


def test_order_by_position_alias_and_hidden_column(people):
    people.expect("SELECT name, age FROM p ORDER BY 2 DESC, 1 DESC LIMIT 2",
                  [["bob", None], ["dan", 30]])
    people.expect("SELECT name AS n FROM p ORDER BY n DESC LIMIT 1", [["eve"]])
    people.expect("SELECT name FROM p ORDER BY score DESC, name LIMIT 3",
                  [["cid"], ["bob"], ["eve"]])
    people.expect("SELECT * FROM p ORDER BY name DESC LIMIT 1", [["eve", 25, 2.5]])
    people.expect("SELECT age AS name FROM p ORDER BY name LIMIT 2", [[25], [25]])


def test_order_by_constant_expressions_keep_order(people):
    people.expect("SELECT name FROM p ORDER BY -1, 1 + 0, 'x', TRUE LIMIT 2", [["ann"], ["bob"]])


def test_order_by_errors(people):
    assert people.error("SELECT name FROM p ORDER BY 0") == "SyntaxError"
    assert people.error("SELECT name FROM p ORDER BY 2") == "SyntaxError"
    assert people.error("SELECT name, name FROM p ORDER BY name") == "NameError"
    assert people.error("SELECT name FROM p ORDER BY nope") == "NameError"
    assert people.error("SELECT DISTINCT name FROM p ORDER BY age") == "SyntaxError"
    assert people.error("SELECT DISTINCT name FROM p ORDER BY name || 'x'") == "SyntaxError"
    people.expect("SELECT DISTINCT age FROM p ORDER BY 1 DESC", [[None], [30], [25]])


def test_order_by_incomparable_types_is_a_type_error(db):
    db.run("CREATE TABLE t (a INT, b TEXT)")
    db.run("INSERT INTO t VALUES (1, 'x'), (2, NULL)")
    db.expect("SELECT a FROM t ORDER BY COALESCE(b, 'z') DESC", [[2], [1]])
    assert db.error("SELECT a FROM t ORDER BY COALESCE(b, a)") == "TypeError"
    db.expect("SELECT a FROM t WHERE a = 1 ORDER BY COALESCE(b, a)", [[1]])


def test_sort_is_stable_and_mixes_int_real(db):
    db.run("CREATE TABLE t (k REAL, v INT)")
    db.run("INSERT INTO t VALUES (2, 1), (1.5, 2), (2, 3), (1, 4), (1.5, 5)")
    db.expect("SELECT v FROM t ORDER BY k", [[4], [2], [5], [1], [3]])
    db.expect("SELECT v FROM t ORDER BY k DESC", [[1], [3], [2], [5], [4]])


def test_limit_offset(people):
    people.expect("SELECT name FROM p LIMIT 2", [["ann"], ["bob"]])
    people.expect("SELECT name FROM p LIMIT 2 OFFSET 4", [["eve"]])
    people.expect("SELECT name FROM p LIMIT 0", [])
    people.expect("SELECT name FROM p LIMIT 10 OFFSET 10", [])
    people.expect("SELECT name FROM p ORDER BY name DESC LIMIT 1 OFFSET 1", [["dan"]])
    assert people.error("SELECT name FROM p OFFSET 1") == "SyntaxError"
    assert people.error("SELECT name FROM p LIMIT 1 + 1") == "SyntaxError"


def test_distinct(db):
    db.run("CREATE TABLE t (a REAL, b INT, c TEXT)")
    db.run("INSERT INTO t VALUES (1, 1, 'x'), (1.0, 1, 'x'), (NULL, NULL, 'y'), "
           "(NULL, NULL, 'y'), (2, 1, 'x')")
    db.expect("SELECT DISTINCT a, b FROM t", [[1.0, 1], [None, None], [2.0, 1]])
    db.expect("SELECT DISTINCT c FROM t ORDER BY c DESC", [["y"], ["x"]])
    db.expect("SELECT DISTINCT b, c FROM t LIMIT 1 OFFSET 1", [[None, "y"]])
    db.expect("SELECT DISTINCT 1, 1.0, TRUE", [[1, 1.0, True]])


def test_distinct_int_and_real_are_duplicates_keeping_first(db):
    db.run("CREATE TABLE t (a INT, b REAL)")
    db.run("INSERT INTO t VALUES (1, 1.0), (2, 3.0)")
    db.expect("SELECT DISTINCT a FROM t WHERE a = 1", [[1]])
    db.expect("SELECT DISTINCT COALESCE(NULL, b) FROM t", [[1.0], [3.0]])


def test_distinct_with_incomparable_values_is_not_an_error(db):
    db.run("CREATE TABLE t (a INT, b TEXT)")
    db.run("INSERT INTO t VALUES (1, NULL), (NULL, '1'), (1, NULL)")
    db.expect("SELECT DISTINCT COALESCE(a, b) FROM t", [[1], ["1"]])


@pytest.mark.parametrize("sql, expected", [
    ("LOWER('AbC')", "abc"), ("UPPER('AbC')", "ABC"), ("LENGTH('héllo')", 5),
    ("LENGTH('')", 0), ("ABS(-3)", 3), ("ABS(-2.5)", 2.5), ("ABS(0.0)", 0.0),
    ("COALESCE(NULL, NULL, 3)", 3), ("COALESCE(NULL)", None), ("COALESCE(1, 1 / 0)", 1),
    ("TYPEOF(1)", "INTEGER"), ("TYPEOF(1.0)", "REAL"), ("TYPEOF('a')", "TEXT"),
    ("TYPEOF(TRUE)", "BOOLEAN"), ("TYPEOF(NULL)", "NULL"), ("lower(NULL)", None),
    ("abs(NULL)", None), ("TypeOf(2 * 1.0)", "REAL"),
])
def test_scalar_functions(db, sql, expected):
    got = db.one("SELECT " + sql)
    assert type(got) is type(expected) and got == expected


@pytest.mark.parametrize("sql, error", [
    ("NOSUCH(1)", "NameError"), ("LOWER()", "SyntaxError"), ("LOWER('a', 'b')", "SyntaxError"),
    ("COALESCE()", "SyntaxError"), ("TYPEOF(1, 2)", "SyntaxError"), ("LOWER(1)", "TypeError"),
    ("LENGTH(TRUE)", "TypeError"), ("ABS('x')", "TypeError"), ("ABS(TRUE)", "TypeError"),
    ("ABS(-9223372036854775807 - 1)", "RuntimeError"), ("LOWER(*)", "SyntaxError"),
    ("LOWER(DISTINCT 'a')", "SyntaxError"), ("COALESCE(NULL, 1 / 0)", "RuntimeError"),
])
def test_scalar_function_errors(db, sql, error):
    assert db.error("SELECT " + sql) == error
