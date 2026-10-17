"""Section 19: WITH queries (common table expressions), including WITH RECURSIVE."""
import pytest

from minidb import nodes as n
from minidb.parser import parse
from minidb.planner import count_references, split_recursive


@pytest.fixture
def emp(db):
    db.run("CREATE TABLE emp (id INT PRIMARY KEY, name TEXT, boss INT, sal INT)")
    db.run("INSERT INTO emp VALUES (1, 'ann', NULL, 100), (2, 'bob', 1, 80), "
           "(3, 'cid', 1, 90), (4, 'dan', 2, 70), (5, 'eve', 4, 60)")
    return db


def test_basic_with(emp):
    assert emp.run("WITH top AS (SELECT name, sal FROM emp WHERE sal >= 90) SELECT * FROM top") \
        == {"columns": ["name", "sal"], "rows": [["ann", 100], ["cid", 90]]}
    emp.expect("WITH a AS (SELECT id FROM emp WHERE id < 4), b AS (SELECT id * 10 AS x FROM a) "
               "SELECT x FROM b", [[10], [20], [30]])
    emp.expect("WITH c (n, s) AS (SELECT name, sal FROM emp WHERE id = 1) SELECT s, n FROM c",
               [[100, "ann"]])
    emp.expect("WITH o AS (SELECT name FROM emp ORDER BY sal) SELECT * FROM o LIMIT 2",
               [["eve"], ["dan"]])  # the name's rows come in its query's order


def test_with_errors(emp):
    assert emp.error("WITH a AS (SELECT 1), a AS (SELECT 2) SELECT * FROM a") == "NameError"
    assert emp.error("WITH a (x, x) AS (SELECT 1, 2) SELECT * FROM a") == "NameError"
    assert emp.error("WITH a (x) AS (SELECT 1, 2) SELECT * FROM a") == "SyntaxError"
    assert emp.error("WITH a AS (SELECT nope FROM emp) SELECT 1") == "NameError"
    # a name is only visible after its definition
    assert emp.error("WITH a AS (SELECT * FROM b), b AS (SELECT 1) SELECT * FROM a") == \
        "NameError"
    for sql in ("WITH a AS SELECT 1 SELECT * FROM a", "WITH a AS (SELECT 1)",
                "WITH a (SELECT 1) SELECT 1", "WITH AS (SELECT 1) SELECT 1",
                "WITH a AS (SELECT 1) INSERT INTO emp VALUES (9, 'x', 1, 1)",
                "SELECT 1 UNION WITH a AS (SELECT 1) SELECT 2", "WITH select AS (SELECT 1) SELECT 1"):
        assert emp.error(sql) == "SyntaxError", sql


def test_names_hide_tables_and_views(emp):
    emp.run("CREATE VIEW v AS SELECT 'view' AS w")
    emp.expect("WITH emp AS (SELECT 'cte' AS name) SELECT name FROM emp", [["cte"]])
    emp.expect("WITH v AS (SELECT 'cte' AS w) SELECT w FROM v", [["cte"]])
    emp.expect("WITH x AS (SELECT 1) SELECT COUNT(*) FROM emp", [[5]])
    # Without RECURSIVE, a query that names itself refers to the table of that name.
    emp.expect("WITH emp AS (SELECT name FROM emp WHERE id = 1) SELECT * FROM emp", [["ann"]])
    assert emp.error("WITH nope AS (SELECT * FROM nope) SELECT * FROM nope") == "NameError"


def test_names_visible_in_subqueries(emp):
    emp.expect("WITH rich AS (SELECT id FROM emp WHERE sal >= 90) "
               "SELECT name FROM emp WHERE id IN (SELECT id FROM rich)", [["ann"], ["cid"]])
    emp.expect("WITH rich AS (SELECT id FROM emp WHERE sal >= 90) "
               "SELECT name, (SELECT COUNT(*) FROM rich r WHERE r.id < e.id) FROM emp e "
               "WHERE id > 3", [["dan", 2], ["eve", 2]])
    emp.expect("WITH a AS (SELECT 2 AS k), b AS (SELECT name FROM emp WHERE id IN "
               "(SELECT k FROM a)) SELECT * FROM b", [["bob"]])
    emp.expect("WITH a AS (SELECT 3 AS k) SELECT * FROM (SELECT name FROM emp "
               "JOIN a ON a.k = emp.id) d", [["cid"]])


