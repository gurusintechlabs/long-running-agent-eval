"""Tier 6: aggregates, GROUP BY, HAVING."""
from _support import COMPANY, assert_error, assert_rows, query, run, run_ok


def test_count_variants():
    r = query(COMPANY, "SELECT COUNT(*), COUNT(salary) AS c2, COUNT(DISTINCT salary) AS c3, "
                       "COUNT(dept_id) AS c4 FROM emp;")
    assert_rows(r, [[7, 6, 5, 6]], columns=["count", "c2", "c3", "c4"])


def test_sum_avg_min_max_types():
    res = run_ok(COMPANY + """
        SELECT SUM(salary), AVG(salary), MIN(salary), MAX(salary), MIN(name), MAX(name) FROM emp;
        SELECT AVG(salary) AS a, SUM(salary) AS s FROM emp WHERE dept_id = 2;
        SELECT SUM(budget) AS s, MIN(budget) AS lo, AVG(budget) AS av FROM dept;
        SELECT MAX(active) AS t, MIN(active) AS f FROM emp;
    """)
    assert_rows(res[-4], [[1150, 1150 / 6, 100, 300, "ada", "gus"]],
                columns=["sum", "avg", "min", "max", "min", "max"])
    assert_rows(res[-3], [[150.0, 300]])
    assert_rows(res[-2], [[1700.0, 200.0, 1700.0 / 3]])
    assert_rows(res[-1], [[True, False]])


def test_aggregates_over_no_rows():
    res = run_ok(COMPANY + """
        SELECT COUNT(*), SUM(salary), AVG(salary), MAX(name), COUNT(DISTINCT dept_id) AS d
          FROM emp WHERE id > 100;
        SELECT dept_id, COUNT(*) FROM emp WHERE id > 100 GROUP BY dept_id;
        SELECT SUM(salary) AS s, COUNT(salary) AS c FROM emp WHERE id = 5;
        CREATE TABLE e (x INTEGER);
        SELECT COUNT(*), MAX(x) FROM e;
        SELECT COUNT(*) FROM e HAVING COUNT(*) > 0;
    """)
    assert_rows(res[-6], [[0, None, None, None, 0]])
    assert_rows(res[-5], [])
    assert_rows(res[-4], [[None, 0]])
    assert_rows(res[-2], [[0, None]])
    assert_rows(res[-1], [])


def test_group_by_first_appearance_order_and_null_group():
    r = query(COMPANY, "SELECT dept_id, COUNT(*) AS n, SUM(salary) AS total FROM emp GROUP BY dept_id;")
    assert_rows(r, [[1, 3, 750], [2, 2, 300], [3, 1, None], [None, 1, 100]],
                columns=["dept_id", "n", "total"])


def test_having_and_order_by_aggregates():
    res = run_ok(COMPANY + """
        SELECT dept_id, AVG(salary) AS avg_sal FROM emp WHERE active GROUP BY dept_id
          HAVING COUNT(*) >= 1 AND MAX(salary) > 120 ORDER BY avg_sal DESC;
        SELECT dept_id FROM emp GROUP BY dept_id HAVING SUM(salary) >= 300
          ORDER BY COUNT(*) DESC, dept_id;
        SELECT dept_id, MAX(salary) - MIN(salary) AS spread FROM emp GROUP BY dept_id
          ORDER BY 2 DESC, 1 LIMIT 2;
    """)
    assert_rows(res[-3], [[1, 250.0], [2, 150.0]])
    assert_rows(res[-2], [[1], [2]])
    assert_rows(res[-1], [[1, 100], [None, 0]])  # NULL group sorts first on the tie


def test_group_by_multiple_columns():
    r = query(COMPANY, "SELECT dept_id, active, COUNT(*) AS n, SUM(salary) * 2 AS dbl FROM emp "
                       "WHERE dept_id IS NOT NULL GROUP BY dept_id, active ORDER BY dept_id, active;")
    assert_rows(r, [[1, True, 3, 1500], [2, False, 1, 300], [2, True, 1, 300], [3, True, 1, None]])


def test_distinct_over_grouped_output():
    r = query(COMPANY, "SELECT DISTINCT COUNT(*) AS c FROM emp GROUP BY dept_id ORDER BY c;")
    assert_rows(r, [[1], [2], [3]])


def test_grouping_errors():
    res = run(COMPANY + """
        SELECT name, COUNT(*) FROM emp GROUP BY dept_id;
        SELECT name, COUNT(*) FROM emp;
        SELECT * FROM emp WHERE COUNT(*) > 1;
        SELECT SUM(COUNT(*)) FROM emp;
        SELECT dept_id FROM emp GROUP BY dept_id ORDER BY salary;
        SELECT SUM(name) FROM emp;
        SELECT AVG(active) FROM emp;
        SELECT dept_id, COUNT(*) FROM emp GROUP BY nope;
    """)
    want = ["SyntaxError"] * 5 + ["TypeError", "TypeError", "NameError"]
    for r, w in zip(res[-8:], want):
        assert_error(r, w)
