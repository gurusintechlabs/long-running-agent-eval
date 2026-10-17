"""Section 12: indexes, implicit indexes, EXPLAIN and the plan rules."""
import random

import pytest

from minidb.access import TableAccess, conjuncts, equi_join, literal_value
from minidb.catalog import Column, Index, Table
from minidb.compiler import Scope
from minidb.engine import Engine
from minidb.parser import parse
from minidb.protocol import DBError


@pytest.fixture
def people(db):
    db.run("CREATE TABLE people (id INT PRIMARY KEY, name TEXT, age INT, email TEXT UNIQUE)")
    db.run("INSERT INTO people VALUES (1, 'ann', 30, 'a@x'), (2, 'bob', 40, NULL), "
           "(3, 'cid', 35, 'c@x'), (4, 'dan', NULL, NULL), (5, 'eve', 30, 'e@x')")
    db.run("CREATE INDEX idx_age ON people (age)")
    return db


def plan(db, sql):
    return [row[0] for row in db.rows("EXPLAIN " + sql)]


# ---------------------------------------------------------------- DDL

def test_create_and_drop_index(people):
    assert people.run("CREATE INDEX idx_name ON people (name)") == {}
    assert people.run("DROP INDEX idx_name") == {}
    assert people.error("DROP INDEX idx_name") == "NameError"
    assert people.run("DROP INDEX IF EXISTS idx_name") == {}
    assert people.error("CREATE INDEX idx_age ON people (name)") == "NameError"
    assert people.run("CREATE INDEX IF NOT EXISTS idx_age ON people (name)") == {}
    assert people.error("CREATE INDEX i ON nope (a)") == "NameError"
    assert people.error("CREATE INDEX i ON people (nope)") == "NameError"
    # Index names have their own namespace.
    assert people.run("CREATE INDEX people ON people (name)") == {}
    assert people.run("CREATE TABLE idx_age (a INT)") == {}
    # Several indexes on one column; the plan reports the one created first.
    people.run("CREATE INDEX idx_age_2 ON people (age)")
    assert plan(people, "SELECT * FROM people WHERE age = 3") == [
        "SEARCH people USING INDEX idx_age (age = ?)"]
    people.run("DROP INDEX idx_age")
    assert plan(people, "SELECT * FROM people WHERE age = 3") == [
        "SEARCH people USING INDEX idx_age_2 (age = ?)"]


@pytest.mark.parametrize("sql", [
    "CREATE INDEX ON people (age)", "CREATE INDEX i people (age)", "CREATE INDEX i ON people",
    "CREATE INDEX i ON people ()", "CREATE INDEX i ON people (age, name)",
    "CREATE UNIQUE TABLE t (a INT)", "DROP INDEX", "CREATE INDEX select ON people (age)",
    "CREATE INDEX IF EXISTS i ON people (age)", "DROP INDEX IF NOT EXISTS i",
])
def test_index_syntax_errors(people, sql):
    assert people.error(sql) == "SyntaxError"


def test_implicit_indexes(people):
    assert plan(people, "SELECT * FROM people WHERE id = 1") == [
        "SEARCH people USING INDEX people_id_key (id = ?)"]
    assert plan(people, "SELECT * FROM people WHERE email = 'a@x'") == [
        "SEARCH people USING INDEX people_email_key (email = ?)"]
    assert people.error("DROP INDEX people_id_key") == "ConstraintError"
    assert people.error("CREATE INDEX people_id_key ON people (age)") == "NameError"
    # The implicit index was created with its table: before any explicit index.
    people.run("CREATE INDEX later_id ON people (id)")
    assert plan(people, "SELECT * FROM people WHERE id = 1") == [
        "SEARCH people USING INDEX people_id_key (id = ?)"]


def test_implicit_index_name_conflict(db):
    db.run("CREATE TABLE other (a INT)", "CREATE INDEX t_id_key ON other (a)")
    assert db.error("CREATE TABLE t (id INT PRIMARY KEY)") == "NameError"
    assert db.error("SELECT * FROM t") == "NameError"  # nothing was created
    db.run("CREATE TABLE t (id INT)")  # no implicit index needed


def test_drop_table_drops_its_indexes(people):
    people.run("DROP TABLE people")
    assert people.error("DROP INDEX idx_age") == "NameError"
    people.run("CREATE TABLE people (id INT PRIMARY KEY, age INT)")
    people.run("CREATE INDEX idx_age ON people (age)")
    people.run("INSERT INTO people VALUES (1, 2)")
    people.expect("SELECT * FROM people WHERE age = 2", [[1, 2]])


