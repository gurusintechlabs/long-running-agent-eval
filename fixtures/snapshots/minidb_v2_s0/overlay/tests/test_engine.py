from minidb.engine import Engine, run_sql
from minidb.protocol import ConstraintError, SQLRuntimeError


def test_dml_rowcounts_and_atomic_unique_checks():
    e = Engine()
    res = run_sql(e, """
        CREATE TABLE k (id INTEGER PRIMARY KEY, v TEXT UNIQUE);
        INSERT INTO k VALUES (1, 'a'), (2, 'b'), (3, NULL);
        UPDATE k SET id = id + 1;
        INSERT INTO k VALUES (9, 'z'), (8, 'z');
        DELETE FROM k WHERE id > 2;
        SELECT * FROM k;
    """)
    assert res[1] == {"rowcount": 3} and res[2] == {"rowcount": 3}
    assert isinstance(res[3], ConstraintError)
    assert res[4] == {"rowcount": 2}
    assert res[5]["rows"] == [[2, "a"]]


def test_insert_evaluates_a_row_before_checking_it():
    e = Engine()
    res = run_sql(e, "CREATE TABLE t (a INTEGER, b TEXT NOT NULL); INSERT INTO t VALUES ('x', 1 / 0);"
                     "SELECT COUNT(*) FROM t;")
    assert isinstance(res[1], SQLRuntimeError) and res[2]["rows"] == [[0]]
