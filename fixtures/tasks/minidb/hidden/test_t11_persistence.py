"""Tier 11: SAVE / LOAD across processes."""
import json

from _support import COMPANY, assert_error, assert_rows, lit, run, run_ok


def test_save_and_load_in_a_new_process_keeps_data_types_and_order(tmp_path):
    db = tmp_path / "company.minidb"
    res = run_ok(COMPANY + """
        CREATE TABLE notes (id INTEGER, body TEXT, weight REAL, flag BOOLEAN);
        INSERT INTO notes VALUES (3, 'it''s ✓ "quoted"', 1, TRUE), (1, 'multi
line', NULL, FALSE), (2, NULL, -0.5, NULL);
        UPDATE notes SET id = 10 WHERE id = 3;
        DELETE FROM emp WHERE id = 2;
        INSERT INTO emp (id, name) VALUES (2, 'bo2');
    """ + f"SAVE {lit(db)};")
    assert res[-1].raw == {"ok": True}
    assert isinstance(json.loads(db.read_text(encoding="utf-8")), (dict, list))
    res = run_ok(f"LOAD {lit(db)};" + """
        SELECT * FROM notes;
        SELECT id, name, salary, active FROM emp;
        SELECT * FROM dept;
    """)
    assert res[0].raw == {"ok": True}
    assert_rows(res[1], [[10, "it's ✓ \"quoted\"", 1.0, True], [1, "multi\nline", None, False],
                         [2, None, -0.5, None]], columns=["id", "body", "weight", "flag"])
    assert_rows(res[2], [[1, "ada", 300, True], [3, "cy", 150, True], [4, "di", 150, False],
                         [5, "ed", None, True], [6, "flo", 100, True], [7, "gus", 250, True],
                         [2, "bo2", None, True]])
    assert_rows(res[3], [[1, "eng", 1000.0], [2, "ops", 500.0], [3, "sales", None],
                         [4, "legal", 200.0]], columns=["id", "name", "budget"])


def test_constraints_and_defaults_survive_load(tmp_path):
    db = tmp_path / "c.minidb"
    run_ok(COMPANY + f"SAVE {lit(db)};")
    res = run(f"LOAD {lit(db)};" + """
        INSERT INTO emp (id, name) VALUES (1, 'dup');
        INSERT INTO emp (id) VALUES (8);
        INSERT INTO dept VALUES (5, 'eng', 1.0);
        INSERT INTO dept (id, name, budget) VALUES (5, 'hr', 7);
        INSERT INTO emp (id, name, salary) VALUES (8, 'hal', 1.5);
        INSERT INTO emp (id, name) VALUES (8, 'hal');
        SELECT active, dept_id FROM emp WHERE id = 8;
        SELECT budget FROM dept WHERE id = 5;
    """)
    assert_error(res[1], "ConstraintError")
    assert_error(res[2], "ConstraintError")
    assert_error(res[3], "ConstraintError")
    assert res[4].ok
    assert_error(res[5], "TypeError")
    assert res[6].ok
    assert_rows(res[7], [[True, None]])
    assert_rows(res[8], [[7.0]])


def test_indexes_survive_load(tmp_path):
    db = tmp_path / "i.minidb"
    run_ok(COMPANY + """
        CREATE INDEX emp_dept ON emp (dept_id);
        CREATE UNIQUE INDEX emp_name ON emp (name);
        CREATE INDEX emp_salary ON emp (salary);
        DROP INDEX emp_salary;
    """ + f"SAVE {lit(db)};")
    res = run(f"LOAD {lit(db)};" + """
        EXPLAIN SELECT * FROM emp WHERE dept_id = 2;
        EXPLAIN SELECT * FROM emp WHERE salary = 2;
        SELECT name FROM emp WHERE dept_id = 2;
        INSERT INTO emp (id, name, dept_id) VALUES (8, 'ada', 2);
        UPDATE emp SET dept_id = 2 WHERE name = 'flo';
        SELECT name FROM emp WHERE dept_id = 2;
        DROP INDEX emp_name;
        CREATE INDEX emp_dept ON emp (name);
    """)
    assert res[1].rows == [["SEARCH emp USING INDEX emp_dept (dept_id = ?)"]]
    assert res[2].rows == [["SCAN emp"]]
    assert_rows(res[3], [["cy"], ["di"]])
    assert_error(res[4], "ConstraintError")
    assert_rows(res[6], [["cy"], ["di"], ["flo"]])
    assert res[7].ok
    assert_error(res[8], "NameError")


