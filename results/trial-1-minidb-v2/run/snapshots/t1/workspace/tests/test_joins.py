"""Section 7: INNER, LEFT and CROSS joins."""
import pytest

from minidb.catalog import Database
from minidb.executor import Executor, SelectPlan
from minidb.parser import parse


@pytest.fixture
def shop(db):
    db.run("CREATE TABLE c (id INT PRIMARY KEY, name TEXT)")
    db.run("CREATE TABLE o (id INT, cid INT, amount INT)")
    db.run("INSERT INTO c VALUES (1, 'ann'), (2, 'bob'), (3, 'cid')")
    db.run("INSERT INTO o VALUES (10, 2, 5), (11, 1, 7), (12, 2, 1), (13, 9, 4)")
    return db


def test_inner_join_nested_loop_order(shop):
    shop.expect("SELECT c.name, o.id FROM c JOIN o ON o.cid = c.id",
                [["ann", 11], ["bob", 10], ["bob", 12]])
    shop.expect("SELECT name, o.id FROM o INNER JOIN c ON cid = c.id",
                [["bob", 10], ["ann", 11], ["bob", 12]])


def test_left_join(shop):
    shop.expect("SELECT c.name, o.amount FROM c LEFT JOIN o ON o.cid = c.id",
                [["ann", 7], ["bob", 5], ["bob", 1], ["cid", None]])
    shop.expect("SELECT o.id, name FROM o LEFT OUTER JOIN c ON cid = c.id AND amount > 4",
                [[10, "bob"], [11, "ann"], [12, None], [13, None]])


def test_cross_join_and_star(shop):
    res = shop.run("SELECT * FROM c CROSS JOIN o WHERE o.id = 10")
    assert res["columns"] == ["id", "name", "id", "cid", "amount"]
    assert res["rows"] == [[1, "ann", 10, 2, 5], [2, "bob", 10, 2, 5], [3, "cid", 10, 2, 5]]
    shop.expect("SELECT o.*, c.name FROM c CROSS JOIN o WHERE c.id = 3 AND o.id < 12",
                [[10, 2, 5, "cid"], [11, 1, 7, "cid"]])


def test_aliases_and_self_join(shop):
    shop.expect("SELECT a.name, b.name FROM c AS a JOIN c b ON a.id < b.id ORDER BY 1, 2",
                [["ann", "bob"], ["ann", "cid"], ["bob", "cid"]])
    assert shop.error("SELECT * FROM c JOIN c ON TRUE") == "NameError"
    assert shop.error("SELECT * FROM c x JOIN o x ON TRUE") == "NameError"
    assert shop.error("SELECT c.name FROM c AS x") == "NameError"


def test_name_resolution(shop):
    assert shop.error("SELECT id FROM c JOIN o ON o.cid = c.id") == "NameError"
    assert shop.error("SELECT nope FROM c JOIN o ON TRUE") == "NameError"
    assert shop.error("SELECT x.* FROM c JOIN o ON TRUE") == "NameError"
    assert shop.error("SELECT * FROM c JOIN o ON c.id = z.id") == "NameError"
    assert shop.error("SELECT * FROM c JOIN nope ON TRUE") == "NameError"
    shop.run("CREATE TABLE e (eid INT)")
    # ON may only refer to the tables joined so far.
    assert shop.error("SELECT * FROM c JOIN o ON o.cid = e.eid JOIN e ON TRUE") == "NameError"
    assert shop.error("SELECT * FROM c JOIN o ON eid = 1 JOIN e ON TRUE") == "NameError"
    shop.expect("SELECT COUNT(*) FROM c JOIN o ON TRUE JOIN e ON eid = c.id", [[0]])


def test_name_errors_on_empty_tables(db):
    db.run("CREATE TABLE a (x INT)", "CREATE TABLE b (x INT)")
    assert db.error("SELECT x FROM a JOIN b ON TRUE") == "NameError"
    assert db.error("SELECT * FROM a JOIN b ON a.x = b.y") == "NameError"


def test_join_syntax_errors(shop):
    for sql in ("SELECT * FROM c, o", "SELECT * FROM c RIGHT JOIN o ON TRUE",
                "SELECT * FROM c FULL OUTER JOIN o ON TRUE", "SELECT * FROM c JOIN o",
                "SELECT * FROM c CROSS JOIN o ON TRUE", "SELECT * FROM c LEFT JOIN o",
                "SELECT * FROM c JOIN o ON COUNT(*) > 0"):
        assert shop.error(sql) == "SyntaxError", sql


def test_on_condition_type_errors(db):
    db.run("CREATE TABLE a (n INT)", "CREATE TABLE b (s TEXT)")
    db.run("INSERT INTO a VALUES (NULL), (1)")
    db.expect("SELECT * FROM a JOIN b ON a.n = b.s", [])
    db.run("INSERT INTO b VALUES (NULL)")
    db.expect("SELECT * FROM a LEFT JOIN b ON a.n = b.s", [[None, None], [1, None]])
    db.run("INSERT INTO b VALUES ('x')")
    assert db.error("SELECT * FROM a JOIN b ON a.n = b.s") == "TypeError"
    assert db.error("SELECT * FROM a JOIN b ON a.n") == "TypeError"


def test_grouping_and_aggregates_over_joins(shop):
    shop.expect("SELECT c.name, COUNT(o.id), SUM(o.amount) FROM c LEFT JOIN o ON o.cid = c.id "
                "GROUP BY c.name ORDER BY 3 DESC",
                [["ann", 1, 7], ["bob", 2, 6], ["cid", 0, None]])
    shop.expect("SELECT DISTINCT c.name FROM c JOIN o ON o.cid = c.id WHERE amount < 6",
                [["bob"]])
    shop.expect("SELECT name FROM c JOIN o ON cid = c.id GROUP BY name HAVING COUNT(*) > 1",
                [["bob"]])


def test_three_way_join(shop):
    shop.run("CREATE TABLE r (oid INT, note TEXT)")
    shop.run("INSERT INTO r VALUES (12, 'late'), (10, 'ok'), (12, 'again')")
    shop.expect("SELECT name, o.id, note FROM c JOIN o ON o.cid = c.id "
                "LEFT JOIN r ON r.oid = o.id",
                [["ann", 11, None], ["bob", 10, "ok"], ["bob", 12, "late"],
                 ["bob", 12, "again"]])


def test_plan_can_be_built_directly():
    database = Database()
    Executor(database).execute(parse("CREATE TABLE t (a INT)"))
    plan = SelectPlan(database, parse("SELECT a FROM t"))
    assert plan.run() == (["a"], [])
