from minidb.engine import Engine, run_sql
from minidb.protocol import SQLRuntimeError, SQLSyntaxError

COMPANY = """
CREATE TABLE dept (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE emp (id INTEGER PRIMARY KEY, name TEXT, dept_id INTEGER, salary INTEGER);
INSERT INTO dept VALUES (1, 'eng'), (2, 'ops'), (3, 'sales');
INSERT INTO emp VALUES (1, 'ada', 1, 300), (2, 'bo', 1, 200), (3, 'cy', 2, 150), (4, 'di', NULL, 100);
"""


def rows(e, sql):
    out = run_sql(e, sql)[-1]
    assert isinstance(out, dict), out
    return out["rows"]


def engine():
    e = Engine()
    run_sql(e, COMPANY)
    return e


def test_correlated_and_uncorrelated_subqueries():
    e = engine()
    assert rows(e, "SELECT name FROM emp e WHERE salary = (SELECT MAX(salary) FROM emp WHERE dept_id = e.dept_id)") == [
        ["ada"], ["cy"]]
    assert rows(e, "SELECT d.name, (SELECT COUNT(*) FROM emp WHERE dept_id = d.id) FROM dept d") == [
        ["eng", 2], ["ops", 1], ["sales", 0]]
    assert rows(e, "SELECT id FROM emp WHERE id > 9 AND id IN (SELECT 1 / 0)") == []
    assert isinstance(run_sql(e, "SELECT (SELECT name FROM emp)")[0], SQLRuntimeError)


def test_set_operations_and_derived_tables():
    e = engine()
    assert rows(e, "SELECT 1 UNION SELECT 2 INTERSECT SELECT 3") == [[1]]
    assert rows(e, "SELECT dept_id FROM emp EXCEPT SELECT id FROM dept") == [[None]]
    assert rows(e, "SELECT x.n FROM (SELECT dept_id AS n, COUNT(*) AS c FROM emp GROUP BY dept_id) x "
                   "WHERE x.c > 1") == [[1]]
    assert isinstance(run_sql(e, "SELECT 1 UNION SELECT 1, 2")[0], SQLSyntaxError)


def test_insert_select_and_case():
    e = engine()
    run_sql(e, "CREATE TABLE t (n TEXT, band TEXT); INSERT INTO t SELECT name, "
               "CASE WHEN salary >= 200 THEN 'high' ELSE 'low' END FROM emp ORDER BY name DESC")
    assert rows(e, "SELECT * FROM t") == [["di", "low"], ["cy", "low"], ["bo", "high"], ["ada", "high"]]
