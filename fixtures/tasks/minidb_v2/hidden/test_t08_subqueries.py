"""Section 8 (stage 1): IN / scalar / EXISTS subqueries, correlation, evaluation rules."""
from _support import COMPANY, assert_error, assert_rows, query, run, run_ok, stage


@stage(1)
def test_in_subquery():
    r = query(COMPANY, "SELECT name FROM emp WHERE dept_id IN "
                       "(SELECT id FROM dept WHERE budget >= 500) ORDER BY name;")
    assert_rows(r, [["ada"], ["bo"], ["cy"], ["di"], ["gus"]])


@stage(1)
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


@stage(1)
def test_scalar_subqueries():
    res = run(COMPANY + """
        SELECT name, salary - (SELECT AVG(salary) FROM emp) AS diff FROM emp
          WHERE salary > (SELECT AVG(salary) FROM emp) ORDER BY id;
        SELECT (SELECT name FROM emp WHERE id = 99) AS x;
        SELECT (SELECT name FROM emp WHERE salary IS NOT NULL ORDER BY salary DESC LIMIT 1);
        SELECT (SELECT name FROM emp);
        SELECT (SELECT id, name FROM emp WHERE id = 1);
        SELECT name FROM emp WHERE id IN (SELECT id, name FROM emp);
    """)
    avg = 1150 / 6
    assert_rows(res[-6], [["ada", 300 - avg], ["bo", 200 - avg], ["gus", 250 - avg]],
                columns=["name", "diff"])
    assert_rows(res[-5], [[None]])
    assert_rows(res[-4], [["ada"]], columns=["?column?"])
    assert_error(res[-3], "RuntimeError")
    assert_error(res[-2], "SyntaxError")
    assert_error(res[-1], "SyntaxError")


@stage(1)
def test_exists_and_not_exists():
    res = run_ok(COMPANY + """
        SELECT name FROM dept d WHERE EXISTS
          (SELECT 1 FROM emp e WHERE e.dept_id = d.id AND e.salary > 200) ORDER BY name;
        SELECT name FROM dept d WHERE NOT EXISTS
          (SELECT * FROM emp e WHERE e.dept_id = d.id AND e.salary > 200) ORDER BY name;
        SELECT EXISTS (SELECT id, name FROM emp WHERE id = 1), NOT EXISTS (SELECT 1 FROM emp WHERE id = 99);
        SELECT EXISTS (SELECT NULL), EXISTS (SELECT 1 FROM dept WHERE FALSE);
    """)
    assert_rows(res[-4], [["eng"]])
    assert_rows(res[-3], [["legal"], ["ops"], ["sales"]])
    assert_rows(res[-2], [[True, True]], columns=["exists", "?column?"])
    assert_rows(res[-1], [[True, False]])


@stage(1)
def test_correlation_resolves_names_innermost_first():
    res = run(COMPANY + """
        SELECT name FROM emp e WHERE salary >= (SELECT MAX(salary) FROM emp WHERE dept_id = e.dept_id)
          ORDER BY id;
        SELECT d.name, (SELECT COUNT(*) FROM emp WHERE dept_id = id) AS c FROM dept d;
        SELECT d.name, (SELECT COUNT(*) FROM emp WHERE dept_id = d.id) AS c FROM dept d;
        SELECT (SELECT COUNT(*) FROM emp JOIN dept ON dept.id = emp.dept_id WHERE id > 0) FROM dept;
        SELECT name FROM dept WHERE budget > (SELECT AVG(budget) FROM dept AS inner_d WHERE inner_d.id <> dept.id);
    """)
    assert_rows(res[-5], [["ada"], ["cy"], ["di"]])
    assert_rows(res[-4], [["eng", 1], ["ops", 1], ["sales", 1], ["legal", 1]])
    assert_rows(res[-3], [["eng", 3], ["ops", 2], ["sales", 1], ["legal", 0]])
    assert_error(res[-2], "NameError")
    assert_rows(res[-1], [["eng"]])


@stage(1)
def test_subqueries_in_update_and_delete_see_the_old_state():
    res = run_ok(COMPANY + """
        UPDATE emp SET salary = salary + (SELECT SUM(salary) FROM emp);
        SELECT SUM(salary) FROM emp;
        UPDATE emp SET manager_id = (SELECT m.id FROM emp m WHERE m.name = 'gus') WHERE emp.name = 'flo';
        DELETE FROM emp WHERE salary < (SELECT AVG(salary) FROM emp);
        SELECT name, manager_id FROM emp;
        DELETE FROM dept WHERE NOT EXISTS (SELECT 1 FROM emp WHERE emp.dept_id = dept.id);
        SELECT name FROM dept;
    """)
    assert_rows(res[-6], [[8050]])
    assert res[-5].rowcount == 1
    assert res[-4].rowcount == 3
    assert_rows(res[-3], [["ada", None], ["bo", 1], ["ed", 1], ["gus", 1]])
    assert res[-2].rowcount == 2
    assert_rows(res[-1], [["eng"], ["sales"]])


