"""Section 10 (stage 1): UNION [ALL], INTERSECT, EXCEPT."""
from _support import COMPANY, assert_error, assert_rows, run, run_ok, stage


@stage(1)
def test_union_all_and_union_keep_first_occurrences_in_order():
    res = run_ok(COMPANY + """
        SELECT dept_id FROM emp WHERE id <= 3 UNION ALL SELECT id FROM dept WHERE id >= 2;
        SELECT dept_id FROM emp WHERE id <= 3 UNION SELECT id FROM dept WHERE id >= 2;
        SELECT salary FROM emp UNION SELECT budget FROM dept;
    """)
    assert_rows(res[-3], [[1], [1], [2], [2], [3], [4]], columns=["dept_id"])
    assert_rows(res[-2], [[1], [2], [3], [4]], columns=["dept_id"])
    assert_rows(res[-1], [[300], [200], [150], [None], [100], [250], [1000.0], [500.0]])


@stage(1)
def test_intersect_and_except():
    res = run_ok(COMPANY + """
        SELECT dept_id FROM emp INTERSECT SELECT id FROM dept;
        SELECT id FROM dept EXCEPT SELECT dept_id FROM emp;
        SELECT dept_id FROM emp EXCEPT SELECT id FROM dept;
        SELECT manager_id FROM emp INTERSECT SELECT manager_id FROM emp;
    """)
    assert_rows(res[-4], [[1], [2], [3]])
    assert_rows(res[-3], [[4]])
    assert_rows(res[-2], [[None]])
    assert_rows(res[-1], [[None], [1], [3], [2]])


@stage(1)
def test_intersect_binds_tighter_than_union_and_except():
    res = run_ok("""
        SELECT 1 UNION SELECT 2 INTERSECT SELECT 3;
        SELECT 1 UNION ALL SELECT 2 EXCEPT SELECT 1;
        SELECT 3 EXCEPT SELECT 3 UNION SELECT 3;
        SELECT 1 EXCEPT SELECT 2 INTERSECT SELECT 2;
        SELECT 5 UNION ALL SELECT 5 UNION ALL SELECT 4;
    """)
    assert_rows(res[0], [[1]])
    assert_rows(res[1], [[2]])
    assert_rows(res[2], [[3]])
    assert_rows(res[3], [[1]])
    assert_rows(res[4], [[5], [5], [4]])


@stage(1)
def test_order_by_and_limit_apply_to_the_whole_result():
    res = run(COMPANY + """
        SELECT name, salary FROM emp WHERE dept_id = 1
          UNION ALL SELECT name, budget FROM dept WHERE budget IS NOT NULL ORDER BY 2 DESC LIMIT 3;
        SELECT name FROM emp WHERE id < 3 UNION SELECT name FROM dept ORDER BY name LIMIT 2 OFFSET 1;
        SELECT name FROM emp UNION SELECT name FROM dept ORDER BY salary;
        SELECT name FROM emp UNION SELECT name FROM dept ORDER BY 2;
        SELECT 1 AS a UNION SELECT 2 AS b ORDER BY b;
        SELECT 1 AS a UNION SELECT 2 AS b ORDER BY a DESC;
        SELECT id AS x, name AS x FROM dept UNION SELECT 1, 'a' ORDER BY x;
    """)
    assert_rows(res[-7], [["eng", 1000.0], ["ops", 500.0], ["ada", 300]], columns=["name", "salary"])
    assert_rows(res[-6], [["bo"], ["eng"]])
    assert_error(res[-5], "SyntaxError")
    assert_error(res[-4], "SyntaxError")
    assert_error(res[-3], "SyntaxError")
    assert_rows(res[-2], [[2], [1]], columns=["a"])
    assert_error(res[-1], "NameError")


@stage(1)
def test_set_operation_syntax_errors():
    res = run(COMPANY + """
        SELECT id, name FROM dept UNION SELECT id FROM emp;
        SELECT id FROM dept ORDER BY id UNION SELECT 1;
        SELECT id FROM dept LIMIT 1 UNION SELECT 1;
        SELECT 1 INTERSECT ALL SELECT 1;
        SELECT 1 EXCEPT ALL SELECT 1;
        (SELECT 1) UNION (SELECT 2);
        SELECT 1 UNION;
        SELECT nope FROM dept UNION SELECT 1;
    """)
    for r in res[-8:-1]:
        assert_error(r, "SyntaxError")
    assert_error(res[-1], "NameError")


@stage(1)
def test_duplicates_follow_the_distinct_rule_and_values_are_not_type_checked():
    res = run_ok("""
        SELECT 1 UNION SELECT 1.0;
        SELECT 1 UNION SELECT TRUE;
        SELECT NULL UNION SELECT NULL;
        SELECT 1, 'a' UNION SELECT 1, 'b';
        SELECT 'x' UNION ALL SELECT 2;
        SELECT 2.0 INTERSECT SELECT 2;
    """)
    assert_rows(res[0], [[1]])
    assert_rows(res[1], [[1], [True]])
    assert_rows(res[2], [[None]])
    assert_rows(res[3], [[1, "a"], [1, "b"]])
    assert_rows(res[4], [["x"], [2]])
    assert_rows(res[5], [[2.0]])


@stage(1)
def test_set_operations_in_subqueries_derived_tables_and_with_grouping():
    res = run_ok(COMPANY + """
        SELECT COUNT(*) FROM (SELECT id FROM emp UNION SELECT id FROM dept) u;
        SELECT name FROM emp WHERE id IN (SELECT id FROM dept INTERSECT SELECT manager_id FROM emp);
        SELECT dept_id, COUNT(*) FROM emp WHERE dept_id IS NOT NULL GROUP BY dept_id
          UNION ALL SELECT NULL, COUNT(*) FROM dept;
        SELECT DISTINCT active FROM emp UNION ALL SELECT DISTINCT active FROM emp WHERE id = 4;
    """)
    assert_rows(res[-4], [[7]])
    assert_rows(res[-3], [["ada"], ["bo"], ["cy"]])
    assert_rows(res[-2], [[1, 3], [2, 2], [3, 1], [None, 4]])
    assert_rows(res[-1], [[True], [False], [False]])
