"""Section 1 (stage 0): lexer/parser, literals, CREATE/DROP TABLE, INSERT ... VALUES, SELECT *."""
from _support import assert_error, assert_rows, run, run_ok, stage


@stage(0)
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


@stage(0)
def test_empty_table_and_type_aliases():
    res = run_ok("CREATE TABLE e (a INT, b BOOL, c REAL, d TEXT); SELECT * FROM e;")
    assert res[1].raw == {"ok": True, "columns": ["a", "b", "c", "d"], "rows": []}


@stage(0)
def test_column_list_fills_missing_columns_with_null():
    res = run_ok("""
        CREATE TABLE t (a INTEGER, b TEXT, c INTEGER);
        INSERT INTO t (c, b) VALUES (3, 'three'), (4, 'four');
        INSERT INTO t (a) VALUES (1);
        SELECT * FROM t;
    """)
    assert_rows(res[-1], [[None, "three", 3], [None, "four", 4], [1, None, None]])


@stage(0, retired=6)
def test_names_are_case_insensitive_and_reported_lowercase():
    res = run_ok("""
        create table Users (Name TEXT, AGE int);
        InSeRt INTO USERS (name, Age) values ('Ann', 30);
        SELECT * FROM users;
        select NAME, users.age FROM USERS;
    """)
    assert_rows(res[2], [["Ann", 30]], columns=["name", "age"])
    assert_rows(res[3], [["Ann", 30]], columns=["name", "age"])


@stage(0)
def test_string_literals_quotes_semicolons_and_unicode():
    res = run_ok("""
        CREATE TABLE s (v TEXT);
        INSERT INTO s VALUES ('it''s'), ('a;b'), ('--not a comment'), (''), ('héllo ✓');
        SELECT * FROM s; -- trailing comment
    """)
    assert_rows(res[-1], [["it's"], ["a;b"], ["--not a comment"], [""], ["héllo ✓"]])


@stage(0)
def test_negative_numbers_and_insertion_order():
    res = run_ok("""
        CREATE TABLE n (a INTEGER, b REAL);
        INSERT INTO n VALUES (3, -1.5);
        INSERT INTO n VALUES (-7, 0.0), (1, 10.75);
        SELECT * FROM n;
    """)
    assert_rows(res[-1], [[3, -1.5], [-7, 0.0], [1, 10.75]])


@stage(0)
def test_errors_and_processing_continues():
    res = run("""
        SELECT * FROM missing;
        SELEC * FROM t;
        CREATE TABLE t (a INTEGER, b TEXT);
        CREATE TABLE t (x INTEGER);
        CREATE TABLE u (a INTEGER, a TEXT);
        CREATE TABLE w (a VARCHAR);
        CREATE TABLE select (a INTEGER);
        CREATE TABLE v (order INTEGER);
        CREATE TABLE z ();
        INSERT INTO t VALUES (1);
        INSERT INTO t (a, nope) VALUES (1, 'x');
        INSERT INTO t (a, a) VALUES (1, 2);
        INSERT INTO nowhere VALUES (1);
        DROP TABLE nowhere;
        INSERT INTO t VALUES (1, 'ok');
        SELECT * FROM t;
    """)
    for i, t in enumerate(["NameError", "SyntaxError", None, "NameError", "NameError",
                           "SyntaxError", "SyntaxError", "SyntaxError", "SyntaxError",
                           "SyntaxError", "NameError", "SyntaxError", "NameError", "NameError"]):
        if t is None:
            assert res[i].ok, res[i]
        else:
            assert_error(res[i], t)
    assert res[14].rowcount == 1
    assert_rows(res[15], [[1, "ok"]])
    for r in res:
        if not r.ok:
            assert r.raw["error"]["message"], r


@stage(0)
def test_integer_literal_range():
    res = run("""
        SELECT 9223372036854775807;
        SELECT 9223372036854775808;
        SELECT -9223372036854775808;
        SELECT -9223372036854775807 - 1;
    """)
    assert_rows(res[0], [[9223372036854775807]])
    assert_error(res[1], "SyntaxError")
    assert_error(res[2], "SyntaxError")
    assert_rows(res[3], [[-9223372036854775808]])


