"""Parser: AST shapes, precedence and syntax errors."""
import pytest

from minidb import nodes as n
from minidb.parser import parse
from minidb.protocol import SQLSyntaxError


def expr(sql):
    stmt = parse("SELECT " + sql)
    return stmt.items[0].expr


def show(e):
    if isinstance(e, n.Literal):
        return repr(e.value)
    if isinstance(e, n.ColumnRef):
        return f"{e.table}.{e.name}" if e.table else e.name
    if isinstance(e, n.Binary):
        return f"({show(e.left)} {e.op} {show(e.right)})"
    if isinstance(e, n.Unary):
        return f"({e.op}{show(e.operand)})"
    if isinstance(e, n.Not):
        return f"(NOT {show(e.operand)})"
    if isinstance(e, n.FuncCall):
        return f"{e.name}({', '.join(show(a) for a in e.args)})"
    return type(e).__name__


@pytest.mark.parametrize("sql, tree", [
    ("1 + 2 * 3", "(1 + (2 * 3))"),
    ("10 - 3 - 2", "((10 - 3) - 2)"),
    ("-a * b", "((-a) * b)"),
    ("a OR b AND c", "(a OR (b AND c))"),
    ("NOT a = b", "(NOT (a = b))"),
    ("a || b + c", "(a || (b + c))"),
    ("a != b", "(a <> b)"),
    ("x NOT LIKE 'a%'", "(NOT (x LIKE 'a%'))"),
    ("t.a + lower(b)", "(t.a + lower(b))"),
    ("(1 + 2) * 3", "((1 + 2) * 3)"),
])
def test_precedence(sql, tree):
    assert show(expr(sql)) == tree


@pytest.mark.parametrize("sql", [
    "SELECT 1 < 2 < 3", "SELECT 1 = 1 IS NULL", "SELECT a b FROM t", "SELECT",
    "SELECT 1 WHERE TRUE", "SELECT 1 ORDER BY 1", "CREATE TABLE t ()",
    "CREATE TABLE t (a VARCHAR)", "CREATE TABLE select (a INT)",
    "CREATE TABLE t (a INT NOT NULL NOT NULL)",
    "CREATE TABLE t (a INT PRIMARY KEY, b INT PRIMARY KEY)",
    "CREATE TABLE t (a INT DEFAULT 1 + 1)", "INSERT INTO t VALUES (DEFAULT)",
    "INSERT INTO t (a, a) VALUES (1, 2)", "UPDATE t SET a = 1, a = 2",
    "UPDATE t SET t.a = 1", "UPDATE t AS x SET a = 1", "UPDATE t x SET a = 1",
    "DELETE FROM t x", "SELECT * FROM a, b", "SELECT * FROM a RIGHT JOIN b ON TRUE",
    "SELECT * FROM a FULL JOIN b ON TRUE", "SELECT * FROM a JOIN b",
    "SELECT * FROM a CROSS JOIN b ON TRUE", "SELECT * FROM t LIMIT -1",
    "SELECT * FROM t OFFSET 1", "SELECT * FROM t LIMIT 1.5",
    "SELECT * FROM t GROUP BY 1", "SELECT * FROM t GROUP BY a + 1",
    "SELECT 1 2", "SELECT -9223372036854775808",
])
def test_syntax_errors(sql):
    with pytest.raises(SQLSyntaxError):
        parse(sql)


def test_select_structure():
    s = parse("SELECT DISTINCT a AS x, t.* FROM t AS u LEFT OUTER JOIN v ON u.a = v.a "
              "CROSS JOIN w z WHERE a > 1 GROUP BY a HAVING COUNT(*) > 1 ORDER BY 1 DESC, x "
              "LIMIT 5 OFFSET 2")
    assert s.distinct
    assert s.items[0].alias == "x" and isinstance(s.items[1], n.Star)
    assert s.from_.first.exposed == "u"
    assert [(j.kind, j.table.exposed) for j in s.from_.joins] == [("LEFT", "v"), ("CROSS", "z")]
    assert [o.desc for o in s.order_by] == [True, False]
    assert all(o.bare for o in s.order_by)
    assert (s.limit, s.offset) == (5, 2)


def test_order_by_bare_flag():
    s = parse("SELECT a FROM t ORDER BY (1), 1 + 0, a, t.a")
    assert [o.bare for o in s.order_by] == [False, False, True, False]


def test_column_definitions():
    s = parse("CREATE TABLE t (a INT PRIMARY KEY, b TEXT DEFAULT 'x' NOT NULL UNIQUE, "
              "c REAL DEFAULT -1.5, d BOOL DEFAULT NULL)")
    a, b, c, d = s.columns
    assert (a.type, a.primary_key) == ("INTEGER", True)
    assert (b.not_null, b.unique, b.default) == (True, True, "x")
    assert c.default == -1.5 and d.has_default and d.default is None


def test_count_star_and_distinct_args():
    e = expr("COUNT(*)")
    assert e.star and e.name == "count"
    assert expr("sum(DISTINCT x)").distinct
