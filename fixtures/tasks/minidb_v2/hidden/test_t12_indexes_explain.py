"""Section 12 (stage 2): indexes (explicit, implicit, UNIQUE), EXPLAIN plans, plans as promises."""
from _support import COMPANY, assert_error, assert_rows, plan, run, run_ok, stage

ITEMS = """
CREATE TABLE items (id INTEGER PRIMARY KEY, sku TEXT, qty INTEGER, price REAL);
INSERT INTO items VALUES (30, 'c-1', 5, 3.0), (10, 'a-1', 2, 1.5), (20, 'b-1', 5, 2.0),
                         (40, 'd-1', NULL, 3), (50, 'b-2', 7, 4.25), (60, 'e-1', 1, NULL);
"""


@stage(2)
def test_explain_reports_search_only_while_an_index_exists():
    res = run_ok(ITEMS + """
        EXPLAIN SELECT * FROM items WHERE qty = 5;
        CREATE INDEX idx_qty ON items (qty);
        EXPLAIN SELECT * FROM items WHERE qty = 5;
        EXPLAIN SELECT id FROM items;
        DROP INDEX idx_qty;
        EXPLAIN SELECT * FROM items WHERE qty = 5;
    """)
    assert plan(res[-6]) == ["SCAN items"]
    assert res[-5].raw == {"ok": True}
    assert res[-4].raw == {"ok": True, "columns": ["plan"],
                           "rows": [["SEARCH items USING INDEX idx_qty (qty = ?)"]]}
    assert plan(res[-3]) == ["SCAN items"]
    assert res[-2].raw == {"ok": True}
    assert plan(res[-1]) == ["SCAN items"]


@stage(2)
def test_explain_plan_rules_for_the_first_table():
    cases = [
        ("price > 1.0 AND qty = 3", "SEARCH items USING INDEX idx_qty (qty = ?)"),
        ("price > 1.0 AND qty > 3", "SEARCH items USING INDEX idx_price (price RANGE)"),
        ("price = 3 AND qty < 2", "SEARCH items USING INDEX idx_price (price = ?)"),
        ("5 > qty", "SEARCH items USING INDEX idx_qty (qty RANGE)"),
        ("qty BETWEEN 1 AND 3", "SEARCH items USING INDEX idx_qty (qty RANGE)"),
        ("sku = 'a' AND qty = -3", "SEARCH items USING INDEX idx_qty (qty = ?)"),
        ("qty = +3", "SEARCH items USING INDEX idx_qty (qty = ?)"),
        ("TRUE AND qty <= 2", "SEARCH items USING INDEX idx_qty (qty RANGE)"),
        ("id >= 20 AND qty = 5", "SEARCH items USING INDEX idx_qty (qty = ?)"),
        ("id = 20 AND qty = 5", "SEARCH items USING INDEX items_id_key (id = ?)"),
        ("qty = 'x'", "SEARCH items USING INDEX idx_qty (qty = ?)"),
        ("qty = 3 OR price = 1.0", "SCAN items"),
        ("qty + 0 = 3", "SCAN items"),
        ("qty = NULL", "SCAN items"),
        ("sku = 'a'", "SCAN items"),
        ("qty = qty", "SCAN items"),
        ("qty IN (1, 2)", "SCAN items"),
        ("NOT qty = 3", "SCAN items"),
        ("qty NOT BETWEEN 1 AND 3", "SCAN items"),
        ("qty <> 3", "SCAN items"),
    ]
    script = ITEMS + "CREATE INDEX idx_qty ON items (qty); CREATE INDEX idx_price ON items (price);\n"
    script += "".join(f"EXPLAIN SELECT * FROM items WHERE {w};\n" for w, _ in cases)
    script += "EXPLAIN SELECT i.id FROM items AS i WHERE i.qty >= 2 AND i.qty <= 5;\n"
    res = run_ok(script)
    got = [plan(r) for r in res[-len(cases) - 1:]]
    assert got == [[p] for _, p in cases] + [["SEARCH items USING INDEX idx_qty (qty RANGE)"]]


