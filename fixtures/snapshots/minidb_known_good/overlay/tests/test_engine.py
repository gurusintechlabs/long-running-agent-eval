from minidb.engine import Engine, run_sql
from minidb.protocol import ConstraintError, SQLNameError, TransactionError


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


def test_transactions_restore_everything():
    e = Engine()
    res = run_sql(e, """
        CREATE TABLE t (a INTEGER);
        INSERT INTO t VALUES (1), (2);
        BEGIN;
        DELETE FROM t WHERE a = 1;
        CREATE INDEX ia ON t (a);
        CREATE TABLE u (b TEXT);
        BEGIN;
        ROLLBACK;
        SELECT * FROM t;
        SELECT * FROM u;
        COMMIT;
    """)
    assert isinstance(res[6], TransactionError)
    assert res[8]["rows"] == [[1], [2]]
    assert isinstance(res[9], SQLNameError) and isinstance(res[10], TransactionError)


def test_views_and_alter_table():
    e = Engine()
    res = run_sql(e, """
        CREATE TABLE t (a INTEGER);
        INSERT INTO t VALUES (1);
        CREATE VIEW v AS SELECT * FROM t;
        ALTER TABLE t ADD COLUMN b TEXT DEFAULT 'x';
        SELECT * FROM v;
        ALTER TABLE t ADD COLUMN c INTEGER NOT NULL;
        DROP TABLE v;
    """)
    assert res[4] == {"columns": ["a", "b"], "rows": [[1, "x"]]}
    assert isinstance(res[5], ConstraintError) and isinstance(res[6], SQLNameError)
