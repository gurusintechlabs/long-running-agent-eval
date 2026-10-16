"""Tier 4: UPDATE and DELETE."""
from _support import PEOPLE, assert_error, assert_rows, run, run_ok


def test_update_rowcount_counts_matched_rows():
    res = run_ok(PEOPLE + """
        UPDATE people SET city = 'Rome' WHERE city = 'Rome';
        UPDATE people SET age = age + 1 WHERE age < 30;
        UPDATE people SET name = 'x' WHERE id > 100;
        SELECT id, age, city FROM people ORDER BY id;
    """)
    assert res[-4].raw == {"ok": True, "rowcount": 2}
    assert res[-3].raw == {"ok": True, "rowcount": 2}
    assert res[-2].raw == {"ok": True, "rowcount": 0}
    assert_rows(res[-1], [[1, 34, "Oslo"], [2, 28, "Rome"], [3, None, "Oslo"], [4, 45, None],
                          [5, 28, "Lima"], [6, 31, "Rome"]])


def test_update_all_rows_with_expressions():
    res = run_ok(PEOPLE + """
        UPDATE people SET score = COALESCE(score, 0.0) * 2, name = UPPER(name);
        SELECT name, score FROM people;
    """)
    assert res[-2].rowcount == 6
    assert_rows(res[-1], [["ANN", 15.0], ["BOB", 0.0], ["CID", 18.0], ["DEE", 12.5], ["EVE", 16.0],
                          ["FAY", 15.0]])


def test_update_evaluates_against_the_old_row():
    res = run_ok("""
        CREATE TABLE t (a INTEGER, b INTEGER);
        INSERT INTO t VALUES (1, 2), (3, 4);
        UPDATE t SET a = b, b = a;
        UPDATE t SET a = a * 10, b = a + 1 WHERE a > 3;
        SELECT * FROM t;
    """)
    assert_rows(res[-1], [[2, 1], [40, 5]])


def test_update_keeps_row_order_and_new_rows_go_last():
    res = run_ok(PEOPLE + """
        UPDATE people SET id = id * 10 WHERE id IN (2, 5);
        DELETE FROM people WHERE id = 3;
        INSERT INTO people (id, name) VALUES (3, 'New');
        SELECT id, name FROM people;
    """)
    assert_rows(res[-1], [[1, "Ann"], [20, "bob"], [4, "Dee"], [50, "Eve"], [6, "Fay"], [3, "New"]])


def test_delete_with_three_valued_where_and_delete_all():
    res = run_ok(PEOPLE + """
        DELETE FROM people WHERE age < 30 OR city = 'Oslo';
        SELECT id FROM people;
        DELETE FROM people;
        SELECT * FROM people;
        DELETE FROM people;
    """)
    assert res[-5].raw == {"ok": True, "rowcount": 4}
    assert_rows(res[-4], [[4], [6]])
    assert res[-3].rowcount == 2
    assert_rows(res[-2], [])
    assert res[-1].rowcount == 0


def test_failing_update_changes_nothing():
    res = run(PEOPLE + """
        UPDATE people SET age = 100 / (age - 31) WHERE age IS NOT NULL;
        SELECT id, age FROM people;
        DELETE FROM people WHERE 10 / (age - 27) > 0;
        SELECT id FROM people;
    """)
    assert_error(res[-4], "RuntimeError")
    assert_rows(res[-3], [[1, 34], [2, 27], [3, None], [4, 45], [5, 27], [6, 31]])
    assert_error(res[-2], "RuntimeError")
    assert_rows(res[-1], [[1], [2], [3], [4], [5], [6]])


def test_update_and_delete_errors():
    res = run("""
        CREATE TABLE e (a INTEGER, b TEXT);
        UPDATE e SET nope = 1;
        UPDATE e SET a = 1, a = 2;
        UPDATE missing SET a = 1;
        DELETE FROM missing;
        DELETE FROM e WHERE zzz = 1;
        UPDATE e SET a = 1 WHERE zzz = 1;
        UPDATE e SET a = 1;
        INSERT INTO e VALUES (1, 'x');
        UPDATE e SET a = 'x' || 1;
        SELECT * FROM e;
    """)
    for r, w in zip(res[1:7], ["NameError", "SyntaxError", "NameError", "NameError", "NameError",
                               "NameError"]):
        assert_error(r, w)
    assert res[7].raw == {"ok": True, "rowcount": 0}
    assert_error(res[9], "TypeError")
    assert_rows(res[10], [[1, "x"]])
