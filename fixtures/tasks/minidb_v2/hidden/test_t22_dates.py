"""Section 22 (stage 6): the DATE type."""
from _support import COMPANY, Session, assert_error, assert_rows, plan, run, run_ok, stage

EVENTS = """
CREATE TABLE ev (id INTEGER PRIMARY KEY, title TEXT, day DATE, due DATE DEFAULT DATE '2000-01-01');
INSERT INTO ev (id, title, day) VALUES
  (1, 'launch', DATE '2024-03-01'), (2, 'review', DATE '2024-02-29'), (3, 'party', NULL),
  (4, 'audit', DATE '2023-12-31'), (5, 'retro', DATE '2024-02-29');
"""


@stage(6)
def test_date_literals_are_their_own_type():
    res = run("""
        SELECT DATE '2024-02-29', TYPEOF(DATE '2024-02-29'), DATE '0001-01-01', DATE '9999-12-31';
        SELECT TYPEOF('2024-02-29'), DATE '2024-02-29' = DATE '2024-02-29';
        SELECT date '1999-12-31' AS d;
    """)
    assert_rows(res[0], [["2024-02-29", "DATE", "0001-01-01", "9999-12-31"]])
    assert_rows(res[1], [["TEXT", True]])
    assert_rows(res[2], [["1999-12-31"]], columns=["d"])


@stage(6)
def test_invalid_date_literals_are_syntax_errors():
    bad = ["DATE '2023-02-29'", "DATE '2023-1-5'", "DATE '2023-13-01'", "DATE '20230101'",
           "DATE ' 2023-01-01'", "DATE '2023-01-01 '", "DATE '0000-01-01'", "DATE '2023-04-31'",
           "DATE 5", "DATE ''"]
    res = run("".join(f"SELECT {b};\n" for b in bad))
    for b, r in zip(bad, res):
        assert_error(r, "SyntaxError")


@stage(6)
def test_date_columns_storage_and_defaults():
    res = run(EVENTS + """
        SELECT id, day, due FROM ev WHERE id <= 3;
        INSERT INTO ev (id, day) VALUES (6, '2024-01-01');
        INSERT INTO ev (id, title) VALUES (7, DATE '2024-01-01');
        INSERT INTO ev (id, day) VALUES (8, 20240101);
        UPDATE ev SET due = day WHERE id = 1;
        CREATE TABLE bad (d DATE DEFAULT '2024-01-01');
        CREATE TABLE bad (d DATE DEFAULT DATE '2024-02-30');
        SELECT due, TYPEOF(due) FROM ev WHERE id = 1;
    """)
    assert_rows(res[2], [[1, "2024-03-01", "2000-01-01"], [2, "2024-02-29", "2000-01-01"],
                         [3, None, "2000-01-01"]], columns=["id", "day", "due"])
    for r in res[3:6]:
        assert_error(r, "ConstraintError")
    assert res[6].rowcount == 1
    assert_error(res[7], "ConstraintError")
    assert_error(res[8], "SyntaxError")
    assert_rows(res[9], [["2024-03-01", "DATE"]])


@stage(6)
def test_date_comparisons():
    res = run(EVENTS + """
        SELECT DATE '2024-01-02' > DATE '2024-01-01', DATE '2024-01-01' BETWEEN DATE '2023-12-31' AND DATE '2024-01-01',
               DATE '2024-05-05' IN (DATE '2024-05-05'), DATE '2024-01-01' <> DATE '2024-01-01';
        SELECT title FROM ev WHERE day >= DATE '2024-02-29';
        SELECT DATE '2024-01-01' = '2024-01-01';
        SELECT title FROM ev WHERE day < 20240101;
        SELECT DATE '2024-01-01' IN ('2024-01-01');
    """)
    assert_rows(res[2], [[True, True, True, False]])
    assert_rows(res[3], [["launch"], ["review"], ["retro"]])
    for r in res[4:]:
        assert_error(r, "TypeError")


