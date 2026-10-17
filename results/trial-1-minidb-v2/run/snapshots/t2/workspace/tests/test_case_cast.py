"""Section 9: CASE, CAST and the new scalar functions."""
import pytest

from minidb.functions import SCALAR_FUNCTIONS, cast
from minidb.protocol import SQLRuntimeError, SQLTypeError


def check(db, sql, expected):
    got = db.one("SELECT " + sql)
    assert type(got) is type(expected) and got == expected, (sql, got)


@pytest.mark.parametrize("sql, expected", [
    ("CASE WHEN FALSE THEN 1 WHEN TRUE THEN 2 ELSE 3 END", 2),
    ("CASE WHEN NULL THEN 1 ELSE 'x' END", "x"),
    ("CASE WHEN FALSE THEN 1 END", None),
    ("CASE WHEN TRUE THEN 1 WHEN 1 / 0 = 1 THEN 2 END", 1),
    ("CASE WHEN FALSE THEN 1 / 0 ELSE 5 END", 5),
    ("CASE WHEN TRUE THEN 1 ELSE 1 / 0 END", 1),
    ("CASE 2 WHEN 1 THEN 'a' WHEN 2 THEN 'b' ELSE 'c' END", "b"),
    ("CASE 2 WHEN 2.0 THEN 'real' END", "real"),
    ("CASE NULL WHEN NULL THEN 1 ELSE 0 END", 0),
    ("CASE 1 WHEN NULL THEN 1 ELSE 0 END", 0),
    ("CASE 1 WHEN 1 THEN 1 WHEN 'a' THEN 2 END", 1),
    ("CASE 1 WHEN 1 THEN 1 WHEN 1 / 0 THEN 2 END", 1),
    ("CASE 'x' WHEN 'y' THEN 1 END", None),
])
def test_case_values(db, sql, expected):
    check(db, sql, expected)


@pytest.mark.parametrize("sql, error", [
    ("CASE WHEN 1 THEN 1 END", "TypeError"),
    ("CASE WHEN FALSE THEN 1 WHEN 'x' THEN 2 END", "TypeError"),
    ("CASE 1 WHEN 'a' THEN 1 END", "TypeError"),
    ("CASE 1 WHEN 2 THEN 1 WHEN 1 / 0 THEN 2 END", "RuntimeError"),
    ("CASE NULL WHEN 1 / 0 THEN 1 END", "RuntimeError"),
    ("CASE END", "SyntaxError"), ("CASE 1 END", "SyntaxError"),
    ("CASE WHEN TRUE THEN 1", "SyntaxError"), ("CASE WHEN TRUE 1 END", "SyntaxError"),
])
def test_case_errors(db, sql, error):
    assert db.error("SELECT " + sql) == error


def test_case_mixed_result_types_and_names(db):
    db.run("CREATE TABLE t (a INT)", "INSERT INTO t VALUES (1), (2)")
    db.expect("SELECT CASE WHEN a = 1 THEN 1 ELSE 'two' END FROM t", [[1], ["two"]])
    assert db.columns("SELECT CASE WHEN TRUE THEN 1 END, CASE 1 WHEN 1 THEN 1 END AS c") == [
        "case", "c"]


def test_case_with_aggregates_in_grouped_query(db):
    db.run("CREATE TABLE t (g TEXT, v INT)")
    db.run("INSERT INTO t VALUES ('a', 1), ('a', 2), ('b', 5)")
    db.expect("SELECT g, CASE WHEN SUM(v) > 2 THEN 'big' ELSE 'small' END FROM t GROUP BY g",
              [["a", "big"], ["b", "big"]])
    db.expect("SELECT SUM(CASE WHEN v > 1 THEN v ELSE 0 END) FROM t", [[7]])
    db.expect("SELECT CASE g WHEN 'a' THEN COUNT(*) END FROM t GROUP BY g", [[2], [None]])
    assert db.error("SELECT CASE WHEN v > 1 THEN 1 END FROM t GROUP BY g") == "SyntaxError"


