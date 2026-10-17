"""Section 20: window functions."""
import pytest

from minidb.windows import RunningAggregate, WindowSpec


@pytest.fixture
def emp(db):
    db.run("CREATE TABLE emp (id INT PRIMARY KEY, name TEXT, dept TEXT, sal INT)")
    db.run("INSERT INTO emp VALUES (1, 'ann', 'a', 100), (2, 'bob', 'a', 80), "
           "(3, 'cid', 'b', 90), (4, 'dan', 'a', 80), (5, 'eve', 'b', NULL), "
           "(6, 'fay', NULL, 70)")
    return db


def test_ranking_functions(emp):
    emp.expect("SELECT name, ROW_NUMBER() OVER (ORDER BY sal DESC), RANK() OVER (ORDER BY sal "
               "DESC), DENSE_RANK() OVER (ORDER BY sal DESC) FROM emp",
               [["ann", 2, 2, 2], ["bob", 4, 4, 4], ["cid", 3, 3, 3], ["dan", 5, 4, 4],
                ["eve", 1, 1, 1], ["fay", 6, 6, 5]])
    emp.expect("SELECT name, ROW_NUMBER() OVER (PARTITION BY dept ORDER BY sal) FROM emp",
               [["ann", 3], ["bob", 1], ["cid", 1], ["dan", 2], ["eve", 2], ["fay", 1]])
    # without ORDER BY all rows of a partition are peers; ROW_NUMBER follows row order
    emp.expect("SELECT ROW_NUMBER() OVER (), RANK() OVER (), DENSE_RANK() OVER (PARTITION BY "
               "dept) FROM emp WHERE id < 4", [[1, 1, 1], [2, 1, 1], [3, 1, 1]])
    assert emp.columns("SELECT ROW_NUMBER() OVER (), rank() OVER (), DENSE_RANK() OVER () "
                       "AS d FROM emp") == ["row_number", "rank", "d"]


def test_window_order_rules(emp):
    # NULL placement (CR-1) and NULLS FIRST / LAST
    emp.expect("SELECT name FROM emp ORDER BY ROW_NUMBER() OVER (ORDER BY sal)",
               [["fay"], ["bob"], ["dan"], ["cid"], ["ann"], ["eve"]])
    emp.expect("SELECT name, ROW_NUMBER() OVER (ORDER BY sal NULLS FIRST) FROM emp "
               "WHERE dept = 'b'", [["cid", 2], ["eve", 1]])
    emp.expect("SELECT name, ROW_NUMBER() OVER (ORDER BY sal DESC NULLS LAST) FROM emp "
               "WHERE dept = 'b'", [["cid", 1], ["eve", 2]])
    # ties keep the order the rows had before window functions were computed
    emp.expect("SELECT name, ROW_NUMBER() OVER (ORDER BY dept) FROM emp ORDER BY id DESC",
               [["fay", 6], ["eve", 5], ["dan", 3], ["cid", 4], ["bob", 2], ["ann", 1]])
    # an integer literal is a constant, not a position
    emp.expect("SELECT ROW_NUMBER() OVER (ORDER BY 2 DESC, 1) FROM emp WHERE id < 4",
               [[1], [2], [3]])
    emp.expect("SELECT ROW_NUMBER() OVER (ORDER BY dept DESC, sal) FROM emp",
               [[6], [4], [2], [5], [3], [1]])


def test_window_order_type_rule_is_per_partition(db):
    db.run("CREATE TABLE t (p INT, v INT, s TEXT)")
    db.run("INSERT INTO t VALUES (1, 1, NULL), (1, 2, NULL), (2, NULL, 'x'), (2, NULL, 'y')")
    db.expect("SELECT ROW_NUMBER() OVER (PARTITION BY p ORDER BY COALESCE(v, s)) FROM t",
              [[1], [2], [1], [2]])
    db.run("INSERT INTO t VALUES (1, NULL, 'z')")
    assert db.error("SELECT ROW_NUMBER() OVER (PARTITION BY p ORDER BY COALESCE(v, s)) FROM t") \
        == "TypeError"


def test_partitions_use_distinct_equality(db):
    db.run("CREATE TABLE t (r REAL, i INT, b BOOLEAN)")
    db.run("INSERT INTO t VALUES (1, 1, TRUE), (1.5, 1, NULL), (NULL, NULL, NULL), (1, 2, FALSE)")
    db.expect("SELECT COUNT(*) OVER (PARTITION BY r) FROM t", [[2], [1], [1], [2]])
    db.expect("SELECT COUNT(*) OVER (PARTITION BY i, b IS NULL) FROM t", [[1], [1], [1], [1]])
    db.expect("SELECT COUNT(*) OVER (PARTITION BY CASE WHEN i = 1 THEN 1 ELSE 1.0 END) FROM t",
              [[4], [4], [4], [4]])


