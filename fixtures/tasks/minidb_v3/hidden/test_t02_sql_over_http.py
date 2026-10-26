"""t02 (stage 0): POST /v1/sql runs statements exactly like the stdin protocol; sessions; durability (brief 0.4)."""
from _support import Server, cli_results, expect_error, run_cli, server, shared, stage, unique  # noqa: F401

SCRIPT = """
CREATE TABLE emp (id INTEGER PRIMARY KEY, name TEXT NOT NULL, dept TEXT, salary REAL, hired DATE);
INSERT INTO emp VALUES (1, 'Ann', 'eng', 120.5, DATE '2020-01-15'), (2, 'Bo', 'eng', 99.0, DATE '2021-06-01'),
                       (3, 'Cy', 'ops', 80.25, NULL), (4, 'Dee', NULL, 70.0, DATE '2019-03-30');
SELECT dept, COUNT(*), SUM(salary) FROM emp GROUP BY dept ORDER BY dept;
SELECT name, RANK() OVER (ORDER BY salary DESC) FROM emp ORDER BY name;
UPDATE emp SET salary = salary * 2 WHERE dept = 'ops';
SELECT * FROM emp WHERE hired > DATE '2020-01-01' ORDER BY id;
INSERT INTO emp VALUES (1, 'Dup', 'x', 1.0, NULL);
SELECT nope FROM emp;
SELECT 1 / 0;
DELETE FROM emp WHERE id = 4;
SELECT COUNT(*) FROM emp;
"""


@stage(0)
def test_results_are_identical_to_the_stdin_protocol(shared):  # noqa: F811
    t = unique()
    script = SCRIPT.replace("emp", t)
    r = shared.post("/v1/sql", {"sql": script})
    assert r.status == 200 and r.ctype == "application/json", r
    assert r.json() == {"results": cli_results(script)}


@stage(0)
def test_a_statement_error_does_not_fail_the_request(shared):  # noqa: F811
    res = shared.sql("SELECT x; SELECT 2;")
    assert res[0]["ok"] is False and res[0]["error"]["type"] == "NameError"
    assert res[1] == {"ok": True, "columns": ["?column?"], "rows": [[2]]}


@stage(0)
def test_no_statements_give_no_results(shared):  # noqa: F811
    assert shared.sql("") == []
    assert shared.sql("  -- only a comment\n ;;") == []


@stage(0)
def test_the_sql_field_is_required_and_must_be_a_string(shared):  # noqa: F811
    for body in ({}, {"sql": 5}, {"sql": None}, {"sql": ["SELECT 1;"]}, ["SELECT 1;"], "SELECT 1;", 7):
        expect_error(shared.post("/v1/sql", body), 400)


@stage(0)
def test_each_request_is_its_own_session(shared):  # noqa: F811
    t = unique()
    shared.sql(f"CREATE TABLE {t} (a INTEGER);")
    res = shared.sql(f"BEGIN; INSERT INTO {t} VALUES (1);")
    assert [x["ok"] for x in res] == [True, True]
    # the open transaction was rolled back at the end of the request; the next request starts clean
    res = shared.sql(f"BEGIN; SELECT COUNT(*) FROM {t}; COMMIT;")
    assert res == [{"ok": True}, {"ok": True, "columns": ["count"], "rows": [[0]]}, {"ok": True}]


@stage(0)
def test_a_committed_transaction_is_kept(shared):  # noqa: F811
    t = unique()
    shared.sql(f"CREATE TABLE {t} (a INTEGER); BEGIN; INSERT INTO {t} VALUES (1), (2); COMMIT;")
    assert shared.sql(f"SELECT SUM(a) FROM {t};")[0]["rows"] == [[3]]


@stage(0)
def test_acknowledged_data_survives_a_crash(server):  # noqa: F811
    server.sql("CREATE TABLE d (a INTEGER, b TEXT);")
    for i in range(20):
        server.sql(f"INSERT INTO d VALUES ({i}, 'v{i}');")
    server.sql("BEGIN; INSERT INTO d VALUES (100, 'tx'); COMMIT; BEGIN; INSERT INTO d VALUES (200, 'open');")
    server.restart(crash=True)
    assert server.sql("SELECT COUNT(*), SUM(a) FROM d;")[0]["rows"] == [[21, sum(range(20)) + 100]]


@stage(0)
def test_data_survives_a_clean_restart(server):  # noqa: F811
    server.sql("CREATE TABLE r (a INTEGER); INSERT INTO r VALUES (5); CREATE VIEW rv AS SELECT a * 2 AS b FROM r;")
    server.restart()
    assert server.sql("SELECT b FROM rv;")[0]["rows"] == [[10]]


@stage(0)
def test_the_sql_database_is_in_the_engines_durable_format(server):  # noqa: F811
    server.sql("CREATE TABLE f (a INTEGER, s TEXT); INSERT INTO f VALUES (1, 'x'), (2, 'y');")
    assert server.stop() == 0
    res = cli_results("SELECT a, s FROM f ORDER BY a;", db=server.data_dir / "sql.db")
    assert res == [{"ok": True, "columns": ["a", "s"], "rows": [[1, "x"], [2, "y"]]}]


@stage(0)
def test_an_existing_engine_database_is_served(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "FORMAT").write_text("minidb-data 1\n")
    p = run_cli(["--db", str(d / "sql.db")], input="CREATE TABLE old (a TEXT); INSERT INTO old VALUES ('kept');")
    assert p.returncode == 0
    with Server(tmp_path, data_dir=d) as s:
        assert s.sql("SELECT a FROM old;")[0]["rows"] == [["kept"]]


@stage(0)
def test_unicode_and_large_results_round_trip(shared):  # noqa: F811
    t = unique()
    shared.sql(f"CREATE TABLE {t} (s TEXT);")
    shared.sql(f"INSERT INTO {t} VALUES ('héllo ✓ \U0001f600'), ('it''s');")
    assert shared.sql(f"SELECT s FROM {t} ORDER BY s;")[0]["rows"] == [["héllo ✓ \U0001f600"], ["it's"]]
    big = unique()
    rows = ",".join(f"({i})" for i in range(5000))
    shared.sql(f"CREATE TABLE {big} (a INTEGER); INSERT INTO {big} VALUES {rows};")
    res = shared.sql(f"SELECT a FROM {big} ORDER BY a;")[0]
    assert res["rows"] == [[i] for i in range(5000)]
