from minidb.engine import Engine, run_sql
from minidb.parser import parse
from minidb.planner import flatten_and, literal_value


def plans(e, sql):
    return [r[0] for r in run_sql(e, "EXPLAIN " + sql)[0]["rows"]]


def test_literals_and_conjuncts():
    w = parse("SELECT 1 FROM t WHERE a = -3 AND (b > 1 OR c < 2) AND d BETWEEN 1 AND 2").where
    assert len(flatten_and(w)) == 3
    assert literal_value(parse("SELECT -3").items[0].expr) == (True, -3)
    assert literal_value(parse("SELECT NULL").items[0].expr) == (False, None)


def test_plans_for_first_table_and_joins():
    e = Engine()
    run_sql(e, """
        CREATE TABLE a (id INTEGER PRIMARY KEY, k INTEGER, v TEXT);
        CREATE TABLE b (id INTEGER, a_id INTEGER, w TEXT);
        CREATE INDEX a_k ON a (k);
    """)
    assert plans(e, "SELECT * FROM a WHERE v = 'x' AND k > 3") == ["SEARCH a USING INDEX a_k (k RANGE)"]
    assert plans(e, "SELECT * FROM a WHERE k > 3 AND id = 1") == ["SEARCH a USING INDEX a_id_key (id = ?)"]
    assert plans(e, "SELECT * FROM b JOIN a ON a.id = b.a_id") == [
        "SCAN b", "SEARCH a USING INDEX a_id_key (id = ?)"]
    assert plans(e, "SELECT * FROM a JOIN b ON b.a_id = a.id") == ["SCAN a", "HASH JOIN b (a_id)"]
    assert plans(e, "SELECT * FROM a CROSS JOIN b") == ["SCAN a", "SCAN b"]


def test_index_and_hash_plans_give_scan_results():
    e = Engine()
    run_sql(e, """
        CREATE TABLE a (id INTEGER PRIMARY KEY, k INTEGER);
        CREATE TABLE b (a_id INTEGER, w TEXT);
        INSERT INTO a VALUES (3, 1), (1, 2), (2, 1);
        INSERT INTO b VALUES (1, 'x'), (3, 'y'), (1, 'z'), (NULL, 'n');
    """)
    sql = "SELECT a.id, b.w FROM a LEFT JOIN b ON b.a_id = a.id WHERE a.k <= 2"
    before = run_sql(e, sql)[0]["rows"]
    run_sql(e, "CREATE INDEX b_a ON b (a_id); CREATE INDEX a_k ON a (k)")
    assert run_sql(e, sql)[0]["rows"] == before == [[3, "y"], [1, "x"], [1, "z"], [2, None]]
