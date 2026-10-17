import pytest

from minidb.engine import Engine, run_sql
from minidb.protocol import SQLRuntimeError, SQLSyntaxError, SQLTypeError
from minidb.windows import Running


def rows(e, sql):
    out = run_sql(e, sql)[-1]
    assert isinstance(out, dict), out
    return out["rows"]


def test_running_aggregate_follows_aggregate_rules():
    r = Running("sum", False)
    for v in (1, None, 2):
        r.add(v)
    assert r.value() == 3
    r.add(0.5)
    assert r.value() == 3.5
    with pytest.raises(SQLTypeError):
        r.add("x")
    m = Running("min", False)
    for v in (2, 1.0, 1):
        m.add(v)
    assert m.value() == 1.0 and isinstance(m.value(), float)


def test_ranking_running_totals_and_lag():
    e = Engine()
    run_sql(e, "CREATE TABLE t (g INTEGER, v INTEGER); INSERT INTO t VALUES (1, 10), (1, 20), (2, 20), (1, 20)")
    assert rows(e, "SELECT v, RANK() OVER (ORDER BY v), SUM(v) OVER (PARTITION BY g ORDER BY v), "
                   "LAG(v, 1, 0) OVER (ORDER BY v DESC) FROM t") == [
        [10, 1, 10, 20], [20, 2, 50, 0], [20, 2, 20, 20], [20, 2, 50, 20]]
    assert isinstance(run_sql(e, "SELECT v FROM t WHERE ROW_NUMBER() OVER () = 1")[0], SQLSyntaxError)


def test_with_recursive_and_views():
    e = Engine()
    assert rows(e, "WITH RECURSIVE n (x) AS (SELECT 1 UNION ALL SELECT x * 2 FROM n WHERE x < 100) "
                   "SELECT COUNT(*), MAX(x) FROM n") == [[8, 128]]
    run_sql(e, "CREATE TABLE two (k INTEGER); INSERT INTO two VALUES (1), (2)")
    assert isinstance(run_sql(e, "WITH RECURSIVE r (x) AS (SELECT 1 UNION ALL SELECT x FROM r CROSS JOIN two) "
                                 "SELECT COUNT(*) FROM r")[0], SQLRuntimeError)
    run_sql(e, "CREATE VIEW v AS SELECT k * 10 AS ten FROM two ORDER BY k DESC")
    assert rows(e, "SELECT * FROM v") == [[20], [10]]
