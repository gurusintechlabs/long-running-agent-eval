"""Section 8: scalar, IN and EXISTS subqueries; correlation; evaluation rules."""
import pytest

from minidb.compiler import QueryContext, Runtime
from minidb.parser import parse
from minidb.planner import build_query


@pytest.fixture
def emp(db):
    db.run("CREATE TABLE emp (id INT PRIMARY KEY, dept TEXT, sal INT)")
    db.run("INSERT INTO emp VALUES (1, 'a', 10), (2, 'a', 20), (3, 'b', 30), (4, NULL, 5)")
    return db


def test_scalar_subquery(emp):
    emp.expect("SELECT id FROM emp WHERE sal > (SELECT AVG(sal) FROM emp)", [[2], [3]])
    emp.expect("SELECT (SELECT MAX(id) FROM emp), (SELECT id FROM emp WHERE id > 99)",
               [[4, None]])
    assert emp.columns("SELECT (SELECT 1)") == ["?column?"]
    assert emp.columns("SELECT (SELECT 1) AS x") == ["x"]


def test_scalar_subquery_errors(emp):
    assert emp.error("SELECT (SELECT id FROM emp)") == "RuntimeError"
    assert emp.error("SELECT (SELECT id, sal FROM emp WHERE id = 1)") == "SyntaxError"
    assert emp.error("SELECT (SELECT * FROM emp WHERE id = 1)") == "SyntaxError"
    assert emp.error("SELECT (SELECT nope FROM emp)") == "NameError"


def test_in_subquery(emp):
    emp.expect("SELECT id FROM emp WHERE id IN (SELECT id FROM emp WHERE dept = 'a')",
               [[1], [2]])
    emp.expect("SELECT id FROM emp WHERE id NOT IN (SELECT id FROM emp WHERE dept = 'a')",
               [[3], [4]])
    emp.expect("SELECT 1 IN (SELECT id FROM emp WHERE FALSE), "
               "NULL IN (SELECT id FROM emp WHERE FALSE), "
               "NULL NOT IN (SELECT id FROM emp WHERE FALSE)", [[False, False, True]])
    # A NULL among the values: NOT IN is never TRUE.
    emp.expect("SELECT id FROM emp WHERE id NOT IN (SELECT CASE WHEN dept IS NULL THEN NULL "
               "ELSE 1 END FROM emp)", [])
    emp.expect("SELECT 5 IN (SELECT dept IS NULL FROM emp WHERE id = 99)", [[False]])
    assert emp.error("SELECT 1 IN (SELECT id, sal FROM emp)") == "SyntaxError"
    assert emp.error("SELECT 1 IN (SELECT dept FROM emp)") == "TypeError"


def test_exists(emp):
    emp.expect("SELECT id FROM emp o WHERE EXISTS (SELECT 1 FROM emp i WHERE i.dept = o.dept "
               "AND i.id <> o.id)", [[1], [2]])
    emp.expect("SELECT NOT EXISTS (SELECT * FROM emp WHERE sal > 100), "
               "EXISTS (SELECT id, sal FROM emp)", [[True, True]])
    assert emp.columns("SELECT EXISTS (SELECT 1), NOT EXISTS (SELECT 1)") == [
        "exists", "?column?"]
    emp.expect("SELECT EXISTS (SELECT NULL)", [[True]])


def test_correlated_select_list(emp):
    emp.expect("SELECT id, (SELECT MAX(sal) FROM emp e2 WHERE e2.dept = emp.dept) FROM emp",
               [[1, 20], [2, 20], [3, 30], [4, None]])


def test_name_resolution_innermost_first(db):
    db.run("CREATE TABLE a (x INT, y INT)", "CREATE TABLE b (x INT, z INT)")
    db.run("INSERT INTO a VALUES (1, 10), (2, 20)", "INSERT INTO b VALUES (2, 7)")
    # x resolves to b.x (innermost); y is found only in the outer query.
    db.expect("SELECT y, (SELECT COUNT(*) FROM b WHERE x = 2) FROM a", [[10, 1], [20, 1]])
    db.expect("SELECT y FROM a WHERE EXISTS (SELECT 1 FROM b WHERE b.x = a.x)", [[20]])
    db.expect("SELECT (SELECT y + z FROM b) FROM a", [[17], [27]])
    # a.x: no table exposed as a inside, so it moves out.
    db.expect("SELECT (SELECT a.x FROM b) FROM a", [[1], [2]])
    # Inner alias hides the outer table name.
    db.expect("SELECT (SELECT a.z FROM b AS a) FROM a", [[7], [7]])