def test_unique_index_enforces_uniqueness(people):
    assert people.error("CREATE UNIQUE INDEX u_age ON people (age)") == "ConstraintError"
    assert people.error("DROP INDEX u_age") == "NameError"  # it was not created
    people.run("CREATE UNIQUE INDEX u_name ON people (name)")
    assert people.error("INSERT INTO people VALUES (6, 'ann', 1, NULL)") == "ConstraintError"
    assert people.error("UPDATE people SET name = 'bob' WHERE id = 1") == "ConstraintError"
    people.run("INSERT INTO people VALUES (6, NULL, 1, NULL), (7, NULL, 1, NULL)")
    people.run("UPDATE people SET name = name || '!'")  # final values distinct: fine
    people.run("DROP INDEX u_name")
    people.run("INSERT INTO people VALUES (8, 'ann!', 1, NULL)")
    # A unique index on an already-unique column keeps the constraint after it is dropped.
    people.run("CREATE UNIQUE INDEX u_email ON people (email)")
    people.run("DROP INDEX u_email")
    assert people.error("INSERT INTO people VALUES (9, 'x', 1, 'a@x')") == "ConstraintError"


def test_two_unique_indexes_on_one_column(db):
    db.run("CREATE TABLE t (a INT)", "CREATE UNIQUE INDEX u1 ON t (a)",
           "CREATE UNIQUE INDEX u2 ON t (a)", "DROP INDEX u1")
    db.run("INSERT INTO t VALUES (1)")
    assert db.error("INSERT INTO t VALUES (1)") == "ConstraintError"
    db.run("DROP INDEX u2", "INSERT INTO t VALUES (1)")


# ---------------------------------------------------------------- EXPLAIN

@pytest.mark.parametrize("where, expected", [
    ("name = 'x' AND age > 30", "SEARCH people USING INDEX idx_age (age RANGE)"),
    ("age > 30 AND id = 2", "SEARCH people USING INDEX people_id_key (id = ?)"),
    ("age = 3 AND id = 2", "SEARCH people USING INDEX idx_age (age = ?)"),
    ("age BETWEEN 1 AND 2", "SEARCH people USING INDEX idx_age (age RANGE)"),
    ("age NOT BETWEEN 1 AND 2", "SCAN people"),
    ("30 < age", "SEARCH people USING INDEX idx_age (age RANGE)"),
    ("-5 = age", "SEARCH people USING INDEX idx_age (age = ?)"),
    ("age >= +5", "SEARCH people USING INDEX idx_age (age RANGE)"),
    ("age <= - 5", "SEARCH people USING INDEX idx_age (age RANGE)"),
    ("age = - -5", "SCAN people"),
    ("age = 1 + 1", "SCAN people"),
    ("age = NULL", "SCAN people"),
    ("age <> 3", "SCAN people"),
    ("age IN (1, 2)", "SCAN people"),
    ("age = age", "SCAN people"),
    ("age = 'x'", "SEARCH people USING INDEX idx_age (age = ?)"),
    ("age = TRUE", "SEARCH people USING INDEX idx_age (age = ?)"),
    ("name = 'x'", "SCAN people"),
    ("age = 3 OR id = 2", "SCAN people"),
    ("(age = 3 OR id = 2) AND id > 1", "SEARCH people USING INDEX people_id_key (id RANGE)"),
    ("NOT age = 3", "SCAN people"),
    ("people.age < 3 AND name = 'a' AND id = 1",
     "SEARCH people USING INDEX people_id_key (id = ?)"),
    ("age BETWEEN 1 AND id", "SCAN people"),
    ("TRUE", "SCAN people"),
])
def test_first_table_plan(people, where, expected):
    assert plan(people, f"SELECT * FROM people WHERE {where}") == [expected]


def test_plan_uses_table_name_not_alias(people):
    assert plan(people, "SELECT * FROM people AS p WHERE p.age = 1") == [
        "SEARCH people USING INDEX idx_age (age = ?)"]
    assert plan(people, "SELECT * FROM people p") == ["SCAN people"]


