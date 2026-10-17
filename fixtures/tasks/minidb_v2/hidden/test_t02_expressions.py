"""Section 2 (stage 0): operators, precedence, NULL logic, evaluation order, WHERE."""
from _support import PEOPLE, assert_error, assert_rows, query, run, run_ok, stage


def one(sql: str):
    return run(sql)[0]


@stage(0)
def test_arithmetic_precedence_and_associativity():
    r = one("SELECT 2 + 3 * 4, (2 + 3) * 4, 10 - 3 - 2, 7 % 3, -7 % 2, 7 % -2, 2 * -3, - - 4, +5")
    assert_rows(r, [[14, 20, 5, 1, -1, 1, -6, 4, 5]])


@stage(0, retired=3)
def test_integer_division_truncates_toward_zero():
    r = one("SELECT 7 / 2, -7 / 2, 7 / -2, 6 / 3, 1 / 3, TYPEOF(4 / 2)")
    assert_rows(r, [[3, -3, -3, 2, 0, "INTEGER"]])


@stage(0)
def test_mixed_numeric_types_give_real():
    r = one("SELECT 1 + 2.5, 3 * 1.0, 7.5 / 2.5, 1.5 - 1, 7.0 / 2, -2.5 * 2, -(1.5)")
    assert_rows(r, [[3.5, 3.0, 3.0, 0.5, 3.5, -5.0, -1.5]])


@stage(0)
def test_division_by_zero_and_overflow_are_runtime_errors():
    big = "1" + "0" * 300 + ".0"
    res = run(f"""
        SELECT 1 / 0;
        SELECT 1 % 0;
        SELECT 1.0 / 0.0;
        SELECT 5 / 0.0;
        SELECT 9223372036854775807 + 1;
        SELECT -9223372036854775807 - 2;
        SELECT 3037000500 * 3037000500;
        SELECT -(-9223372036854775807 - 1);
        SELECT {big} * {big};
        SELECT 5 % 2.0;
        SELECT 9223372036854775807 - 1 + 1;
    """)
    for r in res[:9]:
        assert_error(r, "RuntimeError")
    assert_error(res[9], "TypeError")
    assert_rows(res[10], [[9223372036854775807]])


@stage(0)
def test_null_propagation_and_three_valued_logic():
    res = run("""
        SELECT NULL + 1, NULL || 'a', NULL = NULL, NULL + 'a', -NULL, NULL < 1;
        SELECT TRUE AND NULL, FALSE AND NULL, TRUE OR NULL, FALSE OR NULL, NOT NULL, NULL AND NULL;
        SELECT NULL IS NULL, 1 IS NOT NULL, NULL IS NOT NULL, (1 = NULL) IS NULL;
    """)
    assert_rows(res[0], [[None, None, None, None, None, None]])
    assert_rows(res[1], [[None, False, True, None, None, None]])
    assert_rows(res[2], [[True, True, False, True]])


@stage(0)
def test_short_circuit_and_evaluation_order():
    res = run("""
        SELECT FALSE AND 1 / 0 = 1;
        SELECT TRUE OR 'a';
        SELECT COALESCE(1, 1 / 0), COALESCE(NULL, 2, 'x' || 1);
        SELECT NULL AND 1 / 0 = 1;
        SELECT TRUE AND 'x';
        SELECT NULL + 1 / 0;
        SELECT 1 / 0 = 1 AND FALSE;
        SELECT (1 = 2) OR (2 = 2) OR 'never';
    """)
    assert_rows(res[0], [[False]])
    assert_rows(res[1], [[True]])
    assert_rows(res[2], [[1, 2]])
    assert_error(res[3], "RuntimeError")
    assert_error(res[4], "TypeError")
    assert_error(res[5], "RuntimeError")
    assert_error(res[6], "RuntimeError")
    assert_rows(res[7], [[True]])


@stage(0)
def test_comparisons():
    r = one("SELECT 'B' < 'a', 1 = 1.0, FALSE < TRUE, 'abc' < 'abd', 2 <> 2.5, 3 != 3, "
            "'a' >= 'a', 2.5 > 2, 'é' > 'z'")
    assert_rows(r, [[True, True, True, True, True, False, True, True, True]])


@stage(0)
def test_between_in_and_like():
    res = run("""
        SELECT 1 IN (2, NULL), 2 IN (2, NULL), 1 NOT IN (2, 3), 1 NOT IN (2, NULL), 1 IN (1.0);
        SELECT 5 BETWEEN 1 AND 10, 5 NOT BETWEEN 6 AND 10, NULL BETWEEN 1 AND 2, 3 BETWEEN 5 AND 1;
        SELECT 'abc' LIKE 'a%', 'abc' LIKE '_b_', 'abc' LIKE 'A%', 'a%c' LIKE 'a%', 'ab' LIKE 'a';
        SELECT '' LIKE '%', 'abc' NOT LIKE '%c', 'a.c' LIKE 'a_c', 'line1
line2' LIKE 'line%2', NULL LIKE '%';
    """)
    assert_rows(res[0], [[None, True, True, None, True]])
    assert_rows(res[1], [[True, True, None, False]])
    assert_rows(res[2], [[True, True, False, True, False]])
    assert_rows(res[3], [[True, False, True, True, None]])


