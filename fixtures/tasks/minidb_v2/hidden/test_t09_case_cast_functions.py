"""Section 9 (stage 1): CASE, CAST, SUBSTR, ROUND, NULLIF, REPLACE, TRIM, new reserved words."""
from _support import COMPANY, assert_error, assert_rows, run, run_ok, stage


@stage(1)
def test_searched_case():
    res = run_ok(COMPANY + """
        SELECT name, CASE WHEN salary >= 250 THEN 'high' WHEN salary >= 150 THEN 'mid' ELSE 'low' END AS band
          FROM emp ORDER BY id;
        SELECT CASE WHEN salary > 1000 THEN 'x' END FROM emp WHERE id = 1;
    """)
    assert_rows(res[-2], [["ada", "high"], ["bo", "mid"], ["cy", "mid"], ["di", "mid"], ["ed", "low"],
                          ["flo", "low"], ["gus", "high"]], columns=["name", "band"])
    assert_rows(res[-1], [[None]], columns=["case"])


@stage(1)
def test_simple_case():
    res = run_ok(COMPANY + """
        SELECT CASE dept_id WHEN 1 THEN 'eng' WHEN 2 THEN 'ops' ELSE 'other' END FROM emp;
        SELECT CASE NULL WHEN NULL THEN 'match' ELSE 'no' END;
        SELECT CASE 2.0 WHEN 1 THEN 'one' WHEN 2 THEN 'two' END;
    """)
    assert_rows(res[-3], [["eng"], ["eng"], ["ops"], ["ops"], ["other"], ["other"], ["eng"]],
                columns=["case"])
    assert_rows(res[-2], [["no"]])
    assert_rows(res[-1], [["two"]])


@stage(1)
def test_case_evaluates_only_what_it_needs():
    res = run(COMPANY + """
        SELECT CASE WHEN TRUE THEN 1 ELSE 1 / 0 END;
        SELECT CASE WHEN FALSE THEN 1 / 0 ELSE 2 END;
        SELECT CASE 1 WHEN 1 THEN 'a' WHEN 'x' THEN 'b' END;
        SELECT CASE 1 WHEN 'x' THEN 'a' END;
        SELECT CASE WHEN 1 THEN 'a' END;
        SELECT CASE WHEN NULL THEN 1 ELSE 2 END;
        SELECT CASE WHEN id = 1 THEN 1 WHEN id = 2 THEN 'two' ELSE NULL END AS v FROM emp WHERE id <= 3;
        SELECT CASE WHEN id > 1 THEN 1 / (id - 2) END FROM emp WHERE id <= 2;
    """)
    assert_rows(res[-8], [[1]])
    assert_rows(res[-7], [[2]])
    assert_rows(res[-6], [["a"]])
    assert_error(res[-5], "TypeError")
    assert_error(res[-4], "TypeError")
    assert_rows(res[-3], [[2]])
    assert_rows(res[-2], [[1], ["two"], [None]])
    assert_error(res[-1], "RuntimeError")


@stage(1)
def test_case_with_aggregates_and_in_order_by():
    res = run_ok(COMPANY + """
        SELECT dept_id, CASE WHEN COUNT(*) > 1 THEN 'team' ELSE 'solo' END AS kind FROM emp GROUP BY dept_id;
        SELECT SUM(CASE WHEN active THEN 1 ELSE 0 END) AS n_active FROM emp;
        SELECT name FROM emp ORDER BY CASE WHEN dept_id IS NULL THEN 0 ELSE 1 END, name;
    """)
    assert_rows(res[-3], [[1, "team"], [2, "team"], [3, "solo"], [None, "solo"]])
    assert_rows(res[-2], [[6]])
    assert_rows(res[-1], [["flo"], ["ada"], ["bo"], ["cy"], ["di"], ["ed"], ["gus"]])


@stage(1)
def test_cast_to_text():
    r = run("SELECT CAST(12 AS TEXT), CAST(-3 AS TEXT), CAST(2.5 AS TEXT), CAST(3.0 AS TEXT), "
            "CAST(0.1 AS TEXT), CAST(TRUE AS TEXT), CAST(FALSE AS TEXT), CAST(NULL AS TEXT), "
            "CAST('x' AS TEXT), CAST(-0.25 AS TEXT);")[0]
    assert_rows(r, [["12", "-3", "2.5", "3.0", "0.1", "TRUE", "FALSE", None, "x", "-0.25"]])
    assert r.columns == ["cast"] * 10


