"""Stage 3 change requests: CR-1 NULL ordering, CR-2 division, CR-3 storage type errors.

These replace tests retired at stage 3 in test_t01, test_t02, test_t03, test_t04, test_t05 and
test_t11, and re-check that what the change requests leave alone stays as it was.
"""
from _support import COMPANY, PEOPLE, assert_error, assert_rows, plan, run, run_ok, stage


def col(result, i=0):
    assert result.ok, result
    return [row[i] for row in result.rows]


# ------------------------------------------------------------------ CR-1


@stage(3)
def test_nulls_sort_last_ascending_and_first_descending():
    res = run_ok(PEOPLE + """
        SELECT id FROM people ORDER BY age;
        SELECT id FROM people ORDER BY age DESC;
        SELECT id FROM people ORDER BY city DESC, id;
        SELECT id, score FROM people ORDER BY score, id DESC;
    """)
    assert col(res[-4]) == [2, 5, 6, 1, 4, 3]
    assert col(res[-3]) == [3, 4, 1, 6, 2, 5]
    assert col(res[-2]) == [4, 2, 6, 1, 3, 5]
    assert col(res[-1]) == [4, 6, 1, 5, 3, 2]


@stage(3)
def test_nulls_first_and_nulls_last():
    res = run(PEOPLE + """
        SELECT id FROM people ORDER BY age NULLS FIRST;
        SELECT id FROM people ORDER BY age DESC NULLS LAST;
        SELECT id FROM people ORDER BY age ASC NULLS LAST, id DESC;
        SELECT id, city FROM people ORDER BY 2 NULLS FIRST, 1 DESC;
        SELECT id FROM people ORDER BY score DESC NULLS FIRST, age NULLS FIRST;
        SELECT id FROM people ORDER BY age NULLS;
        SELECT id FROM people ORDER BY age NULLS MIDDLE;
        CREATE TABLE t (nulls INTEGER, first TEXT, last TEXT);
        INSERT INTO t VALUES (2, 'a', 'x'), (NULL, 'b', 'y'), (1, 'c', 'z');
        SELECT first, last FROM t ORDER BY nulls NULLS FIRST;
        SELECT first FROM t ORDER BY nulls DESC NULLS LAST;
    """)
    assert col(res[-11]) == [3, 2, 5, 6, 1, 4]
    assert col(res[-10]) == [4, 1, 6, 2, 5, 3]
    assert col(res[-9]) == [5, 2, 6, 1, 4, 3]
    assert col(res[-8]) == [4, 5, 3, 1, 6, 2]
    assert col(res[-7]) == [2, 3, 5, 6, 1, 4]
    assert_error(res[-6], "SyntaxError")
    assert_error(res[-5], "SyntaxError")
    assert_rows(res[-2], [["b", "y"], ["c", "z"], ["a", "x"]])
    assert col(res[-1]) == ["a", "c", "b"]


@stage(3)
def test_null_ordering_in_set_operations_subqueries_and_derived_tables():
    res = run_ok(COMPANY + """
        SELECT budget FROM dept UNION ALL SELECT salary FROM emp WHERE id <= 5 ORDER BY 1;
        SELECT (SELECT name FROM emp ORDER BY salary DESC LIMIT 1);
        SELECT x.name FROM (SELECT name, salary FROM emp ORDER BY salary LIMIT 2 OFFSET 5) x;
        SELECT DISTINCT dept_id FROM emp ORDER BY dept_id DESC;
        SELECT name FROM emp WHERE id IN (SELECT id FROM emp ORDER BY dept_id DESC LIMIT 1);
    """)
    assert col(res[-5]) == [150, 150, 200.0, 200, 300, 500.0, 1000.0, None, None]
    assert col(res[-4]) == ["ed"]
    assert col(res[-3]) == ["ada", "ed"]
    assert col(res[-2]) == [None, 3, 2, 1]
    assert col(res[-1]) == ["flo"]


@stage(3)
def test_what_cr1_leaves_alone():
    res = run_ok(PEOPLE + """
        SELECT MIN(age), MAX(age), MIN(city), MAX(score) FROM people;
        CREATE INDEX people_age ON people (age);
        SELECT id FROM people WHERE age < 40;
        EXPLAIN SELECT id FROM people WHERE age < 40;
        SELECT city, COUNT(*) FROM people GROUP BY city;
        SELECT id FROM people WHERE age > NULL OR age = NULL;
    """)
    assert_rows(res[-6], [[27, 45, "Lima", 9.0]])
    assert col(res[-4]) == [1, 2, 5, 6]
    assert plan(res[-3]) == ["SEARCH people USING INDEX people_age (age RANGE)"]
    assert_rows(res[-2], [["Oslo", 2], ["Rome", 2], [None, 1], ["Lima", 1]])
    assert_rows(res[-1], [])


# ------------------------------------------------------------------ CR-2


@stage(3)
def test_division_always_returns_real():
    res = run("""
        SELECT 7 / 2, -7 / 2, 4 / 2, TYPEOF(4 / 2), 1 / 3, 7.5 / 2.5, 7 / -2, 0 / 5;
        SELECT -9223372036854775807 / -1, (-9223372036854775807 - 1) / -1;
        SELECT 9007199254740993 / 1;
        SELECT 1 / 0;
        SELECT 0 / 0;
        SELECT 5 % 0;
        SELECT -7 % 2, 7 % -2, TYPEOF(7 % 2);
    """)
    assert_rows(res[0], [[3.5, -3.5, 2.0, "REAL", 1 / 3, 3.0, -3.5, 0.0]])
    assert_rows(res[1], [[9223372036854775807 / 1, 9223372036854775808 / 1]])
    assert res[2].rows == [[9007199254740992.0]] and isinstance(res[2].rows[0][0], float)
    for r in res[3:6]:
        assert_error(r, "RuntimeError")
    assert_rows(res[6], [[-1, 1, "INTEGER"]])


