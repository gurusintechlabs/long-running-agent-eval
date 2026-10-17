"""Section 2: expressions, NULL logic, type rules, WHERE."""
import pytest

from minidb import values
from minidb.protocol import SQLRuntimeError, SQLTypeError


@pytest.mark.parametrize("sql, expected", [
    ("10 - 3 - 2", 5), ("2 + 3 * 4", 14), ("(2 + 3) * 4", 20), ("-7 / 2", -3.5), ("7 / -2", -3.5),
    ("-7 % 2", -1), ("7 % -2", 1), ("7 / 2.0", 3.5), ("7 / 2", 3.5), ("4 / 2", 2.0),
    ("1 / 3", 1 / 3), ("9223372036854775807 / 3", 9223372036854775807 / 3),
    ("(-9223372036854775807 - 1) / -1", 9223372036854775808.0), ("DIV(-7, 2)", -3),
    ("DIV(7, 2)", 3), ("DIV(-7, -2)", 3), ("DIV(6, 3)", 2), ("DIV(NULL, 0)", None),
    ("DIV(1, NULL)", None), ("1 + 1.5", 2.5), ("2 * 1.5", 3.0),
    ("- -3", 3), ("+4", 4), ("-2.5", -2.5), ("'a' || 'b' || 'c'", "abc"),
    ("1 = 1.0", True), ("'B' < 'a'", True), ("FALSE < TRUE", True), ("2 <> 3", True),
    ("2 != 2", False), ("3 >= 3", True), ("1 < 2 = TRUE", None),
    ("NULL + 'a'", None), ("NULL = NULL", None), ("NULL IS NULL", True),
    ("1 IS NOT NULL", True), ("NOT NULL", None),
    ("FALSE AND NULL", False), ("TRUE AND NULL", None), ("TRUE OR NULL", True),
    ("FALSE OR NULL", None), ("NOT TRUE", False),
    ("2 BETWEEN 1 AND 3", True), ("4 NOT BETWEEN 1 AND 3", True), ("NULL BETWEEN 1 AND 2", None),
    ("1 IN (2, NULL)", None), ("1 IN (2, 1)", True), ("1 NOT IN (2, 3)", True),
    ("1 NOT IN (1, NULL)", False), ("3 BETWEEN 4 AND NULL", False),
    ("'abc' LIKE 'a%'", True), ("'abc' LIKE '_b_'", True), ("'abc' LIKE 'A%'", False),
    ("'abc' LIKE 'ab'", False), ("'' LIKE '%'", True), ("'a.c' LIKE 'a.c'", True),
    ("'abc' LIKE 'a.c'", False), ("'a\nb' LIKE 'a_b'", True), ("'abc' NOT LIKE '%c'", False),
    ("FALSE AND 1 / 0 = 1", False), ("TRUE OR 1 / 0 = 1", True),
    ("9223372036854775807 + 0", 9223372036854775807),
])
def test_expression_values(db, sql, expected):
    if sql == "1 < 2 = TRUE":
        assert db.error("SELECT " + sql) == "SyntaxError"
        return
    got = db.one("SELECT " + sql)
    assert type(got) is type(expected) and got == expected


@pytest.mark.parametrize("sql", [
    "1 + 'a'", "'a' || 1", "1 = 'a'", "TRUE + 1", "NOT 5", "1 = TRUE", "-'a'", "+TRUE",
    "1.5 % 2", "5 % 1.5", "1 AND TRUE", "TRUE AND 1", "NULL OR 'x'", "1 LIKE 'a'",
    "'a' < 1", "1 BETWEEN 'a' AND 2", "1 IN ('a')", "'a' + NULL + 1 + 'b'",
])
def test_type_errors(db, sql):
    if sql == "'a' + NULL + 1 + 'b'":  # NULL propagates: no type check against NULL
        assert db.one("SELECT " + sql) is None
        return
    assert db.error("SELECT " + sql) == "TypeError"


