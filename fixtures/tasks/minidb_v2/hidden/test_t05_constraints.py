"""Section 5 (stage 0): column types, DEFAULT, NOT NULL, UNIQUE, PRIMARY KEY."""
from _support import assert_error, assert_rows, run, run_ok, stage


@stage(0)
def test_primary_key_is_unique_and_not_null():
    res = run("""
        CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);
        INSERT INTO t VALUES (1, 'a'), (2, 'b');
        INSERT INTO t VALUES (1, 'dup');
        INSERT INTO t VALUES (NULL, 'null');
        INSERT INTO t (v) VALUES ('omitted');
        UPDATE t SET id = 2 WHERE id = 1;
        UPDATE t SET id = NULL WHERE id = 1;
        SELECT * FROM t;
    """)
    for r in res[2:7]:
        assert_error(r, "ConstraintError")
    assert_rows(res[7], [[1, "a"], [2, "b"]])


@stage(0)
def test_defaults():
    res = run_ok("""
        CREATE TABLE t (a INTEGER DEFAULT -2, b REAL DEFAULT 3, c TEXT DEFAULT 'it''s',
                        d BOOLEAN DEFAULT FALSE, e REAL DEFAULT -0.5, f INTEGER DEFAULT NULL, g TEXT);
        INSERT INTO t (g) VALUES ('x');
        INSERT INTO t (a, g) VALUES (NULL, 'y');
        SELECT * FROM t;
    """)
    assert_rows(res[-1], [[-2, 3.0, "it's", False, -0.5, None, "x"],
                          [None, 3.0, "it's", False, -0.5, None, "y"]])


@stage(0, retired=3)
def test_default_that_does_not_fit_is_a_type_error():
    res = run("""
        CREATE TABLE t (a INTEGER DEFAULT 'x');
        CREATE TABLE t (a INTEGER DEFAULT 1.5);
        CREATE TABLE t (a BOOLEAN DEFAULT 1);
        CREATE TABLE t (a TEXT DEFAULT 5);
        CREATE TABLE t (a REAL DEFAULT 5);
    """)
    for r in res[:4]:
        assert_error(r, "TypeError")
    assert res[4].ok


@stage(0, retired=3)
def test_storing_a_value_of_the_wrong_type_is_a_type_error():
    res = run("""
        CREATE TABLE t (i INTEGER, r REAL, s TEXT, b BOOLEAN);
        INSERT INTO t (i) VALUES ('5');
        INSERT INTO t (i) VALUES (2.0);
        INSERT INTO t (i) VALUES (TRUE);
        INSERT INTO t (r) VALUES ('1.5');
        INSERT INTO t (r) VALUES (FALSE);
        INSERT INTO t (s) VALUES (5);
        INSERT INTO t (b) VALUES (1);
        INSERT INTO t (b) VALUES ('true');
        SELECT COUNT(*) FROM t;
    """)
    for r in res[1:9]:
        assert_error(r, "TypeError")
    assert_rows(res[9], [[0]])


@stage(0)
def test_real_column_stores_integers_as_real_and_types_are_kept():
    res = run_ok("""
        CREATE TABLE t (i INTEGER, r REAL, s TEXT, b BOOLEAN);
        INSERT INTO t VALUES (2, 2, '2', TRUE), (-3, -3.5, '', FALSE);
        UPDATE t SET r = i * 10 WHERE i = 2;
        SELECT * FROM t;
        SELECT TYPEOF(r) FROM t;
    """)
    assert_rows(res[-2], [[2, 20.0, "2", True], [-3, -3.5, "", False]])
    assert_rows(res[-1], [["REAL"], ["REAL"]])


@stage(0)
def test_not_null_including_omitted_columns_and_null_defaults():
    res = run("""
        CREATE TABLE t (a INTEGER NOT NULL, b TEXT NOT NULL DEFAULT 'd', c INTEGER NOT NULL DEFAULT NULL);
        INSERT INTO t (a, c) VALUES (1, 1);
        INSERT INTO t (c) VALUES (2);
        INSERT INTO t (a, b, c) VALUES (2, NULL, 2);
        INSERT INTO t (a, b) VALUES (3, 'x');
        UPDATE t SET b = NULL;
        SELECT * FROM t;
    """)
    assert res[1].rowcount == 1
    for r in res[2:6]:
        assert_error(r, "ConstraintError")
    assert_rows(res[6], [[1, "d", 1]])


