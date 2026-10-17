"""Section 20 (stage 5): window functions."""
from _support import COMPANY, assert_error, assert_rows, run, run_ok, stage


@stage(5)
def test_row_number_rank_and_dense_rank_keep_the_row_order():
    r = run_ok(COMPANY + """
        SELECT name, ROW_NUMBER() OVER (ORDER BY salary DESC) AS rn, RANK() OVER (ORDER BY salary DESC) AS rk,
               DENSE_RANK() OVER (ORDER BY salary DESC) AS dr
          FROM emp WHERE salary IS NOT NULL;
    """)[-1]
    assert_rows(r, [["ada", 1, 1, 1], ["bo", 3, 3, 3], ["cy", 4, 4, 4], ["di", 5, 4, 4], ["flo", 6, 6, 5],
                    ["gus", 2, 2, 2]], columns=["name", "rn", "rk", "dr"])


@stage(5)
def test_partitions_and_null_placement():
    res = run_ok(COMPANY + """
        SELECT name, dept_id, ROW_NUMBER() OVER (PARTITION BY dept_id ORDER BY salary DESC) AS rn
          FROM emp ORDER BY dept_id NULLS FIRST, 3;
        SELECT name, RANK() OVER (ORDER BY salary) FROM emp ORDER BY id;
        SELECT name, RANK() OVER (ORDER BY salary DESC NULLS LAST) FROM emp ORDER BY id;
        SELECT name, ROW_NUMBER() OVER (ORDER BY 1) FROM emp WHERE id <= 3;
    """)
    assert_rows(res[-4], [["flo", None, 1], ["ada", 1, 1], ["gus", 1, 2], ["bo", 1, 3], ["cy", 2, 1],
                          ["di", 2, 2], ["ed", 3, 1]])
    assert_rows(res[-3], [["ada", 6], ["bo", 4], ["cy", 2], ["di", 2], ["ed", 7], ["flo", 1], ["gus", 5]],
                columns=["name", "rank"])
    assert_rows(res[-2], [["ada", 1], ["bo", 3], ["cy", 4], ["di", 4], ["ed", 7], ["flo", 6], ["gus", 2]])
    assert_rows(res[-1], [["ada", 1], ["bo", 2], ["cy", 3]])


@stage(5)
def test_window_aggregates_running_totals_with_peers_and_whole_partitions():
    res = run_ok(COMPANY + """
        SELECT name, salary, SUM(salary) OVER (ORDER BY salary) AS run FROM emp
          WHERE salary IS NOT NULL ORDER BY salary, name;
        SELECT name, COUNT(*) OVER () AS n, AVG(salary) OVER (PARTITION BY dept_id) AS a,
               MAX(salary) OVER (PARTITION BY dept_id ORDER BY id) AS m, COUNT(salary) OVER (ORDER BY id) AS c
          FROM emp;
    """)
    assert_rows(res[-2], [["flo", 100, 100], ["cy", 150, 400], ["di", 150, 400], ["bo", 200, 600],
                          ["gus", 250, 850], ["ada", 300, 1150]])
    assert_rows(res[-1], [["ada", 7, 250.0, 300, 1], ["bo", 7, 250.0, 300, 2], ["cy", 7, 150.0, 150, 3],
                          ["di", 7, 150.0, 150, 4], ["ed", 7, None, None, 4], ["flo", 7, 100.0, 100, 5],
                          ["gus", 7, 250.0, 300, 6]])


@stage(5)
def test_lag_and_lead():
    r = run_ok(COMPANY + """
        SELECT name, LAG(name) OVER (ORDER BY id), LEAD(name, 2, 'none') OVER (ORDER BY id),
               LAG(salary, 0) OVER (ORDER BY id), LAG(salary, 1, -salary) OVER (PARTITION BY dept_id ORDER BY id)
          FROM emp ORDER BY id;
    """)[-1]
    assert_rows(r, [["ada", None, "cy", 300, -300], ["bo", "ada", "di", 200, 300],
                    ["cy", "bo", "ed", 150, -150], ["di", "cy", "flo", 150, 150],
                    ["ed", "di", "gus", None, None], ["flo", "ed", "none", 100, -100],
                    ["gus", "flo", "none", 250, 200]],
                columns=["name", "lag", "lead", "lag", "lag"])