@stage(3)
def test_div_function():
    res = run("""
        SELECT DIV(7, 2), DIV(-7, 2), DIV(7, -2), DIV(6, 3), DIV(NULL, 1), DIV(1, NULL), div(-1, 3);
        SELECT DIV(1, 0);
        SELECT DIV(-9223372036854775807 - 1, -1);
        SELECT DIV(7.0, 2);
        SELECT DIV('7', 2);
        SELECT DIV(TRUE, 1);
        SELECT DIV(1);
        SELECT DIV(9223372036854775807, 1);
    """)
    assert_rows(res[0], [[3, -3, -3, 2, None, None, 0]], columns=["div"] * 7)
    assert_error(res[1], "RuntimeError")
    assert_error(res[2], "RuntimeError")
    for r in res[3:6]:
        assert_error(r, "TypeError")
    assert_error(res[6], "SyntaxError")
    assert_rows(res[7], [[9223372036854775807]])


@stage(3)
def test_division_in_queries_storage_and_aggregates():
    res = run(COMPANY + """
        SELECT SUM(salary) / COUNT(salary), AVG(salary), DIV(SUM(salary), COUNT(salary)) FROM emp;
        SELECT name, salary / 100 AS h FROM emp WHERE salary / 100 > 2 ORDER BY h DESC;
        CREATE TABLE t (i INTEGER, r REAL);
        INSERT INTO t VALUES (7, 7 / 2);
        INSERT INTO t VALUES (7 / 7, 1.0);
        INSERT INTO t VALUES (DIV(7, 7), 1.0);
        UPDATE t SET i = i / 1;
        SELECT * FROM t;
    """)
    assert_rows(res[-8], [[1150 / 6, 1150 / 6, 191]])
    assert_rows(res[-7], [["ada", 3.0], ["gus", 2.5]], columns=["name", "h"])
    assert res[-5].rowcount == 1
    assert_error(res[-4], "ConstraintError")
    assert res[-3].rowcount == 1
    assert_error(res[-2], "ConstraintError")
    assert_rows(res[-1], [[7, 3.5], [1, 1.0]])


# ------------------------------------------------------------------ CR-3


@stage(3)
def test_storing_a_value_that_does_not_fit_is_a_constraint_error():
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
        INSERT INTO t VALUES (1, 2, 'x', NULL), (2, 2.5, 3, FALSE);
        INSERT INTO t VALUES (1, 2, 'x', TRUE);
        UPDATE t SET s = 1;
        UPDATE t SET b = NULL, i = 'x';
        SELECT * FROM t;
    """)
    for r in res[1:10]:
        assert_error(r, "ConstraintError")
    assert res[10].rowcount == 1
    assert_error(res[11], "ConstraintError")
    assert_error(res[12], "ConstraintError")
    assert_rows(res[13], [[1, 2.0, "x", True]])


@stage(3)
def test_default_that_does_not_fit_is_a_constraint_error():
    res = run("""
        CREATE TABLE t (a INTEGER DEFAULT 'x');
        CREATE TABLE t (a INTEGER DEFAULT 1.5);
        CREATE TABLE t (a BOOLEAN DEFAULT 1);
        CREATE TABLE t (a TEXT DEFAULT 5);
        CREATE TABLE t (a REAL DEFAULT 5, b TEXT DEFAULT 'ok');
        INSERT INTO t (b) VALUES ('x');
        SELECT * FROM t;
    """)
    for r in res[:4]:
        assert_error(r, "ConstraintError")
    assert res[4].ok
    assert_rows(res[6], [[5.0, "x"]])


@stage(3)
def test_constraint_error_keeps_its_place_in_the_error_order():
    res = run(COMPANY + """
        CREATE TABLE t (n INTEGER, s TEXT NOT NULL);
        INSERT INTO t VALUES ('x', 1 / 0);
        INSERT INTO t VALUES (1, 'ok'), (2, 'x' || 2);
        INSERT INTO t VALUES (1, 'ok'), (2.5, NULL);
        INSERT INTO t SELECT name, id FROM emp;
        INSERT INTO t (n) SELECT budget FROM dept WHERE id = 1;
        INSERT INTO t SELECT id, name FROM emp WHERE id = 1;
        UPDATE t SET n = n / 0;
        UPDATE t SET n = 'str' || (n / 0);
        UPDATE t SET n = n + 0.5;
        SELECT * FROM t;
    """)
    r = res[-10:]
    assert_error(r[0], "RuntimeError")
    assert_error(r[1], "TypeError")
    assert_error(r[2], "ConstraintError")
    assert_error(r[3], "ConstraintError")
    assert_error(r[4], "ConstraintError")
    assert r[5].rowcount == 1
    assert_error(r[6], "RuntimeError")
    assert_error(r[7], "RuntimeError")
    assert_error(r[8], "ConstraintError")
    assert_rows(r[9], [[1, "ada"]])


@stage(3)
def test_type_errors_that_are_not_about_storage_are_unchanged():
    res = run(COMPANY + """
        SELECT 1 + 'a';
        SELECT CAST(1.5 AS BOOLEAN);
        SELECT name FROM emp WHERE salary;
        SELECT SUM(name) FROM emp;
        SELECT name FROM emp ORDER BY COALESCE(name, salary), COALESCE(salary, name);
        SELECT LENGTH(5);
        SELECT * FROM emp e JOIN dept d ON e.name = d.id;
    """)
    for r in res[-7:]:
        assert_error(r, "TypeError")
