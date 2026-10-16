"""Tier 7: secondary indexes, UNIQUE indexes, EXPLAIN."""
from _support import assert_error, assert_rows, run, run_ok

ITEMS = """
CREATE TABLE items (id INTEGER PRIMARY KEY, sku TEXT, qty INTEGER, price REAL);
INSERT INTO items VALUES (30, 'c-1', 5, 3.0), (10, 'a-1', 2, 1.5), (20, 'b-1', 5, 2.0),
                         (40, 'd-1', NULL, 3), (50, 'b-2', 7, 4.25), (60, 'e-1', 1, NULL);
"""


def plan(result):
    assert result.ok, result
    assert result.columns == ["plan"], result
    return [row[0] for row in result.rows]


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


def test_explain_plan_rules():
    cases = [
        ("price > 1.0 AND qty = 3", "SEARCH items USING INDEX idx_qty (qty = ?)"),
        ("price > 1.0 AND qty > 3", "SEARCH items USING INDEX idx_price (price RANGE)"),
        ("price = 3 AND qty < 2", "SEARCH items USING INDEX idx_price (price = ?)"),
        ("5 > qty", "SEARCH items USING INDEX idx_qty (qty RANGE)"),
        ("qty BETWEEN 1 AND 3", "SEARCH items USING INDEX idx_qty (qty RANGE)"),
        ("sku = 'a' AND qty = -3", "SEARCH items USING INDEX idx_qty (qty = ?)"),
        ("qty = 3 OR price = 1.0", "SCAN items"),
        ("qty + 0 = 3", "SCAN items"),
        ("qty = NULL", "SCAN items"),
        ("sku = 'a'", "SCAN items"),
        ("qty = qty", "SCAN items"),
        ("qty IN (1, 2)", "SCAN items"),
        ("NOT qty = 3", "SCAN items"),
    ]
    script = ITEMS + "CREATE INDEX idx_qty ON items (qty); CREATE INDEX idx_price ON items (price);\n"
    script += "".join(f"EXPLAIN SELECT * FROM items WHERE {w};\n" for w, _ in cases)
    script += "EXPLAIN SELECT i.id FROM items AS i WHERE i.qty >= 2 AND i.qty <= 5;\n"
    res = run_ok(script)
    got = [plan(r) for r in res[-len(cases) - 1:]]
    assert got == [[p] for _, p in cases] + [["SEARCH items USING INDEX idx_qty (qty RANGE)"]]


def test_first_created_index_on_a_column_wins():
    res = run_ok(ITEMS + """
        CREATE INDEX zz ON items (qty);
        CREATE INDEX aa ON items (qty);
        EXPLAIN SELECT * FROM items WHERE qty = 1;
        DROP INDEX zz;
        EXPLAIN SELECT * FROM items WHERE qty = 1;
    """)
    assert plan(res[-3]) == ["SEARCH items USING INDEX zz (qty = ?)"]
    assert plan(res[-1]) == ["SEARCH items USING INDEX aa (qty = ?)"]


def test_index_lookups_return_rows_in_table_order():
    res = run_ok(ITEMS + """
        CREATE INDEX idx_qty ON items (qty);
        CREATE INDEX idx_sku ON items (sku);
        SELECT id FROM items WHERE qty = 5;
        SELECT id FROM items WHERE qty >= 2;
        SELECT id FROM items WHERE qty < 6;
        SELECT id FROM items WHERE qty BETWEEN 2 AND 5 ORDER BY id;
        SELECT sku FROM items WHERE sku >= 'b' AND sku < 'd';
        EXPLAIN SELECT sku FROM items WHERE sku >= 'b' AND sku < 'd';
    """)
    assert_rows(res[-6], [[30], [20]])
    assert_rows(res[-5], [[30], [10], [20], [50]])
    assert_rows(res[-4], [[30], [10], [20], [60]])
    assert_rows(res[-3], [[10], [20], [30]])
    assert_rows(res[-2], [["c-1"], ["b-1"], ["b-2"]])
    assert plan(res[-1]) == ["SEARCH items USING INDEX idx_sku (sku RANGE)"]


def test_integer_literals_find_real_values_through_an_index():
    res = run_ok(ITEMS + """
        CREATE INDEX ip ON items (price);
        SELECT id FROM items WHERE price = 3;
        SELECT id FROM items WHERE price BETWEEN 2 AND 3;
        SELECT id FROM items WHERE price > 4;
        EXPLAIN SELECT id FROM items WHERE price = 3;
    """)
    assert_rows(res[-4], [[30], [40]])
    assert_rows(res[-3], [[30], [20], [40]])
    assert_rows(res[-2], [[50]])
    assert plan(res[-1]) == ["SEARCH items USING INDEX ip (price = ?)"]