def test_ambiguous_innermost_match_is_an_error(db):
    db.run("CREATE TABLE a (x INT)", "CREATE TABLE b (x INT)", "CREATE TABLE c (w INT)")
    assert db.error("SELECT (SELECT x FROM a JOIN b ON TRUE) FROM c") == "NameError"
    assert db.error("SELECT (SELECT nope FROM a) FROM c") == "NameError"


def test_multi_level_correlation(db):
    db.run("CREATE TABLE t (n INT)", "INSERT INTO t VALUES (1), (2), (3)")
    db.expect("SELECT n, (SELECT COUNT(*) FROM t AS u WHERE u.n <= t.n AND EXISTS "
              "(SELECT 1 FROM t AS v WHERE v.n = t.n + u.n - 1)) FROM t",
              [[1, 1], [2, 2], [3, 1]])
    db.expect("SELECT n FROM t WHERE (SELECT COUNT(*) FROM (SELECT * FROM t AS i "
              "WHERE i.n > t.n) d) = 1", [[2]])


def test_uncorrelated_subquery_is_lazy_and_runs_once(db):
    db.run("CREATE TABLE t (a INT)", "CREATE TABLE z (d INT)", "INSERT INTO z VALUES (0)")
    # Never needed: the outer table is empty.
    db.expect("SELECT a FROM t WHERE a > (SELECT 1 / d FROM z)", [])
    db.expect("SELECT (SELECT 1 / d FROM z) FROM t", [])
    db.run("INSERT INTO t VALUES (1)")
    assert db.error("SELECT a FROM t WHERE a > (SELECT 1 / d FROM z)") == "RuntimeError"
    # Short-circuit: the subquery is not needed.
    db.expect("SELECT a FROM t WHERE FALSE AND a > (SELECT 1 / d FROM z)", [])
    db.expect("SELECT CASE WHEN a = 1 THEN 0 ELSE (SELECT 1 / d FROM z) END FROM t", [[0]])


def test_correlated_subquery_respects_short_circuit(db):
    db.run("CREATE TABLE t (a INT)", "INSERT INTO t VALUES (0), (2)")
    db.expect("SELECT a FROM t WHERE a <> 0 AND (SELECT 10 / t.a) = 5", [[2]])
    assert db.error("SELECT a FROM t WHERE (SELECT 10 / t.a) = 5") == "RuntimeError"


def test_aggregate_belongs_to_the_query_it_is_written_in(emp):
    # SUM(o.sal) is an aggregate of the subquery (one row without FROM): it is o.sal.
    emp.expect("SELECT (SELECT SUM(o.sal)) FROM emp o", [[10], [20], [30], [5]])
    emp.expect("SELECT (SELECT SUM(o.sal) FROM emp i WHERE i.dept = 'a') FROM emp o "
               "WHERE o.id < 3", [[20], [40]])
    # The outer query is not grouped by the inner aggregate.
    emp.expect("SELECT id FROM emp WHERE sal = (SELECT MAX(sal) FROM emp)", [[3]])


def test_grouping_rule_extends_into_subqueries(emp):
    emp.expect("SELECT dept, (SELECT COUNT(*) FROM emp i WHERE i.dept = emp.dept) FROM emp "
               "GROUP BY dept", [["a", 2], ["b", 1], [None, 0]])
    emp.expect("SELECT dept FROM emp GROUP BY dept HAVING EXISTS (SELECT 1 FROM emp i "
               "WHERE i.dept = emp.dept AND i.sal > 15)", [["a"], ["b"]])
    emp.expect("SELECT dept FROM emp GROUP BY dept ORDER BY (SELECT COUNT(*) FROM emp i "
               "WHERE i.dept = emp.dept), dept", [[None], ["b"], ["a"]])
    for sql in (
        "SELECT dept, (SELECT COUNT(*) FROM emp i WHERE i.sal = emp.sal) FROM emp "
        "GROUP BY dept",
        "SELECT dept FROM emp GROUP BY dept HAVING (SELECT SUM(emp.sal)) > 15",
        "SELECT COUNT(*), (SELECT emp.id) FROM emp",
    ):
        assert emp.error(sql) == "SyntaxError", sql
    # In WHERE (before grouping) and inside the grouped query's aggregates it is fine.
    emp.expect("SELECT dept, COUNT(*) FROM emp WHERE sal > (SELECT MIN(i.sal) FROM emp i "
               "WHERE i.id <> emp.id) GROUP BY dept", [["a", 2], ["b", 1]])
    emp.expect("SELECT SUM((SELECT emp.sal)) FROM emp", [[65]])