@stage(1)
def test_subqueries_in_values_order_by_having_and_on():
    res = run_ok(COMPANY + """
        INSERT INTO dept VALUES ((SELECT MAX(id) FROM dept) + 1, 'hr', NULL);
        SELECT id FROM dept WHERE name = 'hr';
        SELECT name FROM dept ORDER BY (SELECT COUNT(*) FROM emp WHERE emp.dept_id = dept.id) DESC, name;
        SELECT dept_id FROM emp GROUP BY dept_id HAVING COUNT(*) > (SELECT COUNT(*) FROM dept WHERE budget > 400);
        SELECT e.name FROM emp e JOIN dept d ON d.id = e.dept_id AND d.budget = (SELECT MAX(budget) FROM dept);
    """)
    assert_rows(res[-4], [[5]])
    assert_rows(res[-3], [["eng"], ["ops"], ["sales"], ["hr"], ["legal"]])
    assert_rows(res[-2], [[1]])
    assert_rows(res[-1], [["ada"], ["bo"], ["gus"]])


@stage(1)
def test_uncorrelated_subqueries_are_evaluated_only_when_needed():
    res = run(COMPANY + """
        CREATE TABLE empty (x INTEGER);
        SELECT * FROM empty WHERE x = (SELECT 1 / 0);
        SELECT id FROM emp WHERE id > 100 AND id IN (SELECT 1 / 0);
        SELECT FALSE AND (SELECT 1 / 0) = 1;
        SELECT id FROM emp WHERE id = (SELECT 1 / 0);
        UPDATE emp SET salary = (SELECT 1 / 0) WHERE id > 100;
    """)
    assert_rows(res[-5], [])
    assert_rows(res[-4], [])
    assert_rows(res[-3], [[False]])
    assert_error(res[-2], "RuntimeError")
    assert res[-1].rowcount == 0


@stage(1)
def test_grouping_rule_extends_into_subqueries():
    res = run(COMPANY + """
        SELECT dept_id, (SELECT COUNT(*) FROM dept WHERE dept.id = emp.dept_id) FROM emp GROUP BY dept_id;
        SELECT dept_id, (SELECT COUNT(*) FROM dept WHERE dept.id = emp.manager_id) FROM emp GROUP BY dept_id;
        SELECT dept_id, COUNT(*) FROM emp
          WHERE EXISTS (SELECT 1 FROM dept WHERE dept.id = emp.dept_id AND budget > 400) GROUP BY dept_id;
        SELECT name, (SELECT COUNT(*) + SUM(e.salary) FROM dept) AS x FROM emp e WHERE id = 1;
    """)
    assert_rows(res[-4], [[1, 1], [2, 1], [3, 1], [None, 0]])
    assert_error(res[-3], "SyntaxError")
    assert_rows(res[-2], [[1, 3], [2, 2]])
    assert_rows(res[-1], [["ada", 1204]])


@stage(1)
def test_subquery_errors():
    res = run(COMPANY + """
        SELECT name FROM emp WHERE id IN (SELECT nope FROM dept);
        CREATE TABLE empty (x INTEGER);
        SELECT x FROM empty WHERE x IN (SELECT nope FROM dept);
        SELECT dept_id FROM emp GROUP BY (SELECT 1);
        CREATE TABLE bad (a INTEGER DEFAULT (SELECT 1));
        SELECT (SELECT) FROM emp;
    """)
    assert_error(res[-6], "NameError")
    assert_error(res[-4], "NameError")
    for r in res[-3:]:
        assert_error(r, "SyntaxError")


@stage(1)
def test_in_subquery_with_order_by_limit_and_set_operation():
    res = run_ok(COMPANY + """
        SELECT name FROM emp WHERE id IN
          (SELECT id FROM emp WHERE salary IS NOT NULL ORDER BY salary LIMIT 2);
        SELECT name FROM emp WHERE id IN (SELECT 1 UNION SELECT 7);
    """)
    assert_rows(res[-2], [["cy"], ["flo"]])
    assert_rows(res[-1], [["ada"], ["gus"]])