def test_lag_and_lead(emp):
    emp.expect("SELECT name, LAG(name) OVER (ORDER BY id), LEAD(name) OVER (ORDER BY id), "
               "LAG(sal, 2, -1) OVER (ORDER BY id), LEAD(name, 0) OVER () FROM emp",
               [["ann", None, "bob", -1, "ann"], ["bob", "ann", "cid", -1, "bob"],
                ["cid", "bob", "dan", 100, "cid"], ["dan", "cid", "eve", 80, "dan"],
                ["eve", "dan", "fay", 90, "eve"], ["fay", "eve", None, 80, "fay"]])
    # the default is evaluated for the current row
    emp.expect("SELECT LEAD(sal, 1, id * 1000) OVER (PARTITION BY dept ORDER BY id) FROM emp",
               [[80], [80], [None], [4000], [5000], [6000]])
    emp.expect("SELECT LAG(name, 10) OVER () FROM emp WHERE id = 1", [[None]])
    assert emp.columns("SELECT LAG(id) OVER (), LEAD(id) OVER () FROM emp") == ["lag", "lead"]


@pytest.mark.parametrize("sql", [
    "LAG(id, -1) OVER ()", "LAG(id, 1 + 1) OVER ()", "LAG(id, id) OVER ()",
    "LAG(id, 1.0) OVER ()", "LEAD() OVER ()", "LEAD(id, 1, 2, 3) OVER ()",
    "ROW_NUMBER(1) OVER ()", "RANK(id) OVER ()", "COUNT() OVER ()", "SUM(id, id) OVER ()",
    "SUM(*) OVER ()", "COUNT(DISTINCT id) OVER ()", "SUM(DISTINCT sal) OVER ()",
    "ROW_NUMBER()", "RANK()", "DENSE_RANK()", "LAG(id)", "LEAD(id, 1)",
    "LOWER(name) OVER ()", "ROW_NUMBER() OVER", "ROW_NUMBER() OVER (PARTITION id)",
    "ROW_NUMBER() OVER (ORDER id)", "ROW_NUMBER() OVER w",
])
def test_window_syntax_errors(emp, sql):
    assert emp.error(f"SELECT {sql} FROM emp") == "SyntaxError"


def test_unknown_window_function(emp):
    assert emp.error("SELECT NTILE(2) OVER () FROM emp") == "NameError"


@pytest.mark.parametrize("sql", [
    "SELECT id FROM emp WHERE ROW_NUMBER() OVER () = 1",
    "SELECT dept FROM emp GROUP BY ROW_NUMBER() OVER ()",
    "SELECT dept FROM emp GROUP BY dept HAVING RANK() OVER (ORDER BY dept) = 1",
    "SELECT * FROM emp a JOIN emp b ON ROW_NUMBER() OVER () = 1",
    "UPDATE emp SET sal = ROW_NUMBER() OVER ()",
    "UPDATE emp SET sal = 1 WHERE ROW_NUMBER() OVER () = 1",
    "DELETE FROM emp WHERE ROW_NUMBER() OVER () = 1",
    "INSERT INTO emp VALUES (ROW_NUMBER() OVER (), 'x', 'y', 1)",
    "SELECT SUM(ROW_NUMBER() OVER ()) FROM emp",
    "SELECT LAG(ROW_NUMBER() OVER ()) OVER () FROM emp",
    "SELECT ROW_NUMBER() OVER (PARTITION BY RANK() OVER ()) FROM emp",
    "SELECT ROW_NUMBER() OVER (ORDER BY SUM(id) OVER ()) FROM emp",
    "SELECT CASE WHEN TRUE THEN 1 END FROM emp WHERE CASE WHEN ROW_NUMBER() OVER () = 1 "
    "THEN TRUE END",
])
def test_windows_only_in_select_list_and_order_by(emp, sql):
    assert emp.error(sql) == "SyntaxError"


def test_windows_inside_expressions_and_subqueries(emp):
    emp.expect("SELECT ROW_NUMBER() OVER () * 10 + 1, CASE WHEN RANK() OVER (ORDER BY sal) = 1 "
               "THEN 'low' END FROM emp WHERE id > 4", [[11, None], [21, "low"]])
    emp.expect("SELECT name FROM emp WHERE id = (SELECT x.id FROM (SELECT id, ROW_NUMBER() "
               "OVER (ORDER BY sal DESC NULLS LAST) AS rn FROM emp) x WHERE x.rn = 1)",
               [["ann"]])
    emp.run("CREATE VIEW ranked AS SELECT name, RANK() OVER (ORDER BY sal) AS r FROM emp")
    emp.expect("SELECT name FROM ranked WHERE r = 2", [["bob"], ["dan"]])
    emp.expect("WITH w AS (SELECT name, SUM(sal) OVER (ORDER BY id) AS run FROM emp) "
               "SELECT run FROM w WHERE name = 'cid'", [[270]])
    emp.expect("SELECT ROW_NUMBER() OVER (), COUNT(*) OVER ()", [[1, 1]])


