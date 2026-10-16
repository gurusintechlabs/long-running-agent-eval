"""Section 6 (stage 0): aggregates, GROUP BY, HAVING, grouped-query rules."""
from _support import COMPANY, assert_error, assert_rows, query, run, run_ok, stage


@stage(0)
def test_basic_aggregates():
    r = query(COMPANY, "SELECT COUNT(*), COUNT(salary), SUM(salary), AVG(salary), MIN(salary), "
                       "MAX(salary), MIN(name), MAX(name), MIN(active), MAX(active) FROM emp;")
    assert_rows(r, [[7, 6, 1150, 1150 / 6, 100, 300, "ada", "gus", False, True]],
                columns=["count", "count", "sum", "avg", "min", "max", "min", "max", "min", "max"])


@stage(0)
def test_aggregates_over_no_rows_and_only_nulls():
    res = run_ok(COMPANY + """
        SELECT COUNT(*), COUNT(salary), SUM(salary), AVG(salary), MIN(salary), MAX(name) FROM emp WHERE id > 99;
        SELECT COUNT(salary), SUM(salary), AVG(salary), COUNT(*) FROM emp WHERE salary IS NULL;
        SELECT AVG(id), TYPEOF(AVG(id)), TYPEOF(SUM(id)), TYPEOF(COUNT(*)) FROM emp;
    """)
    assert_rows(res[-3], [[0, 0, None, None, None, None]])
    assert_rows(res[-2], [[0, None, None, 1]])
    assert_rows(res[-1], [[4.0, "REAL", "INTEGER", "INTEGER"]])


@stage(0)
def test_distinct_aggregates():
    r = query(COMPANY, "SELECT COUNT(DISTINCT salary), SUM(DISTINCT salary), AVG(DISTINCT salary), "
                       "MIN(DISTINCT salary), COUNT(DISTINCT dept_id), MAX(DISTINCT name) FROM emp;")
    assert_rows(r, [[5, 1000, 200.0, 100, 3, "gus"]])


@stage(0)
def test_integer_sum_is_exact_and_only_the_total_must_fit():
    res = run("""
        CREATE TABLE n (v INTEGER);
        INSERT INTO n VALUES (9223372036854775807), (1), (-2);
        SELECT SUM(v), AVG(v) FROM n;
        INSERT INTO n VALUES (5);
        SELECT SUM(v) FROM n;
        SELECT COUNT(v), MAX(v) FROM n;
    """)
    assert_rows(res[2], [[9223372036854775806, 9223372036854775806 / 3]])
    assert_error(res[4], "RuntimeError")
    assert_rows(res[5], [[4, 9223372036854775807]])


@stage(0)
def test_real_sum_adds_doubles_in_row_order():
    res = run_ok("""
        CREATE TABLE f (v REAL, w INTEGER);
        INSERT INTO f VALUES (10000000000000000.0, 1), (1.0, 2), (-10000000000000000.0, 3);
        SELECT SUM(v), AVG(v), TYPEOF(SUM(v)) FROM f;
        SELECT SUM(v) FROM f WHERE w > 1;
        CREATE TABLE g (i INTEGER, r REAL);
        INSERT INTO g VALUES (2, NULL), (NULL, 0.5), (3, NULL);
        SELECT SUM(COALESCE(i, r)), TYPEOF(SUM(COALESCE(i, r))), AVG(COALESCE(i, r)) FROM g;
    """)
    assert_rows(res[2], [[0.0, 0.0, "REAL"]])
    assert_rows(res[3], [[-10000000000000000.0]])
    assert_rows(res[-1], [[5.5, "REAL", 5.5 / 3]])


@stage(0)
def test_min_max_ties_and_type_errors():
    res = run("""
        CREATE TABLE u (i INTEGER, r REAL, t TEXT);
        INSERT INTO u VALUES (NULL, 1.0, 'b'), (1, NULL, NULL), (NULL, 3.5, 'a');
        SELECT MIN(COALESCE(i, r)) AS lo, MAX(COALESCE(r, i)) AS hi, MIN(t), MAX(t) FROM u WHERE r IS NULL OR r < 2;
        SELECT MAX(COALESCE(t, i)) FROM u;
        SELECT SUM(t) FROM u;
        SELECT AVG(t) FROM u WHERE t IS NULL;
        SELECT MIN(COALESCE(t, i)) FROM u WHERE t = 'a';
    """)
    assert_rows(res[2], [[1.0, 1.0, "b", "b"]], columns=["lo", "hi", "min", "max"])
    assert_error(res[3], "TypeError")
    assert_error(res[4], "TypeError")
    assert_rows(res[5], [[None]])
    assert_rows(res[6], [["a"]])