def test_join_plans(people):
    people.run("CREATE TABLE orders (oid INT PRIMARY KEY, pid INT, total INT)")
    assert plan(people, "SELECT * FROM people p JOIN orders o ON o.pid = p.id") == [
        "SCAN people", "HASH JOIN orders (pid)"]
    assert plan(people, "SELECT * FROM orders o LEFT JOIN people p ON o.pid = p.id") == [
        "SCAN orders", "SEARCH people USING INDEX people_id_key (id = ?)"]
    assert plan(people, "SELECT * FROM orders JOIN people ON total > 3 AND age = pid") == [
        "SCAN orders", "SEARCH people USING INDEX idx_age (age = ?)"]
    assert plan(people, "SELECT * FROM orders JOIN people ON name = 'x' AND pid = id "
                        "AND age = total") == [
        "SCAN orders", "SEARCH people USING INDEX people_id_key (id = ?)"]
    assert plan(people, "SELECT * FROM orders JOIN people ON pid = id OR age = total") == [
        "SCAN orders", "SCAN people"]
    assert plan(people, "SELECT * FROM orders CROSS JOIN people") == [
        "SCAN orders", "SCAN people"]
    assert plan(people, "SELECT * FROM orders JOIN people ON age = 3") == [
        "SCAN orders", "SCAN people"]
    # A condition between two columns of the joined table is not an equi-join conjunct.
    assert plan(people, "SELECT * FROM orders JOIN people ON age = id") == [
        "SCAN orders", "SCAN people"]
    assert plan(people, "SELECT * FROM people a JOIN people b ON a.name = b.name") == [
        "SCAN people", "HASH JOIN people (name)"]
    assert plan(people, "SELECT * FROM people a JOIN (SELECT id AS k FROM people) d "
                        "ON d.k = a.id JOIN orders o ON o.oid = d.k") == [
        "SCAN people", "HASH JOIN d (k)", "SEARCH orders USING INDEX orders_oid_key (oid = ?)"]
    assert plan(people, "SELECT * FROM (SELECT id FROM people) d JOIN people p "
                        "ON p.id = d.id WHERE d.id = 1") == [
        "SCAN d", "SEARCH people USING INDEX people_id_key (id = ?)"]
    # WHERE conditions only use indexes of the first table reference.
    assert plan(people, "SELECT * FROM orders JOIN people ON pid = id WHERE age = 3") == [
        "SCAN orders", "SEARCH people USING INDEX people_id_key (id = ?)"]


def test_explain_set_operations_and_subqueries(people):
    assert plan(people, "SELECT id FROM people WHERE id = 1 UNION SELECT age FROM people "
                        "INTERSECT SELECT 1") == [
        "SEARCH people USING INDEX people_id_key (id = ?)", "SCAN people"]
    assert plan(people, "SELECT (SELECT COUNT(*) FROM people) FROM people WHERE EXISTS "
                        "(SELECT 1 FROM people WHERE id = 1)") == ["SCAN people"]
    assert plan(people, "SELECT 1") == []
    assert plan(people, "SELECT * FROM (SELECT * FROM people WHERE id = 1) AS d") == ["SCAN d"]
    assert people.columns("EXPLAIN SELECT 1") == ["plan"]


def test_explain_validates_but_does_not_run(people):
    assert people.error("EXPLAIN SELECT nope FROM people") == "NameError"
    assert people.error("EXPLAIN SELECT * FROM nope") == "NameError"
    assert people.error("EXPLAIN SELECT FROM people") == "SyntaxError"
    assert people.error("EXPLAIN SELECT age, COUNT(*) FROM people") == "SyntaxError"
    for sql in ("EXPLAIN UPDATE people SET age = 1", "EXPLAIN DELETE FROM people",
                "EXPLAIN INSERT INTO people VALUES (1)", "EXPLAIN CREATE TABLE x (a INT)",
                "EXPLAIN EXPLAIN SELECT 1", "EXPLAIN", "EXPLAIN (SELECT 1)"):
        assert people.error(sql) == "SyntaxError", sql
    assert plan(people, "SELECT 1 / 0 FROM people WHERE (SELECT id FROM people) = 1") == [
        "SCAN people"]


# ---------------------------------------------------------------- execution semantics

def test_index_lookups_return_table_order(db):
    db.run("CREATE TABLE t (id INT PRIMARY KEY, k INT, s TEXT)", "CREATE INDEX ik ON t (k)",
           "CREATE INDEX isx ON t (s)")
    db.run("INSERT INTO t VALUES (5, 2, 'b'), (1, 1, 'a'), (3, 2, 'c'), (2, 1, 'b'), (4, 3, 'a')")
    db.expect("SELECT id FROM t WHERE k = 2", [[5], [3]])
    db.expect("SELECT id FROM t WHERE k >= 1 AND k < 3", [[5], [1], [3], [2]])
    db.expect("SELECT id FROM t WHERE id BETWEEN 2 AND 4", [[3], [2], [4]])
    db.expect("SELECT id FROM t WHERE s > 'a'", [[5], [3], [2]])
    db.run("UPDATE t SET k = 2 WHERE id = 4")
    db.expect("SELECT id FROM t WHERE k = 2", [[5], [3], [4]])
    db.run("UPDATE t SET k = 9 WHERE id = 5")
    db.expect("SELECT id FROM t WHERE k = 2", [[3], [4]])
    db.expect("SELECT id FROM t WHERE k > 2", [[5]])


