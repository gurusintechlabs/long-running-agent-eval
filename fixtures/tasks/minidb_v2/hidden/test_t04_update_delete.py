"""Section 4 (stage 0): UPDATE and DELETE, row order, atomicity, error order."""
from _support import PEOPLE, assert_error, assert_rows, run, run_ok, stage


@stage(0)
def test_update_with_where_and_rowcount():
    res = run_ok(PEOPLE + """
        UPDATE people SET age = age + 1, city = 'X' WHERE age < 30;
        SELECT id, age, city FROM people;
        UPDATE people SET score = score WHERE id > 100;
    """)
    assert res[-3].rowcount == 2
    assert_rows(res[-2], [[1, 34, "Oslo"], [2, 28, "X"], [3, None, "Oslo"], [4, 45, None],
                          [5, 28, "X"], [6, 31, "Rome"]])
    assert res[-1].rowcount == 0


@stage(0)
def test_update_without_where_counts_every_row_even_if_unchanged():
    res = run_ok(PEOPLE + """
        UPDATE people SET city = city;
        UPDATE people SET score = 1.0;
        SELECT score FROM people;
    """)
    assert res[-3].rowcount == 6
    assert res[-2].rowcount == 6
    assert_rows(res[-1], [[1.0]] * 6)


@stage(0)
def test_update_uses_values_from_before_the_statement():
    res = run_ok("""
        CREATE TABLE t (a INTEGER, b INTEGER);
        INSERT INTO t VALUES (1, 2), (3, 4);
        UPDATE t SET a = b, b = a;
        SELECT * FROM t;
        UPDATE t SET a = a + 10 WHERE a > 1 AND b < 2;
        SELECT * FROM t;
    """)
    assert_rows(res[3], [[2, 1], [4, 3]])
    assert res[4].rowcount == 1
    assert_rows(res[5], [[12, 1], [4, 3]])


@stage(0)
def test_row_order_after_update_delete_insert():
    res = run_ok("""
        CREATE TABLE t (a INTEGER, b TEXT);
        INSERT INTO t VALUES (1, 'a'), (2, 'b'), (3, 'c'), (4, 'd');
        UPDATE t SET b = 'B' WHERE a = 2;
        DELETE FROM t WHERE a = 1;
        INSERT INTO t VALUES (1, 'new');
        UPDATE t SET a = a * 10;
        SELECT * FROM t;
    """)
    assert_rows(res[-1], [[20, "B"], [30, "c"], [40, "d"], [10, "new"]])


@stage(0)
def test_delete_with_where_and_all():
    res = run_ok(PEOPLE + """
        DELETE FROM people WHERE city = 'Rome' OR age IS NULL;
        SELECT id FROM people;
        DELETE FROM people WHERE id > 100;
        DELETE FROM people;
        SELECT * FROM people;
    """)
    assert res[-5].rowcount == 3
    assert_rows(res[-4], [[1], [4], [5]])
    assert res[-3].rowcount == 0
    assert res[-2].rowcount == 3
    assert res[-1].raw == {"ok": True, "columns": ["id", "name", "age", "city", "score"],
                           "rows": []}


@stage(0)
def test_update_and_delete_syntax_and_name_errors():
    res = run(PEOPLE + """
        UPDATE people AS p SET age = 1;
        UPDATE people p SET age = 1;
        DELETE FROM people p WHERE id = 1;
        UPDATE people SET people.age = 1;
        UPDATE people SET nope = 1;
        UPDATE people SET age = 1, age = 2;
        UPDATE people SET age = COUNT(*);
        DELETE FROM people WHERE COUNT(*) > 1;
        UPDATE nowhere SET a = 1;
        DELETE FROM nowhere;
        UPDATE people SET age = nope;
        UPDATE people SET age = people.age + 1 WHERE people.id = 1;
        SELECT age FROM people WHERE id = 1;
    """)
    r = res[-13:]
    for x, t in zip(r, ["SyntaxError", "SyntaxError", "SyntaxError", "SyntaxError", "NameError",
                        "SyntaxError", "SyntaxError", "SyntaxError", "NameError", "NameError",
                        "NameError"]):
        assert_error(x, t)
    assert r[11].rowcount == 1
    assert_rows(r[12], [[35]])


@stage(0)
def test_update_is_atomic_when_a_later_row_fails():
    res = run(PEOPLE + """
        UPDATE people SET age = 100 % (id - 4);
        UPDATE people SET name = name || '!', score = 1 / (6 - id) WHERE id > 1;
        SELECT name, age, score FROM people WHERE id IN (1, 2);
    """)
    assert_error(res[-3], "RuntimeError")
    assert_error(res[-2], "RuntimeError")
    assert_rows(res[-1], [["Ann", 34, 7.5], ["bob", 27, None]])


@stage(0)
def test_update_error_order_follows_rows_and_assignments():
    res = run("""
        CREATE TABLE t (id INTEGER PRIMARY KEY, a INTEGER, b TEXT NOT NULL);
        INSERT INTO t VALUES (1, 1, 'x'), (2, 0, 'y'), (3, 5, 'z');
        UPDATE t SET b = NULL, a = 10 / a WHERE id >= 2;
        UPDATE t SET b = CASE_LESS || 'x' WHERE id = 1;
        UPDATE t SET b = 'v' || (10 / a), a = 1 WHERE id <> 1;
        UPDATE t SET id = 1;
        UPDATE t SET id = 2, b = NULL WHERE id = 3;
        SELECT * FROM t;
    """)
    assert_error(res[2], "RuntimeError")
    assert_error(res[3], "NameError")
    assert_error(res[4], "RuntimeError")
    assert_error(res[5], "ConstraintError")
    assert_error(res[6], "ConstraintError")
    assert_rows(res[7], [[1, 1, "x"], [2, 0, "y"], [3, 5, "z"]])


@stage(0, retired=3)
def test_update_storing_wrong_type_is_a_type_error():
    res = run("""
        CREATE TABLE t (a INTEGER, b TEXT NOT NULL);
        INSERT INTO t VALUES (1, 'x'), (2, 'y');
        UPDATE t SET a = 'str';
        UPDATE t SET b = NULL, a = 2.5;
        UPDATE t SET a = 3 WHERE a = 2;
        SELECT * FROM t;
    """)
    assert_error(res[2], "TypeError")
    assert_error(res[3], "TypeError")
    assert res[4].rowcount == 1
    assert_rows(res[5], [[1, "x"], [3, "y"]])


@stage(0)
def test_delete_is_atomic_when_the_condition_fails():
    res = run(PEOPLE + """
        DELETE FROM people WHERE 10 % (id - 3) = 1;
        SELECT COUNT(*) FROM people;
        DELETE FROM people WHERE age > 30 AND 10 % (age - 45) = 0;
        DELETE FROM people WHERE name = 'x' AND 1 % 0 = 0;
        SELECT COUNT(*) FROM people;
    """)
    assert_error(res[-5], "RuntimeError")
    assert_rows(res[-4], [[6]])
    assert_error(res[-3], "RuntimeError")
    assert res[-2].rowcount == 0
    assert_rows(res[-1], [[6]])