@stage(0)
def test_group_by_order_of_first_rows_and_null_group():
    res = run_ok(COMPANY + """
        SELECT dept_id, COUNT(*), SUM(salary) FROM emp GROUP BY dept_id;
        SELECT emp.dept_id AS d, MIN(name) FROM emp GROUP BY emp.dept_id;
        SELECT dept_id FROM emp WHERE id < 0 GROUP BY dept_id;
    """)
    assert_rows(res[-3], [[1, 3, 750], [2, 2, 300], [3, 1, None], [None, 1, 100]],
                columns=["dept_id", "count", "sum"])
    assert_rows(res[-2], [[1, "ada"], [2, "cy"], [3, "ed"], [None, "flo"]], columns=["d", "min"])
    assert_rows(res[-1], [])


@stage(0)
def test_group_by_several_columns_with_expressions_over_aggregates():
    r = query(COMPANY, "SELECT dept_id, active, COUNT(*) * 10 AS c, MAX(salary) - MIN(salary) AS spread "
                       "FROM emp GROUP BY dept_id, active;")
    assert_rows(r, [[1, True, 30, 100], [2, True, 10, 0], [2, False, 10, 0], [3, True, 10, None],
                    [None, True, 10, 0]])


@stage(0)
def test_having_and_order_by_in_grouped_queries():
    res = run_ok(COMPANY + """
        SELECT dept_id, COUNT(*) AS n FROM emp GROUP BY dept_id HAVING COUNT(*) > 1 ORDER BY n;
        SELECT dept_id FROM emp GROUP BY dept_id HAVING SUM(salary) > 250 ORDER BY MAX(salary) DESC;
        SELECT dept_id, COUNT(*) FROM emp WHERE dept_id IS NOT NULL GROUP BY dept_id ORDER BY 2, dept_id DESC;
        SELECT active, COUNT(*) FROM emp GROUP BY active HAVING active;
        SELECT 1 AS one FROM emp HAVING COUNT(*) > 5;
        SELECT 1 AS one FROM emp HAVING TRUE;
    """)
    assert_rows(res[-6], [[2, 2], [1, 3]])
    assert_rows(res[-5], [[1], [2]])
    assert_rows(res[-4], [[3, 1], [2, 2], [1, 3]])
    assert_rows(res[-3], [[True, 6]])
    assert_rows(res[-2], [[1]])
    assert_rows(res[-1], [[1]])


@stage(0)
def test_grouped_query_rules():
    stmts = [
        ("SELECT name, COUNT(*) FROM emp GROUP BY dept_id", "SyntaxError"),
        ("SELECT * FROM emp GROUP BY id", "SyntaxError"),
        ("SELECT COUNT(*) FROM emp WHERE COUNT(*) > 1", "SyntaxError"),
        ("SELECT dept_id FROM emp GROUP BY COUNT(*)", "SyntaxError"),
        ("SELECT SUM(COUNT(*)) FROM emp", "SyntaxError"),
        ("SELECT dept_id FROM emp GROUP BY 1", "SyntaxError"),
        ("SELECT dept_id + 1 FROM emp GROUP BY dept_id + 1", "SyntaxError"),
        ("SELECT name FROM emp HAVING TRUE", "SyntaxError"),
        ("SELECT name FROM emp ORDER BY COUNT(*)", "SyntaxError"),
        ("SELECT dept_id FROM emp GROUP BY dept_id ORDER BY salary", "SyntaxError"),
        ("SELECT e.name FROM emp e JOIN dept d ON COUNT(*) > 0", "SyntaxError"),
        ("SELECT dept_id, SUM(salary) FROM emp GROUP BY nope", "NameError"),
        ("SELECT COUNT(nope) FROM emp", "NameError"),
        ("SELECT COUNT(*, id) FROM emp", "SyntaxError"),
        ("SELECT SUM(*) FROM emp", "SyntaxError"),
        ("SELECT SUM(id, id) FROM emp", "SyntaxError"),
    ]
    res = run(COMPANY + "".join(s + ";\n" for s, _ in stmts))
    for (s, t), r in zip(stmts, res[-len(stmts):]):
        assert_error(r, t)


@stage(0)
def test_aggregates_without_from_see_one_empty_row():
    res = run("SELECT COUNT(*); SELECT SUM(5), MAX('a'), AVG(2), COUNT(NULL), MIN(NULL);")
    assert_rows(res[0], [[1]])
    assert_rows(res[1], [[5, "a", 2.0, 0, None]])
