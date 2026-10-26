"""t05 (stage 0): regression sentinels for the inherited engine and its stdin protocol, over both interfaces."""
import re

import pytest

from _support import cli_results, run_cli, shared, stage, unique  # noqa: F401

SCRIPTS = {
    "joins_and_sets": """
CREATE TABLE a (id INTEGER PRIMARY KEY, x TEXT); CREATE TABLE b (id INTEGER, a_id INTEGER, y REAL);
INSERT INTO a VALUES (1, 'p'), (2, 'q'), (3, NULL); INSERT INTO b VALUES (10, 1, 1.5), (11, 1, 2.5), (12, 3, NULL);
SELECT a.x, COUNT(b.id), SUM(b.y) FROM a LEFT JOIN b ON b.a_id = a.id GROUP BY a.x ORDER BY a.x;
SELECT x FROM a UNION SELECT 'z' ORDER BY 1; SELECT id FROM a EXCEPT SELECT a_id FROM b ORDER BY id;
SELECT x FROM a WHERE id IN (SELECT a_id FROM b) ORDER BY x;
""",
    "ctes_views_windows": """
CREATE TABLE s (g TEXT, v INTEGER); INSERT INTO s VALUES ('a', 1), ('a', 3), ('b', 2), ('b', 2), ('c', 9);
WITH t AS (SELECT g, SUM(v) AS total FROM s GROUP BY g) SELECT g FROM t WHERE total > 3 ORDER BY g;
CREATE VIEW sv AS SELECT g, v, ROW_NUMBER() OVER (PARTITION BY g ORDER BY v) AS rn FROM s;
SELECT * FROM sv ORDER BY g, rn; SELECT g, LAG(v) OVER (ORDER BY g, v) FROM s ORDER BY g, v;
""",
    "types_and_errors": """
CREATE TABLE t (i INTEGER NOT NULL, r REAL, d DATE, b BOOLEAN, s TEXT UNIQUE);
INSERT INTO t VALUES (1, 2.5, DATE '2024-02-29', TRUE, 'x'); INSERT INTO t VALUES (NULL, 1.0, NULL, NULL, 'y');
INSERT INTO t VALUES (2, 1.0, NULL, FALSE, 'x'); SELECT CAST('12' AS INTEGER) + 1, 7 / 2, 7 % 3, 'a' || 'b';
SELECT d + 1, d - DATE '2024-01-01', YEAR(d) FROM t; SELECT CASE WHEN b THEN 'yes' ELSE 'no' END FROM t;
SELECT 9223372036854775807 + 1; SELECT * FROM nowhere; SELECT 'unterminated;
""",
    "transactions_and_indexes": """
CREATE TABLE k (id INTEGER PRIMARY KEY, v TEXT); CREATE INDEX kv ON k (v);
BEGIN; INSERT INTO k VALUES (1, 'a'), (2, 'b'); ROLLBACK; SELECT COUNT(*) FROM k;
BEGIN; INSERT INTO k VALUES (3, 'c'); COMMIT; COMMIT; EXPLAIN SELECT * FROM k WHERE v = 'c';
SELECT v FROM k WHERE v = 'c'; ALTER TABLE k ADD COLUMN w INTEGER DEFAULT 4; SELECT * FROM k;
""",
}


@stage(0)
@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_engine_features_over_http_match_the_stdin_protocol(shared, name):  # noqa: F811
    script = _isolate(SCRIPTS[name], unique(""))       # unique names on the shared server
    r = shared.post("/v1/sql", {"sql": script})
    assert r.status == 200
    assert r.json()["results"] == cli_results(script)


def _isolate(script: str, suffix: str) -> str:
    """Give every table, view and index of a script a unique suffix (whole-word replacement)."""
    names = set(re.findall(r"CREATE (?:TABLE|VIEW|INDEX) (\w+)", script))
    for n in sorted(names, key=len, reverse=True):
        script = re.sub(rf"\b{n}\b", f"{n}{suffix}", script)
    return script


@stage(0)
def test_the_stdin_protocol_is_unchanged():
    p = run_cli([], input="SELECT 1; SELECT x;\nSELECT 'a;b' -- c;\n;")
    assert p.returncode == 0
    assert p.stdout.splitlines() == [
        '{"ok": true, "columns": ["?column?"], "rows": [[1]]}',
        '{"ok": false, "error": {"type": "NameError", "message": "no such column: x"}}',
        '{"ok": true, "columns": ["?column?"], "rows": [["a;b"]]}']


@stage(0)
def test_the_db_flag_still_keeps_data(tmp_path):
    db = tmp_path / "x.db"
    assert cli_results("CREATE TABLE z (a INTEGER); INSERT INTO z VALUES (3);", db=db)[1] == {"ok": True, "rowcount": 1}
    assert cli_results("SELECT a FROM z;", db=db) == [{"ok": True, "columns": ["a"], "rows": [[3]]}]


@stage(0)
def test_bad_cli_arguments_still_exit_2():
    p = run_cli(["--bogus"], input="")
    assert p.returncode == 2 and p.stderr.strip()
