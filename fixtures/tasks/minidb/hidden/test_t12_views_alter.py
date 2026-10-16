"""Tier 12: views and ALTER TABLE ADD COLUMN, including transactions and persistence."""
from _support import COMPANY, assert_error, assert_rows, lit, run, run_ok

STAFF_VIEW = """
CREATE VIEW staff AS
  SELECT e.id, e.name, d.name AS dept, e.salary FROM emp e JOIN dept d ON e.dept_id = d.id
  WHERE e.active;
"""


def test_view_reflects_current_data():
    res = run_ok(COMPANY + STAFF_VIEW + """
        SELECT * FROM staff ORDER BY id;
        INSERT INTO emp (id, name, dept_id, salary) VALUES (8, 'hal', 4, 120);
        UPDATE emp SET active = FALSE WHERE name = 'ada';
        SELECT name, dept FROM staff WHERE salary > 100 ORDER BY name;
    """)
    assert res[-5].raw == {"ok": True}
    assert_rows(res[-4], [[1, "ada", "eng", 300], [2, "bo", "eng", 200], [3, "cy", "ops", 150],
                          [5, "ed", "sales", None], [7, "gus", "eng", 250]],
                columns=["id", "name", "dept", "salary"])
    assert_rows(res[-1], [["bo", "eng"], ["cy", "ops"], ["gus", "eng"], ["hal", "legal"]])


def test_views_in_joins_aggregates_and_subqueries():
    res = run_ok(COMPANY + STAFF_VIEW + """
        SELECT s.dept, COUNT(*) AS n, MAX(s.salary) AS top FROM staff s GROUP BY s.dept ORDER BY n DESC, s.dept;
        SELECT d.name, s.name FROM dept d LEFT JOIN staff s ON s.dept = d.name WHERE d.budget < 600
          ORDER BY d.name, s.name;
        SELECT name FROM emp WHERE id NOT IN (SELECT id FROM staff) ORDER BY name;
        CREATE VIEW rich AS SELECT name FROM staff WHERE salary >= 250;
        SELECT * FROM rich;
        EXPLAIN SELECT * FROM rich;
    """)
    assert_rows(res[-6], [["eng", 3, 300], ["ops", 1, 150], ["sales", 1, None]])
    assert_rows(res[-5], [["legal", None], ["ops", "cy"]])
    assert_rows(res[-4], [["di"], ["flo"]])
    assert_rows(res[-2], [["ada"], ["gus"]], columns=["name"])
    assert res[-1].rows == [["SCAN rich"]]


def test_view_namespace_and_errors():
    res = run(COMPANY + STAFF_VIEW + """
        CREATE VIEW emp AS SELECT 1 AS x;
        CREATE TABLE staff (a INTEGER);
        CREATE VIEW staff AS SELECT 1 AS x;
        DROP TABLE staff;
        DROP VIEW emp;
        INSERT INTO staff VALUES (9, 'x', 'y', 1);
        UPDATE staff SET salary = 1;
        DELETE FROM staff;
        CREATE INDEX staff_idx ON staff (salary);
        CREATE VIEW broken AS SELECT * FROM nowhere;
        SELECT * FROM broken;
        DROP VIEW nope;
    """)
    for r in res[-12:]:
        assert_error(r, "NameError")


def test_dropping_a_base_table_breaks_the_view_and_drop_view_frees_the_name():
    res = run(COMPANY + STAFF_VIEW + """
        DROP TABLE dept;
        SELECT * FROM staff;
        DROP VIEW staff;
        SELECT * FROM staff;
        CREATE TABLE staff (a INTEGER);
        INSERT INTO staff VALUES (1);
        SELECT * FROM staff;
    """)
    r = res[-7:]
    assert r[0].ok
    assert_error(r[1], "NameError")
    assert r[2].raw == {"ok": True}
    assert_error(r[3], "NameError")
    assert r[4].ok and r[5].ok
    assert_rows(r[6], [[1]])


