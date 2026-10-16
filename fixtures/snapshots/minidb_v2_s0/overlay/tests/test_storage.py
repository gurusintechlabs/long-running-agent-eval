from minidb import storage


def test_tables_keep_insertion_order_and_row_ids_grow():
    db = storage.Database()
    t = storage.Table("t", [storage.Column("a", "INTEGER")])
    db.tables["t"] = t
    for value in (3, 1, 2):
        t.rows[db.new_rowid()] = [value]
    del t.rows[2]
    t.rows[db.new_rowid()] = [9]
    assert list(t.rows.values()) == [[3], [2], [9]] and list(t.rows) == [1, 3, 4]
    assert t.col_index("a") == 0 and t.col_index("b") is None
