"""Section 3 (stage 0): ORDER BY, LIMIT/OFFSET, DISTINCT, scalar functions."""
from _support import PEOPLE, assert_error, assert_rows, run, run_ok, stage

# No NULLs anywhere, so the ordering below does not depend on NULL placement (changed in CR-1).
FRUIT = """
CREATE TABLE s (id INTEGER, name TEXT, grp TEXT, n INTEGER, r REAL);
INSERT INTO s VALUES (1, 'pear', 'b', 3, 2.5), (2, 'apple', 'a', 1, 0.5), (3, 'fig', 'b', 3, 1.0),
                     (4, 'kiwi', 'a', 2, 2.5), (5, 'date', 'c', 1, 3.0), (6, 'Plum', 'b', 2, 0.5);
"""


def col(result, i=0):
    assert result.ok, result
    return [row[i] for row in result.rows]


@stage(0)
def test_order_by_keys_directions_and_stability():
    res = run_ok(FRUIT + """
        SELECT id FROM s ORDER BY grp, n DESC;
        SELECT id FROM s ORDER BY r;
        SELECT name FROM s ORDER BY name;
        SELECT name FROM s ORDER BY n DESC, name ASC;
        SELECT id FROM s ORDER BY r DESC;
    """)
    assert col(res[-5]) == [4, 2, 1, 3, 6, 5]
    assert col(res[-4]) == [2, 6, 3, 1, 4, 5]
    assert col(res[-3]) == ["Plum", "apple", "date", "fig", "kiwi", "pear"]
    assert col(res[-2]) == ["fig", "pear", "Plum", "kiwi", "apple", "date"]
    assert col(res[-1]) == [5, 1, 4, 3, 2, 6]


@stage(0, retired=3)
def test_nulls_sort_first_ascending_and_last_descending():
    res = run_ok(PEOPLE + """
        SELECT id FROM people ORDER BY age;
        SELECT id FROM people ORDER BY age DESC;
        SELECT id FROM people ORDER BY city DESC, id;
        SELECT id, score FROM people ORDER BY score, id DESC;
    """)
    assert col(res[-4]) == [3, 2, 5, 6, 1, 4]
    assert col(res[-3]) == [4, 1, 6, 2, 5, 3]
    assert col(res[-2]) == [2, 6, 1, 3, 5, 4]
    assert col(res[-1]) == [2, 4, 6, 1, 5, 3]


@stage(0)
def test_order_by_position_alias_and_star_names():
    res = run_ok(FRUIT + """
        SELECT name AS fruit, n FROM s ORDER BY 2 DESC, fruit;
        SELECT * FROM s ORDER BY grp DESC, 1;
        SELECT id, name AS grp FROM s ORDER BY grp;
    """)
    assert col(res[-3]) == ["fig", "pear", "Plum", "kiwi", "apple", "date"]
    assert col(res[-2]) == [5, 1, 3, 6, 2, 4]
    assert col(res[-1]) == [6, 2, 5, 3, 4, 1]


@stage(0)
def test_order_by_positions_and_constants():
    res = run(FRUIT + """
        SELECT id FROM s ORDER BY 0;
        SELECT id, name FROM s ORDER BY 3;
        SELECT id FROM s ORDER BY -1;
        SELECT id FROM s ORDER BY 1 + 0;
        SELECT id FROM s ORDER BY TRUE, 'x';
        SELECT id FROM s ORDER BY 1 DESC;
    """)
    assert_error(res[-6], "SyntaxError")
    assert_error(res[-5], "SyntaxError")
    assert col(res[-4]) == [1, 2, 3, 4, 5, 6]
    assert col(res[-3]) == [1, 2, 3, 4, 5, 6]
    assert col(res[-2]) == [1, 2, 3, 4, 5, 6]
    assert col(res[-1]) == [6, 5, 4, 3, 2, 1]


@stage(0)
def test_order_by_name_resolution():
    res = run(FRUIT + """
        SELECT id AS x, n AS x FROM s ORDER BY x;
        SELECT id FROM s ORDER BY nope;
        SELECT id AS n FROM s ORDER BY n DESC;
        SELECT id AS n FROM s ORDER BY s.n, id;
        SELECT id FROM s ORDER BY n * -1, LENGTH(name);
    """)
    assert_error(res[-5], "NameError")
    assert_error(res[-4], "NameError")
    assert col(res[-3]) == [6, 5, 4, 3, 2, 1]
    assert col(res[-2]) == [2, 5, 4, 6, 1, 3]
    assert col(res[-1]) == [3, 1, 4, 6, 5, 2]


@stage(0)
def test_sorting_incomparable_types_is_a_type_error():
    res = run("""
        CREATE TABLE m (t TEXT, i INTEGER);
        INSERT INTO m VALUES ('a', NULL), (NULL, 1), ('b', NULL);
        SELECT * FROM m ORDER BY COALESCE(t, i);
        SELECT * FROM m ORDER BY t DESC, COALESCE(t, i);
        SELECT * FROM m WHERE t = 'a' ORDER BY COALESCE(t, i);
        SELECT * FROM m WHERE i = 1 OR t = 'b' ORDER BY i;
    """)
    assert_error(res[2], "TypeError")
    assert_error(res[3], "TypeError")
    assert_rows(res[4], [["a", None]])
    assert len(res[5].rows) == 2