def test_alter_table_add_column():
    res = run(COMPANY + """
        CREATE VIEW everything AS SELECT * FROM dept;
        ALTER TABLE dept ADD COLUMN region TEXT DEFAULT 'eu';
        ALTER TABLE dept ADD head_count INTEGER;
        ALTER TABLE dept ADD COLUMN rating REAL NOT NULL DEFAULT 1;
        SELECT * FROM dept WHERE id <= 2;
        SELECT * FROM everything WHERE id = 3;
        INSERT INTO dept (id, name) VALUES (5, 'hr');
        UPDATE dept SET head_count = 3, region = NULL WHERE id = 5;
        SELECT id, region, head_count, rating FROM dept WHERE id = 5;
        ALTER TABLE dept ADD COLUMN must INTEGER NOT NULL;
        ALTER TABLE dept ADD COLUMN k INTEGER PRIMARY KEY;
        ALTER TABLE dept ADD COLUMN u TEXT UNIQUE;
        ALTER TABLE dept ADD COLUMN name TEXT;
        ALTER TABLE dept ADD COLUMN bad INTEGER DEFAULT 'x';
        ALTER TABLE nope ADD COLUMN a INTEGER;
        SELECT COUNT(*) AS n FROM dept;
        CREATE TABLE empty_t (a INTEGER);
        ALTER TABLE empty_t ADD COLUMN b INTEGER NOT NULL;
        INSERT INTO empty_t (a) VALUES (1);
        INSERT INTO empty_t VALUES (1, 2);
        SELECT * FROM empty_t;
    """)
    r = res[-21:]
    assert all(x.ok for x in r[:4]), r[:4]
    assert_rows(r[4], [[1, "eng", 1000.0, "eu", None, 1.0], [2, "ops", 500.0, "eu", None, 1.0]],
                columns=["id", "name", "budget", "region", "head_count", "rating"])
    assert_rows(r[5], [[3, "sales", None, "eu", None, 1.0]],
                columns=["id", "name", "budget", "region", "head_count", "rating"])
    assert r[6].ok and r[7].rowcount == 1
    assert_rows(r[8], [[5, None, 3, 1.0]])
    assert_error(r[9], "ConstraintError")
    assert_error(r[10], "SyntaxError")
    assert_error(r[11], "SyntaxError")
    assert_error(r[12], "NameError")
    assert_error(r[13], "TypeError")
    assert_error(r[14], "NameError")
    assert_rows(r[15], [[5]])
    assert r[16].ok and r[17].ok
    assert_error(r[18], "ConstraintError")
    assert_rows(r[20], [[1, 2]], columns=["a", "b"])


def test_views_and_added_columns_roll_back():
    res = run(COMPANY + """
        BEGIN;
        CREATE VIEW v AS SELECT name FROM dept;
        ALTER TABLE dept ADD COLUMN extra INTEGER DEFAULT 7;
        SELECT * FROM v;
        SELECT extra FROM dept WHERE id = 1;
        ROLLBACK;
        SELECT * FROM v;
        SELECT extra FROM dept;
        SELECT * FROM dept WHERE id = 1;
        CREATE VIEW v AS SELECT id FROM dept;
    """)
    r = res[-10:]
    assert all(x.ok for x in r[:6]), r[:6]
    assert_rows(r[4], [[7]])
    assert_error(r[6], "NameError")
    assert_error(r[7], "NameError")
    assert_rows(r[8], [[1, "eng", 1000.0]], columns=["id", "name", "budget"])
    assert r[9].ok


def test_views_and_added_columns_persist(tmp_path):
    db = tmp_path / "v.minidb"
    run_ok(COMPANY + STAFF_VIEW + """
        ALTER TABLE emp ADD COLUMN level INTEGER DEFAULT 1;
        UPDATE emp SET level = 3 WHERE manager_id IS NULL;
        CREATE VIEW seniors AS SELECT name, level FROM emp WHERE level > 1;
    """ + f"SAVE {lit(db)};")
    res = run_ok(f"LOAD {lit(db)};" + """
        SELECT * FROM seniors;
        INSERT INTO emp (id, name, dept_id, salary) VALUES (8, 'hal', 2, 175);
        SELECT name, level FROM emp WHERE id = 8;
        SELECT name FROM staff WHERE dept = 'ops' ORDER BY name;
    """)
    assert_rows(res[1], [["ada", 3]], columns=["name", "level"])
    assert_rows(res[3], [["hal", 1]])
    assert_rows(res[4], [["cy"], ["hal"]])
