"""Section 6: aggregates, GROUP BY, HAVING."""
import pytest

from minidb.compiler import AggregateSpec, contains_aggregate
from minidb.parser import parse


@pytest.fixture
def sales(db):
    db.run("CREATE TABLE s (region TEXT, item TEXT, qty INT, price REAL)")
    db.run("INSERT INTO s VALUES ('n', 'a', 1, 2.0), ('s', 'b', 5, NULL), ('n', 'b', 3, 1.5), "
           "(NULL, 'a', NULL, 4.0), ('s', 'a', 2, 1.0), (NULL, 'c', 4, NULL)")
    return db


def test_whole_table_aggregates(sales):
    sales.expect("SELECT COUNT(*), COUNT(qty), SUM(qty), AVG(qty), MIN(qty), MAX(item), "
                 "SUM(price), AVG(price) FROM s",
                 [[6, 5, 15, 3.0, 1, "c", 8.5, 2.125]])
    assert sales.columns("SELECT COUNT(*), sum(qty) AS total, Max(item) FROM s") == [
        "count", "total", "max"]


def test_aggregates_on_empty_input(sales):
    sales.expect("SELECT COUNT(*), COUNT(qty), SUM(qty), AVG(qty), MIN(qty), MAX(qty) "
                 "FROM s WHERE qty > 100", [[0, 0, None, None, None, None]])


def test_group_by(sales):
    sales.expect("SELECT region, COUNT(*), SUM(qty) FROM s GROUP BY region",
                 [["n", 2, 4], ["s", 2, 7], [None, 2, 4]])
    sales.expect("SELECT region, item, COUNT(*) FROM s GROUP BY region, item ORDER BY 1, 2",
                 [[None, "a", 1], [None, "c", 1], ["n", "a", 1], ["n", "b", 1],
                  ["s", "a", 1], ["s", "b", 1]])
    sales.expect("SELECT COUNT(*) FROM s GROUP BY item", [[3], [2], [1]])


def test_having_and_order_by_aggregates(sales):
    sales.expect("SELECT item FROM s GROUP BY item HAVING COUNT(*) > 1 ORDER BY SUM(qty) DESC",
                 [["b"], ["a"]])
    sales.expect("SELECT item, MAX(qty) AS m FROM s GROUP BY item ORDER BY m", [
        ["a", 2], ["c", 4], ["b", 5]])
    sales.expect("SELECT s.item AS i FROM s GROUP BY item ORDER BY item DESC LIMIT 1", [["c"]])
    sales.expect("SELECT COUNT(*) FROM s HAVING COUNT(*) > 100", [])
    sales.expect("SELECT COUNT(*) + 1 FROM s HAVING MIN(item) = 'a'", [[7]])


def test_having_filters_before_select_list_is_evaluated(sales):
    sales.expect("SELECT item, 10 / (COUNT(*) - 1) FROM s GROUP BY item HAVING COUNT(*) > 1",
                 [["a", 5], ["b", 10]])


def test_grouped_query_without_group_by_returns_one_row(db):
    db.run("CREATE TABLE t (a INT)")
    db.expect("SELECT COUNT(*), SUM(a), MAX(a) FROM t", [[0, None, None]])
    db.expect("SELECT COUNT(*)", [[1]])
    db.expect("SELECT SUM(2), MIN('x'), COUNT(NULL)", [[2, "x", 0]])


def test_group_reports_first_row_value(db):
    db.run("CREATE TABLE t (a REAL, b INT)")
    db.run("INSERT INTO t VALUES (1, 1), (1.0, 2), (2, 3)")
    db.expect("SELECT COUNT(*) FROM t GROUP BY a", [[2], [1]])


def test_distinct_aggregates(db):
    db.run("CREATE TABLE t (a INT, b TEXT)")
    db.run("INSERT INTO t VALUES (1, 'x'), (1, 'x'), (2, NULL), (NULL, 'y'), (2, 'y')")
    db.expect("SELECT COUNT(DISTINCT a), SUM(DISTINCT a), AVG(DISTINCT a), COUNT(DISTINCT b), "
              "MIN(DISTINCT b) FROM t", [[2, 3, 1.5, 2, "x"]])