@stage(6)
def test_date_arithmetic():
    res = run("""
        SELECT DATE '2024-02-28' + 1, 1 + DATE '2024-12-31', DATE '2024-03-01' - 1, DATE '2023-03-01' - 1;
        SELECT DATE '2024-03-01' - DATE '2024-02-01', DATE '2024-01-01' - DATE '2025-01-01', TYPEOF(DATE '2024-03-01' - DATE '2024-02-01');
        SELECT DATE '2024-01-31' + 366 - 365, DATE '2000-01-01' + (-1);
        SELECT DATE '2024-01-01' + 1.5;
        SELECT DATE '2024-01-01' + DATE '2024-01-01';
        SELECT -DATE '2024-01-01';
        SELECT DATE '2024-01-01' * 2;
        SELECT 5 - DATE '2024-01-01';
        SELECT DATE '9999-12-31' + 1;
        SELECT DATE '0001-01-01' - 1;
        SELECT DATE '2024-01-01' % 7;
    """)
    assert_rows(res[0], [["2024-02-29", "2025-01-01", "2024-02-29", "2023-02-28"]])
    assert_rows(res[1], [[29, -366, "INTEGER"]])
    assert_rows(res[2], [["2024-02-01", "1999-12-31"]])
    for r in res[3:8]:
        assert_error(r, "TypeError")
    assert_error(res[8], "RuntimeError")
    assert_error(res[9], "RuntimeError")
    assert_error(res[10], "TypeError")


@stage(6)
def test_date_functions_and_casts():
    res = run("""
        SELECT YEAR(DATE '2024-02-29'), MONTH(DATE '2024-02-29'), DAY(DATE '2024-02-29'), YEAR(NULL);
        SELECT CAST(' 2024-05-06 ' AS DATE), TYPEOF(CAST('2024-05-06' AS DATE)), CAST(DATE '2024-05-06' AS TEXT),
               TYPEOF(CAST(DATE '2024-05-06' AS TEXT)), CAST(NULL AS DATE);
        SELECT CAST('2024-02-30' AS DATE);
        SELECT CAST('2024/05/06' AS DATE);
        SELECT CAST(DATE '2024-05-06' AS INTEGER);
        SELECT CAST(5 AS DATE);
        SELECT CAST(TRUE AS DATE);
        SELECT YEAR('2024-01-01');
        SELECT LOWER(DATE '2024-01-01');
        SELECT LENGTH(DATE '2024-01-01');
        SELECT DATE '2024-01-01' || 'x';
        SELECT DATE '2024-01-01' LIKE '2024%';
        SELECT ABS(DATE '2024-01-01');
        SELECT ROUND(DATE '2024-01-01');
        SELECT SUBSTR(DATE '2024-01-01', 1, 4);
    """)
    assert_rows(res[0], [[2024, 2, 29, None]], columns=["year", "month", "day", "year"])
    assert_rows(res[1], [["2024-05-06", "DATE", "2024-05-06", "TEXT", None]])
    assert_error(res[2], "RuntimeError")
    assert_error(res[3], "RuntimeError")
    for r in res[4:]:
        assert_error(r, "TypeError")


@stage(6)
def test_dates_in_sorting_grouping_distinct_aggregates_and_set_operations():
    res = run(EVENTS + """
        SELECT id FROM ev ORDER BY day, id DESC;
        SELECT id FROM ev ORDER BY day DESC NULLS LAST;
        SELECT day, COUNT(*) FROM ev GROUP BY day;
        SELECT DISTINCT day FROM ev ORDER BY 1 DESC;
        SELECT MIN(day), MAX(day), COUNT(day), COUNT(DISTINCT day) FROM ev;
        SELECT SUM(day) FROM ev;
        SELECT AVG(day) FROM ev;
        SELECT DATE '2024-01-01' UNION SELECT DATE '2024-01-01' UNION SELECT '2024-01-01';
        SELECT CASE WHEN id = 3 THEN DATE '2000-02-02' ELSE day END, COALESCE(day, DATE '1999-01-01') FROM ev WHERE id >= 3;
    """)
    assert_rows(res[2], [[4], [5], [2], [1], [3]])
    assert_rows(res[3], [[1], [2], [5], [4], [3]])
    assert_rows(res[4], [["2024-03-01", 1], ["2024-02-29", 2], [None, 1], ["2023-12-31", 1]])
    assert_rows(res[5], [[None], ["2024-03-01"], ["2024-02-29"], ["2023-12-31"]])
    assert_rows(res[6], [["2023-12-31", "2024-03-01", 4, 3]])
    assert_error(res[7], "TypeError")
    assert_error(res[8], "TypeError")
    assert_rows(res[9], [["2024-01-01"], ["2024-01-01"]])
    assert_rows(res[10], [["2000-02-02", "1999-01-01"], ["2023-12-31", "2023-12-31"],
                          ["2024-02-29", "2024-02-29"]])


