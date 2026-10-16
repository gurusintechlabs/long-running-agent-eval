"""Section 11 (stage 1): INSERT ... SELECT, derived tables, IF [NOT] EXISTS."""
from _support import COMPANY, assert_error, assert_rows, run, run_ok, stage


@stage(1)
def test_insert_select_with_and_without_column_list():
    res = run_ok(COMPANY + """
        CREATE TABLE rich (id INTEGER PRIMARY KEY, name TEXT);
        INSERT INTO rich SELECT id, name FROM emp WHERE salary >= 200;
        SELECT * FROM rich;
        CREATE TABLE t (a INTEGER, b TEXT DEFAULT 'd', c REAL);
        INSERT INTO t (c, a) SELECT salary, id FROM emp WHERE id <= 2;
        INSERT INTO t (a) SELECT id FROM emp WHERE id > 100;
        SELECT * FROM t;
    """)
    assert res[-6].rowcount == 3
    assert_rows(res[-5], [[1, "ada"], [2, "bo"], [7, "gus"]])
    assert res[-3].rowcount == 2
    assert res[-2].rowcount == 0
    assert_rows(res[-1], [[1, "d", 300.0], [2, "d", 200.0]])


@stage(1)
def test_insert_select_keeps_query_order_and_reads_before_writing():
    res = run_ok(COMPANY + """
        CREATE TABLE names (n TEXT);
        INSERT INTO names SELECT name FROM emp WHERE dept_id = 1 ORDER BY name DESC;
        SELECT * FROM names;
        CREATE TABLE nums (v INTEGER);
        INSERT INTO nums VALUES (1), (2);
        INSERT INTO nums SELECT v + 10 FROM nums;
        INSERT INTO nums SELECT v * 100 FROM nums WHERE v > 1;
        SELECT * FROM nums;
        CREATE TABLE ids (i INTEGER);
        INSERT INTO ids SELECT id FROM emp WHERE id < 3 UNION SELECT id FROM dept;
        SELECT * FROM ids;
    """)
    assert_rows(res[-9], [["gus"], ["bo"], ["ada"]])
    assert res[-6].rowcount == 2 and res[-5].rowcount == 3
    assert_rows(res[-4], [[1], [2], [11], [12], [200], [1100], [1200]])
    assert res[-2].rowcount == 4
    assert_rows(res[-1], [[1], [2], [3], [4]])


@stage(1)
def test_insert_select_errors_are_atomic():
    res = run(COMPANY + """
        CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        INSERT INTO t SELECT id FROM emp;
        INSERT INTO t (id) SELECT id, name FROM emp WHERE id > 100;
        INSERT INTO t SELECT dept_id, name FROM emp;
        INSERT INTO t SELECT id, NULL FROM emp WHERE id = 1;
        INSERT INTO t SELECT 1, name FROM emp;
        INSERT INTO t SELECT id, name FROM nope;
        INSERT INTO t SELECT id, name FROM emp WHERE id IN (1, 2);
        SELECT * FROM t;
    """)
    r = res[-8:]
    assert_error(r[0], "SyntaxError")
    assert_error(r[1], "SyntaxError")
    assert_error(r[2], "ConstraintError")
    assert_error(r[3], "ConstraintError")
    assert_error(r[4], "ConstraintError")
    assert_error(r[5], "NameError")
    assert r[6].rowcount == 2
    assert_rows(r[7], [[1, "ada"], [2, "bo"]])


@stage(1, retired=3)
def test_insert_select_wrong_type_is_a_type_error():
    res = run(COMPANY + """
        CREATE TABLE t (n INTEGER, s TEXT);
        INSERT INTO t SELECT name, id FROM emp;
        INSERT INTO t (n) SELECT budget FROM dept WHERE id = 1;
        SELECT COUNT(*) FROM t;
    """)
    assert_error(res[-3], "TypeError")
    assert_error(res[-2], "TypeError")
    assert_rows(res[-1], [[0]])


