"""Tier 8: INNER / LEFT / CROSS joins, aliases, qualified names, ambiguity."""
from _support import COMPANY, assert_error, assert_rows, query, run, run_ok


def test_inner_join_with_aliases_where_and_order():
    r = query(COMPANY, "SELECT e.name, d.name AS dept FROM emp e JOIN dept d ON e.dept_id = d.id "
                       "WHERE e.salary >= 150 ORDER BY d.name, e.name;")
    assert_rows(r, [["ada", "eng"], ["bo", "eng"], ["gus", "eng"], ["cy", "ops"], ["di", "ops"]],
                columns=["name", "dept"])


def test_left_join_fills_nulls_and_anti_join():
    res = run_ok(COMPANY + """
        SELECT d.name, e.name FROM dept d LEFT JOIN emp e ON e.dept_id = d.id ORDER BY d.id, e.id;
        SELECT d.name FROM dept d LEFT OUTER JOIN emp e ON e.dept_id = d.id WHERE e.id IS NULL;
        SELECT e.name FROM emp AS e LEFT JOIN dept AS d ON e.dept_id = d.id WHERE d.id IS NULL;
    """)
    assert_rows(res[-3], [["eng", "ada"], ["eng", "bo"], ["eng", "gus"], ["ops", "cy"],
                          ["ops", "di"], ["sales", "ed"], ["legal", None]], columns=["name", "name"])
    assert_rows(res[-2], [["legal"]])
    assert_rows(res[-1], [["flo"]])


def test_left_join_on_condition_versus_where_and_nested_loop_order():
    r = query(COMPANY, "SELECT d.name, e.name FROM dept d LEFT JOIN emp e "
                       "ON e.dept_id = d.id AND e.salary > 200 ORDER BY d.id;")
    assert_rows(r, [["eng", "ada"], ["eng", "gus"], ["ops", None], ["sales", None], ["legal", None]])
    r = query("CREATE TABLE a (x INTEGER); CREATE TABLE b (y INTEGER);"
              "INSERT INTO a VALUES (2), (1); INSERT INTO b VALUES (1), (3), (2);",
              "SELECT x, y FROM a JOIN b ON y >= x;")
    assert_rows(r, [[2, 3], [2, 2], [1, 1], [1, 3], [1, 2]])


def test_aggregates_over_joins():
    r = query(COMPANY, "SELECT d.name, COUNT(e.id) AS n, SUM(e.salary) AS total FROM dept d "
                       "LEFT JOIN emp e ON e.dept_id = d.id GROUP BY d.name ORDER BY n DESC, d.name;")
    assert_rows(r, [["eng", 3, 750], ["ops", 2, 300], ["sales", 1, None], ["legal", 0, None]],
                columns=["name", "n", "total"])
    r = query(COMPANY, "SELECT d.name, AVG(e.salary) AS a FROM emp e JOIN dept d ON d.id = e.dept_id "
                       "WHERE e.active GROUP BY d.name HAVING COUNT(*) > 1 ORDER BY a DESC;")
    assert_rows(r, [["eng", 250.0]])


def test_self_join_and_three_way_join():
    res = run_ok(COMPANY + """
        SELECT e.name, m.name AS manager FROM emp e LEFT JOIN emp m ON e.manager_id = m.id ORDER BY e.id;
        SELECT e.name, m.name, d.name FROM emp e JOIN emp m ON e.manager_id = m.id
          JOIN dept d ON m.dept_id = d.id WHERE d.name = 'ops' ORDER BY e.name;
        SELECT COUNT(*) AS pairs FROM dept CROSS JOIN emp;
        SELECT d.name, e.name FROM dept d CROSS JOIN emp e WHERE e.id = 6 ORDER BY d.name DESC LIMIT 2;
    """)
    assert_rows(res[-4], [["ada", None], ["bo", "ada"], ["cy", "ada"], ["di", "cy"], ["ed", "ada"],
                          ["flo", "bo"], ["gus", "ada"]], columns=["name", "manager"])
    assert_rows(res[-3], [["di", "cy", "ops"]])
    assert_rows(res[-2], [[28]])
    assert_rows(res[-1], [["sales", "flo"], ["ops", "flo"]])


def test_star_and_qualified_star():
    res = run_ok(COMPANY + """
        SELECT * FROM dept d JOIN emp e ON e.dept_id = d.id WHERE e.id = 3;
        SELECT d.*, e.name FROM dept d JOIN emp e ON e.dept_id = d.id WHERE e.id = 3;
        SELECT budget FROM emp JOIN dept ON dept_id = dept.id WHERE salary = 300;
    """)
    assert_rows(res[-3], [[2, "ops", 500.0, 3, "cy", 2, 150, 1, True]],
                columns=["id", "name", "budget", "id", "name", "dept_id", "salary", "manager_id",
                         "active"])
    assert_rows(res[-2], [[2, "ops", 500.0, "cy"]], columns=["id", "name", "budget", "name"])
    assert_rows(res[-1], [[1000.0]])


def test_name_resolution_errors():
    res = run(COMPANY + """
        SELECT name FROM emp JOIN dept ON dept_id = dept.id;
        SELECT id FROM emp e JOIN dept d ON e.dept_id = d.id;
        SELECT * FROM emp JOIN emp ON TRUE;
        SELECT emp.name FROM emp e;
        SELECT x.name FROM emp e;
        SELECT e.nope FROM emp e;
        SELECT * FROM emp e JOIN missing m ON TRUE;
        CREATE TABLE empty1 (a INTEGER); CREATE TABLE empty2 (a INTEGER);
        SELECT a FROM empty1 JOIN empty2 ON TRUE;
        SELECT * FROM emp e JOIN emp m ON e.manager_id = m.id WHERE e.id = 2;
    """)
    for r in res[-11:-5]:
        assert_error(r, "NameError")
    assert_error(res[-5], "NameError")
    assert res[-4].ok and res[-3].ok
    assert_error(res[-2], "NameError")
    assert len(res[-1].rows) == 1 and len(res[-1].columns) == 12


def test_join_with_index_on_first_table():
    res = run_ok(COMPANY + """
        CREATE INDEX emp_dept ON emp (dept_id);
        EXPLAIN SELECT * FROM emp e JOIN dept d ON e.dept_id = d.id WHERE e.dept_id = 1;
        EXPLAIN SELECT * FROM dept d JOIN emp e ON e.dept_id = d.id WHERE e.dept_id = 1;
        SELECT e.name, d.name FROM emp e JOIN dept d ON e.dept_id = d.id WHERE e.dept_id = 1;
        UPDATE emp SET dept_id = 1 WHERE id = 6;
        SELECT e.name FROM emp e LEFT JOIN dept d ON e.dept_id = d.id WHERE e.dept_id = 1 AND d.budget > 900;
    """)
    assert res[-5].rows == [["SEARCH emp USING INDEX emp_dept (dept_id = ?)"], ["SCAN dept"]]
    assert res[-4].rows == [["SCAN dept"], ["SCAN emp"]]
    assert_rows(res[-3], [["ada", "eng"], ["bo", "eng"], ["gus", "eng"]])
    assert_rows(res[-1], [["ada"], ["bo"], ["flo"], ["gus"]])
