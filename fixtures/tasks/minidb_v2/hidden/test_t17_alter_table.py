"""Section 17 (stage 4): ALTER TABLE ADD / DROP COLUMN, with indexes, transactions and --db."""
from _support import COMPANY, assert_error, assert_rows, plan, run, run_ok, stage


@stage(4)
def test_add_column_fills_existing_rows():
    res = run_ok(COMPANY + """
        ALTER TABLE dept ADD COLUMN floor INTEGER DEFAULT 1;
        ALTER TABLE dept ADD note TEXT;
        ALTER TABLE dept ADD COLUMN rating REAL NOT NULL DEFAULT 3;
        SELECT * FROM dept WHERE id <= 2;
        INSERT INTO dept (id, name) VALUES (5, 'hr');
        INSERT INTO dept VALUES (6, 'pr', NULL, 7, 'x', 1.5);
        UPDATE dept SET floor = floor + 1 WHERE budget IS NULL;
        SELECT id, floor, note, rating FROM dept WHERE id >= 3;
    """)
    assert_rows(res[-5], [[1, "eng", 1000.0, 1, None, 3.0], [2, "ops", 500.0, 1, None, 3.0]],
                columns=["id", "name", "budget", "floor", "note", "rating"])
    assert res[-2].rowcount == 3
    assert_rows(res[-1], [[3, 2, None, 3.0], [4, 1, None, 3.0], [5, 2, None, 3.0], [6, 8, "x", 1.5]])


@stage(4)
def test_add_column_errors():
    res = run(COMPANY + """
        ALTER TABLE dept ADD COLUMN boss TEXT NOT NULL;
        ALTER TABLE dept ADD COLUMN boss TEXT NOT NULL DEFAULT NULL;
        ALTER TABLE dept ADD COLUMN code INTEGER UNIQUE;
        ALTER TABLE dept ADD COLUMN code INTEGER PRIMARY KEY;
        ALTER TABLE dept ADD COLUMN name TEXT;
        ALTER TABLE dept ADD COLUMN NAME INTEGER;
        ALTER TABLE nope ADD COLUMN x INTEGER;
        ALTER TABLE dept ADD COLUMN x INTEGER DEFAULT 'one';
        ALTER TABLE dept ADD COLUMN x VARCHAR;
        CREATE TABLE empty (a INTEGER);
        ALTER TABLE empty ADD COLUMN b TEXT NOT NULL;
        INSERT INTO empty VALUES (1, NULL);
        SELECT * FROM dept WHERE id = 1;
    """)
    r = res[-13:]
    assert_error(r[0], "ConstraintError")
    assert_error(r[1], "ConstraintError")
    assert_error(r[2], "SyntaxError")
    assert_error(r[3], "SyntaxError")
    assert_error(r[4], "NameError")
    assert_error(r[5], "NameError")
    assert_error(r[6], "NameError")
    assert_error(r[7], "ConstraintError")
    assert_error(r[8], "SyntaxError")
    assert r[10].ok
    assert_error(r[11], "ConstraintError")
    assert_rows(r[12], [[1, "eng", 1000.0]], columns=["id", "name", "budget"])


@stage(4)
def test_drop_column_and_its_indexes():
    res = run(COMPANY + """
        CREATE INDEX emp_sal ON emp (salary);
        CREATE INDEX emp_mgr ON emp (manager_id);
        ALTER TABLE emp DROP COLUMN salary;
        SELECT * FROM emp WHERE id = 2;
        EXPLAIN SELECT * FROM emp WHERE manager_id = 1;
        CREATE INDEX emp_sal ON emp (dept_id);
        DROP INDEX emp_sal;
        ALTER TABLE dept DROP name;
        EXPLAIN SELECT * FROM dept WHERE budget > 1;
        CREATE INDEX dept_name_key ON dept (budget);
        INSERT INTO dept VALUES (5, 9.5);
        SELECT * FROM dept;
        ALTER TABLE emp ADD COLUMN salary TEXT DEFAULT 'n/a';
        SELECT name, salary FROM emp WHERE id = 1;
    """)
    r = res[-14:]
    assert all(x.ok for x in r), [x for x in r if not x.ok]
    assert_rows(r[3], [[2, "bo", 1, 1, True]], columns=["id", "name", "dept_id", "manager_id", "active"])
    assert plan(r[4]) == ["SEARCH emp USING INDEX emp_mgr (manager_id = ?)"]
    assert plan(r[8]) == ["SCAN dept"]
    assert_rows(r[11], [[1, 1000.0], [2, 500.0], [3, None], [4, 200.0], [5, 9.5]])
    assert_rows(r[13], [["ada", "n/a"]])


@stage(4)
def test_drop_column_errors():
    res = run(COMPANY + """
        ALTER TABLE emp DROP COLUMN id;
        ALTER TABLE emp DROP COLUMN nope;
        ALTER TABLE nope DROP COLUMN x;
        CREATE TABLE one (a INTEGER);
        ALTER TABLE one DROP COLUMN a;
        ALTER TABLE emp DROP COLUMN;
        SELECT COUNT(*) FROM emp WHERE id = 1;
    """)
    r = res[-7:]
    assert_error(r[0], "ConstraintError")
    assert_error(r[1], "NameError")
    assert_error(r[2], "NameError")
    assert_error(r[4], "ConstraintError")
    assert_error(r[5], "SyntaxError")
    assert_rows(r[6], [[1]])


@stage(4)
def test_altered_tables_work_with_queries_indexes_and_restarts(tmp_path):
    path = str(tmp_path / "alter.db")
    res = run(COMPANY + """
        ALTER TABLE emp ADD COLUMN level INTEGER DEFAULT 1;
        UPDATE emp SET level = 2 WHERE salary >= 200;
        CREATE INDEX emp_level ON emp (level);
        ALTER TABLE emp DROP COLUMN manager_id;
        BEGIN;
        ALTER TABLE emp ADD COLUMN tmp TEXT;
        ALTER TABLE emp DROP COLUMN level;
        ROLLBACK;
    """, args=("--db", path))
    assert all(r.ok for r in res), [r for r in res if not r.ok]
    res = run("""
        SELECT d.name, SUM(e.level) FROM dept d JOIN emp e ON e.dept_id = d.id GROUP BY d.name ORDER BY 1;
        EXPLAIN SELECT name FROM emp WHERE level = 2;
        SELECT name FROM emp WHERE level = 2;
        SELECT * FROM emp WHERE id = 7;
    """, args=("--db", path))
    assert_rows(res[0], [["eng", 6], ["ops", 2], ["sales", 1]])
    assert plan(res[1]) == ["SEARCH emp USING INDEX emp_level (level = ?)"]
    assert_rows(res[2], [["ada"], ["bo"], ["gus"]])
    assert_rows(res[3], [[7, "gus", 1, 250, True, 2]],
                columns=["id", "name", "dept_id", "salary", "active", "level"])