def test_index_on_real_and_boolean_columns(db):
    db.run("CREATE TABLE t (r REAL, b BOOLEAN)", "CREATE INDEX ir ON t (r)",
           "CREATE INDEX ib ON t (b)")
    db.run("INSERT INTO t VALUES (1, TRUE), (2.5, FALSE), (NULL, NULL), (-0.0, TRUE)")
    db.expect("SELECT r FROM t WHERE r = 1", [[1.0]])
    db.expect("SELECT r FROM t WHERE r >= 0 AND r < 2.5", [[1.0], [-0.0]])
    db.expect("SELECT r FROM t WHERE r = 0", [[-0.0]])
    db.expect("SELECT r FROM t WHERE b = TRUE", [[1.0], [-0.0]])
    db.expect("SELECT r FROM t WHERE b < TRUE", [[2.5]])
    db.expect("SELECT COUNT(*) FROM t WHERE r > 100 AND r < -100", [[0]])
    db.expect("SELECT COUNT(*) FROM t WHERE r >= 1 AND r <= 1", [[1]])
    db.expect("SELECT COUNT(*) FROM t WHERE r > 1 AND r <= 1", [[0]])


def test_rows_excluded_by_an_index_are_never_evaluated(people):
    # With the index, only the row with id = 1 is evaluated against 10 / (age - 40).
    people.expect("SELECT name FROM people WHERE id = 1 AND 10 / (age - 40) = -1", [["ann"]])
    people.expect("SELECT name FROM people WHERE age > 30 AND age < 39 AND 10 / (age - 30) > 0",
                  [["cid"]])
    # Without an index (name has none) the full scan reaches the row with age 40.
    assert people.error("SELECT name FROM people WHERE 10 / (age - 40) = -1 AND name = 'ann'"
                        ) == "RuntimeError"
    # A conjunct before the indexed one is still only evaluated on the rows found.
    people.expect("SELECT name FROM people WHERE 10 / (age - 40) = -1 AND id = 1", [["ann"]])


def test_update_and_delete_use_the_index(people):
    assert people.run("UPDATE people SET age = 100 / (age - 40) WHERE id = 3") == {"rowcount": 1}
    people.expect("SELECT age FROM people WHERE id = 3", [[-20]])
    assert people.run("DELETE FROM people WHERE id = 1 AND 10 / (age - 40) < 0") == {
        "rowcount": 1}
    assert people.error("DELETE FROM people WHERE name = 'bob' AND 10 / (age - 40) < 0") == \
        "RuntimeError"


def test_incomparable_literal_behaves_like_a_full_scan(people):
    assert plan(people, "SELECT * FROM people WHERE age = 'x'") == [
        "SEARCH people USING INDEX idx_age (age = ?)"]
    assert people.error("SELECT * FROM people WHERE age = 'x'") == "TypeError"
    assert people.error("SELECT * FROM people WHERE age > TRUE") == "TypeError"
    people.expect("SELECT * FROM people WHERE id < 0 AND age = 'x'", [])
    people.expect("SELECT * FROM people WHERE FALSE AND age = 'x'", [])
    people.run("CREATE TABLE e (a INT)", "CREATE INDEX ea ON e (a)",
               "INSERT INTO e VALUES (NULL)")
    people.expect("SELECT * FROM e WHERE a = 'x'", [])


def test_join_probes_skip_non_matching_pairs(people):
    people.run("CREATE TABLE orders (oid INT PRIMARY KEY, pid INT, total INT)")
    people.run("INSERT INTO orders VALUES (10, 1, 5), (11, 9, 0), (12, 2, 7), (13, NULL, 0)")
    # Order 11 matches nobody and order 13 has a NULL key: 1 / total is never evaluated
    # for them, whether the partner is found through an index or a hash table.
    people.expect("SELECT o.oid, p.name FROM orders o JOIN people p ON p.id = o.pid "
                  "AND 10 / o.total > 0", [[10, "ann"], [12, "bob"]])
    people.expect("SELECT p.name, o.oid FROM people p LEFT JOIN orders o ON o.pid = p.id "
                  "AND 10 / o.total > 0", [["ann", 10], ["bob", 12], ["cid", None],
                                           ["dan", None], ["eve", None]])
    # Without an equi-join conjunct every pair is evaluated.
    assert people.error("SELECT * FROM orders o JOIN people p ON p.id = o.pid OR "
                        "10 / o.total > 0") == "RuntimeError"


