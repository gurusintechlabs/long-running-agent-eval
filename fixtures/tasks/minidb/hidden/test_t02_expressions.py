"""Tier 2: expressions, operators, NULL logic, WHERE, select lists."""
from _support import PEOPLE, assert_error, assert_rows, query, run, run_ok


def test_arithmetic_precedence_and_integer_rules():
    r = query("", "SELECT 1 + 2 * 3 AS a, (1 + 2) * 3 AS b, 10 - 3 - 2 AS c, 20 / 2 / 5 AS d, "
                  "-7 / 2 AS e, -7 % 2 AS f, 7 % -2 AS g, 7 / 2.0 AS h, 2 * 1.5 AS i, - -4 AS j;")
    assert_rows(r, [[7, 9, 5, 2, -3, -1, 1, 3.5, 3.0, 4]],
                columns=["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"])


def test_comparisons_produce_booleans():
    r = query("", "SELECT 1 < 2 AS a, 1 = 1.0 AS b, 'B' < 'a' AS c, FALSE < TRUE AS d, "
                  "'abc' = 'abc' AS e, 2 <> 2 AS f, 3 != 4 AS g, 2.5 >= 3 AS h, 'b' <= 'b' AS i;")
    assert_rows(r, [[True, True, True, True, True, False, True, False, True]])


def test_three_valued_logic_and_null_propagation():
    r = query("", "SELECT NULL = NULL AS a, NULL IS NULL AS b, FALSE AND NULL AS c, "
                  "TRUE AND NULL AS d, TRUE OR NULL AS e, FALSE OR NULL AS f, NOT NULL AS g, "
                  "1 + NULL AS h, 1 IN (2, NULL) AS i, 2 IN (2, NULL) AS j, 1 NOT IN (2, 3) AS k, "
                  "NULL IS NOT NULL AS l, NOT (1 > 2) AS m, NULL || 'x' AS n;")
    assert_rows(r, [[None, True, False, None, True, None, None, None, None, True, True, False,
                     True, None]])


def test_where_filters_only_true_rows():
    res = run_ok(PEOPLE + """
        SELECT id FROM people WHERE age > 30;
        SELECT id FROM people WHERE NOT (age > 30);
        SELECT id FROM people WHERE age = NULL;
        SELECT id FROM people WHERE city IS NULL;
        SELECT id FROM people WHERE age BETWEEN 27 AND 31;
        SELECT id FROM people WHERE city IN ('Rome', 'Lima');
        SELECT id FROM people WHERE city NOT IN ('Rome');
        SELECT id FROM people WHERE age < 30 OR city = 'Oslo';
        SELECT id FROM people WHERE score >= 7.5 AND age IS NOT NULL AND age NOT BETWEEN 32 AND 40;
    """)
    q = res[-9:]
    assert_rows(q[0], [[1], [4], [6]])
    assert_rows(q[1], [[2], [5]])
    assert_rows(q[2], [])
    assert_rows(q[3], [[4]])
    assert_rows(q[4], [[2], [5], [6]])
    assert_rows(q[5], [[2], [5], [6]])
    assert_rows(q[6], [[1], [3], [5]])
    assert_rows(q[7], [[1], [2], [3], [5]])
    assert_rows(q[8], [[5], [6]])


def test_like_patterns():
    res = run_ok(PEOPLE + """
        SELECT name FROM people WHERE name LIKE '%e';
        SELECT name FROM people WHERE name LIKE 'b%';
        SELECT name FROM people WHERE name NOT LIKE '%a%';
        SELECT 'abc' LIKE 'a_c' AS a, 'abc' LIKE 'A%' AS b, 'a' LIKE 'a%' AS c, 'ab' LIKE '_' AS d,
               '' LIKE '%' AS e, 'a.c' LIKE 'a.c' AS f, 'abc' LIKE 'b' AS g;
    """)
    assert_rows(res[-4], [["Dee"], ["Eve"]])
    assert_rows(res[-3], [["bob"]])
    assert_rows(res[-2], [["Ann"], ["bob"], ["Cid"], ["Dee"], ["Eve"]])
    assert_rows(res[-1], [[True, False, True, False, True, True, False]])


def test_projection_expressions_and_column_names():
    res = run_ok(PEOPLE + """
        SELECT name || '@' || city AS tag, age * 2 AS dbl, score + 1 AS s FROM people WHERE id IN (1, 4);
        SELECT id, people.name, age + 1, age AS a FROM people WHERE id = 1;
        SELECT *, age + 1 AS next FROM people WHERE id = 2;
    """)
    assert_rows(res[-3], [["Ann@Oslo", 68, 8.5], [None, 90, 7.25]], columns=["tag", "dbl", "s"])
    assert_rows(res[-2], [[1, "Ann", 35, 34]], columns=["id", "name", "?column?", "a"])
    assert_rows(res[-1], [[2, "bob", 27, "Rome", None, 28]],
                columns=["id", "name", "age", "city", "score", "next"])


def test_insert_values_may_be_expressions():
    r = query("CREATE TABLE t (a INTEGER, b TEXT, c BOOLEAN); "
              "INSERT INTO t VALUES (1 + 2 * 3, 'a' || 'b', 1 < 2), (-(4 - 10), NULL || 'x', NULL);",
              "SELECT * FROM t;")
    assert_rows(r, [[7, "ab", True], [6, None, None]])


def test_type_and_runtime_errors():
    res = run(PEOPLE + """
        SELECT 1 + 'a';
        SELECT 'a' || 1;
        SELECT 1 = 'a';
        SELECT NOT 5;
        SELECT 5 % 2.0;
        SELECT TRUE + 1;
        SELECT 1 = TRUE;
        SELECT 'a' LIKE 1;
        SELECT * FROM people WHERE age;
        SELECT 1 / 0;
        SELECT 1.5 / 0;
        SELECT 5 % 0;
        SELECT 9223372036854775807 + 1;
        SELECT -9223372036854775807 - 2;
        SELECT 1 < 2 < 3;
        SELECT name FROM people WHERE 1 +;
        SELECT nope FROM people;
        SELECT NULL + 'a' AS x;
    """)
    want = ["TypeError"] * 9 + ["RuntimeError"] * 5 + ["SyntaxError", "SyntaxError", "NameError"]
    for r, w in zip(res[-18:-1], want):
        assert_error(r, w)
    assert_rows(res[-1], [[None]])


def test_name_errors_are_reported_on_empty_tables():
    res = run("""
        CREATE TABLE e (a INTEGER);
        SELECT * FROM e WHERE b = 1;
        SELECT a, c FROM e;
        SELECT * FROM e WHERE a = 1;
    """)
    assert_error(res[1], "NameError")
    assert_error(res[2], "NameError")
    assert_rows(res[3], [])