def test_with_anywhere_a_query_can_be(emp):
    emp.expect("SELECT (WITH c AS (SELECT MAX(sal) AS m FROM emp) SELECT m FROM c)", [[100]])
    emp.expect("SELECT * FROM (WITH c AS (SELECT 1 AS one) SELECT one FROM c) d", [[1]])
    emp.expect("SELECT 1 IN (WITH c AS (SELECT 1 AS x) SELECT x FROM c)", [[True]])
    emp.expect("SELECT EXISTS (WITH c AS (SELECT 1 AS x) SELECT x FROM c WHERE x > 1)",
               [[False]])
    emp.run("CREATE TABLE copy (id INT, name TEXT)")
    assert emp.run("INSERT INTO copy WITH c AS (SELECT id, name FROM emp WHERE id > 3) "
                   "SELECT * FROM c") == {"rowcount": 2}
    emp.expect("SELECT * FROM copy", [[4, "dan"], [5, "eve"]])
    emp.run("CREATE VIEW v AS WITH c AS (SELECT name FROM emp WHERE sal < 70) SELECT * FROM c")
    emp.expect("SELECT * FROM v", [["eve"]])
    emp.expect("WITH a AS (SELECT 1 AS x) SELECT x FROM a UNION SELECT 2 ORDER BY 1 DESC",
               [[2], [1]])


def test_correlated_with_in_a_subquery(emp):
    emp.expect("SELECT name, (WITH c AS (SELECT e.sal * 2 AS d) SELECT d FROM c) FROM emp e "
               "WHERE id < 3", [["ann", 200], ["bob", 160]])
    emp.expect("SELECT name FROM emp e WHERE EXISTS (WITH sub AS (SELECT id FROM emp "
               "WHERE boss = e.id) SELECT 1 FROM sub)", [["ann"], ["bob"], ["dan"]])


def test_with_plans(emp):
    emp.expect("EXPLAIN WITH c AS (SELECT * FROM emp WHERE id = 1) SELECT * FROM c",
               [["SCAN c"]])
    emp.expect("EXPLAIN WITH c AS (SELECT id FROM emp) SELECT * FROM emp JOIN c AS x "
               "ON x.id = emp.boss", [["SCAN emp"], ["HASH JOIN c (id)"]])


# ---------------------------------------------------------------- recursive

def test_recursive_hierarchy(emp):
    emp.expect("WITH RECURSIVE chain (id, name, depth) AS ("
               "SELECT id, name, 0 FROM emp WHERE boss IS NULL "
               "UNION ALL SELECT e.id, e.name, c.depth + 1 FROM emp e JOIN chain c "
               "ON e.boss = c.id) SELECT * FROM chain",
               [[1, "ann", 0], [2, "bob", 1], [3, "cid", 1], [4, "dan", 2], [5, "eve", 3]])
    emp.expect("WITH RECURSIVE up AS (SELECT id, boss FROM emp WHERE id = 5 UNION ALL "
               "SELECT emp.id, emp.boss FROM up JOIN emp ON emp.id = up.boss) "
               "SELECT id FROM up", [[5], [4], [2], [1]])


def test_recursive_counting_and_limits(db):
    db.expect("WITH RECURSIVE r (n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 5) "
              "SELECT * FROM r", [[1], [2], [3], [4], [5]])
    db.expect("WITH RECURSIVE r (n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 100000)"
              " SELECT COUNT(*), SUM(n) FROM r", [[100000, 5000050000]])
    assert db.error("WITH RECURSIVE r (n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r "
                    "WHERE n < 100001) SELECT COUNT(*) FROM r") == "RuntimeError"
    assert db.error("WITH RECURSIVE r (n) AS (SELECT 1 UNION ALL SELECT n FROM r) "
                    "SELECT 1 FROM r LIMIT 1") == "RuntimeError"


def test_recursive_union_removes_duplicates(db):
    db.run("CREATE TABLE edge (a INT, b INT)")
    db.run("INSERT INTO edge VALUES (1, 2), (2, 3), (3, 1), (3, 4), (2, 4)")
    # A cycle: UNION stops when nothing new is found.
    db.expect("WITH RECURSIVE reach (n) AS (SELECT 1 UNION SELECT edge.b FROM reach "
              "JOIN edge ON edge.a = reach.n) SELECT * FROM reach", [[1], [2], [3], [4]])
    # The anchor's own duplicates are removed too, and duplicates within a round.
    db.expect("WITH RECURSIVE r (n) AS (SELECT 1 UNION ALL SELECT 1 UNION SELECT n + 1 FROM r "
              "WHERE n < 3) SELECT * FROM r", [[1], [2], [3]])
    db.expect("WITH RECURSIVE r (n) AS (SELECT a FROM edge UNION SELECT n FROM r) "
              "SELECT * FROM r", [[1], [2], [3]])
    # UNION ALL keeps them: each round sees only the previous round's rows.
    db.expect("WITH RECURSIVE r (n, step) AS (SELECT 1, 0 UNION ALL SELECT edge.b, step + 1 "
              "FROM r JOIN edge ON edge.a = r.n WHERE step < 2) SELECT * FROM r",
              [[1, 0], [2, 1], [3, 2], [4, 2]])


