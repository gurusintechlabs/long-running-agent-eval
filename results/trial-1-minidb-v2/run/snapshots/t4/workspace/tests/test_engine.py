"""Engine-level behaviour: robustness and the full stack through ``python -m minidb``."""
from minidb.engine import Engine
from tests.test_cli import run


def test_deep_nesting_is_an_error_not_a_crash(db):
    assert db.one("SELECT " + "+".join(["1"] * 1000)) == 1000
    assert db.one("SELECT " + "(" * 500 + "1" + ")" * 500) == 1
    assert db.error("SELECT " + "(" * 100000 + "1" + ")" * 100000) == "SyntaxError"
    assert db.error("SELECT " + "+".join(["1"] * 100000)) in ("SyntaxError", "RuntimeError")


def test_engines_are_independent():
    a, b = Engine(), Engine()
    a.execute("CREATE TABLE t (x INT)")
    b.execute("CREATE TABLE t (x TEXT)")
    a.execute("INSERT INTO t VALUES (1)")
    assert b.execute("SELECT * FROM t") == {"columns": ["x"], "rows": []}


def test_end_to_end_session():
    res = run("CREATE TABLE t (id INT PRIMARY KEY, r REAL, s TEXT);\n"
              "INSERT INTO t VALUES (1, 3, 'a;b'), (2, 0.5, 'it''s');\n"
              "SELECT id, r, s, r > 1 FROM t ORDER BY id DESC; -- comment\n"
              "INSERT INTO t VALUES (1, 1, 'dup');\n"
              "UPDATE t SET r = r * 2;\n"
              "SELECT SUM(r), COUNT(*) FROM t\n")
    assert res == [
        {"ok": True},
        {"ok": True, "rowcount": 2},
        {"ok": True, "columns": ["id", "r", "s", "?column?"],
         "rows": [[2, 0.5, "it's", False], [1, 3.0, "a;b", True]]},
        {"ok": False, "error": res[3]["error"]},
        {"ok": True, "rowcount": 2},
        {"ok": True, "columns": ["sum", "count"], "rows": [[7.0, 2]]},
    ]
    assert res[3]["error"]["type"] == "ConstraintError"


def test_deep_nesting_does_not_kill_the_process():
    """Through a real process: a stack overflow would crash the interpreter, not just fail."""
    deep_subquery = "SELECT " + "(SELECT " * 20000 + "1" + ")" * 20000
    deep_parens = "SELECT " + "(" * 30000 + "1" + ")" * 30000
    long_chain = "SELECT " + " + ".join(["1"] * 30000)
    res = run(";\n".join([deep_subquery, deep_parens, long_chain, "SELECT 'still alive'"]))
    assert [r["ok"] for r in res] == [False, False, False, True]
    assert {r["error"]["type"] for r in res[:3]} <= {"SyntaxError", "RuntimeError"}
    assert res[3]["rows"] == [["still alive"]]