@stage(5)
def test_windows_in_grouped_queries_and_with_distinct_order_limit():
    res = run_ok(COMPANY + """
        SELECT dept_id, SUM(salary) AS total, RANK() OVER (ORDER BY SUM(salary) DESC NULLS LAST) AS r
          FROM emp WHERE dept_id IS NOT NULL GROUP BY dept_id;
        SELECT dept_id, COUNT(*) AS n, SUM(COUNT(*)) OVER () AS all_rows FROM emp GROUP BY dept_id ORDER BY n DESC, 1;
        SELECT DISTINCT dept_id, COUNT(*) OVER (PARTITION BY dept_id) AS c FROM emp ORDER BY c DESC, dept_id;
        SELECT name, ROW_NUMBER() OVER (ORDER BY id) AS rn FROM emp ORDER BY id DESC LIMIT 2;
        SELECT name FROM emp ORDER BY ROW_NUMBER() OVER (ORDER BY name DESC) LIMIT 3;
        SELECT name, ROW_NUMBER() OVER () * 10 AS t FROM emp WHERE dept_id = 2;
    """)
    assert_rows(res[-6], [[1, 750, 1], [2, 300, 2], [3, None, 3]])
    assert_rows(res[-5], [[1, 3, 7], [2, 2, 7], [3, 1, 7], [None, 1, 7]])
    assert_rows(res[-4], [[1, 3], [2, 2], [3, 1], [None, 1]])
    assert_rows(res[-3], [["gus", 7], ["flo", 6]])
    assert_rows(res[-2], [["gus"], ["flo"], ["ed"]])
    assert_rows(res[-1], [["cy", 10], ["di", 20]])


@stage(5)
def test_where_window_functions_are_not_allowed():
    stmts = [
        "SELECT name FROM emp WHERE ROW_NUMBER() OVER () > 1",
        "SELECT dept_id FROM emp GROUP BY ROW_NUMBER() OVER ()",
        "SELECT dept_id FROM emp GROUP BY dept_id HAVING RANK() OVER (ORDER BY dept_id) = 1",
        "SELECT * FROM emp e JOIN dept d ON ROW_NUMBER() OVER () = d.id",
        "UPDATE emp SET salary = ROW_NUMBER() OVER ()",
        "INSERT INTO dept VALUES (ROW_NUMBER() OVER (), 'x', 1.0)",
        "SELECT SUM(ROW_NUMBER() OVER ()) FROM emp",
        "SELECT ROW_NUMBER() OVER (ORDER BY RANK() OVER ()) FROM emp",
        "SELECT LAG(ROW_NUMBER() OVER ()) OVER () FROM emp",
        "SELECT ROW_NUMBER() FROM emp",
        "SELECT LAG(name) FROM emp",
        "SELECT COUNT(DISTINCT name) OVER () FROM emp",
        "SELECT LAG(name, id) OVER (ORDER BY id) FROM emp",
        "SELECT ROW_NUMBER() OVER (PARTITION id) FROM emp",
    ]
    res = run(COMPANY + "".join(s + ";\n" for s in stmts))
    for s, r in zip(stmts, res[-len(stmts):]):
        assert_error(r, "SyntaxError")


@stage(5)
def test_window_ordering_type_rule_applies_within_a_partition():
    res = run("""
        CREATE TABLE m (g INTEGER, t TEXT, i INTEGER);
        INSERT INTO m VALUES (1, 'a', NULL), (1, NULL, 5), (2, 'b', NULL), (3, NULL, 7);
        SELECT g, ROW_NUMBER() OVER (PARTITION BY g ORDER BY COALESCE(t, i)) FROM m;
        SELECT g, ROW_NUMBER() OVER (PARTITION BY g, t IS NULL ORDER BY COALESCE(t, i)) FROM m;
    """)
    assert_error(res[2], "TypeError")
    assert_rows(res[3], [[1, 1], [1, 1], [2, 1], [3, 1]])


@stage(5)
def test_windows_over_views_and_generated_series():
    res = run_ok(COMPANY + """
        CREATE VIEW pay AS SELECT d.name AS dept, e.name, e.salary FROM emp e JOIN dept d ON d.id = e.dept_id;
        SELECT dept, name, salary - AVG(salary) OVER (PARTITION BY dept) AS diff FROM pay
          WHERE salary IS NOT NULL ORDER BY dept, diff DESC;
        WITH RECURSIVE s (i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM s WHERE i < 2000)
          SELECT k, COUNT(*), MAX(run) FROM
            (SELECT i % 4 AS k, SUM(i) OVER (PARTITION BY i % 4 ORDER BY i) AS run FROM s) x GROUP BY k;
    """)
    assert_rows(res[-2], [["eng", "ada", 50.0], ["eng", "gus", 0.0], ["eng", "bo", -50.0],
                          ["ops", "cy", 0.0], ["ops", "di", 0.0]])
    expect = [[k, 500, sum(i for i in range(1, 2001) if i % 4 == k)] for k in (1, 2, 3, 0)]
    assert_rows(res[-1], expect)