@stage(2)
def test_implicit_indexes_for_primary_key_and_unique_columns():
    res = run("""
        CREATE TABLE u (id INTEGER PRIMARY KEY, code TEXT UNIQUE, n INTEGER);
        INSERT INTO u VALUES (1, 'a', 10), (2, 'b', 20);
        EXPLAIN SELECT * FROM u WHERE code = 'b';
        EXPLAIN SELECT * FROM u WHERE id > 1;
        CREATE INDEX first_code ON u (code);
        EXPLAIN SELECT * FROM u WHERE code = 'b';
        CREATE INDEX u_code_key ON u (n);
        DROP INDEX u_id_key;
        CREATE INDEX v_a_key ON u (n);
        CREATE TABLE v (a INTEGER PRIMARY KEY);
        DROP INDEX v_a_key;
        CREATE TABLE v (a INTEGER PRIMARY KEY);
        EXPLAIN SELECT * FROM v WHERE a = 1;
        DROP TABLE u;
        CREATE INDEX u_id_key ON v (a);
        SELECT * FROM u;
    """)
    assert plan(res[2]) == ["SEARCH u USING INDEX u_code_key (code = ?)"]
    assert plan(res[3]) == ["SEARCH u USING INDEX u_id_key (id RANGE)"]
    assert res[4].ok
    assert plan(res[5]) == ["SEARCH u USING INDEX u_code_key (code = ?)"]
    assert_error(res[6], "NameError")
    assert_error(res[7], "ConstraintError")
    assert res[8].ok
    assert_error(res[9], "NameError")
    assert res[10].ok and res[11].ok
    assert plan(res[12]) == ["SEARCH v USING INDEX v_a_key (a = ?)"]
    assert res[13].ok and res[14].ok
    assert_error(res[15], "NameError")


@stage(2)
def test_unique_indexes_and_first_created_index():
    res = run(ITEMS + """
        CREATE INDEX q1 ON items (qty);
        CREATE UNIQUE INDEX q2 ON items (qty);
        CREATE INDEX q3 ON items (qty);
        EXPLAIN SELECT * FROM items WHERE qty = 1;
        CREATE UNIQUE INDEX s1 ON items (sku);
        INSERT INTO items VALUES (70, 'b-2', 8, 1.0);
        INSERT INTO items VALUES (70, 'z-1', 9, 1.0), (80, 'z-1', 10, 1.0);
        UPDATE items SET sku = 'a-1' WHERE id = 20;
        UPDATE items SET sku = CASE WHEN sku = 'a-1' THEN 'b-1' WHEN sku = 'b-1' THEN 'a-1' ELSE sku END;
        SELECT id FROM items WHERE sku = 'a-1';
        INSERT INTO items VALUES (90, NULL, NULL, NULL), (91, NULL, NULL, NULL);
        DROP INDEX s1;
        INSERT INTO items VALUES (92, 'b-2', NULL, NULL);
        SELECT COUNT(*) FROM items WHERE sku = 'b-2';
    """)
    r = res[-14:]
    assert r[0].ok
    assert_error(r[1], "ConstraintError")
    assert r[2].ok
    assert plan(r[3]) == ["SEARCH items USING INDEX q1 (qty = ?)"]
    assert r[4].ok
    assert_error(r[5], "ConstraintError")
    assert_error(r[6], "ConstraintError")
    assert_error(r[7], "ConstraintError")
    assert r[8].rowcount == 6
    assert_rows(r[9], [[20]])
    assert r[10].rowcount == 2
    assert r[11].ok and r[12].rowcount == 1
    assert_rows(r[13], [[2]])


@stage(2)
def test_index_ddl_errors_and_if_exists():
    res = run(ITEMS + """
        CREATE INDEX ix ON items (qty);
        CREATE INDEX ix ON items (price);
        CREATE INDEX IF NOT EXISTS ix ON items (price);
        CREATE INDEX iy ON nope (qty);
        CREATE INDEX iy ON items (nope);
        DROP INDEX nope;
        DROP INDEX IF EXISTS nope;
        CREATE INDEX items ON items (sku);
        EXPLAIN SELECT * FROM items WHERE sku = 'x';
        DROP TABLE items;
        CREATE INDEX ix ON nope (a);
        CREATE TABLE items (id INTEGER);
        CREATE INDEX ix ON items (id);
        CREATE INDEX items ON items (id);
        CREATE INDEX (id);
    """)
    r = res[-15:]
    assert r[0].ok
    assert_error(r[1], "NameError")
    assert r[2].raw == {"ok": True}
    assert_error(r[3], "NameError")
    assert_error(r[4], "NameError")
    assert_error(r[5], "NameError")
    assert r[6].raw == {"ok": True}
    assert r[7].ok
    assert plan(r[8]) == ["SEARCH items USING INDEX items (sku = ?)"]
    assert r[9].ok
    assert_error(r[10], "NameError")
    assert r[11].ok and r[12].ok and r[13].ok
    assert_error(r[14], "SyntaxError")


