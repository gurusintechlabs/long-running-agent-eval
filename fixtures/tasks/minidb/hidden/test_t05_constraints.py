"""Tier 5: storage types, PRIMARY KEY, NOT NULL, UNIQUE, DEFAULT, statement-level checks."""
from _support import assert_error, assert_rows, run, run_ok


def test_integer_values_are_stored_as_real_in_real_columns():
    res = run_ok("""
        CREATE TABLE m (i INTEGER, r REAL, t TEXT, b BOOLEAN);
        INSERT INTO m VALUES (1, 3, 'x', TRUE), (2, -2, 'y', NULL);
        UPDATE m SET r = r + 4 WHERE i = 2;
        INSERT INTO m (i, r) VALUES (3, 10 / 4);
        SELECT * FROM m;
    """)
    assert_rows(res[-1], [[1, 3.0, "x", True], [2, 2.0, "y", None], [3, 2.0, None, None]])


def test_type_errors_on_store_change_nothing():
    res = run("""
        CREATE TABLE m (i INTEGER, r REAL, t TEXT, b BOOLEAN);
        INSERT INTO m VALUES (1, 1.5, 'a', FALSE);
        INSERT INTO m VALUES (2, 1.0, 'b', TRUE), ('5', 1.0, 'c', TRUE);
        INSERT INTO m (i) VALUES (1.5);
        INSERT INTO m (t) VALUES (1);
        INSERT INTO m (b) VALUES (1);
        INSERT INTO m (i) VALUES (TRUE);
        INSERT INTO m (r) VALUES ('1.5');
        UPDATE m SET i = 'x';
        UPDATE m SET r = r * 2, b = 0;
        SELECT * FROM m;
    """)
    for r in res[2:10]:
        assert_error(r, "TypeError")
    assert_rows(res[-1], [[1, 1.5, "a", False]])


def test_primary_key_rejects_duplicates_and_null():
    res = run("""
        CREATE TABLE k (id INTEGER PRIMARY KEY, v TEXT);
        INSERT INTO k VALUES (1, 'a'), (2, 'b');
        INSERT INTO k VALUES (3, 'c'), (2, 'dup');
        INSERT INTO k VALUES (NULL, 'n');
        INSERT INTO k (v) VALUES ('no id');
        UPDATE k SET id = NULL WHERE id = 1;
        UPDATE k SET id = 1 WHERE id = 2;
        INSERT INTO k VALUES (3, 'c');
        SELECT * FROM k;
    """)
    for r in res[2:7]:
        assert_error(r, "ConstraintError")
    assert res[7].rowcount == 1
    assert_rows(res[-1], [[1, "a"], [2, "b"], [3, "c"]])


def test_defaults_and_not_null():
    res = run("""
        CREATE TABLE d (id INT PRIMARY KEY, name TEXT NOT NULL DEFAULT 'anon', qty INTEGER DEFAULT 1,
                        price REAL DEFAULT 2, flag BOOLEAN DEFAULT FALSE, delta INTEGER DEFAULT -1,
                        note TEXT, tag TEXT DEFAULT NULL);
        INSERT INTO d (id) VALUES (1);
        INSERT INTO d (id, name, note) VALUES (2, 'bo', 'hi');
        INSERT INTO d (id, name) VALUES (3, NULL);
        CREATE TABLE z (a INTEGER DEFAULT 5 NOT NULL, b INTEGER NOT NULL);
        INSERT INTO z (b) VALUES (1);
        INSERT INTO z (a) VALUES (1);
        UPDATE d SET name = NULL;
        SELECT * FROM d;
        SELECT * FROM z;
    """)
    assert [r.ok for r in res[:3]] == [True, True, True]
    assert_error(res[3], "ConstraintError")
    assert res[4].ok and res[5].ok
    assert_error(res[6], "ConstraintError")
    assert_error(res[7], "ConstraintError")
    assert_rows(res[8], [[1, "anon", 1, 2.0, False, -1, None, None],
                         [2, "bo", 1, 2.0, False, -1, "hi", None]],
                columns=["id", "name", "qty", "price", "flag", "delta", "note", "tag"])
    assert_rows(res[9], [[5, 1]])


def test_bad_default_and_bad_definitions_create_nothing():
    res = run("""
        CREATE TABLE bad (a INTEGER DEFAULT 'x');
        SELECT * FROM bad;
        CREATE TABLE bad2 (a BOOLEAN DEFAULT 1);
        CREATE TABLE two (a INTEGER PRIMARY KEY, b INTEGER PRIMARY KEY);
        SELECT * FROM two;
        CREATE TABLE ok (a REAL DEFAULT -2, b TEXT UNIQUE NOT NULL);
        SELECT * FROM ok;
    """)
    assert_error(res[0], "TypeError")
    assert_error(res[1], "NameError")
    assert_error(res[2], "TypeError")
    assert_error(res[3], "SyntaxError")
    assert_error(res[4], "NameError")
    assert res[5].ok
    assert res[6].raw == {"ok": True, "columns": ["a", "b"], "rows": []}


def test_unique_allows_many_nulls_and_rejects_in_statement_collisions():
    res = run("""
        CREATE TABLE u (id INTEGER, email TEXT UNIQUE, x REAL UNIQUE);
        INSERT INTO u VALUES (1, NULL, NULL), (2, NULL, NULL), (3, 'a@x', 1);
        INSERT INTO u VALUES (4, 'b@x', 2.0), (5, 'b@x', 3.0);
        INSERT INTO u VALUES (6, 'c@x', 1.0);
        INSERT INTO u VALUES (7, 'a@x', 4.0);
        INSERT INTO u VALUES (8, 'A@x', 5.0);
        UPDATE u SET email = 'z@x' WHERE email IS NULL;
        SELECT id, email, x FROM u;
    """)
    assert res[1].rowcount == 3
    for r in res[2:5]:
        assert_error(r, "ConstraintError")
    assert res[5].rowcount == 1
    assert_error(res[6], "ConstraintError")
    assert_rows(res[-1], [[1, None, None], [2, None, None], [3, "a@x", 1.0], [8, "A@x", 5.0]])


def test_constraints_are_checked_at_end_of_statement():
    res = run("""
        CREATE TABLE k (id INTEGER PRIMARY KEY, v TEXT);
        INSERT INTO k VALUES (1, 'a'), (2, 'b'), (3, 'c');
        UPDATE k SET id = id + 1;
        UPDATE k SET id = 5 WHERE id >= 3;
        UPDATE k SET id = 5 - id;
        SELECT * FROM k;
    """)
    assert res[2].rowcount == 3
    assert_error(res[3], "ConstraintError")
    assert res[4].rowcount == 3
    assert_rows(res[-1], [[3, "a"], [2, "b"], [1, "c"]])
