"""Tier 10: BEGIN / COMMIT / ROLLBACK over data, order, indexes and schema."""
from _support import COMPANY, PEOPLE, assert_error, assert_rows, run, run_ok


def test_rollback_restores_rows_and_their_order():
    res = run_ok(PEOPLE + """
        BEGIN;
        INSERT INTO people (id, name) VALUES (7, 'Gil');
        UPDATE people SET age = 0, city = 'X' WHERE id <= 2;
        DELETE FROM people WHERE id IN (3, 5);
        SELECT COUNT(*) FROM people;
        ROLLBACK;
        SELECT * FROM people;
    """)
    assert res[-7].raw == {"ok": True}
    assert_rows(res[-3], [[5]])
    assert res[-2].raw == {"ok": True}
    assert_rows(res[-1], [[1, "Ann", 34, "Oslo", 7.5], [2, "bob", 27, "Rome", None],
                          [3, "Cid", None, "Oslo", 9.0], [4, "Dee", 45, None, 6.25],
                          [5, "Eve", 27, "Lima", 8.0], [6, "Fay", 31, "Rome", 7.5]])


def test_commit_keeps_changes_and_transaction_sees_its_own_writes():
    res = run_ok(COMPANY + """
        BEGIN TRANSACTION;
        UPDATE emp SET salary = salary * 2;
        SELECT SUM(salary) AS s FROM emp;
        COMMIT;
        SELECT SUM(salary) AS s FROM emp;
        BEGIN;
        UPDATE emp SET salary = 0;
        ROLLBACK;
        SELECT SUM(salary) AS s FROM emp;
    """)
    assert_rows(res[-7], [[2300]])
    assert res[-6].raw == {"ok": True}
    assert_rows(res[-5], [[2300]])
    assert res[-2].raw == {"ok": True}
    assert_rows(res[-1], [[2300]])


def test_transaction_state_errors():
    res = run(PEOPLE + """
        COMMIT;
        ROLLBACK;
        BEGIN;
        DELETE FROM people WHERE id = 1;
        BEGIN;
        DELETE FROM people WHERE id = 2;
        ROLLBACK;
        ROLLBACK;
        SELECT id FROM people;
    """)
    r = res[-9:]
    assert_error(r[0], "TransactionError")
    assert_error(r[1], "TransactionError")
    assert r[2].ok and r[3].rowcount == 1
    assert_error(r[4], "TransactionError")
    assert r[5].rowcount == 1 and r[6].ok
    assert_error(r[7], "TransactionError")
    assert_rows(r[8], [[1], [2], [3], [4], [5], [6]])


def test_failed_statement_does_not_end_the_transaction():
    res = run(COMPANY + """
        BEGIN;
        INSERT INTO dept VALUES (5, 'hr', 10.0);
        INSERT INTO dept VALUES (6, 'eng', 1.0);
        INSERT INTO dept VALUES (7, 'it', 2.0), (5, 'dup', 3.0);
        UPDATE dept SET budget = budget / 0 WHERE id = 1;
        INSERT INTO dept VALUES (8, 'pr', 3);
        COMMIT;
        SELECT id, name, budget FROM dept WHERE id >= 5 ORDER BY id;
        SELECT budget FROM dept WHERE id = 1;
    """)
    r = res[-9:]
    assert r[0].ok and r[1].ok
    assert_error(r[2], "ConstraintError")
    assert_error(r[3], "ConstraintError")
    assert_error(r[4], "RuntimeError")
    assert r[5].ok and r[6].ok
    assert_rows(r[7], [[5, "hr", 10.0], [8, "pr", 3.0]])
    assert_rows(r[8], [[1000.0]])


def test_rollback_restores_index_contents():
    res = run(COMPANY + """
        CREATE INDEX emp_salary ON emp (salary);
        CREATE UNIQUE INDEX emp_name ON emp (name);
        BEGIN;
        UPDATE emp SET salary = 999 WHERE dept_id = 1;
        DELETE FROM emp WHERE name = 'cy';
        INSERT INTO emp (id, name, salary) VALUES (8, 'hal', 150);
        SELECT id FROM emp WHERE salary = 150;
        ROLLBACK;
        SELECT id FROM emp WHERE salary = 150;
        SELECT id FROM emp WHERE salary = 999;
        SELECT id FROM emp WHERE salary > 220;
        EXPLAIN SELECT id FROM emp WHERE salary > 220;
        INSERT INTO emp (id, name) VALUES (9, 'cy');
        INSERT INTO emp (id, name) VALUES (8, 'hal');
        SELECT id FROM emp WHERE name = 'hal';
    """)
    r = res[-15:]
    assert all(x.ok for x in r[:8]), r[:8]
    assert_rows(r[6], [[4], [8]])
    assert_rows(r[8], [[3], [4]])
    assert_rows(r[9], [])
    assert_rows(r[10], [[1], [7]])
    assert r[11].rows == [["SEARCH emp USING INDEX emp_salary (salary RANGE)"]]
    assert_error(r[12], "ConstraintError")
    assert r[13].rowcount == 1
    assert_rows(r[14], [[8]])


def test_rollback_undoes_schema_changes():
    res = run(COMPANY + """
        CREATE INDEX keep_me ON emp (dept_id);
        BEGIN;
        CREATE TABLE scratch (a INTEGER);
        INSERT INTO scratch VALUES (1);
        CREATE INDEX tmp_idx ON emp (salary);
        DROP INDEX keep_me;
        DROP TABLE dept;
        SELECT * FROM scratch;
        ROLLBACK;
        SELECT * FROM scratch;
        SELECT COUNT(*) AS n, SUM(budget) AS b FROM dept;
        EXPLAIN SELECT * FROM emp WHERE salary = 1;
        EXPLAIN SELECT * FROM emp WHERE dept_id = 1;
        CREATE TABLE scratch (b TEXT);
        CREATE INDEX tmp_idx ON emp (name);
    """)
    r = res[-15:]
    assert all(x.ok for x in r[:9]), r[:9]
    assert_rows(r[7], [[1]])
    assert_error(r[9], "NameError")
    assert_rows(r[10], [[4, 1700.0]])
    assert r[11].rows == [["SCAN emp"]]
    assert r[12].rows == [["SEARCH emp USING INDEX keep_me (dept_id = ?)"]]
    assert r[13].ok and r[14].ok


def test_committed_ddl_and_unique_constraints_inside_transactions():
    res = run(COMPANY + """
        BEGIN;
        CREATE TABLE audit (id INTEGER PRIMARY KEY, what TEXT NOT NULL);
        CREATE UNIQUE INDEX audit_what ON audit (what);
        INSERT INTO audit VALUES (1, 'a'), (2, 'b');
        INSERT INTO audit VALUES (3, 'a');
        COMMIT;
        INSERT INTO audit VALUES (4, 'b');
        SELECT a.what, COUNT(e.id) AS n FROM audit a LEFT JOIN emp e ON e.id = a.id GROUP BY a.what
          ORDER BY a.what;
    """)
    r = res[-8:]
    assert all(x.ok for x in r[:4])
    assert_error(r[4], "ConstraintError")
    assert r[5].ok
    assert_error(r[6], "ConstraintError")
    assert_rows(r[7], [["a", 1], ["b", 1]])