@stage(2)
def test_index_lookups_return_full_scan_rows_in_table_order():
    queries = ["qty = 5", "qty > 1", "qty >= 5", "qty < 5", "qty BETWEEN 2 AND 6", "price <= 3",
               "price = 3", "1 < qty", "price > 2 AND qty = 5", "sku >= 'b'", "id > 25"]
    script = ITEMS + "".join(f"SELECT id FROM items WHERE {w};\n" for w in queries)
    script += ("CREATE INDEX iq ON items (qty); CREATE INDEX ip ON items (price);"
               "CREATE INDEX isku ON items (sku);\n")
    script += "".join(f"SELECT id FROM items WHERE {w};\n" for w in queries)
    script += """
        UPDATE items SET qty = 5 WHERE id = 60;
        DELETE FROM items WHERE id = 30;
        INSERT INTO items VALUES (5, 'a-0', 5, 0.5), (35, 'c-2', NULL, 3.0);
        UPDATE items SET price = 3.0 WHERE qty = 7;
    """
    script += "".join(f"SELECT id FROM items WHERE {w};\n" for w in queries)
    script += "DROP INDEX iq; DROP INDEX ip; DROP INDEX isku;\n"
    script += "".join(f"SELECT id FROM items WHERE {w};\n" for w in queries)
    res = run_ok(script)
    n = len(queries)
    before_scan = [r.rows for r in res[2:2 + n]]
    before_index = [r.rows for r in res[5 + n:5 + 2 * n]]
    assert before_index == before_scan
    assert before_scan[0] == [[30], [20]]
    assert before_scan[1] == [[30], [10], [20], [50]]
    after_index = [r.rows for r in res[9 + 2 * n:9 + 3 * n]]
    after_scan = [r.rows for r in res[12 + 3 * n:12 + 4 * n]]
    assert after_index == after_scan
    assert after_index[0] == [[20], [60], [5]]
    assert after_index[6] == [[40], [50], [35]]


@stage(2)
def test_incomparable_literal_still_searches_but_fails_like_a_scan():
    res = run(ITEMS + """
        CREATE INDEX iq ON items (qty);
        EXPLAIN SELECT * FROM items WHERE qty = 'x';
        SELECT * FROM items WHERE qty = 'x';
        SELECT * FROM items WHERE qty > TRUE;
        CREATE TABLE e (a INTEGER);
        CREATE INDEX ea ON e (a);
        SELECT * FROM e WHERE a = 'x';
        SELECT id FROM items WHERE qty < 100;
        SELECT id FROM items WHERE price >= 3;
    """)
    assert plan(res[-8]) == ["SEARCH items USING INDEX iq (qty = ?)"]
    assert_error(res[-7], "TypeError")
    assert_error(res[-6], "TypeError")
    assert_rows(res[-3], [])
    assert_rows(res[-2], [[30], [10], [20], [50], [60]])
    assert_rows(res[-1], [[30], [40], [50]])


