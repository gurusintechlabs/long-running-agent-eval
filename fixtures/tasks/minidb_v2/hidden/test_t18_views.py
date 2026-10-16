"""Section 18 (stage 5): views."""
from _support import COMPANY, Session, assert_error, assert_rows, plan, run, run_ok, stage


@stage(5)
def test_views_reflect_current_data_and_keep_query_order():
    res = run_ok(COMPANY + """
        CREATE VIEW well_paid AS SELECT name, salary FROM emp WHERE salary >= 200 ORDER BY salary DESC;
        SELECT * FROM well_paid;
        INSERT INTO emp (id, name, salary) VALUES (8, 'hal', 260);
        UPDATE emp SET salary = 100 WHERE name = 'ada';
        SELECT * FROM well_paid;
        SELECT name FROM well_paid WHERE salary < 255;
    """)
    assert_rows(res[-5], [["ada", 300], ["gus", 250], ["bo", 200]], columns=["name", "salary"])
    assert_rows(res[-2], [["hal", 260], ["gus", 250], ["bo", 200]])
    assert_rows(res[-1], [["gus"], ["bo"]])


@stage(5)
def test_view_column_lists_namespace_and_if_not_exists():
    res = run(COMPANY + """
        CREATE VIEW v (who, pay) AS SELECT name, salary FROM emp WHERE id <= 2;
        SELECT * FROM v;
        CREATE VIEW v2 (a) AS SELECT name, salary FROM emp;
        CREATE VIEW v3 (a, a) AS SELECT name, salary FROM emp;
        CREATE VIEW v4 AS SELECT nope FROM emp;
        CREATE VIEW emp AS SELECT 1;
        CREATE TABLE v (x INTEGER);
        CREATE VIEW IF NOT EXISTS v AS SELECT 1 AS other;
        CREATE VIEW IF NOT EXISTS dept AS SELECT 1 AS other;
        CREATE TABLE IF NOT EXISTS v (x INTEGER);
        SELECT * FROM v;
        CREATE VIEW v5 AS SELECT d.name, COUNT(*) AS n FROM dept d JOIN emp e ON e.dept_id = d.id GROUP BY d.name;
        SELECT * FROM v5 ORDER BY n DESC;
    """)
    r = res[-13:]
    assert r[0].ok
    assert_rows(r[1], [["ada", 300], ["bo", 200]], columns=["who", "pay"])
    assert_error(r[2], "SyntaxError")
    assert_error(r[3], "NameError")
    assert_error(r[4], "NameError")
    assert_error(r[5], "NameError")
    assert_error(r[6], "NameError")
    assert r[7].raw == {"ok": True} and r[8].raw == {"ok": True} and r[9].raw == {"ok": True}
    assert_rows(r[10], [["ada", 300], ["bo", 200]], columns=["who", "pay"])
    assert_rows(r[12], [["eng", 3], ["ops", 2], ["sales", 1]])


@stage(5)
def test_views_in_joins_subqueries_other_views_and_plans():
    res = run_ok(COMPANY + """
        CREATE VIEW heads AS SELECT dept_id, COUNT(*) AS n FROM emp GROUP BY dept_id;
        CREATE VIEW big_depts AS SELECT * FROM heads WHERE n >= 2;
        SELECT d.name, h.n FROM dept d JOIN heads h ON h.dept_id = d.id;
        SELECT name FROM dept WHERE id IN (SELECT dept_id FROM big_depts);
        SELECT b.dept_id, x.c FROM big_depts b JOIN (SELECT COUNT(*) AS c FROM heads) x ON TRUE;
        EXPLAIN SELECT d.name, h.n FROM dept d JOIN heads h ON h.dept_id = d.id;
        EXPLAIN SELECT * FROM heads h JOIN dept d ON d.id = h.dept_id WHERE h.dept_id = 1;
        EXPLAIN SELECT * FROM big_depts;
    """)
    assert_rows(res[-6], [["eng", 3], ["ops", 2], ["sales", 1]])
    assert_rows(res[-5], [["eng"], ["ops"]])
    assert_rows(res[-4], [[1, 4], [2, 4]])
    assert plan(res[-3]) == ["SCAN dept", "HASH JOIN heads (dept_id)"]
    assert plan(res[-2]) == ["SCAN heads", "SEARCH dept USING INDEX dept_id_key (id = ?)"]
    assert plan(res[-1]) == ["SCAN big_depts"]


