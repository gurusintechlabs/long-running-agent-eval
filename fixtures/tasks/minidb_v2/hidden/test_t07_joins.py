"""Section 7 (stage 0): INNER / LEFT / CROSS joins, exposed names, nested-loop order."""
from _support import COMPANY, assert_error, assert_rows, run, run_ok, stage

ABC = """
CREATE TABLE a (x INTEGER);
CREATE TABLE b (y TEXT, x INTEGER);
CREATE TABLE c (z INTEGER);
INSERT INTO a VALUES (1), (2);
INSERT INTO b VALUES ('p', 2), ('q', 1), ('r', 2);
INSERT INTO c VALUES (2), (1);
"""


@stage(0)
def test_inner_join_rows_come_in_nested_loop_order():
    res = run_ok(COMPANY + """
        SELECT e.name, d.name FROM emp e JOIN dept d ON e.dept_id = d.id;
        SELECT d.name, e.name FROM dept d INNER JOIN emp e ON e.dept_id = d.id;
    """)
    assert_rows(res[-2], [["ada", "eng"], ["bo", "eng"], ["cy", "ops"], ["di", "ops"],
                          ["ed", "sales"], ["gus", "eng"]], columns=["name", "name"])
    assert_rows(res[-1], [["eng", "ada"], ["eng", "bo"], ["eng", "gus"], ["ops", "cy"],
                          ["ops", "di"], ["sales", "ed"]])


@stage(0)
def test_left_join_keeps_unmatched_left_rows():
    res = run_ok(COMPANY + """
        SELECT d.name, e.name FROM dept d LEFT JOIN emp e ON e.dept_id = d.id AND e.salary > 200;
        SELECT e.name, d.* FROM emp e LEFT OUTER JOIN dept d ON d.id = e.dept_id WHERE d.id IS NULL;
        SELECT d.name, e.name FROM dept d LEFT JOIN emp e ON e.dept_id = d.id WHERE e.salary > 200;
    """)
    assert_rows(res[-3], [["eng", "ada"], ["eng", "gus"], ["ops", None], ["sales", None],
                          ["legal", None]])
    assert_rows(res[-2], [["flo", None, None, None]], columns=["name", "id", "name", "budget"])
    assert_rows(res[-1], [["eng", "ada"], ["eng", "gus"]])


@stage(0)
def test_cross_join_and_three_way_joins():
    res = run_ok(ABC + COMPANY + """
        SELECT a.x, b.y FROM a CROSS JOIN b;
        SELECT * FROM a JOIN b ON b.x = a.x JOIN c ON c.z = a.x;
        SELECT e.name, d.name, m.name FROM emp e JOIN dept d ON d.id = e.dept_id
          JOIN emp m ON m.id = e.manager_id;
    """)
    assert_rows(res[-3], [[1, "p"], [1, "q"], [1, "r"], [2, "p"], [2, "q"], [2, "r"]])
    assert_rows(res[-2], [[1, "q", 1, 1], [2, "p", 2, 2], [2, "r", 2, 2]],
                columns=["x", "y", "x", "z"])
    assert_rows(res[-1], [["bo", "eng", "ada"], ["cy", "ops", "ada"], ["di", "ops", "cy"],
                          ["ed", "sales", "ada"], ["gus", "eng", "ada"]])


@stage(0)
def test_self_join_needs_aliases():
    res = run(COMPANY + """
        SELECT e.name, m.name AS manager FROM emp e JOIN emp m ON e.manager_id = m.id;
        SELECT e.name, m.name FROM emp AS e LEFT JOIN emp AS m ON m.id = e.manager_id WHERE e.id <= 2;
        SELECT * FROM emp JOIN emp ON emp.id = emp.manager_id;
        SELECT * FROM emp e JOIN dept e ON TRUE;
        SELECT * FROM emp JOIN dept emp ON TRUE;
    """)
    assert_rows(res[-5], [["bo", "ada"], ["cy", "ada"], ["di", "cy"], ["ed", "ada"], ["flo", "bo"],
                          ["gus", "ada"]], columns=["name", "manager"])
    assert_rows(res[-4], [["ada", None], ["bo", "ada"]])
    for r in res[-3:]:
        assert_error(r, "NameError")


@stage(0)
def test_an_alias_hides_the_table_name():
    res = run(COMPANY + """
        SELECT emp.name FROM emp e;
        SELECT e.name FROM emp e WHERE emp.id = 1;
        SELECT x.name FROM emp e;
        SELECT e.name FROM emp e WHERE e.id = 1;
    """)
    for r in res[-4:-1]:
        assert_error(r, "NameError")
    assert_rows(res[-1], [["ada"]])


