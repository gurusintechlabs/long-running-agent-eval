import pytest
from minidb import nodes as n
from minidb.parser import parse
from minidb.protocol import SQLSyntaxError


def test_precedence():
    e = parse("SELECT 1 + 2 * 3 = 7 AND NOT FALSE OR NULL").items[0].expr
    assert isinstance(e, n.Binary) and e.op == "OR"
    left = e.left
    assert left.op == "AND" and left.left.op == "=" and left.left.left.op == "+"
    assert isinstance(left.right, n.Unary) and left.right.op == "NOT"


def test_select_clauses():
    q = parse("SELECT DISTINCT a AS x, t.* FROM t AS u LEFT JOIN v ON u.id = v.id "
              "WHERE a > 1 GROUP BY a HAVING COUNT(*) > 1 ORDER BY 1 DESC, x LIMIT 5 OFFSET 2")
    assert q.distinct and q.items[0].alias == "x" and isinstance(q.items[1].expr, n.Star)
    assert q.from_.exposed == "u" and q.joins[0].kind == "left"
    assert [o.desc for o in q.order_by] == [True, False]
    assert (q.limit, q.offset) == (5, 2)


def test_statements():
    assert isinstance(parse("BEGIN TRANSACTION"), n.Begin)
    ct = parse("CREATE TABLE t (id INT PRIMARY KEY, name TEXT NOT NULL DEFAULT 'x', r REAL DEFAULT -1)")
    assert ct.columns[0].primary_key and ct.columns[1].default == "x" and ct.columns[2].default == -1
    view = parse("CREATE VIEW v AS SELECT a FROM t WHERE a > 1")
    assert view.sql == "SELECT a FROM t WHERE a > 1"
    assert isinstance(parse("ALTER TABLE t ADD COLUMN c BOOL"), n.AlterAddColumn)


@pytest.mark.parametrize("sql", [
    "SELECT 1 < 2 < 3", "SELECT * ", "CREATE TABLE t (a VARCHAR)", "CREATE TABLE select (a INT)",
    "UPDATE t SET a = 1, a = 2", "INSERT INTO t (a, a) VALUES (1, 2)", "EXPLAIN DELETE FROM t",
    "CREATE TABLE t (a INT PRIMARY KEY, b INT PRIMARY KEY)", "SELECT 1 LIMIT 1", "SELECT SUM(*) FROM t",
    "ALTER TABLE t ADD c INT UNIQUE"])
def test_syntax_errors(sql):
    with pytest.raises(SQLSyntaxError):
        parse(sql)