def test_equi_join_type_errors(db):
    db.run("CREATE TABLE a (n INT)", "CREATE TABLE b (s TEXT)", "CREATE TABLE c (s TEXT)",
           "CREATE INDEX cs ON c (s)")
    db.run("INSERT INTO a VALUES (1), (NULL)")
    for right in ("b", "c"):
        db.expect(f"SELECT * FROM a JOIN {right} ON a.n = {right}.s", [])
        db.run(f"INSERT INTO {right} VALUES (NULL)")
        db.expect(f"SELECT * FROM a LEFT JOIN {right} ON a.n = {right}.s",
                  [[1, None], [None, None]])
        db.run(f"INSERT INTO {right} VALUES ('x')")
        assert db.error(f"SELECT * FROM a JOIN {right} ON a.n = {right}.s") == "TypeError"
        assert db.error(f"SELECT * FROM a JOIN {right} ON {right}.s = a.n AND FALSE"
                        ) == "TypeError"
    db.run("DELETE FROM a WHERE n IS NOT NULL")
    db.expect("SELECT * FROM a JOIN c ON a.n = c.s", [])


# ---------------------------------------------------------------- consistency

def _random_dml(r):
    k = r.random()
    key = r.choice(["NULL", str(r.randint(0, 9)), str(r.randint(0, 9))])
    if k < 0.5:
        return f"INSERT INTO {{t}} VALUES ({r.randint(0, 40)}, {key}, '{r.choice('abcde')}')"
    if k < 0.75:
        return f"UPDATE {{t}} SET k = {key} WHERE id % {r.randint(2, 5)} = {r.randint(0, 1)}"
    return f"DELETE FROM {{t}} WHERE k = {r.randint(0, 9)} OR s = '{r.choice('abcde')}'"


def _random_predicate(r):
    col = r.choice(["k", "s", "id"])
    lit = f"'{r.choice('abcde')}'" if col == "s" else str(r.randint(-1, 10))
    lit2 = f"'{r.choice('abcde')}'" if col == "s" else str(r.randint(-1, 10))
    return r.choice([f"{col} = {lit}", f"{col} < {lit}", f"{lit} <= {col}",
                     f"{col} > {lit} AND {col} <= {lit2}", f"{col} BETWEEN {lit} AND {lit2}",
                     f"{col} >= {lit} AND s <> 'a'"])


@pytest.mark.parametrize("seed", range(60))
def test_indexed_and_unindexed_tables_agree(seed):
    r = random.Random(seed)
    engine = Engine()
    engine.execute("CREATE TABLE ix (id INT, k INT, s TEXT)")
    engine.execute("CREATE TABLE plain (id INT, k INT, s TEXT)")
    for col in ("id", "k", "s"):
        engine.execute(f"CREATE INDEX ix_{col} ON ix ({col})")
    for _ in range(40):
        sql = _random_dml(r)
        results = []
        for t in ("ix", "plain"):
            try:
                results.append(engine.execute(sql.format(t=t)))
            except DBError as exc:
                results.append(exc.type_name)
        assert results[0] == results[1], sql
        pred = _random_predicate(r)
        got = engine.execute(f"SELECT * FROM ix WHERE {pred}")["rows"]
        assert got == engine.execute(f"SELECT * FROM plain WHERE {pred}")["rows"], pred
    assert engine.execute("SELECT * FROM ix")["rows"] == \
        engine.execute("SELECT * FROM plain")["rows"]


# ---------------------------------------------------------------- module level

def test_access_helpers():
    assert len(conjuncts(parse("SELECT 1 FROM t WHERE a AND (b AND c) AND d").where)) == 4
    assert conjuncts(None) == []
    assert literal_value(parse("SELECT -5").items[0].expr) == (True, -5)
    assert literal_value(parse("SELECT NULL").items[0].expr) == (False, None)
    table = Table("t", [Column("a", "INTEGER"), Column("b", "TEXT")])
    table.insert_rows([(i, str(i)) for i in range(10)])
    table.add_index(Index("ia", table, 0))
    scope = Scope()
    scope.add("t", ["a", "b"])
    access = TableAccess(table, parse("SELECT 1 FROM t WHERE a > 2 AND a <= 4").where, scope)
    assert access.rows() == [(3, "3"), (4, "4")]
    other = Scope()
    other.add("t", ["a", "b"])
    other.add("u", ["c"])
    eq = equi_join(parse("SELECT 1 FROM t JOIN u ON c = a").from_.joins[0].on, other, 2)
    assert (eq.left_index, eq.right_column, eq.only_conjunct) == (0, 0, True)