@stage(2)
def test_explain_join_plans():
    cases = [
        ("FROM emp e JOIN dept d ON d.id = e.dept_id",
         ["SCAN emp", "SEARCH dept USING INDEX dept_id_key (id = ?)"]),
        ("FROM emp e LEFT JOIN dept d ON e.name = d.name",
         ["SCAN emp", "SEARCH dept USING INDEX dept_name_key (name = ?)"]),
        ("FROM dept d JOIN emp e ON e.dept_id = d.id", ["SCAN dept", "HASH JOIN emp (dept_id)"]),
        ("FROM dept d LEFT JOIN emp e ON e.salary > 100 AND dept_id = d.id",
         ["SCAN dept", "HASH JOIN emp (dept_id)"]),
        ("FROM dept d JOIN emp e ON e.dept_id = d.id + 0", ["SCAN dept", "SCAN emp"]),
        ("FROM dept d JOIN emp e ON e.dept_id = 1", ["SCAN dept", "SCAN emp"]),
        ("FROM dept d JOIN emp e ON e.id = e.manager_id", ["SCAN dept", "SCAN emp"]),
        ("FROM dept d CROSS JOIN emp e", ["SCAN dept", "SCAN emp"]),
        ("FROM dept d JOIN emp e ON e.dept_id = d.id OR e.id = 1", ["SCAN dept", "SCAN emp"]),
        ("FROM emp e JOIN dept d ON d.id = e.dept_id WHERE e.id = 3",
         ["SEARCH emp USING INDEX emp_id_key (id = ?)", "SEARCH dept USING INDEX dept_id_key (id = ?)"]),
        ("FROM emp e JOIN emp m ON m.id = e.manager_id JOIN dept d ON d.budget = m.salary",
         ["SCAN emp", "SEARCH emp USING INDEX emp_id_key (id = ?)", "HASH JOIN dept (budget)"]),
        ("FROM dept d JOIN (SELECT dept_id, COUNT(*) AS c FROM emp GROUP BY dept_id) s ON s.dept_id = d.id",
         ["SCAN dept", "HASH JOIN s (dept_id)"]),
        ("FROM (SELECT dept_id FROM emp) s JOIN dept d ON d.id = s.dept_id WHERE s.dept_id = 1",
         ["SCAN s", "SEARCH dept USING INDEX dept_id_key (id = ?)"]),
    ]
    script = COMPANY + "".join(f"EXPLAIN SELECT * {c};\n" for c, _ in cases)
    script += """
        EXPLAIN SELECT id FROM emp WHERE id = 1 UNION SELECT id FROM dept;
        EXPLAIN SELECT (SELECT COUNT(*) FROM dept), name FROM emp WHERE id IN (SELECT id FROM dept);
        EXPLAIN SELECT 1;
        EXPLAIN DELETE FROM emp;
        EXPLAIN SELECT nope FROM emp;
        EXPLAIN INSERT INTO dept VALUES (9, 'x', NULL);
        EXPLAIN SELECT * FROM emp e JOIN dept d ON d.id = x.id;
    """
    res = run(script)
    got = [plan(r) for r in res[-len(cases) - 7:-7]]
    assert got == [p for _, p in cases]
    r = res[-7:]
    assert plan(r[0]) == ["SEARCH emp USING INDEX emp_id_key (id = ?)", "SCAN dept"]
    assert plan(r[1]) == ["SCAN emp"]
    assert r[2].raw == {"ok": True, "columns": ["plan"], "rows": []}
    assert_error(r[3], "SyntaxError")
    assert_error(r[4], "NameError")
    assert_error(r[5], "SyntaxError")
    assert_error(r[6], "NameError")


@stage(2)
def test_join_results_are_identical_under_every_plan():
    joins = [
        "SELECT e.name, d.name FROM emp e JOIN dept d ON d.id = e.dept_id",
        "SELECT d.name, e.name FROM dept d JOIN emp e ON e.dept_id = d.id",
        "SELECT d.name, e.name FROM dept d LEFT JOIN emp e ON e.dept_id = d.id AND e.salary >= 150",
        "SELECT e.name, m.name FROM emp e LEFT JOIN emp m ON m.id = e.manager_id",
        "SELECT x.v, y.v FROM x JOIN y ON y.r = x.i",
        "SELECT x.v, y.v FROM x LEFT JOIN y ON x.i = y.r",
    ]
    setup = COMPANY + """
        CREATE TABLE x (i INTEGER, v TEXT);
        CREATE TABLE y (r REAL, v TEXT);
        INSERT INTO x VALUES (1, 'x1'), (2, 'x2'), (NULL, 'xn'), (1, 'x1b');
        INSERT INTO y VALUES (1.0, 'y1'), (NULL, 'yn'), (2.5, 'y25'), (1, 'y1b'), (2.0, 'y2');
    """
    script = setup + "".join(j + ";\n" for j in joins)
    script += "CREATE INDEX e_dept ON emp (dept_id); CREATE INDEX y_r ON y (r);\n"
    script += "".join(j + ";\n" for j in joins)
    script += "".join("EXPLAIN " + j + ";\n" for j in joins[4:])
    res = run_ok(script)
    n, base = len(joins), 9
    first = [r.rows for r in res[base:base + n]]
    second = [r.rows for r in res[base + n + 2:base + 2 * n + 2]]
    assert first == second
    assert first[4] == [["x1", "y1"], ["x1", "y1b"], ["x2", "y2"], ["x1b", "y1"], ["x1b", "y1b"]]
    assert first[5] == [["x1", "y1"], ["x1", "y1b"], ["x2", "y2"], ["xn", None], ["x1b", "y1"],
                        ["x1b", "y1b"]]
    assert plan(res[-2]) == ["SCAN x", "SEARCH y USING INDEX y_r (r = ?)"]


