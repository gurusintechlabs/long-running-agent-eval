"""Tier 9: IN / scalar / EXISTS subqueries, correlation, subqueries in UPDATE and DELETE."""
from _support import COMPANY, assert_error, assert_rows, query, run, run_ok


def test_in_subquery():
    r = query(COMPANY, "SELECT name FROM emp WHERE dept_id IN "
                       "(SELECT id FROM dept WHERE budget >= 500) ORDER BY name;")
    assert_rows(r, [["ada"], ["bo"], ["cy"], ["di"], ["gus"]])


def test_not_in_with_null_and_empty_subqueries():
    res = run_ok(COMPANY + """
        SELECT name FROM emp WHERE id NOT IN (SELECT manager_id FROM emp);
        SELECT name FROM emp WHERE id NOT IN (SELECT manager_id FROM emp WHERE manager_id IS NOT NULL)
          ORDER BY id;
        SELECT name FROM emp WHERE id IN (SELECT id FROM dept WHERE id > 99);
        SELECT COUNT(*) AS n FROM emp WHERE id NOT IN (SELECT id FROM dept WHERE id > 99);
        SELECT NULL IN (SELECT id FROM dept WHERE id > 99) AS a, NULL IN (SELECT id FROM dept) AS b;
    """)
    assert_rows(res[-5], [])
    assert_rows(res[-4], [["di"], ["ed"], ["flo"], ["gus"]])
    assert_rows(res[-3], [])
    assert_rows(res[-2], [[7]])
    assert_rows(res[-1], [[False, None]])


def test_scalar_subqueries():
    res = run(COMPANY + """
        SELECT name, salary - (SELECT AVG(salary) FROM emp) AS diff FROM emp
          WHERE salary > (SELECT AVG(salary) FROM emp) ORDER BY id;
        SELECT (SELECT name FROM emp WHERE id = 99) AS x;
        SELECT (SELECT name FROM emp ORDER BY salary DESC LIMIT 1) AS top;
        SELECT (SELECT name FROM emp);
        SELECT (SELECT id, name FROM emp WHERE id = 1);
        SELECT name FROM emp WHERE id IN (SELECT id, name FROM emp);
    """)
    avg = 1150 / 6
    assert_rows(res[-6], [["ada", 300 - avg], ["bo", 200 - avg], ["gus", 250 - avg]],
                columns=["name", "diff"])
    assert_rows(res[-5], [[None]])
    assert_rows(res[-4], [["ada"]])
    assert_error(res[-3], "RuntimeError")
    assert_error(res[-2], "SyntaxError")
    assert_error(res[-1], "SyntaxError")


def test_exists_and_not_exists_correlated():
    res = run_ok(COMPANY + """
        SELECT name FROM dept d WHERE EXISTS
          (SELECT 1 FROM emp e WHERE e.dept_id = d.id AND e.salary > 200) ORDER BY name;
        SELECT name FROM dept d WHERE NOT EXISTS (SELECT 1 FROM emp WHERE dept_id = d.id);
        SELECT EXISTS (SELECT 1 FROM emp WHERE salary IS NULL) AS a,
               EXISTS (SELECT 1 FROM emp WHERE id < 0) AS b;
    """)
    assert_rows(res[-3], [["eng"]])
    assert_rows(res[-2], [["legal"]])
    assert_rows(res[-1], [[True, False]])


def test_correlated_scalar_subquery_runs_per_row():
    res = run_ok(COMPANY + """
        SELECT e.name, (SELECT COUNT(*) FROM emp r WHERE r.manager_id = e.id) AS reports
          FROM emp e ORDER BY reports DESC, e.name;
        SELECT name FROM emp e WHERE salary > (SELECT AVG(salary) FROM emp WHERE dept_id = e.dept_id)
          ORDER BY name;
    """)
    assert_rows(res[-2], [["ada", 4], ["bo", 1], ["cy", 1], ["di", 0], ["ed", 0], ["flo", 0],
                          ["gus", 0]])
    assert_rows(res[-1], [["ada"]])


def test_name_resolution_prefers_the_innermost_query():
    r = query(COMPANY + "CREATE TABLE t (id INTEGER, name TEXT); INSERT INTO t VALUES (1, 'x'), (9, 'y');",
              "SELECT name FROM t WHERE EXISTS (SELECT 1 FROM emp WHERE id = 1) "
              "AND (SELECT name FROM emp WHERE id = t.id) IS NULL;")
    assert_rows(r, [["y"]])


def test_subqueries_in_update_and_delete_see_the_old_state():
    res = run_ok(COMPANY + """
        UPDATE emp SET salary = (SELECT MAX(salary) FROM emp) + 10 WHERE dept_id = 1;
        SELECT salary FROM emp WHERE dept_id = 1 ORDER BY id;
        DELETE FROM emp WHERE salary = (SELECT MAX(salary) FROM emp WHERE dept_id = 1) AND id <> 2;
        SELECT id FROM emp ORDER BY id;
        UPDATE dept SET budget = (SELECT SUM(salary) FROM emp WHERE emp.dept_id = dept.id);
        SELECT name, budget FROM dept ORDER BY id;
        DELETE FROM emp WHERE salary < (SELECT AVG(salary) FROM emp);
        SELECT id FROM emp ORDER BY id;
    """)
    assert_rows(res[-7], [[310], [310], [310]])
    assert res[-6].rowcount == 2
    assert_rows(res[-5], [[2], [3], [4], [5], [6]])
    assert res[-4].rowcount == 4
    assert_rows(res[-3], [["eng", 310.0], ["ops", 300.0], ["sales", None], ["legal", None]])
    assert res[-2].rowcount == 3
    assert_rows(res[-1], [[2], [5]])


def test_subqueries_with_joins_and_having():
    res = run_ok(COMPANY + """
        SELECT name FROM emp WHERE id IN
          (SELECT e.manager_id FROM emp e JOIN dept d ON e.dept_id = d.id WHERE d.name = 'eng')
          ORDER BY name;
        SELECT dept_id, COUNT(*) AS n FROM emp GROUP BY dept_id
          HAVING COUNT(*) > (SELECT COUNT(*) FROM dept WHERE budget < 600) ORDER BY dept_id;
        SELECT d.name FROM dept d WHERE EXISTS (SELECT 1 FROM emp e WHERE e.dept_id = d.id AND
          EXISTS (SELECT 1 FROM emp m WHERE m.id = e.manager_id AND m.dept_id <> d.id)) ORDER BY d.name;
    """)
    assert_rows(res[-3], [["ada"]])
    assert_rows(res[-2], [[1, 3]])
    assert_rows(res[-1], [["ops"], ["sales"]])


def test_explain_ignores_subqueries():
    r = query(COMPANY + "CREATE INDEX ed ON emp (dept_id);",
              "EXPLAIN SELECT name FROM emp WHERE dept_id = 2 AND id IN (SELECT manager_id FROM emp);")
    assert r.rows == [["SEARCH emp USING INDEX ed (dept_id = ?)"]]