@stage(1)
def test_derived_tables():
    res = run(COMPANY + """
        SELECT x.n, x.total FROM (SELECT dept_id AS n, SUM(salary) AS total FROM emp GROUP BY dept_id) AS x
          WHERE x.total > 250;
        SELECT d.name, s.cnt FROM dept d JOIN (SELECT dept_id, COUNT(*) AS cnt FROM emp GROUP BY dept_id) s
          ON s.dept_id = d.id;
        SELECT s.v, d.name FROM (SELECT id AS v FROM dept ORDER BY id DESC) s LEFT JOIN dept d ON d.id = s.v - 1;
        SELECT * FROM (SELECT 1 AS a, 'b' AS b) one;
        SELECT * FROM (SELECT id FROM dept);
    """)
    assert_rows(res[-5], [[1, 750], [2, 300]], columns=["n", "total"])
    assert_rows(res[-4], [["eng", 3], ["ops", 2], ["sales", 1]])
    assert_rows(res[-3], [[4, "sales"], [3, "ops"], [2, "eng"], [1, None]])
    assert_rows(res[-2], [[1, "b"]], columns=["a", "b"])
    assert_error(res[-1], "SyntaxError")


@stage(1)
def test_derived_table_columns_and_scoping():
    res = run(COMPANY + """
        SELECT * FROM (SELECT id, id FROM dept WHERE id = 1) x;
        SELECT id FROM (SELECT id, id FROM dept) x;
        SELECT * FROM dept d JOIN (SELECT * FROM emp WHERE emp.dept_id = d.id) e ON TRUE;
        SELECT name FROM dept d WHERE EXISTS (SELECT 1 FROM (SELECT * FROM emp WHERE emp.dept_id = d.id) x);
        SELECT * FROM dept JOIN (SELECT 1 AS a) dept ON TRUE;
        SELECT x.name FROM (SELECT name FROM emp WHERE id = 1) AS x JOIN (SELECT name FROM dept WHERE id = 1) AS y
          ON TRUE;
    """)
    assert_rows(res[-6], [[1, 1]], columns=["id", "id"])
    assert_error(res[-5], "NameError")
    assert_error(res[-4], "NameError")
    assert_rows(res[-3], [["eng"], ["ops"], ["sales"]])
    assert_error(res[-2], "NameError")
    assert_rows(res[-1], [["ada"]])


@stage(1)
def test_a_group_reports_the_grouping_value_of_its_first_row():
    res = run_ok("""
        CREATE TABLE u (i INTEGER, r REAL);
        INSERT INTO u VALUES (NULL, 1.0), (1, NULL), (2, NULL), (NULL, 2.0);
        SELECT v, COUNT(*) FROM (SELECT COALESCE(i, r) AS v FROM u) x GROUP BY v;
    """)
    assert_rows(res[-1], [[1.0, 2], [2, 2]])


@stage(1)
def test_if_not_exists_and_if_exists_for_tables():
    res = run(COMPANY + """
        CREATE TABLE IF NOT EXISTS emp (x INTEGER);
        SELECT COUNT(*) FROM emp;
        CREATE TABLE IF NOT EXISTS t3 (a INTEGER);
        INSERT INTO t3 VALUES (1);
        CREATE TABLE IF NOT EXISTS t3 (a INTEGER, b INTEGER);
        SELECT * FROM t3;
        DROP TABLE IF EXISTS nope;
        DROP TABLE IF EXISTS t3;
        SELECT * FROM t3;
        CREATE TABLE IF NOT EXISTS emp (x VARCHAR);
        DROP TABLE nope;
        CREATE TABLE emp (x INTEGER);
    """)
    r = res[-12:]
    assert r[0].raw == {"ok": True}
    assert_rows(r[1], [[7]])
    assert r[2].ok and r[4].raw == {"ok": True}
    assert_rows(r[5], [[1]], columns=["a"])
    assert r[6].raw == {"ok": True} and r[7].raw == {"ok": True}
    assert_error(r[8], "NameError")
    assert_error(r[9], "SyntaxError")
    assert_error(r[10], "NameError")
    assert_error(r[11], "NameError")