@stage(2)
def test_hash_join_key_types_and_nulls():
    res = run("""
        CREATE TABLE a (k INTEGER, v TEXT);
        CREATE TABLE b (k TEXT, w TEXT);
        CREATE TABLE c (k INTEGER, w TEXT);
        INSERT INTO a VALUES (1, 'a1'), (NULL, 'an');
        INSERT INTO b VALUES (NULL, 'bn'), ('1', 'b1');
        INSERT INTO c VALUES (NULL, 'cn'), (1, 'c1');
        EXPLAIN SELECT * FROM a JOIN b ON b.k = a.k;
        SELECT * FROM a JOIN b ON b.k = a.k;
        SELECT * FROM a LEFT JOIN b ON b.k = a.k WHERE a.k IS NULL;
        DELETE FROM b WHERE k IS NOT NULL;
        SELECT * FROM a LEFT JOIN b ON b.k = a.k;
        SELECT * FROM a LEFT JOIN c ON c.k = a.k;
    """)
    assert plan(res[6]) == ["SCAN a", "HASH JOIN b (k)"]
    assert_error(res[7], "TypeError")
    assert_error(res[8], "TypeError")
    assert_rows(res[10], [[1, "a1", None, None], [None, "an", None, None]])
    assert_rows(res[11], [[1, "a1", 1, "c1"], [None, "an", None, None]])


@stage(2)
def test_rows_excluded_by_a_plan_are_never_evaluated():
    res = run("""
        CREATE TABLE plain (id INTEGER, v INTEGER);
        CREATE TABLE keyed (id INTEGER PRIMARY KEY, v INTEGER);
        INSERT INTO plain VALUES (1, 1), (2, 0), (3, 3);
        INSERT INTO keyed VALUES (1, 1), (2, 0), (3, 3);
        SELECT id FROM plain WHERE 10 % v = 0 AND id = 1;
        SELECT id FROM keyed WHERE 10 % v = 0 AND id = 1;
        SELECT id FROM keyed WHERE 9 % v = 0 AND id >= 3;
        UPDATE keyed SET v = 5 WHERE 10 % v = 1 AND id = 3;
        DELETE FROM keyed WHERE 10 % v = 0 AND id = 1;
        CREATE TABLE probe (k INTEGER);
        INSERT INTO probe VALUES (3);
        SELECT p.k, plain.v FROM probe p JOIN plain ON 6 % plain.v = 0 AND plain.id = p.k;
        SELECT keyed.id FROM keyed;
    """)
    assert_error(res[4], "RuntimeError")
    assert_rows(res[5], [[1]])
    assert_rows(res[6], [[3]])
    assert res[7].rowcount == 1
    assert res[8].rowcount == 1
    assert_rows(res[11], [[3, 3]])
    assert_rows(res[12], [[2], [3]])


@stage(2, retired=6)
def test_plans_report_names_in_lower_case():
    res = run_ok("""
        CREATE TABLE Stock (Sku TEXT PRIMARY KEY, Qty INTEGER);
        CREATE INDEX ByQty ON STOCK (QTY);
        EXPLAIN SELECT * FROM stock WHERE Qty = 1;
        EXPLAIN SELECT * FROM STOCK WHERE sku > 'a';
        EXPLAIN SELECT * FROM stock s JOIN Stock t ON T.QTY = s.qty;
    """)
    assert plan(res[2]) == ["SEARCH stock USING INDEX byqty (qty = ?)"]
    assert plan(res[3]) == ["SEARCH stock USING INDEX stock_sku_key (sku RANGE)"]
    assert plan(res[4]) == ["SCAN stock", "SEARCH stock USING INDEX byqty (qty = ?)"]
