"""Section 16 (stage 4): `--db PATH` durable storage, crash recovery (SIGKILL), startup errors."""
import time

from _support import DIGITS, Session, assert_error, assert_rows, big_table_sql, plan, run, stage, value


def db(tmp_path, name="main.db") -> str:
    return str(tmp_path / name)


@stage(4)
def test_data_schema_and_indexes_survive_a_restart(tmp_path):
    path = db(tmp_path)
    res = run("""
        CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT NOT NULL, score REAL DEFAULT 1, ok BOOLEAN UNIQUE);
        INSERT INTO t (id, name, ok) VALUES (3, 'c', TRUE), (1, 'a', FALSE), (2, 'b', NULL);
        CREATE INDEX t_name ON t (name);
        UPDATE t SET score = 2.5 WHERE id = 1;
        DELETE FROM t WHERE id = 3;
        INSERT INTO t (id, name) VALUES (4, 'd');
    """, args=("--db", path))
    assert all(r.ok for r in res), res
    res = run("""
        SELECT * FROM t;
        EXPLAIN SELECT * FROM t WHERE name = 'b';
        EXPLAIN SELECT * FROM t WHERE id > 1;
        INSERT INTO t (id, name) VALUES (1, 'dup');
        INSERT INTO t (id, name, ok) VALUES (5, 'e', FALSE);
        INSERT INTO t (id) VALUES (6);
        INSERT INTO t (id, name) VALUES (0, 'z');
        SELECT id, score FROM t;
    """, args=("--db", path))
    assert_rows(res[0], [[1, "a", 2.5, False], [2, "b", 1.0, None], [4, "d", 1.0, None]],
                columns=["id", "name", "score", "ok"])
    assert plan(res[1]) == ["SEARCH t USING INDEX t_name (name = ?)"]
    assert plan(res[2]) == ["SEARCH t USING INDEX t_id_key (id RANGE)"]
    for r in res[3:6]:
        assert_error(r, "ConstraintError")
    assert_rows(res[7], [[1, 2.5], [2, 1.0], [4, 1.0], [0, 1.0]])


@stage(4)
def test_without_db_every_process_starts_empty(tmp_path):
    run("CREATE TABLE t (a INTEGER); INSERT INTO t VALUES (1);")
    assert_error(run("SELECT * FROM t;")[0], "NameError")
    assert not any(tmp_path.iterdir())


@stage(4)
def test_acknowledged_statements_survive_sigkill(tmp_path):
    path = db(tmp_path)
    with Session("--db", path) as s:
        s.ok("""
            CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);
            INSERT INTO t VALUES (1, 'a'), (2, 'b');
            BEGIN;
            INSERT INTO t VALUES (3, 'c');
            UPDATE t SET v = 'B' WHERE id = 2;
            COMMIT;
            DELETE FROM t WHERE id = 1;
            CREATE INDEX tv ON t (v);
        """)
        s.kill()
    with Session("--db", path) as s:
        assert_rows(s.execute("SELECT * FROM t"), [[2, "B"], [3, "c"]])
        assert plan(s.execute("EXPLAIN SELECT * FROM t WHERE v = 'c'")) == [
            "SEARCH t USING INDEX tv (v = ?)"]
        s.ok("INSERT INTO t VALUES (4, 'd')")
        s.kill()
    with Session("--db", path) as s:
        assert_rows(s.execute("SELECT id FROM t"), [[2], [3], [4]])


@stage(4)
def test_uncommitted_work_and_failed_statements_leave_no_trace(tmp_path):
    path = db(tmp_path)
    with Session("--db", path) as s:
        s.ok("""
            CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT NOT NULL);
            INSERT INTO t VALUES (1, 'a');
            BEGIN;
            INSERT INTO t VALUES (2, 'b');
            CREATE TABLE u (x INTEGER);
            DELETE FROM t WHERE id = 1;
        """)
        s.kill()
    with Session("--db", path) as s:
        assert_rows(s.execute("SELECT * FROM t"), [[1, "a"]])
        assert_error(s.execute("SELECT * FROM u"), "NameError")
        assert_error(s.execute("INSERT INTO t VALUES (5, 'e'), (6, NULL)"), "ConstraintError")
        assert_error(s.execute("UPDATE t SET v = v || (1 / 0)"), "RuntimeError")
        assert_error(s.execute("CREATE TABLE t (z INTEGER)"), "NameError")
        assert s.execute("BEGIN").ok
        assert s.execute("INSERT INTO t VALUES (7, 'g')").ok
        s.close()
    res = run("SELECT * FROM t; SELECT COUNT(*) FROM t WHERE id > 1;", args=("--db", path))
    assert_rows(res[0], [[1, "a"]])
    assert_rows(res[1], [[0]])