@pytest.mark.parametrize("sql", [
    "1 / 0", "1 % 0", "1.0 / 0", "1 / 0.0", "9223372036854775807 + 1",
    "-9223372036854775807 - 2", "-(-9223372036854775807 - 1)",
    "DIV(-9223372036854775807 - 1, -1)", "DIV(1, 0)", "DIV(0, 0)",
    "4611686018427387904 * 2",
    "1" + "0" * 300 + ".0 * 1" + "0" * 10 + ".0",
])
def test_runtime_errors(db, sql):
    assert db.error("SELECT " + sql) == "RuntimeError"


def test_operands_are_evaluated_left_to_right(db):
    assert db.error("SELECT 1 / 0 + 'a'") == "RuntimeError"
    assert db.error("SELECT 'a' + 1 / 0") == "RuntimeError"
    assert db.error("SELECT 1 IN (2, 1 / 0)") == "RuntimeError"
    assert db.error("SELECT NULL AND 1 / 0 = 1") == "RuntimeError"
    assert db.error("SELECT 5 AND FALSE") == "TypeError"


def test_output_column_names(db):
    db.run("CREATE TABLE t (a INT, b TEXT)")
    assert db.columns("SELECT a, t.b, (a), a + 1, a AS x, lower(b), LOWER(b), 1 FROM t") == [
        "a", "b", "a", "?column?", "x", "lower", "lower", "?column?"]


def test_where_filters_true_only(db):
    db.run("CREATE TABLE t (a INT, b BOOLEAN)")
    db.run("INSERT INTO t VALUES (1, TRUE), (2, FALSE), (3, NULL), (4, TRUE)")
    db.expect("SELECT a FROM t WHERE b", [[1], [4]])
    db.expect("SELECT a FROM t WHERE NOT b", [[2]])
    db.expect("SELECT a FROM t WHERE b IS NULL OR a > 3", [[3], [4]])
    db.expect("SELECT a * 10 AS x FROM t WHERE t.a BETWEEN 2 AND 3", [[20], [30]])


def test_where_errors(db):
    db.run("CREATE TABLE t (a INT)")
    assert db.error("SELECT a FROM t WHERE zz = 1") == "NameError"
    assert db.error("SELECT zz FROM t") == "NameError"
    assert db.error("SELECT u.a FROM t") == "NameError"
    assert db.one("SELECT COUNT(*) FROM t WHERE a") == 0  # empty table: never evaluated
    db.run("INSERT INTO t VALUES (1)")
    assert db.error("SELECT a FROM t WHERE a") == "TypeError"
    assert db.error("SELECT a FROM t WHERE 'x'") == "TypeError"
    db.expect("SELECT a FROM t WHERE NULL", [])


def test_select_without_from(db):
    db.expect("SELECT 1 AS a, 'x'", [[1, "x"]])
    assert db.error("SELECT *") == "SyntaxError"
    assert db.error("SELECT 1 WHERE TRUE") == "SyntaxError"
    assert db.error("SELECT 1 LIMIT 1") == "SyntaxError"
    assert db.error("SELECT a") == "NameError"


def test_star_with_other_items(db):
    db.run("CREATE TABLE t (a INT, b INT)", "INSERT INTO t VALUES (1, 2)")
    assert db.run("SELECT *, a + 1 AS c, * FROM t") == {
        "columns": ["a", "b", "c", "a", "b"], "rows": [[1, 2, 2, 1, 2]]}
    db.expect("SELECT t.*, b FROM t", [[1, 2, 2]])


def test_values_module_directly():
    assert values.type_name(True) == "BOOLEAN" and values.type_name(1) == "INTEGER"
    assert values.value_key(True) != values.value_key(1)
    assert values.value_key(1) == values.value_key(1.0)
    assert values.div(-7, 2) == -3.5 and values.mod(-7, 2) == -1
    assert values.int_div(-7, 2) == -3 and type(values.div(4, 2)) is float
    with pytest.raises(SQLRuntimeError):
        values.div(1, 0)
    with pytest.raises(SQLTypeError):
        values.add(True, 1)
    assert values.like("100%", "100%") and not values.like("abc", "ABC")
    assert values.coerce_to_column(3, "REAL", "c") == 3.0
