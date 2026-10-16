"""Section 15 (stage 4): BEGIN / COMMIT / ROLLBACK over data, order, indexes and schema."""
from _support import (
    COMPANY,
    DIGITS,
    PEOPLE,
    Session,
    assert_error,
    assert_rows,
    big_table_sql,
    plan,
    run,
    run_ok,
    stage,
)


@stage(4)
def test_rollback_restores_rows_and_their_order():
    res = run_ok(PEOPLE + """
        BEGIN;
        INSERT INTO people (id, name) VALUES (7, 'Gil');
        UPDATE people SET age = 0, city = 'X' WHERE id <= 2;
        DELETE FROM people WHERE id IN (3, 5);
        SELECT COUNT(*) FROM people;
        ROLLBACK;
        SELECT * FROM people;
        INSERT INTO people (id, name) VALUES (8, 'Hal');
        SELECT id FROM people;
    """)
    assert res[2].raw == {"ok": True}
    assert_rows(res[6], [[5]])
    assert res[7].raw == {"ok": True}
    assert_rows(res[8], [[1, "Ann", 34, "Oslo", 7.5], [2, "bob", 27, "Rome", None],
                         [3, "Cid", None, "Oslo", 9.0], [4, "Dee", 45, None, 6.25],
                         [5, "Eve", 27, "Lima", 8.0], [6, "Fay", 31, "Rome", 7.5]])
    assert_rows(res[10], [[1], [2], [3], [4], [5], [6], [8]])


@stage(4)
def test_commit_keeps_changes_and_a_transaction_sees_its_own_writes():
    res = run_ok(COMPANY + """
        BEGIN TRANSACTION;
        UPDATE emp SET salary = salary * 2;
        SELECT SUM(salary) AS s FROM emp;
        COMMIT TRANSACTION;
        SELECT SUM(salary) AS s FROM emp;
        BEGIN;
        UPDATE emp SET salary = 0;
        INSERT INTO emp (id, name) SELECT id + 100, name || '2' FROM emp;
        ROLLBACK TRANSACTION;
        SELECT SUM(salary) AS s, COUNT(*) FROM emp;
    """)
    assert_rows(res[-8], [[2300]])
    assert res[-7].raw == {"ok": True}
    assert_rows(res[-6], [[2300]])
    assert res[-3].rowcount == 7
    assert res[-2].raw == {"ok": True}
    assert_rows(res[-1], [[2300, 7]])