@stage(0)
def test_operand_type_errors():
    exprs = ["1 + 'a'", "'a' || 1", "1 = 'a'", "TRUE + 1", "NOT 5", "1 = TRUE", "-'a'", "+'a'",
             "1 LIKE 'a'", "'a' BETWEEN 1 AND 2", "1 AND TRUE", "'a' < TRUE", "1 IN ('a')",
             "TRUE || 'a'", "'x' * 2"]
    res = run("".join(f"SELECT {e};\n" for e in exprs))
    for e, r in zip(exprs, res):
        assert_error(r, "TypeError")


@stage(0)
def test_where_filters_with_three_valued_logic():
    res = run_ok(PEOPLE + """
        SELECT id FROM people WHERE age > 30;
        SELECT id FROM people WHERE NOT (age > 30);
        SELECT id FROM people WHERE city = 'Oslo' OR age < 30;
        SELECT name FROM people WHERE score IS NULL OR city IS NULL;
        SELECT id FROM people WHERE age BETWEEN 27 AND 31 AND name LIKE '%e%';
    """)
    assert_rows(res[-5], [[1], [4], [6]])
    assert_rows(res[-4], [[2], [5]])
    assert_rows(res[-3], [[1], [2], [3], [5]])
    assert_rows(res[-2], [["bob"], ["Dee"]])
    assert_rows(res[-1], [[5]])


@stage(0)
def test_where_errors_and_lazy_evaluation():
    res = run(PEOPLE + """
        SELECT id FROM people WHERE age;
        SELECT id FROM people WHERE nope = 1;
        CREATE TABLE e (a INTEGER);
        SELECT a FROM e WHERE nope = 1;
        SELECT a FROM e WHERE 1 / 0 = 1;
        SELECT id FROM people WHERE age > 40 AND 1 / (age - 45) = 0;
        SELECT id FROM people WHERE id = 1 OR 10 / (id - 2) > 0;
        SELECT id FROM people WHERE name = 'x' AND age = 'old';
    """)
    r = res[-8:]
    assert_error(r[0], "TypeError")
    assert_error(r[1], "NameError")
    assert_error(r[3], "NameError")
    assert_rows(r[4], [])
    assert_error(r[5], "RuntimeError")
    assert_error(r[6], "RuntimeError")
    assert_rows(r[7], [])


@stage(0)
def test_select_without_from():
    res = run("""
        SELECT 1, 'a' AS x, 2.5 * 2, NULL;
        SELECT DISTINCT 1 AS one;
        SELECT 1 WHERE TRUE;
        SELECT 1 ORDER BY 1;
        SELECT 1 LIMIT 1;
        SELECT *;
    """)
    assert_rows(res[0], [[1, "a", 5.0, None]], columns=["?column?", "x", "?column?", "?column?"])
    assert_rows(res[1], [[1]], columns=["one"])
    for r in res[2:]:
        assert_error(r, "SyntaxError")


@stage(0)
def test_output_column_names():
    r = query(PEOPLE, "SELECT id, people.name, (age), age + 1, lower(name), UPPER(city), "
                      "name AS n, -id, (people.score) AS s FROM people WHERE id = 1;")
    assert_rows(r, [[1, "Ann", 34, 35, "ann", "OSLO", "Ann", -1, 7.5]],
                columns=["id", "name", "age", "?column?", "lower", "upper", "n", "?column?", "s"])


@stage(0)
def test_select_star_combined_with_other_items():
    r = query(PEOPLE, "SELECT id * 10 AS x, *, name || '!' AS y FROM people WHERE id <= 2;")
    assert_rows(r, [[10, 1, "Ann", 34, "Oslo", 7.5, "Ann!"], [20, 2, "bob", 27, "Rome", None, "bob!"]],
                columns=["x", "id", "name", "age", "city", "score", "y"])


@stage(0)
def test_alias_requires_as_and_comparisons_do_not_chain():
    res = run(PEOPLE + """
        SELECT id ident FROM people;
        SELECT 1 < 2 < 3;
        SELECT 1 = 1 = TRUE;
        SELECT (1 < 2) = TRUE;
    """)
    assert_error(res[-4], "SyntaxError")
    assert_error(res[-3], "SyntaxError")
    assert_error(res[-2], "SyntaxError")
    assert_rows(res[-1], [[True]])
