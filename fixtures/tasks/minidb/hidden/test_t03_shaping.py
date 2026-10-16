"""Tier 3: ORDER BY, LIMIT/OFFSET, DISTINCT, scalar functions."""
from _support import PEOPLE, assert_error, assert_rows, query, run, run_ok


def test_order_by_multiple_keys_with_nulls_last_in_desc():
    r = query(PEOPLE, "SELECT name, age FROM people ORDER BY age DESC, name;")
    assert_rows(r, [["Dee", 45], ["Ann", 34], ["Fay", 31], ["Eve", 27], ["bob", 27], ["Cid", None]])


def test_order_by_nulls_first_ascending_and_stable_ties():
    r = query(PEOPLE, "SELECT id FROM people ORDER BY city;")
    assert_rows(r, [[4], [5], [1], [3], [2], [6]])
    r = query(PEOPLE, "SELECT id, city FROM people ORDER BY city DESC;")
    assert_rows(r, [[2, "Rome"], [6, "Rome"], [1, "Oslo"], [3, "Oslo"], [5, "Lima"], [4, None]])


def test_order_by_alias_position_and_hidden_expression():
    res = run_ok(PEOPLE + """
        SELECT name AS n, score * 2 AS s2 FROM people ORDER BY s2 DESC, 1;
        SELECT name FROM people ORDER BY age, id DESC;
        SELECT name FROM people ORDER BY LOWER(name) DESC;
        SELECT id AS name, name AS id FROM people ORDER BY id LIMIT 2;
    """)
    assert_rows(res[-4], [["Cid", 18.0], ["Eve", 16.0], ["Ann", 15.0], ["Fay", 15.0], ["Dee", 12.5],
                          ["bob", None]], columns=["n", "s2"])
    assert_rows(res[-3], [["Cid"], ["Eve"], ["bob"], ["Fay"], ["Ann"], ["Dee"]])
    assert_rows(res[-2], [["Fay"], ["Eve"], ["Dee"], ["Cid"], ["bob"], ["Ann"]])
    # a bare name in ORDER BY refers to the output column first
    assert_rows(res[-1], [[1, "Ann"], [3, "Cid"]], columns=["name", "id"])


def test_limit_and_offset():
    res = run_ok(PEOPLE + """
        SELECT id FROM people ORDER BY id DESC LIMIT 2 OFFSET 1;
        SELECT id FROM people LIMIT 0;
        SELECT id FROM people ORDER BY id DESC LIMIT 10 OFFSET 5;
        SELECT id FROM people LIMIT 3;
        SELECT id FROM people LIMIT 2 OFFSET 10;
    """)
    assert_rows(res[-5], [[5], [4]])
    assert_rows(res[-4], [])
    assert_rows(res[-3], [[1]])
    assert_rows(res[-2], [[1], [2], [3]])
    assert_rows(res[-1], [])


def test_distinct_keeps_first_occurrence_then_sorts():
    res = run_ok(PEOPLE + """
        SELECT DISTINCT city FROM people;
        SELECT DISTINCT age FROM people ORDER BY age DESC LIMIT 3;
        SELECT DISTINCT city, age > 30 AS old FROM people ORDER BY 1, 2;
        SELECT DISTINCT score FROM people ORDER BY score;
    """)
    assert_rows(res[-4], [["Oslo"], ["Rome"], [None], ["Lima"]], columns=["city"])
    assert_rows(res[-3], [[45], [34], [31]])
    assert_rows(res[-2], [[None, True], ["Lima", False], ["Oslo", None], ["Oslo", True],
                          ["Rome", False], ["Rome", True]], columns=["city", "old"])
    assert_rows(res[-1], [[None], [6.25], [7.5], [8.0], [9.0]])


def test_scalar_functions():
    res = run_ok(PEOPLE + """
        SELECT LOWER(name), UPPER(city), LENGTH(name || city) AS len, ABS(-3) AS a, ABS(-2.5) AS b,
               COALESCE(city, 'none') AS c FROM people WHERE id = 4;
        SELECT lower('MiXeD') AS l, upper('ab c') AS u, LENGTH('héllo') AS n, LENGTH('') AS z,
               COALESCE(NULL, NULL, 3) AS c1, COALESCE(NULL) AS c2, ABS(NULL) AS a;
        SELECT name, LENGTH(name) AS n FROM people WHERE UPPER(city) = 'ROME' ORDER BY n, name DESC;
    """)
    assert_rows(res[-3], [["dee", None, None, 3, 2.5, "none"]],
                columns=["lower", "upper", "len", "a", "b", "c"])
    assert_rows(res[-2], [["mixed", "AB C", 5, 0, 3, None, None]])
    assert_rows(res[-1], [["bob", 3], ["Fay", 3]])


def test_function_errors():
    res = run("""
        SELECT FOO(1);
        SELECT LOWER('a', 'b');
        SELECT COALESCE();
        SELECT LENGTH(5);
        SELECT ABS('x');
        SELECT UPPER(TRUE);
    """)
    for r, w in zip(res, ["NameError", "SyntaxError", "SyntaxError", "TypeError", "TypeError",
                          "TypeError"]):
        assert_error(r, w)


def test_order_by_errors():
    res = run(PEOPLE + """
        SELECT id FROM people ORDER BY 3;
        SELECT id FROM people ORDER BY 0;
        SELECT id AS x, age AS x FROM people ORDER BY x;
        SELECT DISTINCT city FROM people ORDER BY age;
        SELECT * FROM people ORDER BY nope;
        SELECT id FROM people LIMIT -1;
    """)
    for r, w in zip(res[-6:], ["SyntaxError", "SyntaxError", "NameError", "SyntaxError",
                               "NameError", "SyntaxError"]):
        assert_error(r, w)


def test_order_by_mixed_integer_and_real_keys():
    r = query(PEOPLE, "SELECT id, COALESCE(score, age) AS k FROM people ORDER BY k DESC, id;")
    assert_rows(r, [[2, 27], [3, 9.0], [5, 8.0], [1, 7.5], [6, 7.5], [4, 6.25]])
