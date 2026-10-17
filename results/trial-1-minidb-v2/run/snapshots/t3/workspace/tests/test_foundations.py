"""Section 1: CREATE/DROP TABLE, INSERT, SELECT *."""
import pytest

from minidb.catalog import Database, Table
from minidb.protocol import SQLNameError


def test_create_insert_select(db):
    assert db.run("CREATE TABLE t (a INTEGER, b TEXT, c REAL, d BOOLEAN)") == {}
    assert db.run("INSERT INTO t VALUES (1, 'x', 2.5, TRUE), (2, 'y', 3, FALSE)") == {
        "rowcount": 2}
    res = db.run("SELECT * FROM t")
    assert res["columns"] == ["a", "b", "c", "d"]
    db.expect("SELECT * FROM t", [[1, "x", 2.5, True], [2, "y", 3.0, False]])


def test_names_are_case_insensitive_and_lower_case(db):
    db.run("CREATE TABLE Users (Name TEXT, AGE int)")
    db.run("INSERT INTO USERS (NAME) VALUES ('bob')")
    assert db.columns("SELECT * FROM users") == ["name", "age"]
    db.expect("select * from UsErS", [["bob", None]])


def test_empty_table_returns_columns(db):
    db.run("CREATE TABLE t (a INT)")
    assert db.run("SELECT * FROM t") == {"columns": ["a"], "rows": []}


def test_type_aliases(db):
    db.run("CREATE TABLE t (a INT, b BOOL)")
    db.run("INSERT INTO t VALUES (1, TRUE)")
    db.expect("SELECT * FROM t", [[1, True]])


def test_literals(db):
    db.expect("SELECT 42, 3.25, 'it''s', TRUE, FALSE, NULL, -5",
              [[42, 3.25, "it's", True, False, None, -5]])
    db.expect("SELECT 9223372036854775807, -9223372036854775807 - 1",
              [[9223372036854775807, -9223372036854775808]])


@pytest.mark.parametrize("sql", ["SELECT .5", "SELECT 5.", "SELECT 1e5", "SELECT 12abc",
                                 "SELECT -9223372036854775808", "SELECT 9223372036854775808",
                                 "SELECT 1" + "0" * 400 + ".0"])
def test_bad_literals(db, sql):
    assert db.error(sql) == "SyntaxError"


def test_create_errors(db):
    db.run("CREATE TABLE t (a INT)")
    assert db.error("CREATE TABLE t (b INT)") == "NameError"
    assert db.error("CREATE TABLE T (b INT)") == "NameError"
    assert db.error("CREATE TABLE u (a INT, A TEXT)") == "NameError"
    assert db.error("CREATE TABLE u (a VARCHAR)") == "SyntaxError"
    assert db.error("CREATE TABLE u ()") == "SyntaxError"
    assert db.error("CREATE TABLE from (a INT)") == "SyntaxError"
    assert db.error("CREATE TABLE u (select INT)") == "SyntaxError"
    db.run("CREATE TABLE u (text TEXT, count INT)")  # type/function names are not reserved


def test_drop_table(db):
    db.run("CREATE TABLE t (a INT)", "INSERT INTO t VALUES (1)")
    assert db.run("DROP TABLE t") == {}
    assert db.error("SELECT * FROM t") == "NameError"
    assert db.error("DROP TABLE t") == "NameError"
    db.run("CREATE TABLE t (b TEXT)")
    db.expect("SELECT * FROM t", [])


def test_insert_with_column_list_uses_defaults_and_null(db):
    db.run("CREATE TABLE t (a INT, b TEXT DEFAULT 'd', c REAL)")
    db.run("INSERT INTO t (c, a) VALUES (1, 2)")
    db.expect("SELECT * FROM t", [[2, "d", 1.0]])


def test_insert_errors(db):
    db.run("CREATE TABLE t (a INT, b TEXT)")
    assert db.error("INSERT INTO nope VALUES (1)") == "NameError"
    assert db.error("INSERT INTO t VALUES (1)") == "SyntaxError"
    assert db.error("INSERT INTO t VALUES (1, 'a', 2)") == "SyntaxError"
    assert db.error("INSERT INTO t (a) VALUES (1, 2)") == "SyntaxError"
    assert db.error("INSERT INTO t VALUES (1, 'a'), (2)") == "SyntaxError"
    assert db.error("INSERT INTO t (zz) VALUES (1)") == "NameError"
    assert db.error("INSERT INTO t (a, a) VALUES (1, 2)") == "SyntaxError"
    assert db.error("INSERT INTO t VALUES (a, 'x')") == "NameError"
    assert db.error("INSERT INTO t VALUES (COUNT(*), 'x')") == "SyntaxError"
    assert db.error("INSERT INTO t VALUES (DEFAULT, 'x')") == "SyntaxError"
    db.expect("SELECT * FROM t", [])


def test_insert_values_are_expressions(db):
    db.run("CREATE TABLE t (a INT, b TEXT)")
    db.run("INSERT INTO t VALUES (1 + 2 * 3, 'a' || 'b')")
    db.expect("SELECT * FROM t", [[7, "ab"]])


def test_insert_is_atomic(db):
    db.run("CREATE TABLE t (a INT)")
    assert db.error("INSERT INTO t VALUES (1), (2), (1 / 0)") == "RuntimeError"
    assert db.error("INSERT INTO t VALUES (1), ('x')") == "ConstraintError"
    db.expect("SELECT * FROM t", [])


def test_insert_error_order_is_row_by_row(db):
    db.run("CREATE TABLE t (a INT NOT NULL, b INT)")
    # Row 1 fails its NOT NULL check before row 2 is evaluated.
    assert db.error("INSERT INTO t VALUES (NULL, 1), (1 / 0, 1)") == "ConstraintError"
    # Values are evaluated before they are type-checked.
    assert db.error("INSERT INTO t VALUES ('x', 1 / 0)") == "RuntimeError"
    # Type checks come before NOT NULL checks.
    assert db.error_message("INSERT INTO t VALUES (NULL, 'x')").startswith(
        "ConstraintError: type constraint")


def test_rows_keep_insertion_order(db):
    db.run("CREATE TABLE t (a INT)")
    for x in (3, 1, 2):
        db.run(f"INSERT INTO t VALUES ({x})")
    db.expect("SELECT * FROM t", [[3], [1], [2]])


def test_catalog_directly():
    database = Database()
    assert database.find_table("t") is None
    database.add_table(Table("t", []))
    assert database.get_table("t").name == "t"
    with pytest.raises(SQLNameError):
        database.add_table(Table("t", []))
