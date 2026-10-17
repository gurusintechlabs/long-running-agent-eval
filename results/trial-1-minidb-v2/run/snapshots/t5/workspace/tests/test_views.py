"""Section 18: views."""
import pytest

from minidb.catalog import View, view_from_spec
from tests.test_storage import session


@pytest.fixture
def emp(db):
    db.run("CREATE TABLE emp (id INT PRIMARY KEY, name TEXT, dept TEXT, sal INT)")
    db.run("INSERT INTO emp VALUES (3, 'cid', 'b', 90), (1, 'ann', 'a', 100), "
           "(2, 'bob', 'a', 80), (4, 'dan', NULL, NULL)")
    return db


def test_create_and_use_a_view(emp):
    assert emp.run("CREATE VIEW rich AS SELECT name, sal FROM emp WHERE sal >= 90") == {}
    assert emp.run("SELECT * FROM rich") == {"columns": ["name", "sal"],
                                             "rows": [["cid", 90], ["ann", 100]]}
    emp.run("INSERT INTO emp VALUES (5, 'eve', 'b', 95)", "UPDATE emp SET sal = 10 WHERE id = 3")
    emp.expect("SELECT name FROM rich", [["ann"], ["eve"]])  # always the current data


def test_column_list_renames(emp):
    emp.run("CREATE VIEW v (who, pay) AS SELECT name, sal * 2 FROM emp WHERE id < 3")
    assert emp.columns("SELECT * FROM v") == ["who", "pay"]
    emp.expect("SELECT pay FROM v WHERE who = 'ann'", [[200]])
    assert emp.error("SELECT name FROM v") == "NameError"
    assert emp.error("CREATE VIEW w (a) AS SELECT name, sal FROM emp") == "SyntaxError"
    assert emp.error("CREATE VIEW w (a, b, c) AS SELECT name, sal FROM emp") == "SyntaxError"
    assert emp.error("CREATE VIEW w (a, a) AS SELECT name, sal FROM emp") == "NameError"
    assert emp.error("SELECT * FROM w") == "NameError"


def test_view_row_order_is_its_query_order(emp):
    emp.run("CREATE VIEW by_sal AS SELECT name FROM emp ORDER BY sal DESC")
    emp.expect("SELECT * FROM by_sal", [["dan"], ["ann"], ["cid"], ["bob"]])
    emp.expect("SELECT b.name, e.id FROM by_sal b JOIN emp e ON e.name = b.name "
               "WHERE e.id < 3", [["ann", 1], ["bob", 2]])


def test_views_everywhere_a_table_can_appear(emp):
    emp.run("CREATE VIEW a_team AS SELECT id, name FROM emp WHERE dept = 'a'")
    emp.run("CREATE VIEW a_names AS SELECT name FROM a_team")  # a view over a view
    emp.expect("SELECT * FROM a_names", [["ann"], ["bob"]])
    emp.expect("SELECT e.name FROM emp e LEFT JOIN a_team t ON t.id = e.id WHERE t.id IS NULL",
               [["cid"], ["dan"]])
    emp.expect("SELECT name FROM emp WHERE id IN (SELECT id FROM a_team)", [["ann"], ["bob"]])
    emp.expect("SELECT COUNT(*) FROM (SELECT * FROM a_team) d", [[2]])
    emp.expect("SELECT (SELECT COUNT(*) FROM a_team t WHERE t.id < e.id) FROM emp e "
               "WHERE e.id = 3", [[2]])
    emp.expect("WITH x AS (SELECT * FROM a_team) SELECT name FROM x", [["ann"], ["bob"]])
    emp.expect("SELECT t.name FROM a_team AS t CROSS JOIN a_team u WHERE u.id = 1",
               [["ann"], ["bob"]])


def test_a_view_does_not_see_the_names_of_its_users(emp):
    emp.run("CREATE VIEW v AS SELECT name FROM emp WHERE id = 1")
    # The WITH name emp does not hide the table emp inside the view.
    emp.expect("WITH emp AS (SELECT 'shadow' AS name) SELECT v.name, e.name FROM v "
               "CROSS JOIN emp e", [["ann", "shadow"]])


def test_view_plans(emp):
    emp.run("CREATE VIEW v AS SELECT id, name FROM emp")
    emp.expect("EXPLAIN SELECT * FROM v WHERE id = 1", [["SCAN v"]])
    emp.expect("EXPLAIN SELECT * FROM emp JOIN v ON v.id = emp.id",
               [["SCAN emp"], ["HASH JOIN v (id)"]])
    emp.expect("EXPLAIN SELECT * FROM v AS x JOIN emp ON emp.id = x.id",
               [["SCAN v"], ["SEARCH emp USING INDEX emp_id_key (id = ?)"]])


def test_select_star_view_picks_up_new_columns(emp):
    emp.run("CREATE VIEW everything AS SELECT * FROM emp")
    emp.run("ALTER TABLE emp ADD COLUMN bonus INT DEFAULT 5")
    assert emp.columns("SELECT * FROM everything") == ["id", "name", "dept", "sal", "bonus"]
    emp.run("ALTER TABLE emp DROP COLUMN dept")
    emp.expect("SELECT * FROM everything WHERE id = 1", [[1, "ann", 100, 5]])
    emp.run("CREATE VIEW named (a, b, c, d) AS SELECT * FROM emp")
    emp.run("ALTER TABLE emp ADD COLUMN extra INT")
    assert emp.error("SELECT * FROM named") == "SyntaxError"  # 4 names, 5 columns now