def test_recursive_result_order_and_types(db):
    db.expect("WITH RECURSIVE r (x) AS (SELECT 1 UNION ALL SELECT 2 UNION ALL "
              "SELECT x * 10 FROM r WHERE x < 100) SELECT * FROM r",
              [[1], [2], [10], [20], [100], [200]])
    db.expect("WITH RECURSIVE r (x) AS (SELECT 1 UNION ALL SELECT CAST(x AS TEXT) FROM r "
              "WHERE TYPEOF(x) = 'INTEGER') SELECT x, TYPEOF(x) FROM r",
              [[1, "INTEGER"], ["1", "TEXT"]])
    db.expect("WITH RECURSIVE r AS (SELECT 1 AS first UNION ALL SELECT first + 1 FROM r "
              "WHERE first < 2) SELECT * FROM r", [[1], [2]])
    assert db.columns("WITH RECURSIVE r AS (SELECT 1 AS first UNION ALL SELECT first + 1 "
                      "AS other FROM r WHERE first < 2) SELECT * FROM r") == ["first"]


def test_recursive_not_needed(db):
    db.run("CREATE TABLE t (a INT)", "INSERT INTO t VALUES (7)")
    db.expect("WITH RECURSIVE a AS (SELECT 1 AS x), b AS (SELECT x + 1 AS y FROM a) "
              "SELECT * FROM b", [[2]])
    # a non-self-referencing query in WITH RECURSIVE that names a table
    db.expect("WITH RECURSIVE c AS (SELECT a FROM t) SELECT * FROM c", [[7]])


@pytest.mark.parametrize("cte", [
    "SELECT n FROM r",                                              # no anchor
    "SELECT 1 INTERSECT SELECT n FROM r",                           # not UNION
    "SELECT 1 EXCEPT SELECT n FROM r",
    "SELECT n FROM r UNION ALL SELECT 1",                           # anchor refers to r
    "SELECT 1 UNION ALL SELECT r.n FROM r JOIN r AS s ON TRUE",     # twice
    "SELECT 1 UNION ALL SELECT 1 FROM emp WHERE id IN (SELECT n FROM r)",   # in a subquery
    "SELECT 1 UNION ALL SELECT d.n FROM (SELECT n FROM r) d",       # in a derived table
    "SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE (SELECT COUNT(*) FROM r) < 3",
    "SELECT 1 UNION ALL SELECT COUNT(*) FROM r",                    # aggregate
    "SELECT 1 UNION ALL SELECT n FROM r GROUP BY n",
    "SELECT 1 UNION ALL SELECT DISTINCT n FROM r",
    "SELECT 1 UNION ALL SELECT n FROM r ORDER BY n",
    "SELECT 1 UNION ALL SELECT n FROM r LIMIT 3",
    "SELECT 1 UNION ALL SELECT 2 INTERSECT SELECT n FROM r",
    "WITH q AS (SELECT 1) SELECT n FROM r",
])
def test_recursive_syntax_errors(emp, cte):
    assert emp.error(f"WITH RECURSIVE r (n) AS ({cte}) SELECT * FROM r") == "SyntaxError"


def test_recursive_anchor_and_step_column_counts(db):
    assert db.error("WITH RECURSIVE r (n) AS (SELECT 1 UNION ALL SELECT n, n FROM r) "
                    "SELECT * FROM r") == "SyntaxError"


def test_recursive_inside_a_correlated_subquery(emp):
    emp.expect("SELECT name, (WITH RECURSIVE up (id, boss) AS (SELECT id, boss FROM emp "
               "WHERE id = e.id UNION ALL SELECT emp.id, emp.boss FROM up JOIN emp "
               "ON emp.id = up.boss) SELECT COUNT(*) FROM up) FROM emp e",
               [["ann", 1], ["bob", 2], ["cid", 2], ["dan", 3], ["eve", 4]])


def test_helpers():
    q = parse("WITH RECURSIVE r (n) AS (SELECT 1 UNION SELECT n FROM r) SELECT 1").ctes[0].query
    anchor, step, distinct = split_recursive(q, "r")
    assert isinstance(anchor, n.Select) and isinstance(step, n.Select) and distinct
    assert count_references(q, "r") == 1
    inner = parse("SELECT * FROM (WITH r AS (SELECT 1) SELECT * FROM r) d JOIN r ON TRUE")
    assert count_references(inner, "r") == 1  # the inner r is another name


def test_correlated_with_first_used_deeper_than_its_definition(emp):
    # c depends on the outer row e; it is first needed two subquery levels below its WITH,
    # and must be recomputed for every outer row.
    emp.expect("SELECT name, (WITH c AS (SELECT e.id * 10 AS k) "
               "SELECT (SELECT k + 1 FROM c) + (SELECT COUNT(*) FROM c WHERE k > 20)) "
               "FROM emp e", [["ann", 11], ["bob", 21], ["cid", 32], ["dan", 42], ["eve", 52]])
    emp.expect("SELECT e.name FROM emp e WHERE (WITH c AS (SELECT sal FROM emp WHERE boss = e.id) "
               "SELECT COUNT(*) FROM emp x WHERE x.sal IN (SELECT sal FROM c)) = 2", [["ann"]])
