"""t06 (stage 1): the VECTOR SQL type, its literals and distance functions (brief 1.1)."""
import json
import math

import numpy as np

from _support import cli_results, server, shared, stage, unique  # noqa: F401


def _one(srv, sql):
    (res,) = srv.sql(sql)
    return res


def _vec(text):
    return json.loads(text)


@stage(1)
def test_vectors_round_trip_as_json_array_text(shared):  # noqa: F811
    t = unique()
    shared.sql(f"CREATE TABLE {t} (id INTEGER, v VECTOR(3));"
               f"INSERT INTO {t} VALUES (1, VECTOR '[1, 2.5, -3]'), (2, NULL);")
    res = _one(shared, f"SELECT v, typeof(v) FROM {t} ORDER BY id;")
    assert res["ok"] and res["rows"][1] == [None, "NULL"]
    text, typ = res["rows"][0]
    assert isinstance(text, str) and _vec(text) == [1.0, 2.5, -3.0] and typ == "VECTOR"


@stage(1)
def test_storing_a_vector_of_another_length_is_a_type_error(shared):  # noqa: F811
    t = unique()
    shared.sql(f"CREATE TABLE {t} (v VECTOR(3));")
    for lit in ("VECTOR '[1, 2]'", "VECTOR '[1, 2, 3, 4]'"):
        res = _one(shared, f"INSERT INTO {t} VALUES ({lit});")
        assert res["ok"] is False and res["error"]["type"] == "TypeError", res
    assert _one(shared, f"SELECT COUNT(*) FROM {t};")["rows"] == [[0]]


@stage(1)
def test_malformed_literals_are_type_errors(shared):  # noqa: F811
    for lit in ("VECTOR '[]'", "VECTOR 'abc'", "VECTOR '[1, \"a\"]'", "VECTOR '{\"a\": 1}'", "VECTOR '[1, [2]]'"):
        res = _one(shared, f"SELECT {lit};")
        assert res["ok"] is False and res["error"]["type"] == "TypeError", (lit, res)


@stage(1)
def test_distance_functions_are_exact(shared):  # noqa: F811
    rng = np.random.default_rng(7)
    a, b = rng.normal(size=16).round(4), rng.normal(size=16).round(4)
    la, lb = json.dumps(a.tolist()), json.dumps(b.tolist())
    res = _one(shared, f"SELECT l2_distance(VECTOR '{la}', VECTOR '{lb}'), cosine_distance(VECTOR '{la}', VECTOR '{lb}'),"
                       f" inner_product(VECTOR '{la}', VECTOR '{lb}');")
    l2, cos, ip = res["rows"][0]
    assert math.isclose(l2, float(np.linalg.norm(a - b)), rel_tol=1e-9)
    assert math.isclose(cos, 1 - float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b))), rel_tol=1e-9, abs_tol=1e-12)
    assert math.isclose(ip, float(a @ b), rel_tol=1e-9, abs_tol=1e-12)
    assert all(isinstance(x, float) for x in (l2, cos, ip))


@stage(1)
def test_distance_function_errors_and_nulls(shared):  # noqa: F811
    cases = {"SELECT l2_distance(VECTOR '[1, 2]', VECTOR '[1, 2, 3]');": "TypeError",
             "SELECT inner_product(VECTOR '[1, 2]', '[1, 2]');": "TypeError",
             "SELECT cosine_distance(VECTOR '[1, 2]', 3);": "TypeError",
             "SELECT cosine_distance(VECTOR '[0, 0]', VECTOR '[1, 2]');": "RuntimeError"}
    for sql, typ in cases.items():
        res = _one(shared, sql)
        assert res["ok"] is False and res["error"]["type"] == typ, (sql, res)
    res = _one(shared, "SELECT l2_distance(NULL, VECTOR '[1]'), inner_product(VECTOR '[1]', NULL);")
    assert res["rows"] == [[None, None]]


@stage(1)
def test_vectors_compare_only_for_equality(shared):  # noqa: F811
    t = unique()
    shared.sql(f"CREATE TABLE {t} (id INTEGER, v VECTOR(2));"
               f"INSERT INTO {t} VALUES (1, VECTOR '[1, 2]'), (2, VECTOR '[1.0, 2.0]'), (3, VECTOR '[2, 1]'), (4, NULL);")
    assert _one(shared, f"SELECT id FROM {t} WHERE v = VECTOR '[1, 2]' ORDER BY id;")["rows"] == [[1], [2]]
    assert _one(shared, f"SELECT id FROM {t} WHERE v <> VECTOR '[1, 2]' ORDER BY id;")["rows"] == [[3]]
    assert _one(shared, f"SELECT id FROM {t} WHERE v IS NULL;")["rows"] == [[4]]
    for sql in (f"SELECT id FROM {t} WHERE v < VECTOR '[1, 3]';", f"SELECT v + v FROM {t};",
                f"SELECT id FROM {t} ORDER BY v;", f"SELECT MAX(v) FROM {t};", f"SELECT -v FROM {t};"):
        res = _one(shared, sql)
        assert res["ok"] is False and res["error"]["type"] == "TypeError", (sql, res)


@stage(1)
def test_order_by_distance_limit_is_exact(shared):  # noqa: F811
    rng = np.random.default_rng(11)
    data = rng.integers(-50, 50, size=(300, 8))
    t = unique()
    rows = ",".join(f"({i}, VECTOR '{json.dumps(v.tolist())}')" for i, v in enumerate(data))
    shared.sql(f"CREATE TABLE {t} (id INTEGER, v VECTOR(8)); INSERT INTO {t} VALUES {rows};")
    q = rng.integers(-50, 50, size=8)
    res = _one(shared, f"SELECT id, l2_distance(v, VECTOR '{json.dumps(q.tolist())}') AS d FROM {t} "
                       f"ORDER BY d, id LIMIT 7;")
    d = np.sqrt(((data - q) ** 2).sum(1))
    want = sorted(range(300), key=lambda i: (d[i], i))[:7]
    assert [r[0] for r in res["rows"]] == want
    assert all(math.isclose(r[1], d[i], rel_tol=1e-12) for r, i in zip(res["rows"], want, strict=True))


@stage(1)
def test_vector_columns_are_durable(server):  # noqa: F811
    server.sql("CREATE TABLE dv (id INTEGER, v VECTOR(4)); INSERT INTO dv VALUES (1, VECTOR '[0.5, -1, 2, 3.25]');")
    server.restart(crash=True)
    (row,) = _one(server, "SELECT v FROM dv;")["rows"]
    assert _vec(row[0]) == [0.5, -1.0, 2.0, 3.25]
    assert _one(server, "SELECT l2_distance(v, VECTOR '[0.5, -1, 2, 3.25]') FROM dv;")["rows"] == [[0.0]]


@stage(1)
def test_vectors_work_on_the_stdin_protocol_with_db(tmp_path):
    db = tmp_path / "v.db"
    cli_results("CREATE TABLE cv (v VECTOR(2)); INSERT INTO cv VALUES (VECTOR '[3, 4]');", db=db)
    res = cli_results("SELECT v, l2_distance(v, VECTOR '[0, 0]') FROM cv;", db=db)
    assert res[0]["ok"] and _vec(res[0]["rows"][0][0]) == [3.0, 4.0] and res[0]["rows"][0][1] == 5.0


@stage(1)
def test_vector_dimension_bounds(shared):  # noqa: F811
    for n, ok in ((0, False), (1, True), (4096, True), (4097, False)):
        res = _one(shared, f"CREATE TABLE {unique()} (v VECTOR({n}));")
        assert res["ok"] is ok, (n, res)