@stage(0)
def test_ambiguous_and_unknown_columns():
    res = run(COMPANY + """
        SELECT name FROM emp e JOIN dept d ON e.dept_id = d.id;
        SELECT id FROM emp JOIN dept ON dept_id = dept.id;
        SELECT budget, emp.name FROM emp JOIN dept ON dept_id = dept.id WHERE emp.id = 1;
        SELECT e.nope FROM emp e;
        CREATE TABLE e1 (k INTEGER);
        CREATE TABLE e2 (k INTEGER);
        SELECT k FROM e1 JOIN e2 ON e1.k = e2.k;
        SELECT * FROM e1 JOIN e2 ON k = 1;
    """)
    assert_error(res[-8], "NameError")
    assert_error(res[-7], "NameError")
    assert_rows(res[-6], [[1000.0, "ada"]])
    assert_error(res[-5], "NameError")
    assert_error(res[-2], "NameError")
    assert_error(res[-1], "NameError")


@stage(0)
def test_star_and_qualified_star_with_duplicate_output_names():
    res = run("""
        CREATE TABLE p (id INTEGER, v TEXT);
        CREATE TABLE q (id INTEGER, w TEXT);
        INSERT INTO p VALUES (1, 'a'), (2, 'b');
        INSERT INTO q VALUES (2, 'x'), (1, 'y'), (2, 'z');
        SELECT * FROM p JOIN q ON p.id = q.id;
        SELECT q.*, p.v FROM p JOIN q ON p.id = q.id;
        SELECT z.* FROM p;
        SELECT * FROM p JOIN q ON p.id = q.id ORDER BY id;
        SELECT * FROM p JOIN q ON p.id = q.id ORDER BY w DESC;
    """)
    assert_rows(res[4], [[1, "a", 1, "y"], [2, "b", 2, "x"], [2, "b", 2, "z"]],
                columns=["id", "v", "id", "w"])
    assert_rows(res[5], [[1, "y", "a"], [2, "x", "b"], [2, "z", "b"]], columns=["id", "w", "v"])
    assert_error(res[6], "NameError")
    assert_error(res[7], "NameError")
    assert_rows(res[8], [[2, "b", 2, "z"], [1, "a", 1, "y"], [2, "b", 2, "x"]])


@stage(0)
def test_on_may_only_reference_tables_joined_so_far():
    res = run(ABC + """
        SELECT * FROM a JOIN b ON a.x = c.z JOIN c ON TRUE;
        SELECT * FROM a JOIN b ON z = 1 JOIN c ON TRUE;
        SELECT a.x, y, z FROM a JOIN b ON b.y = 'q' JOIN c ON c.z = a.x;
        SELECT a.x, y FROM a LEFT JOIN b ON b.x = a.x AND a.x > 1;
    """)
    assert_error(res[-4], "NameError")
    assert_error(res[-3], "NameError")
    assert_rows(res[-2], [[1, "q", 1], [2, "q", 2]])
    assert_rows(res[-1], [[1, None], [2, "p"], [2, "r"]])


@stage(0)
def test_join_syntax_errors():
    res = run(ABC + """
        SELECT * FROM a, b;
        SELECT * FROM a RIGHT JOIN b ON TRUE;
        SELECT * FROM a FULL JOIN b ON TRUE;
        SELECT * FROM a JOIN b;
        SELECT * FROM a LEFT JOIN b;
        SELECT * FROM a CROSS JOIN b ON TRUE;
        SELECT * FROM a FULL OUTER JOIN b ON TRUE;
        SELECT COUNT(*) FROM a INNER JOIN b ON TRUE LEFT OUTER JOIN c ON FALSE;
    """)
    for r in res[-8:-1]:
        assert_error(r, "SyntaxError")
    assert_rows(res[-1], [[6]])


@stage(0)
def test_grouping_distinct_and_ordering_over_joins():
    res = run_ok(COMPANY + """
        SELECT d.name, COUNT(e.id), SUM(e.salary) FROM dept d LEFT JOIN emp e ON e.dept_id = d.id
          GROUP BY d.name ORDER BY d.name;
        SELECT DISTINCT d.name FROM emp e JOIN dept d ON e.dept_id = d.id;
        SELECT e.name FROM emp e JOIN dept d ON e.dept_id = d.id WHERE d.budget IS NOT NULL
          ORDER BY d.budget DESC, e.salary;
    """)
    assert_rows(res[-3], [["eng", 3, 750], ["legal", 0, None], ["ops", 2, 300], ["sales", 1, None]])
    assert_rows(res[-2], [["eng"], ["ops"], ["sales"]])
    assert_rows(res[-1], [["bo"], ["gus"], ["ada"], ["cy"], ["di"]])


@stage(0)
def test_on_condition_types():
    res = run(ABC + """
        SELECT * FROM a JOIN c ON a.x;
        SELECT * FROM a JOIN b ON a.x = b.y;
        CREATE TABLE empty_b (y TEXT);
        SELECT * FROM a JOIN empty_b ON a.x = empty_b.y;
        SELECT * FROM a LEFT JOIN empty_b ON a.x = empty_b.y;
        SELECT * FROM a JOIN c ON NULL;
        SELECT * FROM a LEFT JOIN c ON NULL;
    """)
    assert_error(res[-7], "TypeError")
    assert_error(res[-6], "TypeError")
    assert_rows(res[-4], [])
    assert_rows(res[-3], [[1, None], [2, None]])
    assert_rows(res[-2], [])
    assert_rows(res[-1], [[1, None], [2, None]])