def test_subqueries_in_on_and_order_by(db):
    db.run("CREATE TABLE a (x INT)", "CREATE TABLE b (y INT)")
    db.run("INSERT INTO a VALUES (1), (2)", "INSERT INTO b VALUES (2), (3)")
    db.expect("SELECT x, y FROM a JOIN b ON y = (SELECT MAX(x) FROM a) ", [[1, 2], [2, 2]])
    db.expect("SELECT x, y FROM a JOIN b ON y IN (SELECT a.x + 1)", [[1, 2], [2, 3]])
    db.expect("SELECT x FROM a ORDER BY (SELECT -a.x)", [[2], [1]])


def test_subqueries_in_insert_update_delete(emp):
    emp.run("CREATE TABLE log (n INT, top INT)")
    emp.run("INSERT INTO log VALUES ((SELECT COUNT(*) FROM emp), (SELECT MAX(sal) FROM emp))")
    emp.expect("SELECT * FROM log", [[4, 30]])
    assert emp.error("INSERT INTO log VALUES ((SELECT id FROM emp), 1)") == "RuntimeError"
    # UPDATE: subqueries correlate with the target and see it as before the statement.
    assert emp.run("UPDATE emp SET sal = (SELECT MAX(sal) FROM emp e2 WHERE e2.dept = "
                   "emp.dept) + (SELECT COUNT(*) FROM emp WHERE sal >= 20)") == {"rowcount": 4}
    emp.expect("SELECT sal FROM emp", [[22], [22], [32], [None]])
    assert emp.run("UPDATE emp SET sal = 0 WHERE sal = (SELECT MAX(sal) FROM emp)") == {
        "rowcount": 1}
    # DELETE: the subquery sees the table before any row is deleted.
    assert emp.run("DELETE FROM emp WHERE sal < (SELECT MAX(e.sal) FROM emp e WHERE "
                   "e.id <> emp.id)") == {"rowcount": 1}
    emp.expect("SELECT id FROM emp", [[1], [2], [4]])
    assert emp.run("DELETE FROM emp WHERE id IN (SELECT id FROM emp WHERE id > 1)") == {
        "rowcount": 2}
    emp.expect("SELECT id FROM emp", [[1]])


def test_subqueries_not_allowed_in_default_and_group_by(emp):
    assert emp.error("CREATE TABLE x (a INT DEFAULT (SELECT 1))") == "SyntaxError"
    assert emp.error("SELECT COUNT(*) FROM emp GROUP BY (SELECT 1)") == "SyntaxError"


def test_subquery_syntax(emp):
    for sql in ("SELECT (SELECT 1 ORDER BY 1)", "SELECT EXISTS SELECT 1", "SELECT EXISTS (1)",
                "SELECT 1 IN SELECT 1", "SELECT (SELECT)", "SELECT 1 IN (SELECT 1) = TRUE"):
        assert emp.error(sql) == "SyntaxError", sql
    emp.expect("SELECT (SELECT id FROM emp ORDER BY id DESC LIMIT 1)", [[4]])
    emp.expect("SELECT ((SELECT 1)) + (SELECT 2)", [[3]])


def test_plans_report_correlation():
    from minidb.catalog import Database
    db = Database()
    ctx = QueryContext(db, Runtime())
    plan = build_query(parse("SELECT (SELECT 1), 2"), ctx)
    assert plan.columns == ["?column?", "?column?"] and plan.run() == [(1, 2)]
    assert not ctx.correlated


def _linear_in(x, items):
    """Reference semantics of section 2: x = item for each item in order, OR-combined."""
    from minidb.values import COMPARISONS
    result = False
    for item in items:
        if x is None or item is None:
            result = None
        elif COMPARISONS["="](x, item):
            return True
    return result


