"""Tier 1: lexer/parser, CREATE/DROP TABLE, INSERT, SELECT *."""
from _support import assert_error, assert_rows, run, run_ok


def test_create_insert_select_star_all_types():
    res = run_ok("""
        CREATE TABLE t (i INTEGER, r REAL, s TEXT, b BOOLEAN);
        INSERT INTO t VALUES (1, 2.5, 'x', TRUE), (2, 0.25, 'y', FALSE);
        INSERT INTO t VALUES (3, NULL, NULL, NULL);
        SELECT * FROM t;
    """)
    assert res[0].raw == {"ok": True}
    assert res[1].raw == {"ok": True, "rowcount": 2}
    assert res[2].raw == {"ok": True, "rowcount": 1}
    assert_rows(res[3], [[1, 2.5, "x", True], [2, 0.25, "y", False], [3, None, None, None]],
                columns=["i", "r", "s", "b"])


def test_empty_table_and_type_aliases():
    res = run_ok("CREATE TABLE e (a INT, b BOOL, c REAL, d TEXT); SELECT * FROM e;")
    assert res[1].raw == {"ok": True, "columns": ["a", "b", "c", "d"], "rows": []}


def test_column_list_fills_missing_columns_with_null():
    res = run_ok("""
        CREATE TABLE t (a INTEGER, b TEXT, c INTEGER);
        INSERT INTO t (c, b) VALUES (3, 'three'), (4, 'four');
        INSERT INTO t (a) VALUES (1);
        SELECT * FROM t;
    """)
    assert_rows(res[-1], [[None, "three", 3], [None, "four", 4], [1, None, None]])


def test_names_and_keywords_are_case_insensitive_and_reported_lowercase():
    res = run_ok("""
        create table Users (Name TEXT, AGE int);
        InSeRt INTO USERS (name, Age) values ('Ann', 30);
        SELECT * FROM users;
        select * from USERS;
    """)
    assert_rows(res[2], [["Ann", 30]], columns=["name", "age"])
    assert_rows(res[3], [["Ann", 30]], columns=["name", "age"])


def test_string_literals_quotes_semicolons_and_unicode():
    res = run_ok("""
        CREATE TABLE s (v TEXT);
        INSERT INTO s VALUES ('it''s'), ('a;b'), ('--not a comment'), (''), ('héllo ✓');
        SELECT * FROM s; -- trailing comment
    """)
    assert_rows(res[-1], [["it's"], ["a;b"], ["--not a comment"], [""], ["héllo ✓"]])


def test_negative_numbers_and_insertion_order():
    res = run_ok("""
        CREATE TABLE n (a INTEGER, b REAL);
        INSERT INTO n VALUES (3, -1.5);
        INSERT INTO n VALUES (-7, 0.0), (1, 10.75);
        SELECT * FROM n;
    """)
    assert_rows(res[-1], [[3, -1.5], [-7, 0.0], [1, 10.75]])


def test_errors_and_processing_continues():
    res = run("""
        SELECT * FROM missing;
        SELEC * FROM t;
        CREATE TABLE t (a INTEGER, b TEXT);
        CREATE TABLE t (x INTEGER);
        CREATE TABLE u (a INTEGER, a TEXT);
        CREATE TABLE w (a VARCHAR);
        CREATE TABLE select (a INTEGER);
        INSERT INTO t VALUES (1);
        INSERT INTO t (a, nope) VALUES (1, 'x');
        INSERT INTO t (a, a) VALUES (1, 2);
        INSERT INTO nowhere VALUES (1);
        DROP TABLE nowhere;
        INSERT INTO t VALUES (1, 'ok');
        SELECT * FROM t;
    """)
    expected = ["NameError", "SyntaxError", None, "NameError", "NameError", "SyntaxError",
                "SyntaxError", "SyntaxError", "NameError", "SyntaxError", "NameError", "NameError",
                None]
    for r, want in zip(res, expected):
        if want is None:
            assert r.ok, r
        else:
            assert_error(r, want)
    assert_rows(res[-1], [[1, "ok"]], columns=["a", "b"])
    assert res[0].raw["error"]["message"]


def test_failed_multi_row_insert_inserts_nothing():
    res = run("""
        CREATE TABLE t (a INTEGER, b TEXT);
        INSERT INTO t VALUES (1, 'a'), (2), (3, 'c');
        INSERT INTO t VALUES (9, 'z');
        SELECT * FROM t;
    """)
    assert_error(res[1], "SyntaxError")
    assert_rows(res[-1], [[9, "z"]])


def test_drop_table_and_recreate():
    res = run("""
        CREATE TABLE t (a INTEGER);
        INSERT INTO t VALUES (1);
        DROP TABLE t;
        SELECT * FROM t;
        CREATE TABLE t (b TEXT, c BOOLEAN);
        SELECT * FROM t;
    """)
    assert res[2].raw == {"ok": True}
    assert_error(res[3], "NameError")
    assert res[5].raw == {"ok": True, "columns": ["b", "c"], "rows": []}