def test_sum_and_avg_typing(db):
    db.run("CREATE TABLE t (i INT, r REAL)")
    db.run("INSERT INTO t VALUES (9223372036854775807, 0.1), (1, 0.2), (-2, 0.3)")
    db.expect("SELECT SUM(i), SUM(r), AVG(i) FROM t",
              [[9223372036854775806, 0.1 + 0.2 + 0.3, 9223372036854775806 / 3]])
    assert db.error("SELECT SUM(i) FROM t WHERE i > 0") == "RuntimeError"
    db.expect("SELECT SUM(i + 0.0) FROM t WHERE i < 2", [[-1.0]])


def test_min_max_rules(db):
    db.run("CREATE TABLE t (r REAL, i INT, b BOOLEAN)")
    db.run("INSERT INTO t VALUES (1.0, 1, TRUE), (2.5, 1, FALSE)")
    db.expect("SELECT MIN(COALESCE(r, 0) * 0 + 1.0), MAX(b), MIN(b) FROM t", [[1.0, True, False]])
    db.expect("SELECT MIN(r), MAX(r), MIN(i) FROM t", [[1.0, 2.5, 1]])
    assert db.error("SELECT MAX(r) FROM t GROUP BY i HAVING MIN(b) = 1") == "TypeError"


def test_min_returns_first_of_equal_values(db):
    db.run("CREATE TABLE t (r REAL, i INT)")
    db.run("INSERT INTO t VALUES (1.0, 1), (NULL, 1)")
    db.expect("SELECT MIN(COALESCE(r, i)), MAX(COALESCE(i * 1.0, 0)) FROM t", [[1.0, 1.0]])
    db.run("DELETE FROM t", "INSERT INTO t VALUES (NULL, 1), (1.0, 1)")
    db.expect("SELECT MIN(COALESCE(r, i)) FROM t", [[1]])


@pytest.mark.parametrize("sql", [
    "SELECT SUM(item) FROM s", "SELECT AVG(region) FROM s",
    "SELECT MAX(COALESCE(price, item)) FROM s",
    "SELECT SUM(qty = 1) FROM s",
])
def test_aggregate_type_errors(sales, sql):
    assert sales.error(sql) == "TypeError"


@pytest.mark.parametrize("sql", [
    "SELECT region, COUNT(*) FROM s",
    "SELECT item FROM s GROUP BY region",
    "SELECT region FROM s GROUP BY region HAVING qty > 1",
    "SELECT region FROM s GROUP BY region ORDER BY qty",
    "SELECT * FROM s GROUP BY region",
    "SELECT s.* FROM s GROUP BY region",
    "SELECT COUNT(*) FROM s WHERE COUNT(*) > 1",
    "SELECT COUNT(*) FROM s GROUP BY COUNT(*)",
    "SELECT SUM(COUNT(*)) FROM s",
    "SELECT COUNT(*, qty) FROM s",
    "SELECT COUNT() FROM s",
    "SELECT SUM(*) FROM s",
    "SELECT SUM(qty, qty) FROM s",
    "SELECT region FROM s GROUP BY 1",
    "SELECT region FROM s GROUP BY region || 'x'",
    "SELECT qty FROM s ORDER BY COUNT(*)",
    "SELECT DISTINCT region FROM s GROUP BY region ORDER BY COUNT(*)",
])
def test_grouping_syntax_errors(sales, sql):
    assert sales.error(sql) == "SyntaxError"


def test_grouping_name_errors(sales):
    assert sales.error("SELECT COUNT(*) FROM s GROUP BY nope") == "NameError"
    assert sales.error("SELECT COUNT(nope) FROM s") == "NameError"


def test_grouping_errors_on_empty_table(db):
    db.run("CREATE TABLE t (a INT, b INT)")
    assert db.error("SELECT a, COUNT(*) FROM t") == "SyntaxError"
    assert db.error("SELECT b FROM t GROUP BY a") == "SyntaxError"


def test_grouped_expressions_over_grouping_columns(sales):
    sales.expect("SELECT region || '!' AS r, COUNT(*) * 2 FROM s WHERE region IS NOT NULL "
                 "GROUP BY s.region ORDER BY region DESC", [["s!", 4], ["n!", 4]])


def test_compiler_helpers():
    sel = parse("SELECT lower(x), 1 + COUNT(*) FROM t")
    assert [contains_aggregate(i.expr) for i in sel.items] == [False, True]
    assert AggregateSpec("count", False, True, None).compute([(), ()]) == 2