def test_load_replaces_the_whole_database_and_snapshots_are_point_in_time(tmp_path):
    db = tmp_path / "r.minidb"
    res = run(f"""
        CREATE TABLE a (x INTEGER);
        INSERT INTO a VALUES (1), (2);
        SAVE {lit(db)};
        CREATE TABLE b (y INTEGER);
        INSERT INTO a VALUES (3);
        DROP TABLE a;
        CREATE TABLE a (z TEXT);
        LOAD {lit(db)};
        SELECT * FROM a;
        SELECT * FROM b;
        INSERT INTO a VALUES (4);
        SAVE {lit(db)};
    """)
    assert all(r.ok for r in res[:8]), res[:8]
    assert_rows(res[8], [[1], [2]], columns=["x"])
    assert_error(res[9], "NameError")
    res = run_ok(f"CREATE TABLE b (q INTEGER); LOAD {lit(db)}; SELECT x FROM a;")
    assert_rows(res[-1], [[1], [2], [4]])


def test_bad_files_are_io_errors_and_leave_the_database_unchanged(tmp_path):
    garbage = tmp_path / "garbage.minidb"
    garbage.write_text("this is not a database", encoding="utf-8")
    empty = tmp_path / "empty.minidb"
    empty.write_text("", encoding="utf-8")
    wrong = tmp_path / "wrong.minidb"
    wrong.write_text("[1, 2, 3]", encoding="utf-8")
    missing = tmp_path / "missing.minidb"
    nodir = tmp_path / "no" / "such" / "dir" / "x.minidb"
    res = run(f"""
        CREATE TABLE keep (v INTEGER);
        INSERT INTO keep VALUES (42);
        LOAD {lit(missing)};
        LOAD {lit(garbage)};
        LOAD {lit(empty)};
        LOAD {lit(wrong)};
        SAVE {lit(nodir)};
        SELECT * FROM keep;
    """)
    for r in res[2:7]:
        assert_error(r, "IOError")
    assert_rows(res[-1], [[42]])
    assert not nodir.exists()


def test_save_overwrites_and_is_not_allowed_in_a_transaction(tmp_path):
    db = tmp_path / "t.minidb"
    db.write_text("old junk", encoding="utf-8")
    res = run(f"""
        CREATE TABLE t (v INTEGER);
        INSERT INTO t VALUES (1);
        SAVE {lit(db)};
        BEGIN;
        INSERT INTO t VALUES (2);
        SAVE {lit(db)};
        LOAD {lit(db)};
        ROLLBACK;
        SELECT * FROM t;
        LOAD {lit(db)};
        SELECT * FROM t;
    """)
    assert res[2].ok
    assert_error(res[5], "TransactionError")
    assert_error(res[6], "TransactionError")
    assert res[7].ok
    assert_rows(res[8], [[1]])
    assert res[9].ok
    assert_rows(res[10], [[1]])


def test_loaded_database_supports_full_queries(tmp_path):
    db = tmp_path / "q.minidb"
    run_ok(COMPANY + f"SAVE {lit(db)};")
    res = run_ok(f"LOAD {lit(db)};" + """
        SELECT d.name, COUNT(e.id) AS n FROM dept d LEFT JOIN emp e ON e.dept_id = d.id
          WHERE d.id IN (SELECT dept_id FROM emp WHERE salary >= 150) GROUP BY d.name ORDER BY n DESC;
        BEGIN;
        DELETE FROM emp;
        ROLLBACK;
        SELECT COUNT(*) FROM emp;
    """)
    assert_rows(res[1], [["eng", 3], ["ops", 2]])
    assert_rows(res[-1], [[7]])