@pytest.mark.parametrize("sql, expected", [
    ("CAST(NULL AS INT)", None), ("CAST(5 AS INTEGER)", 5), ("CAST(5 AS REAL)", 5.0),
    ("CAST(-12 AS TEXT)", "-12"), ("CAST(0 AS BOOLEAN)", False), ("CAST(-3 AS BOOL)", True),
    ("CAST(3.9 AS INT)", 3), ("CAST(-3.9 AS INT)", -3), ("CAST(2.5 AS TEXT)", "2.5"),
    ("CAST(3.0 AS TEXT)", "3.0"), ("CAST(0.1 AS TEXT)", "0.1"),
    ("CAST(10000000000000000.0 AS TEXT)", "1e+16"), ("CAST(1.5 AS REAL)", 1.5),
    ("CAST(' 42 ' AS INT)", 42), ("CAST('-7' AS INT)", -7), ("CAST('+7' AS INT)", 7),
    ("CAST('007' AS INT)", 7), ("CAST('2.5' AS REAL)", 2.5), ("CAST(' -3 ' AS REAL)", -3.0),
    ("CAST('true' AS BOOLEAN)", True), ("CAST(' FaLsE ' AS BOOL)", False),
    ("CAST('x' AS TEXT)", "x"), ("CAST(TRUE AS INT)", 1), ("CAST(FALSE AS INTEGER)", 0),
    ("CAST(TRUE AS TEXT)", "TRUE"), ("CAST(FALSE AS TEXT)", "FALSE"),
    ("CAST(TRUE AS BOOLEAN)", True), ("CAST('9223372036854775807' AS INT)", 9223372036854775807),
    ("CAST(9223372036854774784.0 AS INT)", 9223372036854774784),
])
def test_cast_values(db, sql, expected):
    check(db, sql, expected)


@pytest.mark.parametrize("sql, error", [
    ("CAST(1.5 AS BOOLEAN)", "TypeError"), ("CAST(TRUE AS REAL)", "TypeError"),
    ("CAST(9223372036854775807.0 AS INT)", "RuntimeError"),
    ("CAST('abc' AS INT)", "RuntimeError"), ("CAST('1.5' AS INT)", "RuntimeError"),
    ("CAST('' AS INT)", "RuntimeError"), ("CAST('1 2' AS INT)", "RuntimeError"),
    ("CAST('9223372036854775808' AS INT)", "RuntimeError"),
    ("CAST('\t5' AS INT)", "RuntimeError"), ("CAST('５' AS INT)", "RuntimeError"),
    ("CAST('1_000' AS INT)", "RuntimeError"), ("CAST('.5' AS REAL)", "RuntimeError"),
    ("CAST('5.' AS REAL)", "RuntimeError"), ("CAST('1e5' AS REAL)", "RuntimeError"),
    ("CAST('inf' AS REAL)", "RuntimeError"), ("CAST('nan' AS REAL)", "RuntimeError"),
    ("CAST('1" + "0" * 400 + "' AS REAL)", "RuntimeError"),
    ("CAST('yes' AS BOOLEAN)", "RuntimeError"), ("CAST('1' AS BOOLEAN)", "RuntimeError"),
    ("CAST(1 AS VARCHAR)", "SyntaxError"), ("CAST(1)", "SyntaxError"),
    ("CAST(1 AS)", "SyntaxError"), ("CAST(1, INT)", "SyntaxError"),
])
def test_cast_errors(db, sql, error):
    assert db.error("SELECT " + sql) == error


def test_cast_of_very_long_digit_strings(db):
    check(db, "CAST('" + "0" * 5000 + "12' AS INT)", 12)
    assert db.error("SELECT CAST('" + "1" * 5000 + "' AS INT)") == "RuntimeError"


def test_cast_output_name(db):
    assert db.columns("SELECT CAST(1 AS TEXT), CAST(1 AS REAL) AS r") == ["cast", "r"]