@stage(1)
def test_cast_between_numbers_text_and_booleans():
    r = run("SELECT CAST(' 42 ' AS INTEGER), CAST('-7' AS INT), CAST('+5' AS INTEGER), "
            "CAST(3.9 AS INTEGER), CAST(-3.9 AS INTEGER), CAST(TRUE AS INTEGER), CAST(7 AS REAL), "
            "CAST(' 2.50 ' AS REAL), CAST('-1' AS REAL), CAST(0 AS BOOLEAN), CAST(-2 AS BOOL), "
            "CAST(' True ' AS BOOLEAN), CAST('FALSE' AS BOOLEAN), CAST(5 AS INTEGER);")[0]
    assert_rows(r, [[42, -7, 5, 3, -3, 1, 7.0, 2.5, -1.0, False, True, True, False, 5]])


@stage(1)
def test_cast_errors():
    cases = [
        ("CAST('4.5' AS INTEGER)", "RuntimeError"),
        ("CAST('abc' AS INTEGER)", "RuntimeError"),
        ("CAST('' AS INTEGER)", "RuntimeError"),
        ("CAST('9223372036854775808' AS INTEGER)", "RuntimeError"),
        ("CAST(10000000000000000000.0 AS INTEGER)", "RuntimeError"),
        ("CAST('1e5' AS REAL)", "RuntimeError"),
        ("CAST('.5' AS REAL)", "RuntimeError"),
        ("CAST('yes' AS BOOLEAN)", "RuntimeError"),
        ("CAST(1.5 AS BOOLEAN)", "TypeError"),
        ("CAST(TRUE AS REAL)", "TypeError"),
        ("CAST(1 AS VARCHAR)", "SyntaxError"),
        ("CAST(1)", "SyntaxError"),
    ]
    res = run("".join(f"SELECT {e};\n" for e, _ in cases))
    for (e, t), r in zip(cases, res):
        assert_error(r, t)


@stage(1)
def test_substr():
    res = run("""
        SELECT SUBSTR('hello', 2, 3), SUBSTR('hello', 0, 2), SUBSTR('hello', 9), SUBSTR('hello', 2),
               SUBSTR('hello', -1, 3), SUBSTR('hello', 1, 0), SUBSTR(NULL, 1), SUBSTR('abc', NULL),
               SUBSTR('héllo', 2, 1);
        SELECT SUBSTR('hello', 2, -1);
        SELECT SUBSTR(5, 1);
        SELECT SUBSTR('x', 1.0);
        SELECT SUBSTR('x');
    """)
    assert_rows(res[0], [["ell", "h", "", "ello", "h", "", None, None, "é"]])
    assert_error(res[1], "RuntimeError")
    assert_error(res[2], "TypeError")
    assert_error(res[3], "TypeError")
    assert_error(res[4], "SyntaxError")


@stage(1)
def test_round():
    res = run("""
        SELECT ROUND(2.675, 2), ROUND(-0.5), ROUND(2.5), ROUND(1.2345, 3), ROUND(7), ROUND(7, 2),
               ROUND(0.125, 2), ROUND(2.4), TYPEOF(ROUND(2.4)), TYPEOF(ROUND(7)), ROUND(NULL, 1);
        SELECT ROUND(1.5, -1);
        SELECT ROUND('x');
        SELECT ROUND(2.5, 1.0);
    """)
    assert_rows(res[0], [[2.68, -1.0, 3.0, 1.235, 7, 7, 0.13, 2.0, "REAL", "INTEGER", None]])
    assert_error(res[1], "RuntimeError")
    assert_error(res[2], "TypeError")
    assert_error(res[3], "TypeError")


@stage(1)
def test_nullif_replace_trim():
    res = run("""
        SELECT NULLIF(1, 1), NULLIF(1, 2), NULLIF('a', NULL), NULLIF(NULL, 1), NULLIF(2, 2.0);
        SELECT REPLACE('banana', 'an', 'AN'), REPLACE('aaa', 'aa', 'b'), REPLACE('abc', '', 'x'),
               REPLACE('abc', 'b', ''), TRIM('  a b  '), TRIM(''), REPLACE(NULL, 'a', 'b');
        SELECT NULLIF(1, 'a');
        SELECT TRIM(5);
        SELECT REPLACE('a', 'b');
    """)
    assert_rows(res[0], [[None, 1, "a", None, None]])
    assert_rows(res[1], [["bANANa", "ba", "abc", "ac", "a b", "", None]])
    assert_error(res[2], "TypeError")
    assert_error(res[3], "TypeError")
    assert_error(res[4], "SyntaxError")


@stage(1)
def test_new_reserved_words():
    res = run("""
        CREATE TABLE t1 (end INTEGER);
        CREATE TABLE all (a INTEGER);
        SELECT 1 AS cast;
        CREATE TABLE union (a INTEGER);
        CREATE TABLE t2 (if INTEGER, recursive TEXT);
        INSERT INTO t2 VALUES (1, 'x');
        SELECT if, recursive FROM t2;
    """)
    for r in res[:4]:
        assert_error(r, "SyntaxError")
    assert_rows(res[-1], [[1, "x"]])