@stage(6)
def test_dates_with_indexes_joins_and_plans():
    res = run(EVENTS + """
        CREATE INDEX ev_day ON ev (day);
        EXPLAIN SELECT * FROM ev WHERE day = DATE '2024-02-29';
        EXPLAIN SELECT * FROM ev WHERE day BETWEEN DATE '2024-01-01' AND DATE '2024-12-31';
        SELECT id FROM ev WHERE day = DATE '2024-02-29';
        SELECT id FROM ev WHERE day BETWEEN DATE '2024-01-01' AND DATE '2024-12-31';
        SELECT id FROM ev WHERE day > '2024-01-01';
        CREATE TABLE holidays (d DATE, name TEXT);
        INSERT INTO holidays VALUES (DATE '2024-02-29', 'leap'), (DATE '2023-12-31', 'nye'), (NULL, 'tbd');
        SELECT e.title, h.name FROM ev e JOIN holidays h ON h.d = e.day;
        EXPLAIN SELECT e.title, h.name FROM ev e JOIN holidays h ON h.d = e.day;
        SELECT h.name, e.id FROM holidays h LEFT JOIN ev e ON e.day = h.d;
        CREATE TABLE texts (t TEXT);
        INSERT INTO texts VALUES ('2024-02-29');
        SELECT * FROM ev e JOIN texts x ON x.t = e.day;
    """)
    assert plan(res[3]) == ["SEARCH ev USING INDEX ev_day (day = ?)"]
    assert plan(res[4]) == ["SEARCH ev USING INDEX ev_day (day RANGE)"]
    assert_rows(res[5], [[2], [5]])
    assert_rows(res[6], [[1], [2], [5]])
    assert_error(res[7], "TypeError")
    assert_rows(res[10], [["review", "leap"], ["audit", "nye"], ["retro", "leap"]])
    assert plan(res[11]) == ["SCAN ev", "HASH JOIN holidays (d)"]
    assert_rows(res[12], [["leap", 2], ["leap", 5], ["nye", 4], ["tbd", None]])
    assert_error(res[15], "TypeError")


@stage(6)
def test_dates_in_windows_recursive_queries_and_views():
    res = run_ok(EVENTS + """
        WITH RECURSIVE days (d) AS (SELECT DATE '2024-02-27' UNION ALL SELECT d + 1 FROM days WHERE d < DATE '2024-03-02')
          SELECT d, TYPEOF(d) FROM days;
        SELECT title, day - LAG(day) OVER (ORDER BY day, id) AS gap FROM ev WHERE day IS NOT NULL ORDER BY day, id;
        CREATE VIEW upcoming AS SELECT title, day FROM ev WHERE day > DATE '2024-01-01';
        SELECT title, YEAR(day) FROM upcoming ORDER BY day DESC, title;
    """)
    assert_rows(res[2], [["2024-02-27", "DATE"], ["2024-02-28", "DATE"], ["2024-02-29", "DATE"],
                         ["2024-03-01", "DATE"], ["2024-03-02", "DATE"]])
    assert_rows(res[3], [["audit", None], ["review", 60], ["retro", 0], ["launch", 1]])
    assert_rows(res[5], [["launch", 2024], ["retro", 2024], ["review", 2024]])


@stage(6)
def test_dates_are_durable_and_transactional(tmp_path):
    path = str(tmp_path / "dates.db")
    res = run(EVENTS + """
        CREATE INDEX ev_day ON ev (day);
        BEGIN;
        UPDATE ev SET day = day + 365 WHERE id = 1;
        ROLLBACK;
        UPDATE ev SET due = DATE '2030-06-15' WHERE id = 2;
    """, args=("--db", path))
    assert all(r.ok for r in res), [r for r in res if not r.ok]
    with Session("--db", path) as s:
        assert_rows(s.execute("SELECT day, TYPEOF(day), due FROM ev WHERE id <= 2"),
                    [["2024-03-01", "DATE", "2000-01-01"], ["2024-02-29", "DATE", "2030-06-15"]])
        assert_error(s.execute("SELECT * FROM ev WHERE day = '2024-03-01'"), "TypeError")
        assert plan(s.execute("EXPLAIN SELECT id FROM ev WHERE day < DATE '2024-01-01'")) == [
            "SEARCH ev USING INDEX ev_day (day RANGE)"]
        s.ok("INSERT INTO ev (id, day) VALUES (9, DATE '2024-06-30')")
        s.kill()
    res = run("SELECT id FROM ev WHERE day > DATE '2024-03-01'; SELECT due FROM ev WHERE id = 9;",
              args=("--db", path))
    assert_rows(res[0], [[9]])
    assert_rows(res[1], [["2000-01-01"]])
