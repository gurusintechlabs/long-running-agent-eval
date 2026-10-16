from minidb.engine import Engine, run_sql
from minidb.executor import Executor
from minidb.parser import parse
from minidb.protocol import SQLNameError, SQLSyntaxError

SETUP = """
CREATE TABLE emp (id INTEGER, name TEXT, dept INTEGER, salary INTEGER);
CREATE TABLE dept (id INTEGER, name TEXT);
INSERT INTO emp VALUES (1, 'a', 1, 10), (2, 'b', 1, NULL), (3, 'c', 2, 30), (4, 'd', NULL, 5);
INSERT INTO dept VALUES (1, 'x'), (2, 'y'), (3, 'z');
"""


def engine():
    e = Engine()
    run_sql(e, SETUP)
    return e


def q(e, sql):
    return Executor(e.db).query(parse(sql))["rows"]


def test_grouping_and_aggregates():
    e = engine()
    assert q(e, "SELECT dept, COUNT(*), COUNT(salary), SUM(salary), AVG(salary) FROM emp GROUP BY dept") == [
        [1, 2, 1, 10, 10.0], [2, 1, 1, 30, 30.0], [None, 1, 1, 5, 5.0]]
    assert q(e, "SELECT COUNT(*), SUM(salary) FROM emp WHERE id > 9") == [[0, None]]


def test_joins_and_correlated_subqueries():
    e = engine()
    assert q(e, "SELECT d.name, COUNT(e.id) AS n FROM dept d LEFT JOIN emp e ON e.dept = d.id "
                "GROUP BY d.name ORDER BY n DESC, d.name") == [["x", 2], ["y", 1], ["z", 0]]
    assert q(e, "SELECT name FROM emp e WHERE salary >= (SELECT MAX(salary) FROM emp WHERE dept = e.dept)") == [
        ["a"], ["c"]]
    assert q(e, "SELECT name FROM emp WHERE id NOT IN (SELECT dept FROM emp)") == []


def test_explain_and_index_use():
    e = engine()
    run_sql(e, "CREATE INDEX es ON emp (salary)")
    plan = Executor(e.db).explain(parse("SELECT * FROM emp WHERE name = 'a' AND salary > 6"))
    assert plan["rows"] == [["SEARCH emp USING INDEX es (salary RANGE)"]]
    assert q(e, "SELECT id FROM emp WHERE salary > 6") == [[1], [3]]


def test_static_name_errors():
    e = engine()
    for sql, err in (("SELECT id FROM emp JOIN dept ON TRUE", SQLNameError),
                     ("SELECT name, COUNT(*) FROM emp", SQLSyntaxError),
                     ("SELECT nope(1)", SQLNameError)):
        try:
            q(e, sql)
        except err:
            continue
        raise AssertionError(sql)