@stage(0)
def test_unique_allows_any_number_of_nulls():
    res = run("""
        CREATE TABLE t (a INTEGER UNIQUE, b TEXT);
        INSERT INTO t VALUES (NULL, 'x'), (NULL, 'y'), (1, 'z');
        INSERT INTO t VALUES (NULL, 'w');
        INSERT INTO t VALUES (1, 'dup');
        SELECT b FROM t;
    """)
    assert res[1].rowcount == 3 and res[2].rowcount == 1
    assert_error(res[3], "ConstraintError")
    assert_rows(res[4], [["x"], ["y"], ["z"], ["w"]])


@stage(0)
def test_unique_uses_numeric_equality():
    res = run("""
        CREATE TABLE t (r REAL UNIQUE);
        INSERT INTO t VALUES (1);
        INSERT INTO t VALUES (1.0);
        INSERT INTO t VALUES (1.5), (2);
        SELECT * FROM t;
    """)
    assert_error(res[2], "ConstraintError")
    assert_rows(res[4], [[1.0], [1.5], [2.0]])


@stage(0)
def test_constraints_are_checked_at_end_of_statement():
    res = run("""
        CREATE TABLE t (id INTEGER PRIMARY KEY, code TEXT UNIQUE);
        INSERT INTO t VALUES (1, 'a'), (2, 'b'), (3, 'c');
        UPDATE t SET id = id + 1;
        SELECT id FROM t;
        UPDATE t SET code = 'x' WHERE id >= 3;
        INSERT INTO t VALUES (10, 'k'), (11, 'k');
        INSERT INTO t VALUES (12, 'm'), (12, 'n');
        UPDATE t SET code = CASE_X WHERE id = 2;
        SELECT * FROM t;
    """)
    assert res[2].rowcount == 3
    assert_rows(res[3], [[2], [3], [4]])
    assert_error(res[4], "ConstraintError")
    assert_error(res[5], "ConstraintError")
    assert_error(res[6], "ConstraintError")
    assert_error(res[7], "NameError")
    assert_rows(res[8], [[2, "a"], [3, "b"], [4, "c"]])


@stage(0)
def test_column_definition_syntax():
    res = run("""
        CREATE TABLE a (x INTEGER NOT NULL NOT NULL);
        CREATE TABLE a (x INTEGER PRIMARY KEY, y INTEGER PRIMARY KEY);
        CREATE TABLE a (x INTEGER DEFAULT 1 DEFAULT 2);
        CREATE TABLE a (x INTEGER DEFAULT 1 + 1);
        CREATE TABLE a (x INTEGER DEFAULT (1));
        CREATE TABLE a (x INTEGER UNIQUE UNIQUE);
        CREATE TABLE a (x INTEGER PRIMARY);
        CREATE TABLE a (x INTEGER DEFAULT 7 UNIQUE NOT NULL, y TEXT NOT NULL DEFAULT 'q' PRIMARY KEY);
        INSERT INTO a (x) VALUES (1);
        SELECT * FROM a;
    """)
    for r in res[:7]:
        assert_error(r, "SyntaxError")
    assert res[7].ok and res[8].rowcount == 1
    assert_rows(res[9], [[1, "q"]])


@stage(0)
def test_failed_insert_leaves_unique_state_untouched():
    res = run("""
        CREATE TABLE t (id INTEGER PRIMARY KEY, v INTEGER UNIQUE);
        INSERT INTO t VALUES (1, 10);
        INSERT INTO t VALUES (2, 20), (3, 10);
        INSERT INTO t VALUES (2, 20);
        INSERT INTO t VALUES (3, 30), (4, 40), (5, 50 / 0);
        INSERT INTO t VALUES (3, 30);
        SELECT * FROM t;
    """)
    assert_error(res[2], "ConstraintError")
    assert res[3].rowcount == 1
    assert_error(res[4], "RuntimeError")
    assert res[5].rowcount == 1
    assert_rows(res[6], [[1, 10], [2, 20], [3, 30]])