def test_index_stays_consistent_through_insert_update_delete():
    res = run_ok(ITEMS + """
        CREATE INDEX idx_qty ON items (qty);
        UPDATE items SET qty = 5 WHERE id = 50;
        UPDATE items SET qty = qty + 1 WHERE id = 30;
        DELETE FROM items WHERE id = 20;
        INSERT INTO items VALUES (70, 'f-1', 5, 1.0), (80, 'g-1', NULL, 2.0);
        UPDATE items SET qty = NULL WHERE id = 10;
        SELECT id FROM items WHERE qty = 5;
        SELECT id FROM items WHERE qty + 0 = 5;
        SELECT id FROM items WHERE qty > 0;
        SELECT id FROM items WHERE qty = 2;
        SELECT id FROM items WHERE qty = 6;
        SELECT id, qty FROM items WHERE qty <= 5 ORDER BY qty DESC, id;
    """)
    assert_rows(res[-6], [[50], [70]])
    assert_rows(res[-5], [[50], [70]])
    assert_rows(res[-4], [[30], [50], [60], [70]])
    assert_rows(res[-3], [])
    assert_rows(res[-2], [[30]])
    assert_rows(res[-1], [[50, 5], [70, 5], [60, 1]])


def test_unique_index_enforces_uniqueness():
    res = run(ITEMS + """
        CREATE UNIQUE INDEX uq ON items (qty);
        EXPLAIN SELECT * FROM items WHERE qty = 1;
        DROP INDEX uq;
        CREATE UNIQUE INDEX usku ON items (sku);
        INSERT INTO items VALUES (90, 'a-1', 1, 1.0);
        INSERT INTO items VALUES (90, NULL, 1, 1.0), (91, NULL, 1, 1.0);
        UPDATE items SET sku = 'zz' WHERE qty = 5;
        SELECT id FROM items WHERE sku = 'a-1';
        DROP INDEX usku;
        INSERT INTO items VALUES (92, 'a-1', 1, 1.0);
        SELECT id FROM items WHERE sku = 'a-1';
    """)
    r = res[-11:]
    assert_error(r[0], "ConstraintError")
    assert plan(r[1]) == ["SCAN items"]
    assert_error(r[2], "NameError")
    assert r[3].raw == {"ok": True}
    assert_error(r[4], "ConstraintError")
    assert r[5].rowcount == 2
    assert_error(r[6], "ConstraintError")
    assert_rows(r[7], [[10]])
    assert r[9].rowcount == 1
    assert_rows(r[10], [[10], [92]])


def test_index_name_errors_and_namespace():
    res = run(ITEMS + """
        CREATE INDEX i1 ON items (qty);
        CREATE INDEX i1 ON items (price);
        CREATE INDEX i2 ON nope (qty);
        CREATE INDEX i3 ON items (nope);
        DROP INDEX nope;
        CREATE INDEX items ON items (sku);
        EXPLAIN UPDATE items SET qty = 1;
        EXPLAIN SELECT * FROM nope;
        EXPLAIN SELECT nope FROM items;
        EXPLAIN SELECT * FROM items WHERE sku = 'x';
    """)
    r = res[-10:]
    assert r[0].ok
    for x, w in zip(r[1:5], ["NameError"] * 4):
        assert_error(x, w)
    assert r[5].ok
    assert_error(r[6], "SyntaxError")
    assert_error(r[7], "NameError")
    assert_error(r[8], "NameError")
    assert plan(r[9]) == ["SEARCH items USING INDEX items (sku = ?)"]


def test_drop_table_drops_its_indexes_and_explain_does_not_execute():
    res = run(ITEMS + """
        CREATE INDEX iq ON items (qty);
        DROP TABLE items;
        DROP INDEX iq;
    """ + ITEMS + """
        CREATE INDEX iq ON items (qty);
        EXPLAIN SELECT 1 / 0 FROM items WHERE qty = 5;
        SELECT id FROM items WHERE qty = 5;
    """)
    assert_error(res[4], "NameError")
    assert res[7].ok
    assert plan(res[8]) == ["SEARCH items USING INDEX iq (qty = ?)"]
    assert_rows(res[9], [[30], [20]])