@stage(4)
def test_a_statement_killed_while_executing_is_all_or_nothing(tmp_path):
    create, index, insert = [x for x in big_table_sql("big", 5).split(";\n") if x.strip()]
    for i, delay in enumerate((0.0, 0.03, 0.15, 0.4, 1.0)):
        path = db(tmp_path, f"k{i}.db")
        with Session("--db", path) as s:
            s.ok(DIGITS + create + ";\n" + index + ";")
            s.send(insert)
            time.sleep(delay)
            s.kill()
        with Session("--db", path) as s:
            n = value(s.execute("SELECT COUNT(*) FROM big"))
            assert n in (0, 50_000), n
            if n:
                assert_rows(s.execute("SELECT COUNT(*) FROM big WHERE k BETWEEN 100 AND 199"), [[100]])
            assert s.execute("INSERT INTO big (id) VALUES (-1)").ok
    path = db(tmp_path, "commit.db")
    with Session("--db", path) as s:
        s.ok(DIGITS + "BEGIN;" + big_table_sql("big", 5).replace(";\n", ";"))
        s.send("COMMIT")
        s.kill()
    with Session("--db", path) as s:
        r = s.execute("SELECT COUNT(*) FROM big")
        assert (not r.ok and r.error_type == "NameError") or value(r) == 50_000, r
    with Session("--db", path) as s:
        s.ok("DROP TABLE IF EXISTS big;BEGIN;" + big_table_sql("big", 5).replace(";\n", ";") + "COMMIT;")
        s.kill()
    with Session("--db", path) as s:
        assert value(s.execute("SELECT COUNT(*) FROM big")) == 50_000


@stage(4)
def test_repeated_crashes_and_restarts_accumulate_exactly(tmp_path):
    path = db(tmp_path)
    run("CREATE TABLE log (n INTEGER PRIMARY KEY, note TEXT);", args=("--db", path))
    expected = []
    for round_ in range(6):
        with Session("--db", path) as s:
            for j in range(20):
                n = round_ * 100 + j
                assert s.execute(f"INSERT INTO log VALUES ({n}, 'r{round_}')").ok
                expected.append(n)
            s.ok(f"UPDATE log SET note = note || '+' WHERE n % 7 = {round_}")
            s.ok("BEGIN")
            s.ok(f"DELETE FROM log WHERE n < {round_ * 100}")
            if round_ % 2:
                s.kill()
            else:
                s.close()
    res = run("SELECT COUNT(*), MIN(n), MAX(n) FROM log; SELECT n FROM log WHERE n % 7 = 0 AND n < 30;",
              args=("--db", path))
    assert_rows(res[0], [[len(expected), 0, 519]])
    assert_rows(res[1], [[0], [7], [14]])
    notes = run("SELECT note FROM log WHERE n = 14; SELECT note FROM log WHERE n = 16;"
                "SELECT note FROM log WHERE n = 105;", args=("--db", path))
    assert_rows(notes[0], [["r0+"]])
    assert_rows(notes[1], [["r0+"]])
    assert_rows(notes[2], [["r1"]])


@stage(4)
def test_a_file_that_is_not_a_database_and_an_unusable_path(tmp_path):
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"this is not a minidb database\n\x00\x01")
    res = run("SELECT 1; CREATE TABLE t (a INTEGER); SELECT * FROM t;", args=("--db", str(junk)))
    for r in res:
        assert_error(r, "IOError")
    assert junk.read_bytes() == b"this is not a minidb database\n\x00\x01"
    missing = tmp_path / "no" / "such" / "dir" / "x.db"
    res = run("SELECT 1; CREATE TABLE t (a INTEGER);", args=("--db", str(missing)))
    for r in res:
        assert_error(r, "IOError")
    assert not (tmp_path / "no").exists()


@stage(4)
def test_durable_mode_performance(tmp_path):
    path = db(tmp_path)
    with Session("--db", path) as s:
        s.ok(DIGITS)
        for stmt in (x.strip() for x in big_table_sql("big", 5).split(";\n")):
            if stmt:
                assert s.execute(stmt, timeout=60).ok
        ins = [f"INSERT INTO big VALUES ({60_000 + i}, {60_000 + i}, 1, 'n', 0.5)" for i in range(1000)]
        t, res = s.pipeline(ins)
        assert all(r.ok for r in res)
        assert t / len(ins) * 1000 <= 5, f"{t / len(ins) * 1000:.2f} ms per autocommit INSERT (limit 5 ms)"
        upd = [f"UPDATE big SET tag = 'u' WHERE id = {(i * 13) % 50_000}" for i in range(500)]
        t, res = s.pipeline(upd)
        assert all(r.ok and r.rowcount == 1 for r in res)
        assert t / len(upd) * 1000 <= 5, f"{t / len(upd) * 1000:.2f} ms per autocommit UPDATE (limit 5 ms)"
        s.ok("BEGIN")
        assert s.execute("UPDATE big SET grp = -1 WHERE id BETWEEN 1000 AND 1999").rowcount == 1000
        t, r = s.timed("COMMIT")
        assert r.ok and t <= 0.2, f"COMMIT of 1,000 changed rows took {t:.3f}s (limit 0.2 s)"
        s.kill()
    with Session("--db", path) as s:
        r = s.execute("SELECT COUNT(*), SUM(grp) FROM big WHERE id < 60000", timeout=30)
        startup = time.perf_counter() - s.t_start
        assert startup <= 2.0, f"opening a 50,000-row database took {startup:.2f}s (limit 2 s)"
        grp_sum = sum(i % 1000 for i in range(50_000)) - sum(i % 1000 for i in range(1000, 2000)) - 1000
        assert_rows(r, [[50_000, grp_sum]])
        assert_rows(s.execute("SELECT COUNT(*) FROM big WHERE tag = 'u' OR id >= 60000"), [[1500]])
