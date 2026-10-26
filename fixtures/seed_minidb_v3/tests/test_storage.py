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


def test_index_lookups_return_row_ids_in_table_order():
    ix = storage.Index("i", "t", "a", False, 1)
    for rid, key in enumerate([5, 1, 3, 5, None, 9], start=1):
        ix.add(key, rid)
    assert ix.eq(5) == [1, 4] and ix.eq(5.0) == [1, 4]
    assert ix.range(None, True, 5, False) == [2, 3]
    assert ix.range(3, False, None, True) == [1, 4, 6]
    ix.remove(5, 1)
    assert ix.eq(5) == [4] and len(ix) == 4
    ix.add_many([(k, 100 + k) for k in range(100)])
    assert ix.eq(7) == [107] and ix.range(98, True, None, True) == [198, 199]
