"""The VECTOR SQL type (stage 1) and the linear-time LIKE."""
import json
import time

import pytest

from minidb.engine import Engine, run_sql
from minidb.protocol import SQLRuntimeError, SQLTypeError
from minidb.values import Vector, like, parse_vector, to_wire


def _rows(engine, sql):
    (res,) = run_sql(engine, sql)
    assert isinstance(res, dict), res
    return res["rows"]


def test_vector_columns_literals_and_wire_form():
    e = Engine()
    run_sql(e, "CREATE TABLE t (id INTEGER, v VECTOR(3)); INSERT INTO t VALUES (1, VECTOR '[1, 2.5, -3]');")
    (row,) = _rows(e, "SELECT v, typeof(v) FROM t;")
    assert json.loads(row[0]) == [1.0, 2.5, -3.0] and row[1] == "VECTOR"


@pytest.mark.parametrize("lit", ["[]", "abc", '[1, "a"]', "[true]", "[NaN]", "[[1]]"])
def test_malformed_literals_are_type_errors(lit):
    with pytest.raises(SQLTypeError):
        parse_vector(lit)


def test_dimension_mismatch_and_ordering_are_type_errors():
    e = Engine()
    run_sql(e, "CREATE TABLE t (v VECTOR(2)); INSERT INTO t VALUES (VECTOR '[1, 2]'), (VECTOR '[2, 1]');")
    for sql in ("INSERT INTO t VALUES (VECTOR '[1]');", "SELECT v FROM t ORDER BY v;", "SELECT v < v FROM t;",
                "SELECT v + v FROM t;", "SELECT MIN(v) FROM t;", "CREATE INDEX tv ON t (v);"):
        (res,) = run_sql(e, sql)
        assert isinstance(res, SQLTypeError), sql


def test_distance_functions():
    e = Engine()
    assert _rows(e, "SELECT l2_distance(VECTOR '[0, 0]', VECTOR '[3, 4]'), inner_product(VECTOR '[1, 2]', VECTOR '[3, 4]'),"
                    " cosine_distance(VECTOR '[1, 0]', VECTOR '[0, 2]');") == [[5.0, 11.0, 1.0]]
    (res,) = run_sql(e, "SELECT cosine_distance(VECTOR '[0, 0]', VECTOR '[1, 1]');")
    assert isinstance(res, SQLRuntimeError)
    (res,) = run_sql(e, "SELECT l2_distance(VECTOR '[1]', VECTOR '[1, 2]');")
    assert isinstance(res, SQLTypeError)
    assert _rows(e, "SELECT l2_distance(NULL, VECTOR '[1]');") == [[None]]


def test_order_by_distance_limit():
    e = Engine()
    run_sql(e, "CREATE TABLE p (id INTEGER, v VECTOR(2));")
    run_sql(e, "INSERT INTO p VALUES " + ",".join(f"({i}, VECTOR '[{i}, {-i}]')" for i in range(20)) + ";")
    assert _rows(e, "SELECT id FROM p ORDER BY l2_distance(v, VECTOR '[5, -5]'), id LIMIT 3;") == [[5], [4], [6]]


def test_vectors_are_durable(tmp_path):
    db = str(tmp_path / "x.db")
    run_sql(Engine(db), "CREATE TABLE d (v VECTOR(2)); INSERT INTO d VALUES (VECTOR '[0.5, 1]');")
    assert _rows(Engine(db), "SELECT v FROM d;") == [["[0.5, 1.0]"]]
    assert Engine(db).db.tables["d"].rows[1] == [Vector([0.5, 1.0])]


def test_to_wire():
    assert to_wire(Vector([1, 2.5])) == "[1.0, 2.5]"


def test_like_semantics_and_linear_time():
    assert like("abcabc", "a%c_b%") and like("abc", "a_c") and not like("abc", "a_") and like("", "%")
    assert like("a%b", "a%b") and not like("ab", "a%c") and like("x\ny", "x_y") and like("aXbXc", "%X%X%")
    t0 = time.monotonic()
    assert like("a" * 20_000, "%a" * 30 + "%b") is False
    assert time.monotonic() - t0 < 1.0
