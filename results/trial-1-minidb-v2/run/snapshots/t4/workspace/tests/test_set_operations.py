"""Section 10: UNION [ALL], INTERSECT, EXCEPT."""
import pytest

from minidb import nodes as n
from minidb.parser import parse


@pytest.fixture
def ab(db):
    db.run("CREATE TABLE a (x INT, s TEXT)", "CREATE TABLE b (y INT, t TEXT)")
    db.run("INSERT INTO a VALUES (3, 'c'), (1, 'a'), (3, 'c'), (2, 'b'), (NULL, NULL)")
    db.run("INSERT INTO b VALUES (2, 'b'), (4, 'd'), (NULL, NULL), (2, 'b')")
    return db


def test_union_all_keeps_everything_in_order(ab):
    ab.expect("SELECT x FROM a UNION ALL SELECT y FROM b",
              [[3], [1], [3], [2], [None], [2], [4], [None], [2]])


def test_union_removes_later_duplicates(ab):
    ab.expect("SELECT x FROM a UNION SELECT y FROM b", [[3], [1], [2], [None], [4]])
    ab.expect("SELECT x, s FROM a UNION SELECT y, t FROM b",
              [[3, "c"], [1, "a"], [2, "b"], [None, None], [4, "d"]])


def test_intersect_and_except(ab):
    ab.expect("SELECT x FROM a INTERSECT SELECT y FROM b", [[2], [None]])
    ab.expect("SELECT x FROM a EXCEPT SELECT y FROM b", [[3], [1]])
    ab.expect("SELECT y FROM b EXCEPT SELECT x FROM a", [[4]])
    ab.expect("SELECT y FROM b INTERSECT SELECT x FROM a", [[2], [None]])


def test_duplicates_follow_distinct_rules(db):
    db.expect("SELECT 1 UNION SELECT 1.0", [[1]])
    db.expect("SELECT 1.0 UNION SELECT 1", [[1.0]])
    db.expect("SELECT 1 UNION SELECT TRUE UNION SELECT '1'", [[1], [True], ["1"]])
    db.expect("SELECT 1 INTERSECT SELECT 1.0", [[1]])
    db.expect("SELECT NULL EXCEPT SELECT NULL", [])


def test_precedence_and_associativity(db):
    # INTERSECT binds tighter: 1 UNION (2 INTERSECT 3) = {1}
    db.expect("SELECT 1 UNION SELECT 2 INTERSECT SELECT 3", [[1]])
    # Left associative: (1 UNION 2) EXCEPT 1 = {2}
    db.expect("SELECT 1 UNION SELECT 2 EXCEPT SELECT 1", [[2]])
    # (1 EXCEPT 1) UNION 1 = {1}
    db.expect("SELECT 1 EXCEPT SELECT 1 UNION SELECT 1", [[1]])
    db.expect("SELECT 1 UNION ALL SELECT 1 UNION ALL SELECT 2", [[1], [1], [2]])
    # (1 UNION ALL 1) UNION 2 removes the duplicate
    db.expect("SELECT 1 UNION ALL SELECT 1 UNION SELECT 2", [[1], [2]])
    db.expect("SELECT 1 UNION SELECT 1 UNION ALL SELECT 1", [[1], [1]])
    q = parse("SELECT 1 UNION SELECT 2 INTERSECT SELECT 3")
    assert isinstance(q, n.Compound) and q.op == "UNION" and q.right.op == "INTERSECT"


def test_column_names_and_untyped_operands(ab):
    res = ab.run("SELECT x AS first, s FROM a WHERE x = 1 UNION SELECT t, y FROM b WHERE y = 4")
    assert res == {"columns": ["first", "s"], "rows": [[1, "a"], ["d", 4]]}


def test_order_by_and_limit_apply_to_the_whole_result(ab):
    ab.expect("SELECT x FROM a UNION SELECT y FROM b ORDER BY 1 DESC",
              [[None], [4], [3], [2], [1]])
    ab.expect("SELECT x FROM a UNION SELECT y FROM b ORDER BY 1 DESC NULLS LAST",
              [[4], [3], [2], [1], [None]])
    ab.expect("SELECT x AS v FROM a UNION ALL SELECT y FROM b ORDER BY v LIMIT 3 OFFSET 1",
              [[2], [2], [2]])
    ab.expect("SELECT x, s FROM a UNION SELECT y, t FROM b ORDER BY s DESC, x LIMIT 2",
              [[None, None], [4, "d"]])
    ab.expect("SELECT 2 AS k UNION SELECT 1 ORDER BY k", [[1], [2]])


def test_order_by_errors(ab):
    for sql in ("SELECT x FROM a UNION SELECT y FROM b ORDER BY y",
                "SELECT x FROM a UNION SELECT y FROM b ORDER BY x + 1",
                "SELECT x FROM a UNION SELECT y FROM b ORDER BY a.x",
                "SELECT x FROM a UNION SELECT y FROM b ORDER BY 2",
                "SELECT x FROM a UNION SELECT y FROM b ORDER BY (1)"):
        assert ab.error(sql) == "SyntaxError", sql
    assert ab.error("SELECT x, x FROM a UNION SELECT y, y FROM b ORDER BY x") == "NameError"


def test_order_by_of_mixed_types_is_a_type_error(db):
    assert db.error("SELECT 1 UNION SELECT 'a' ORDER BY 1") == "TypeError"


@pytest.mark.parametrize("sql", [
    "SELECT 1 UNION SELECT 1, 2",
    "SELECT 1 INTERSECT ALL SELECT 1",
    "SELECT 1 EXCEPT ALL SELECT 1",
    "SELECT x FROM a ORDER BY x UNION SELECT y FROM b",
    "SELECT x FROM a LIMIT 1 UNION SELECT y FROM b",
    "(SELECT 1) UNION (SELECT 2)",
    "SELECT 1 UNION (SELECT 2)",
    "SELECT 1 UNION",
    "SELECT 1 UNION DISTINCT SELECT 2",
    "SELECT * FROM a UNION SELECT * FROM b UNION SELECT 1",
])
def test_syntax_errors(ab, sql):
    assert ab.error(sql) == "SyntaxError"


def test_errors_in_either_operand(ab):
    assert ab.error("SELECT x FROM a UNION SELECT nope FROM b") == "NameError"
    assert ab.error("SELECT x FROM a UNION SELECT 1 / 0") == "RuntimeError"


def test_set_operations_as_subqueries(ab):
    ab.expect("SELECT (SELECT 1 UNION SELECT 1)", [[1]])
    assert ab.error("SELECT (SELECT 1 UNION SELECT 2)") == "RuntimeError"
    ab.expect("SELECT x FROM a WHERE x IN (SELECT y FROM b EXCEPT SELECT 4)", [[2]])
    ab.expect("SELECT EXISTS (SELECT x FROM a INTERSECT SELECT y FROM b WHERE y = 4)", [[False]])
    ab.expect("SELECT COUNT(*) FROM (SELECT x FROM a UNION SELECT y FROM b) AS u", [[5]])
    ab.expect("SELECT x FROM a WHERE x IN (SELECT y FROM b WHERE y = a.x UNION SELECT 3)",
              [[3], [3], [2]])
