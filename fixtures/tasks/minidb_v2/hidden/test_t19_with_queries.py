"""Section 19 (stage 5): WITH and WITH RECURSIVE."""
from _support import COMPANY, assert_error, assert_rows, plan, run, run_ok, stage


@stage(5)
def test_with_names_chain_and_column_lists():
    res = run_ok(COMPANY + """
        WITH paid AS (SELECT name, salary, dept_id FROM emp WHERE salary >= 200)
        SELECT name FROM paid;
        WITH a AS (SELECT dept_id, SUM(salary) AS total FROM emp GROUP BY dept_id),
             b (d, t) AS (SELECT * FROM a WHERE total > 200)
        SELECT dept.name, b.t FROM b JOIN dept ON dept.id = b.d;
        WITH x (one, two) AS (SELECT 1, 2 UNION ALL SELECT 3, 4) SELECT two, one FROM x ORDER BY two DESC;
    """)
    assert_rows(res[-3], [["ada"], ["bo"], ["gus"]])
    assert_rows(res[-2], [["eng", 750], ["ops", 300]], columns=["name", "t"])
    assert_rows(res[-1], [[4, 3], [2, 1]], columns=["two", "one"])


@stage(5)
def test_with_names_hide_tables_and_are_scoped_to_the_statement():
    res = run(COMPANY + """
        WITH emp AS (SELECT 1 AS x) SELECT * FROM emp;
        SELECT COUNT(*) FROM emp;
        WITH d AS (SELECT id FROM dept WHERE budget > 400)
          SELECT name FROM emp WHERE dept_id IN (SELECT id FROM d) AND EXISTS (SELECT 1 FROM d WHERE d.id = 2);
        SELECT * FROM d;
        WITH a AS (SELECT 1 AS x), a AS (SELECT 2 AS x) SELECT * FROM a;
        WITH a (p, q) AS (SELECT 1) SELECT * FROM a;
        WITH a AS (SELECT * FROM b), b AS (SELECT 1 AS x) SELECT * FROM a;
    """)
    r = res[-7:]
    assert_rows(r[0], [[1]], columns=["x"])
    assert_rows(r[1], [[7]])
    assert_rows(r[2], [["ada"], ["bo"], ["cy"], ["di"], ["gus"]])
    assert_error(r[3], "NameError")
    assert_error(r[4], "NameError")
    assert_error(r[5], "SyntaxError")
    assert_error(r[6], "NameError")


@stage(5)
def test_with_everywhere_a_query_can_go():
    res = run_ok(COMPANY + """
        SELECT name FROM emp WHERE salary = (WITH m AS (SELECT MAX(salary) AS s FROM emp) SELECT s FROM m);
        SELECT * FROM (WITH t AS (SELECT id FROM dept) SELECT COUNT(*) AS c FROM t) AS x;
        CREATE TABLE copy (id INTEGER, name TEXT);
        INSERT INTO copy WITH r AS (SELECT id, name FROM emp WHERE dept_id = 2) SELECT * FROM r;
        SELECT * FROM copy;
        CREATE VIEW vw AS WITH r AS (SELECT name FROM dept) SELECT name FROM r WHERE name LIKE '%s%';
        SELECT * FROM vw;
        EXPLAIN WITH r AS (SELECT * FROM dept) SELECT * FROM emp e JOIN r ON r.id = e.dept_id;
    """)
    assert_rows(res[-8], [["ada"]])
    assert_rows(res[-7], [[4]])
    assert res[-5].rowcount == 2
    assert_rows(res[-4], [[3, "cy"], [4, "di"]])
    assert_rows(res[-2], [["ops"], ["sales"]])
    assert plan(res[-1]) == ["SCAN emp", "HASH JOIN r (id)"]


@stage(5)
def test_recursive_counting_and_round_order():
    res = run_ok("""
        WITH RECURSIVE n (x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < 5) SELECT x FROM n;
        WITH RECURSIVE t (a, b) AS (SELECT 1, 'x' UNION ALL SELECT 2, 'y'
                                    UNION ALL SELECT a + 10, b || '!' FROM t WHERE a < 20)
          SELECT * FROM t;
        WITH RECURSIVE f (i, fact) AS (SELECT 1, 1 UNION ALL SELECT i + 1, fact * (i + 1) FROM f WHERE i < 20)
          SELECT fact FROM f WHERE i = 20;
    """)
    assert_rows(res[0], [[1], [2], [3], [4], [5]], columns=["x"])
    assert_rows(res[1], [[1, "x"], [2, "y"], [11, "x!"], [12, "y!"], [21, "x!!"], [22, "y!!"]])
    assert_rows(res[2], [[2432902008176640000]])


@stage(5)
def test_recursive_hierarchy_walks_the_org_chart():
    r = run_ok(COMPANY + """
        WITH RECURSIVE chain (id, name, depth) AS (
            SELECT id, name, 0 FROM emp WHERE manager_id IS NULL
            UNION ALL
            SELECT e.id, e.name, c.depth + 1 FROM emp e JOIN chain c ON e.manager_id = c.id)
        SELECT name, depth FROM chain;
    """)[-1]
    assert_rows(r, [["ada", 0], ["bo", 1], ["cy", 1], ["ed", 1], ["gus", 1], ["di", 2], ["flo", 2]])