def test_window_aggregates(emp):
    emp.expect("SELECT name, SUM(sal) OVER (ORDER BY sal), COUNT(*) OVER (ORDER BY sal), "
               "COUNT(sal) OVER (ORDER BY sal), AVG(sal) OVER (PARTITION BY dept), "
               "MIN(name) OVER (PARTITION BY dept ORDER BY name DESC), MAX(sal) OVER () "
               "FROM emp",
               [["ann", 420, 5, 5, 260 / 3, "ann", 100], ["bob", 230, 3, 3, 260 / 3, "bob", 100],
                ["cid", 320, 4, 4, 90.0, "cid", 100], ["dan", 230, 3, 3, 260 / 3, "dan", 100],
                ["eve", 420, 6, 5, 90.0, "eve", 100], ["fay", 70, 1, 1, 70.0, "fay", 100]])
    emp.expect("SELECT SUM(sal) OVER (PARTITION BY dept) FROM emp WHERE id IN (3, 5)",
               [[90], [90]])
    emp.expect("SELECT SUM(sal) OVER (ORDER BY id), AVG(sal) OVER (ORDER BY id) FROM emp "
               "WHERE id > 4", [[None, None], [70, 70.0]])
    assert emp.columns("SELECT SUM(sal) OVER (), COUNT(*) OVER (), MIN(id) OVER () FROM emp") \
        == ["sum", "count", "min"]


def test_window_aggregates_follow_section_6(db):
    db.run("CREATE TABLE t (i INT, r REAL, s TEXT)")
    db.run("INSERT INTO t VALUES (9223372036854775807, 0.5, 'a'), (1, 0.25, 'b'), "
           "(-2, NULL, NULL)")
    assert db.error("SELECT SUM(i) OVER (ORDER BY s) FROM t") == "RuntimeError"
    db.expect("SELECT SUM(i) OVER () FROM t", [[9223372036854775806]] * 3)
    db.expect("SELECT SUM(r) OVER (ORDER BY s), TYPEOF(SUM(i + 0.0) OVER ()) FROM t",
              [[0.5, "REAL"], [0.75, "REAL"], [0.75, "REAL"]])
    assert db.error("SELECT SUM(s) OVER () FROM t") == "TypeError"
    assert db.error("SELECT MAX(COALESCE(s, i)) OVER () FROM t") == "TypeError"
    db.expect("SELECT MIN(COALESCE(s, i)) OVER (PARTITION BY s IS NULL) FROM t",
              [["a"], ["a"], [-2]])


def test_windows_in_grouped_queries(emp):
    emp.expect("SELECT dept, SUM(sal), RANK() OVER (ORDER BY SUM(sal) DESC NULLS LAST), "
               "SUM(SUM(sal)) OVER (), ROW_NUMBER() OVER (ORDER BY dept) FROM emp GROUP BY dept",
               [["a", 260, 1, 420, 1], ["b", 90, 2, 420, 2], [None, 70, 3, 420, 3]])
    emp.expect("SELECT COUNT(*), ROW_NUMBER() OVER () FROM emp", [[6, 1]])
    emp.expect("SELECT dept, LAG(dept) OVER (ORDER BY COUNT(*) DESC, dept) FROM emp "
               "GROUP BY dept HAVING COUNT(*) > 1", [["a", None], ["b", "a"]])
    assert emp.error("SELECT dept, ROW_NUMBER() OVER (ORDER BY sal) FROM emp GROUP BY dept") \
        == "SyntaxError"
    assert emp.error("SELECT dept, LAG(name) OVER () FROM emp GROUP BY dept") == "SyntaxError"


def test_windows_do_not_change_row_order_and_come_before_distinct(emp):
    emp.expect("SELECT id, ROW_NUMBER() OVER (ORDER BY id DESC) FROM emp WHERE id < 5",
               [[1, 4], [2, 3], [3, 2], [4, 1]])
    emp.expect("SELECT DISTINCT dept, COUNT(*) OVER (PARTITION BY dept) FROM emp",
               [["a", 3], ["b", 2], [None, 1]])
    emp.expect("SELECT name, RANK() OVER (ORDER BY sal) AS r FROM emp ORDER BY r DESC, 1 "
               "LIMIT 3", [["eve", 6], ["ann", 5], ["cid", 4]])
    emp.expect("SELECT name FROM emp ORDER BY 1 DESC LIMIT 2", [["fay"], ["eve"]])
    emp.expect("SELECT name, ROW_NUMBER() OVER () FROM emp ORDER BY 2 DESC LIMIT 1",
               [["fay", 6]])
    # windows see the rows after WHERE, before LIMIT
    emp.expect("SELECT COUNT(*) OVER () FROM emp WHERE sal > 75 LIMIT 1", [[4]])


def test_over_and_partition_are_not_reserved(db):
    db.run("CREATE TABLE over (partition INT, recursive INT)")
    db.run("INSERT INTO over VALUES (1, 2), (1, 3)")
    db.expect("SELECT partition, SUM(recursive) OVER (PARTITION BY partition) AS over "
              "FROM over", [[1, 5], [1, 5]])


def test_window_module_directly():
    spec = WindowSpec("row_number", order=[(lambda env: env[0], True, False)])
    assert spec.compute([(1,), (3,), (2,)]) == [3, 1, 2]
    running = RunningAggregate("avg", False)
    for x in (1, 2, None):
        running.add(x)
    assert running.value() == 1.5