def test_namespace_and_drop_rules(emp):
    emp.run("CREATE VIEW v AS SELECT 1 AS one")
    for sql in ("CREATE VIEW v AS SELECT 2", "CREATE VIEW emp AS SELECT 2",
                "CREATE TABLE v (a INT)", "DROP TABLE v", "DROP TABLE IF EXISTS v",
                "DROP VIEW emp", "DROP VIEW IF EXISTS emp", "DROP VIEW nope",
                "INSERT INTO v VALUES (1)", "UPDATE v SET one = 2", "DELETE FROM v",
                "CREATE INDEX vi ON v (one)", "ALTER TABLE v ADD x INT",
                "ALTER TABLE v DROP one", "CREATE VIEW w AS SELECT * FROM nope",
                "CREATE VIEW w AS SELECT nope FROM emp"):
        assert emp.error(sql) == "NameError", sql
    assert emp.run("CREATE VIEW IF NOT EXISTS v AS SELECT nope FROM nothing") == {}
    assert emp.run("CREATE VIEW IF NOT EXISTS emp AS SELECT 3") == {}
    assert emp.run("CREATE TABLE IF NOT EXISTS v (a INT)") == {}
    emp.expect("SELECT * FROM v", [[1]])
    assert emp.run("DROP VIEW IF EXISTS nope") == {}
    assert emp.run("DROP VIEW v") == {}
    assert emp.error("SELECT * FROM v") == "NameError"
    emp.run("CREATE TABLE v (a INT)")  # the name is free again
    emp.run("CREATE INDEX v ON emp (sal)")  # indexes have their own namespace


def test_view_syntax(emp):
    for sql in ("CREATE VIEW v SELECT 1", "CREATE VIEW v AS", "CREATE VIEW v AS (SELECT 1)",
                "CREATE VIEW v () AS SELECT 1", "CREATE VIEW select AS SELECT 1",
                "CREATE VIEW v AS SELECT 1; SELECT 2", "DROP VIEW", "CREATE VIEW v AS INSERT "
                "INTO emp VALUES (9, 'x', 'y', 1)"):
        assert emp.error(sql) == "SyntaxError", sql


def test_dropping_what_a_view_uses(emp):
    emp.run("CREATE VIEW v AS SELECT name, sal FROM emp")
    emp.run("ALTER TABLE emp DROP COLUMN sal")
    assert emp.error("SELECT * FROM v") == "NameError"
    emp.run("ALTER TABLE emp ADD COLUMN sal INT DEFAULT 1")
    emp.expect("SELECT sal FROM v WHERE name = 'ann'", [[1]])
    emp.run("DROP TABLE emp")
    assert emp.error("SELECT * FROM v") == "NameError"
    emp.run("CREATE TABLE emp (name TEXT, sal REAL)", "INSERT INTO emp VALUES ('new', 2)")
    emp.expect("SELECT * FROM v", [["new", 2.0]])


def test_a_view_cycle_cannot_be_created(emp):
    emp.run("CREATE VIEW a AS SELECT id FROM emp", "CREATE VIEW b AS SELECT * FROM a",
            "DROP VIEW a")
    # Creating a over b would close a cycle; checking a's query plans b, which needs a.
    assert emp.error("CREATE VIEW a AS SELECT * FROM b") == "NameError"
    assert emp.error("SELECT * FROM b") == "NameError"


def test_views_in_transactions(emp):
    emp.run("BEGIN", "CREATE VIEW v AS SELECT id FROM emp", "ROLLBACK")
    assert emp.error("SELECT * FROM v") == "NameError"
    emp.run("CREATE VIEW v AS SELECT id FROM emp")
    emp.run("BEGIN", "DROP VIEW v", "CREATE TABLE v (x TEXT)", "ROLLBACK")
    emp.expect("SELECT COUNT(*) FROM v", [[4]])
    emp.run("BEGIN", "DROP VIEW v", "COMMIT")
    assert emp.error("SELECT * FROM v") == "NameError"


def test_views_are_durable(tmp_path):
    path = tmp_path / "db"
    session(path, """
        CREATE TABLE t (a INT, b TEXT);
        INSERT INTO t VALUES (1, 'x'), (2, 'y');
        CREATE VIEW v (n, s) AS SELECT a * 10, b || '!' FROM t   -- a comment
        ;
        CREATE VIEW w AS WITH c AS (SELECT a FROM t) SELECT * FROM c ORDER BY a DESC;
        BEGIN; CREATE VIEW gone AS SELECT 1; ROLLBACK;
        CREATE VIEW dropped AS SELECT 1; DROP VIEW dropped;
    """)
    res = session(path, "SELECT * FROM v; SELECT * FROM w; SELECT * FROM gone; "
                        "SELECT * FROM dropped; CREATE TABLE v (z INT)")
    assert res[0] == {"ok": True, "columns": ["n", "s"], "rows": [[10, "x!"], [20, "y!"]]}
    assert res[1]["rows"] == [[2], [1]]
    assert [r["error"]["type"] for r in res[2:]] == ["NameError"] * 3


def test_view_from_stored_form():
    view = view_from_spec(["v", ["a"], "SELECT 1"])
    assert isinstance(view, View) and view.columns == ["a"] and view.sql == "SELECT 1"