@pytest.mark.parametrize("sql, expected", [
    ("SUBSTR('hello', 2, 3)", "ell"), ("SUBSTR('hello', 0, 2)", "h"),
    ("SUBSTR('hello', 9)", ""), ("SUBSTR('hello', 2)", "ello"), ("SUBSTR('hello', -5, 7)", "h"),
    ("SUBSTR('hello', 1, 0)", ""), ("SUBSTR('hello', -1)", "hello"),
    ("SUBSTR('héllo', 2, 1)", "é"), ("SUBSTR(NULL, 1)", None), ("SUBSTR('x', NULL)", None),
    ("SUBSTR('x', 1, NULL)", None),
    ("ROUND(2.675, 2)", 2.68), ("ROUND(-0.5)", -1.0), ("ROUND(0.5)", 1.0), ("ROUND(1.4)", 1.0),
    ("ROUND(7)", 7), ("ROUND(7, 3)", 7), ("ROUND(1.005, 2)", 1.01), ("ROUND(-2.5)", -3.0),
    ("ROUND(2.5, 10)", 2.5), ("ROUND(123.456, 1)", 123.5), ("ROUND(NULL)", None),
    ("ROUND(1.5, NULL)", None), ("ROUND(0.125, 2)", 0.13),
    ("NULLIF(1, 1)", None), ("NULLIF(1, 2)", 1), ("NULLIF(1, 1.0)", None),
    ("NULLIF('a', NULL)", "a"), ("NULLIF(NULL, 1)", None),
    ("REPLACE('aaa', 'aa', 'b')", "ba"), ("REPLACE('abc', '', 'x')", "abc"),
    ("REPLACE('a.b.c', '.', '--')", "a--b--c"), ("REPLACE('abc', 'z', 'y')", "abc"),
    ("REPLACE(NULL, 'a', 'b')", None), ("REPLACE('a', 'a', NULL)", None),
    ("TRIM('  x y  ')", "x y"), ("TRIM('\tx ')", "\tx"), ("TRIM('')", ""), ("TRIM(NULL)", None),
])
def test_new_functions(db, sql, expected):
    check(db, sql, expected)


@pytest.mark.parametrize("sql, error", [
    ("SUBSTR('x')", "SyntaxError"), ("SUBSTR('x', 1, 2, 3)", "SyntaxError"),
    ("SUBSTR(1, 1)", "TypeError"), ("SUBSTR('x', 1.0)", "TypeError"),
    ("SUBSTR('x', TRUE)", "TypeError"), ("SUBSTR('x', 1, -1)", "RuntimeError"),
    ("ROUND()", "SyntaxError"), ("ROUND(1, 2, 3)", "SyntaxError"),
    ("ROUND('1')", "TypeError"), ("ROUND(1.5, 1.0)", "TypeError"), ("ROUND(TRUE)", "TypeError"),
    ("ROUND(1.5, -1)", "RuntimeError"), ("ROUND(5, -1)", "RuntimeError"),
    ("NULLIF(1)", "SyntaxError"), ("NULLIF(1, 'a')", "TypeError"),
    ("REPLACE('a', 'b')", "SyntaxError"), ("REPLACE('a', 1, 'b')", "TypeError"),
    ("TRIM()", "SyntaxError"), ("TRIM(1)", "TypeError"), ("TRIM('a', 'b')", "SyntaxError"),
])
def test_new_function_errors(db, sql, error):
    assert db.error("SELECT " + sql) == error


def test_function_output_names(db):
    assert db.columns("SELECT SUBSTR('a', 1), ROUND(1), NULLIF(1, 2), REPLACE('a', 'a', 'b'), "
                      "TRIM('a')") == ["substr", "round", "nullif", "replace", "trim"]


def test_functions_module_directly():
    assert cast(3, "TEXT") == "3" and cast("TRUE", "BOOLEAN") is True
    with pytest.raises(SQLRuntimeError):
        cast("x", "REAL")
    with pytest.raises(SQLTypeError):
        cast(True, "REAL")
    lo, hi, impl, _ = SCALAR_FUNCTIONS["substr"]
    assert (lo, hi) == (2, 3) and impl("hello", 2, 3) == "ell"