@stage(4)
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
        COMMIT TRANSACTION;
        BEGIN WORK;
        SELECT id FROM people;
    """)
    r = res[-11:]
    assert_error(r[0], "TransactionError")
    assert_error(r[1], "TransactionError")
    assert r[2].ok and r[3].rowcount == 1
    assert_error(r[4], "TransactionError")
    assert r[5].rowcount == 1 and r[6].ok
    assert_error(r[7], "TransactionError")
    assert_error(r[8], "TransactionError")
    assert_error(r[9], "SyntaxError")
    assert_rows(r[10], [[1], [2], [3], [4], [5], [6]])


@stage(4)
def test_a_failed_statement_does_not_end_the_transaction():
    res = run(COMPANY + """
        BEGIN;
        INSERT INTO dept VALUES (5, 'hr', 10.0);
        INSERT INTO dept VALUES (6, 'eng', 1.0);
        INSERT INTO dept VALUES (7, 'it', 2.0), (5, 'dup', 3.0);
        UPDATE dept SET budget = budget / 0 WHERE id = 1;
        INSERT INTO dept VALUES (9, 'bad', 'x');
        INSERT INTO dept VALUES (8, 'pr', 3);
        COMMIT;
        SELECT id, name, budget FROM dept WHERE id >= 5 ORDER BY id;
        SELECT budget FROM dept WHERE id = 1;
    """)
    r = res[-10:]
    assert r[0].ok and r[1].ok
    assert_error(r[2], "ConstraintError")
    assert_error(r[3], "ConstraintError")
    assert_error(r[4], "RuntimeError")
    assert_error(r[5], "ConstraintError")
    assert r[6].ok and r[7].ok
    assert_rows(r[8], [[5, "hr", 10.0], [8, "pr", 3.0]])
    assert_rows(r[9], [[1000.0]])


@stage(4)
def test_rollback_restores_index_contents_and_plans():
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
    assert plan(r[11]) == ["SEARCH emp USING INDEX emp_salary (salary RANGE)"]
    assert_error(r[12], "ConstraintError")
    assert r[13].rowcount == 1
    assert_rows(r[14], [[8]])


@stage(4)
def test_rollback_undoes_schema_changes():
    res = run(COMPANY + """
        CREATE INDEX keep_me ON emp (dept_id);
        BEGIN;
        CREATE TABLE scratch (a INTEGER PRIMARY KEY);
        INSERT INTO scratch VALUES (1);
        DROP INDEX keep_me;
        CREATE INDEX temp_ix ON emp (salary);
        DROP TABLE dept;
        ALTER TABLE emp ADD COLUMN bonus INTEGER DEFAULT 5;
        ALTER TABLE emp DROP COLUMN manager_id;
        SELECT * FROM emp WHERE id = 1;
        ROLLBACK;
        SELECT * FROM scratch;
        SELECT COUNT(*) FROM dept;
        SELECT * FROM emp WHERE id = 1;
        EXPLAIN SELECT * FROM emp WHERE dept_id = 2;
        EXPLAIN SELECT * FROM emp WHERE salary = 2;
        CREATE TABLE scratch (b TEXT);
        CREATE INDEX scratch_a_key ON emp (salary);
        EXPLAIN SELECT * FROM dept WHERE id = 1;
    """)
    r = res[-19:]
    assert all(x.ok for x in r[:11]), r[:11]
    assert_rows(r[9], [[1, "ada", 1, 300, True, 5]])
    assert_error(r[11], "NameError")
    assert_rows(r[12], [[4]])
    assert_rows(r[13], [[1, "ada", 1, 300, None, True]],
                columns=["id", "name", "dept_id", "salary", "manager_id", "active"])
    assert plan(r[14]) == ["SEARCH emp USING INDEX keep_me (dept_id = ?)"]
    assert plan(r[15]) == ["SCAN emp"]
    assert r[16].ok and r[17].ok
    assert plan(r[18]) == ["SEARCH dept USING INDEX dept_id_key (id = ?)"]


@stage(4)
def test_unique_keys_inside_transactions():
    res = run("""
        CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT UNIQUE);
        INSERT INTO t VALUES (1, 'a'), (2, 'b');
        BEGIN;
        DELETE FROM t WHERE id = 1;
        INSERT INTO t VALUES (1, 'a2');
        UPDATE t SET v = 'a' WHERE id = 2;
        INSERT INTO t VALUES (3, 'a');
        ROLLBACK;
        INSERT INTO t VALUES (3, 'a');
        INSERT INTO t VALUES (3, 'c');
        BEGIN;
        INSERT INTO t VALUES (4, 'd');
        COMMIT;
        SELECT * FROM t;
    """)
    assert [x.ok for x in res[2:7]] == [True, True, True, True, False]
    assert_error(res[6], "ConstraintError")
    assert_error(res[8], "ConstraintError")
    assert res[9].rowcount == 1
    assert_rows(res[13], [[1, "a"], [2, "b"], [3, "c"], [4, "d"]])


@stage(4)
def test_transaction_control_cost_does_not_grow_with_the_database():
    with Session() as s:
        s.ok(DIGITS)
        for stmt in (x.strip() for x in big_table_sql("big", 5).split(";\n")):
            if stmt:
                assert s.execute(stmt, timeout=60).ok
        stmts = []
        for i in range(150):
            k = (i * 331) % 50_000
            stmts += ["BEGIN", f"UPDATE big SET tag = 'x', k = k + 1 WHERE id = {k}",
                      f"DELETE FROM big WHERE id = {k + 1}",
                      f"INSERT INTO big VALUES ({100_000 + i}, -1, 0, 'n', 0.0)", "ROLLBACK"]
        t, res = s.pipeline(stmts)
        assert all(r.ok for r in res), [r for r in res if not r.ok][:3]
        avg_ms = t / len(stmts) * 1000
        assert avg_ms <= 5, f"{avg_ms:.2f} ms per statement in small transactions (limit 5 ms)"
        assert_rows(s.execute("SELECT COUNT(*), SUM(k), MAX(id) FROM big"),
                    [[50_000, sum(range(50_000)), 49_999]])
        assert_rows(s.execute("SELECT COUNT(*) FROM big WHERE tag = 'x' OR k = -1"), [[0]])
        assert_rows(s.execute("SELECT id FROM big WHERE id BETWEEN 330 AND 333"),
                    [[330], [331], [332], [333]])
        stmts = []
        for i in range(100):
            stmts += ["BEGIN", f"INSERT INTO big VALUES ({200_000 + i}, {200_000 + i}, 1, 'c', 1.0)",
                      f"UPDATE big SET grp = 2 WHERE id = {200_000 + i}", "COMMIT"]
        t, res = s.pipeline(stmts)
        assert all(r.ok for r in res), [r for r in res if not r.ok][:3]
        avg_ms = t / len(stmts) * 1000
        assert avg_ms <= 5, f"{avg_ms:.2f} ms per statement in small transactions (limit 5 ms)"
        assert_rows(s.execute("SELECT COUNT(*), MIN(grp) FROM big WHERE id >= 200000"), [[100, 2]])