@stage(5)
def test_recursive_union_removes_duplicates_and_runaways_stop():
    res = run("""
        CREATE TABLE edges (src INTEGER, dst INTEGER);
        INSERT INTO edges VALUES (1, 2), (2, 3), (3, 1), (2, 4), (4, 2);
        WITH RECURSIVE reach (n) AS (SELECT 1 UNION SELECT e.dst FROM edges e JOIN reach r ON e.src = r.n)
          SELECT n FROM reach;
        WITH RECURSIVE dup (n) AS (SELECT 5 UNION SELECT 5 UNION SELECT n FROM dup) SELECT * FROM dup;
        CREATE TABLE two (k INTEGER);
        INSERT INTO two VALUES (1), (2);
        WITH RECURSIVE r (x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM r CROSS JOIN two) SELECT COUNT(*) FROM r;
        WITH RECURSIVE r (x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM r CROSS JOIN two WHERE x < 16)
          SELECT COUNT(*), MAX(x) FROM r;
    """)
    assert_rows(res[2], [[1], [2], [3], [4]])
    assert_rows(res[3], [[5]])
    assert_error(res[6], "RuntimeError")
    assert_rows(res[7], [[2 ** 16 - 1, 16]])


@stage(5)
def test_recursive_definition_errors():
    stmts = [
        ("WITH RECURSIVE r (x) AS (SELECT x FROM r UNION ALL SELECT 1) SELECT * FROM r", "SyntaxError"),
        ("WITH RECURSIVE r (x) AS (SELECT 1 UNION ALL SELECT a.x FROM r a JOIN r b ON TRUE) SELECT * FROM r",
         "SyntaxError"),
        ("WITH RECURSIVE r (x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM emp WHERE id IN (SELECT x FROM r)) "
         "SELECT * FROM r", "SyntaxError"),
        ("WITH RECURSIVE r (x) AS (SELECT 1 UNION ALL SELECT MAX(x) FROM r) SELECT * FROM r", "SyntaxError"),
        ("WITH RECURSIVE r (x) AS (SELECT 1 UNION ALL SELECT DISTINCT x FROM r) SELECT * FROM r", "SyntaxError"),
        ("WITH RECURSIVE r (x) AS (SELECT 1 UNION ALL SELECT x, x FROM r) SELECT * FROM r", "SyntaxError"),
        ("WITH RECURSIVE r (x) AS (SELECT 1 INTERSECT SELECT x FROM r) SELECT * FROM r", "SyntaxError"),
        ("WITH r (x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM r WHERE x < 3) SELECT * FROM r", "NameError"),
        ("WITH RECURSIVE r (x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM (SELECT * FROM r) s) SELECT * FROM r",
         "SyntaxError"),
        ("CREATE TABLE with (a INTEGER)", "SyntaxError"),
    ]
    res = run(COMPANY + "".join(s + ";\n" for s, _ in stmts))
    for (s, t), r in zip(stmts, res[-len(stmts):]):
        assert_error(r, t)


@stage(5)
def test_recursive_queries_generate_data_for_other_features():
    res = run_ok("""
        CREATE TABLE nums (n INTEGER PRIMARY KEY, sq INTEGER);
        INSERT INTO nums WITH RECURSIVE g (n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM g WHERE n < 3000)
          SELECT n, n * n FROM g;
        SELECT COUNT(*), SUM(sq), MAX(n) FROM nums WHERE n % 3 = 0;
        EXPLAIN SELECT sq FROM nums WHERE n = 77;
        SELECT sq FROM nums WHERE n = 77;
        WITH RECURSIVE g (n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM g WHERE n < 10)
          SELECT a.n * 10 + b.n AS v FROM g a JOIN g b ON b.n = a.n - 1 ORDER BY v DESC LIMIT 2;
    """)
    assert res[1].rowcount == 3000
    assert_rows(res[2], [[1000, sum((3 * k) ** 2 for k in range(1, 1001)), 3000]])
    assert plan(res[3]) == ["SEARCH nums USING INDEX nums_n_key (n = ?)"]
    assert_rows(res[4], [[5929]])
    assert_rows(res[5], [[109], [98]])


@stage(5, retired=6)
def test_with_and_view_column_lists_are_reported_in_lower_case():
    res = run_ok(COMPANY + """
        WITH Totals (Dept, Total) AS (SELECT dept_id, SUM(salary) FROM emp GROUP BY dept_id)
          SELECT * FROM totals WHERE dept = 1;
        CREATE VIEW Summary (Who, Pay) AS SELECT Name, Salary FROM emp WHERE id = 1;
        SELECT * FROM SUMMARY;
        SELECT Who, PAY AS Amount FROM summary;
    """)
    assert_rows(res[-4], [[1, 750]], columns=["dept", "total"])
    assert_rows(res[-2], [["ada", 300]], columns=["who", "pay"])
    assert_rows(res[-1], [["ada", 300]], columns=["who", "amount"])