def test_in_index_matches_linear_semantics():
    import random

    from minidb.compiler import InIndex
    from minidb.protocol import SQLTypeError
    pool = [None, 0, 1, 2, 1.0, 2.5, True, False, "a", "1", ""]
    r = random.Random(7)
    for _ in range(3000):
        items = [r.choice(pool) for _ in range(r.randint(0, 5))]
        x = r.choice(pool)
        try:
            expected = ("ok", _linear_in(x, items))
        except SQLTypeError:
            expected = ("TypeError",)
        try:
            got = ("ok", InIndex(items).lookup(x))
        except SQLTypeError:
            got = ("TypeError",)
        assert got == expected and (len(got) == 1 or type(got[1]) is type(expected[1])), (
            x, items)


def test_large_in_subquery(db):
    db.run("CREATE TABLE t (id INT)")
    db.run("INSERT INTO t VALUES " + ", ".join(f"({i})" for i in range(3000)))
    db.expect("SELECT COUNT(*) FROM t WHERE id IN (SELECT id * 2 FROM t)", [[1500]])
    db.expect("SELECT COUNT(*) FROM t WHERE id NOT IN (SELECT id * 2 FROM t)", [[1500]])


def _probe_outcomes(seed):
    """Each correlated query two ways: WHERE i.k = o.k ... (probed through a hash of i.k) and
    WHERE TRUE AND i.k = o.k ... (the same condition, but the probe does not apply)."""
    import random as _random

    from minidb.engine import Engine
    from minidb.protocol import DBError
    r = _random.Random(seed)
    engine = Engine()
    engine.execute("CREATE TABLE i (k INT, v INT)")
    if r.random() < 0.3:
        engine.execute("CREATE INDEX i_v ON i (v)")
    rows = [f"({r.choice(['NULL', r.randint(0, 3)])}, {r.choice(['NULL', r.randint(0, 2)])})"
            for _ in range(r.randint(0, 8))]
    if rows:
        engine.execute("INSERT INTO i VALUES " + ", ".join(rows))
    # outer keys: mostly integers, sometimes NULL, a REAL or (incomparable) a TEXT
    keys = [r.choice(["NULL", "0", "1", "2", "3", "1.0", "'1'"]) for _ in range(r.randint(1, 5))]
    outer = "(" + " UNION ALL ".join(f"SELECT {x} AS k" for x in keys) + ") o"
    rest = r.choice(["", " AND 10 / i.v > 1", " AND i.v IS NOT NULL", " OR i.v = 0"])
    shapes = [f"SELECT o.k, (SELECT SUM(i.v) FROM i WHERE {{c}}{rest}) FROM {outer}",
              f"SELECT o.k FROM {outer} WHERE EXISTS (SELECT 1 FROM i WHERE {{c}}{rest})",
              f"SELECT o.k FROM {outer} WHERE 2 IN (SELECT i.v FROM i WHERE {{c}}{rest})",
              f"SELECT o.k, (SELECT COUNT(*) FROM i WHERE {{c}}{rest} AND i.v = 1) FROM {outer}"]
    results = []
    for shape in shapes:
        pair = []
        for cond in ("i.k = o.k", "TRUE AND i.k = o.k"):
            try:
                pair.append(("ok", engine.execute(shape.format(c=cond))["rows"]))
            except DBError as exc:
                pair.append((exc.type_name,))
        results.append(pair)
    return results


@pytest.mark.parametrize("seed", range(200))
def test_correlated_probe_matches_full_scan(seed):
    for probed, scanned in _probe_outcomes(seed):
        assert probed == scanned


def test_correlated_probe_test_covers_errors_and_rows():
    kinds = {p[0] if p[0] != "ok" else ("rows" if p[1] else "empty")
             for seed in range(200) for p, _ in _probe_outcomes(seed)}
    assert {"TypeError", "RuntimeError", "rows"} <= kinds


def test_correlated_probe_is_fast(db):
    import time
    db.run("CREATE TABLE c (id INT PRIMARY KEY)", "CREATE TABLE o (cid INT, amount INT)")
    db.run("INSERT INTO c VALUES " + ", ".join(f"({i})" for i in range(5000)))
    db.run("INSERT INTO o VALUES " + ", ".join(f"({i % 6000}, {i % 7})" for i in range(20000)))
    start = time.perf_counter()
    rows = db.rows("SELECT id, (SELECT SUM(amount) FROM o WHERE o.cid = c.id) FROM c")
    assert time.perf_counter() - start < 2  # a full scan per outer row would take minutes
    assert len(rows) == 5000 and rows[1] == [1, 1 + 6001 % 7 + 12001 % 7 + 18001 % 7]