@stage(0)
def test_limit_and_offset():
    res = run(FRUIT + """
        SELECT id FROM s ORDER BY id LIMIT 2;
        SELECT id FROM s ORDER BY id LIMIT 2 OFFSET 3;
        SELECT id FROM s LIMIT 0;
        SELECT id FROM s ORDER BY id DESC LIMIT 10 OFFSET 5;
        SELECT id FROM s LIMIT 3 OFFSET 10;
        SELECT id FROM s OFFSET 2;
        SELECT id FROM s LIMIT -1;
        SELECT id FROM s LIMIT 1.5;
        SELECT id FROM s LIMIT 1 + 1;
        SELECT id FROM s LIMIT NULL;
        SELECT id FROM s LIMIT 2 OFFSET 'a';
    """)
    r = res[-11:]
    assert col(r[0]) == [1, 2]
    assert col(r[1]) == [4, 5]
    assert col(r[2]) == []
    assert col(r[3]) == [1]
    assert col(r[4]) == []
    for x in r[5:]:
        assert_error(x, "SyntaxError")


@stage(0)
def test_distinct_semantics():
    res = run_ok(FRUIT + PEOPLE + """
        SELECT DISTINCT grp FROM s;
        SELECT DISTINCT grp, n FROM s;
        SELECT DISTINCT city FROM people;
        CREATE TABLE u (i INTEGER, r REAL);
        INSERT INTO u VALUES (1, NULL), (NULL, 1.0), (2, NULL), (NULL, 2.5), (NULL, 2.0);
        SELECT DISTINCT COALESCE(i, r) AS v FROM u;
        CREATE TABLE bi (f BOOLEAN, i INTEGER);
        INSERT INTO bi VALUES (TRUE, NULL), (NULL, 1), (TRUE, NULL), (NULL, NULL), (NULL, NULL);
        SELECT DISTINCT COALESCE(f, i) AS v FROM bi;
    """)
    assert col(res[-9]) == ["b", "a", "c"]
    assert_rows(res[-8], [["b", 3], ["a", 1], ["a", 2], ["c", 1], ["b", 2]])
    assert col(res[-7]) == ["Oslo", "Rome", None, "Lima"]
    assert_rows(res[-4], [[1], [2], [2.5]], columns=["v"])
    assert_rows(res[-1], [[True], [1], [None]])


@stage(0)
def test_distinct_with_order_by():
    res = run(FRUIT + """
        SELECT DISTINCT grp FROM s ORDER BY grp DESC;
        SELECT DISTINCT grp FROM s ORDER BY 1;
        SELECT DISTINCT grp FROM s ORDER BY n;
        SELECT DISTINCT grp FROM s ORDER BY UPPER(grp);
        SELECT DISTINCT grp, n FROM s ORDER BY n DESC, grp LIMIT 3;
    """)
    assert col(res[-5]) == ["c", "b", "a"]
    assert col(res[-4]) == ["a", "b", "c"]
    assert_error(res[-3], "SyntaxError")
    assert_error(res[-2], "SyntaxError")
    assert_rows(res[-1], [["b", 3], ["a", 2], ["b", 2]])


@stage(0)
def test_scalar_functions():
    res = run("""
        SELECT LOWER('AbC'), UPPER('mixed Case 1'), LENGTH('héllo'), LENGTH(''), ABS(-3), ABS(-2.5),
               ABS(4), COALESCE(NULL, NULL, 'z'), COALESCE(NULL);
        SELECT lower(NULL), LENGTH(NULL), ABS(NULL), Upper(NULL), coalesce(NULL, 7);
    """)
    assert_rows(res[0], [["abc", "MIXED CASE 1", 5, 0, 3, 2.5, 4, "z", None]],
                columns=["lower", "upper", "length", "length", "abs", "abs", "abs", "coalesce",
                         "coalesce"])
    assert_rows(res[1], [[None, None, None, None, 7]])


@stage(0)
def test_scalar_function_errors():
    res = run("""
        SELECT NOSUCH(1);
        SELECT LOWER('a', 'b');
        SELECT LENGTH();
        SELECT COALESCE();
        SELECT TYPEOF(1, 2);
        SELECT LENGTH(5);
        SELECT ABS('x');
        SELECT UPPER(TRUE);
        SELECT ABS(-9223372036854775807 - 1);
        SELECT ABS(-9223372036854775807);
    """)
    assert_error(res[0], "NameError")
    for r in res[1:5]:
        assert_error(r, "SyntaxError")
    for r in res[5:8]:
        assert_error(r, "TypeError")
    assert_error(res[8], "RuntimeError")
    assert_rows(res[9], [[9223372036854775807]])


@stage(0)
def test_typeof():
    res = run_ok("""
        SELECT TYPEOF(1), TYPEOF(1.5), TYPEOF('a'), TYPEOF(TRUE), TYPEOF(NULL), TYPEOF(1 + 1.0),
               TYPEOF(-5), TYPEOF(NULL + 1);
        CREATE TABLE t (r REAL, b BOOLEAN);
        INSERT INTO t VALUES (3, FALSE);
        SELECT TYPEOF(r), r, TYPEOF(b) FROM t;
    """)
    assert_rows(res[0], [["INTEGER", "REAL", "TEXT", "BOOLEAN", "NULL", "REAL", "INTEGER", "NULL"]])
    assert_rows(res[-1], [["REAL", 3.0, "BOOLEAN"]], columns=["typeof", "r", "typeof"])