@stage(5)
def test_views_follow_schema_changes():
    res = run(COMPANY + """
        CREATE VIEW all_dept AS SELECT * FROM dept;
        CREATE VIEW names AS SELECT name, budget FROM dept;
        ALTER TABLE dept ADD COLUMN floor INTEGER DEFAULT 3;
        SELECT * FROM all_dept WHERE id = 1;
        ALTER TABLE dept DROP COLUMN budget;
        SELECT * FROM names;
        SELECT * FROM all_dept WHERE id = 1;
        DROP TABLE dept;
        SELECT * FROM all_dept;
        CREATE TABLE dept (id INTEGER, name TEXT, budget REAL);
        INSERT INTO dept VALUES (9, 'new', 1.5);
        SELECT * FROM names;
    """)
    r = res[-12:]
    assert_rows(r[3], [[1, "eng", 1000.0, 3]], columns=["id", "name", "budget", "floor"])
    assert_error(r[5], "NameError")
    assert_rows(r[6], [[1, "eng", 3]], columns=["id", "name", "floor"])
    assert r[7].ok
    assert_error(r[8], "NameError")
    assert_rows(r[11], [["new", 1.5]])


@stage(5)
def test_views_cannot_be_written_or_dropped_as_tables():
    res = run(COMPANY + """
        CREATE VIEW v AS SELECT id, name FROM emp;
        INSERT INTO v VALUES (9, 'x');
        UPDATE v SET name = 'x';
        DELETE FROM v;
        CREATE INDEX vi ON v (id);
        ALTER TABLE v ADD COLUMN c INTEGER;
        DROP TABLE v;
        DROP TABLE IF EXISTS v;
        DROP VIEW emp;
        DROP VIEW IF EXISTS emp;
        DROP VIEW IF EXISTS nope;
        DROP VIEW nope;
        DROP VIEW v;
        SELECT * FROM v;
    """)
    r = res[-14:]
    assert r[0].ok
    for x in r[1:10]:
        assert_error(x, "NameError")
    assert r[10].raw == {"ok": True}
    assert_error(r[11], "NameError")
    assert r[12].raw == {"ok": True}
    assert_error(r[13], "NameError")


@stage(5)
def test_views_in_transactions_and_durable_storage(tmp_path):
    path = str(tmp_path / "views.db")
    res = run(COMPANY + """
        CREATE VIEW keep AS SELECT name FROM emp WHERE dept_id = 2;
        BEGIN;
        CREATE VIEW temp_v AS SELECT 1 AS one;
        DROP VIEW keep;
        ROLLBACK;
        SELECT * FROM temp_v;
        SELECT * FROM keep;
        CREATE VIEW (bad) AS SELECT 1;
    """, args=("--db", path))
    assert_error(res[-3], "NameError")
    assert_rows(res[-2], [["cy"], ["di"]])
    assert_error(res[-1], "SyntaxError")
    with Session("--db", path) as s:
        assert_rows(s.execute("SELECT * FROM keep"), [["cy"], ["di"]])
        s.ok("CREATE VIEW Later (n) AS SELECT COUNT(*) FROM emp; UPDATE emp SET dept_id = 2 WHERE id = 1")
        s.kill()
    res = run("SELECT * FROM later; SELECT * FROM keep; DROP VIEW keep;", args=("--db", path))
    assert_rows(res[0], [[7]])
    assert_rows(res[1], [["ada"], ["cy"], ["di"]])
    assert_error(run("SELECT * FROM keep;", args=("--db", path))[0], "NameError")