@stage(0)
def test_number_literal_shapes():
    huge = "1" + "0" * 400 + ".0"
    res = run(f"""
        SELECT 0.5, 1.250, 10.0;
        SELECT 1e5;
        SELECT .5;
        SELECT 5.;
        SELECT 12abc;
        SELECT {huge};
        SELECT 1{"0" * 300}.0;
    """)
    assert_rows(res[0], [[0.5, 1.25, 10.0]])
    for r in res[1:6]:
        assert_error(r, "SyntaxError")
    assert res[6].ok and res[6].rows[0][0] == 1e300 and isinstance(res[6].rows[0][0], float)


@stage(0)
def test_insert_values_rules():
    res = run("""
        CREATE TABLE t (a INTEGER, b TEXT);
        INSERT INTO t VALUES (DEFAULT, 'x');
        INSERT INTO t VALUES (a, 'x');
        INSERT INTO t VALUES (COUNT(*), 'x');
        INSERT INTO t VALUES (1, 'x', 3);
        INSERT INTO t VALUES (1 + 2 * 3, 'a' || 'b'), (-(4), NULL);
        SELECT * FROM t;
    """)
    assert_error(res[1], "SyntaxError")
    assert_error(res[2], "NameError")
    assert_error(res[3], "SyntaxError")
    assert_error(res[4], "SyntaxError")
    assert res[5].rowcount == 2
    assert_rows(res[6], [[7, "ab"], [-4, None]])


@stage(0)
def test_insert_error_order_and_atomicity():
    res = run("""
        CREATE TABLE t (a INTEGER PRIMARY KEY, b TEXT NOT NULL);
        INSERT INTO t VALUES (1, NULL), (1 / 0, 'x');
        INSERT INTO t VALUES (1, 'a'), (1, 'b'), (2, 'c' || 5);
        INSERT INTO t VALUES (1, 'a'), (2, 'b'), (3, 'x' || (1 / 0));
        INSERT INTO t VALUES (1 / 0, 'x' || 1);
        INSERT INTO t VALUES ('x' || 1, 1 / 0);
        INSERT INTO t VALUES (1, 'a'), (2, 'b'), (1, 'c');
        SELECT COUNT(*) FROM t;
    """)
    assert_error(res[1], "ConstraintError")
    assert_error(res[2], "TypeError")
    assert_error(res[3], "RuntimeError")
    assert_error(res[4], "RuntimeError")
    assert_error(res[5], "TypeError")
    assert_error(res[6], "ConstraintError")
    assert_rows(res[7], [[0]])


@stage(0, retired=3)
def test_insert_type_check_precedes_not_null_check():
    res = run("""
        CREATE TABLE t (a INTEGER, b TEXT NOT NULL);
        INSERT INTO t (a, b) VALUES ('str', NULL);
        INSERT INTO t VALUES (1, 'ok'), (2.5, 'x'), (3, NULL);
        INSERT INTO t (b, a) VALUES (NULL, 'str');
        SELECT * FROM t;
    """)
    assert_error(res[1], "TypeError")
    assert_error(res[2], "TypeError")
    assert_error(res[3], "TypeError")
    assert_rows(res[4], [])


@stage(0)
def test_drop_table_and_recreate():
    res = run("""
        CREATE TABLE t (a INTEGER);
        INSERT INTO t VALUES (1), (2);
        DROP TABLE t;
        SELECT * FROM t;
        CREATE TABLE t (b TEXT);
        INSERT INTO t VALUES ('x');
        SELECT * FROM t;
        DROP TABLE T;
        DROP TABLE t;
    """)
    assert res[2].raw == {"ok": True}
    assert_error(res[3], "NameError")
    assert_rows(res[6], [["x"]], columns=["b"])
    assert res[7].ok
    assert_error(res[8], "NameError")
