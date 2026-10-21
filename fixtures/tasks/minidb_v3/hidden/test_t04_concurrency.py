"""t04 (stage 0): concurrent requests behave as if each ran alone, as a whole; nothing acknowledged is lost."""
import threading
from concurrent.futures import ThreadPoolExecutor

from _support import server, shared, stage, unique  # noqa: F401


def _parallel(n, fn):
    with ThreadPoolExecutor(n) as ex:
        return list(ex.map(fn, range(n)))


@stage(0)
def test_requests_are_isolated_as_wholes(shared):  # noqa: F811
    t = unique()
    shared.sql(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY, v INTEGER); INSERT INTO {t} VALUES (1, 0);")
    seen, stop = [], threading.Event()

    def writer(i):
        for _ in range(15):
            res = shared.sql(f"UPDATE {t} SET v = v + 1 WHERE id = 1; UPDATE {t} SET v = v - 1 WHERE id = 1;")
            assert all(x["ok"] for x in res), res

    def reader():
        while not stop.is_set():
            res = shared.sql(f"SELECT v FROM {t} WHERE id = 1; SELECT v FROM {t} WHERE id = 1;")
            seen.extend(x["rows"][0][0] for x in res)
    readers = [threading.Thread(target=reader) for _ in range(3)]
    for r in readers:
        r.start()
    try:
        _parallel(6, writer)
    finally:
        stop.set()
        for r in readers:
            r.join(30)
    assert seen and set(seen) == {0}, sorted(set(seen))


@stage(0)
def test_concurrent_transactions_lose_no_update(shared):  # noqa: F811
    t = unique()
    shared.sql(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY, v INTEGER); INSERT INTO {t} VALUES (1, 0);")

    def work(i):
        out = []
        for _ in range(20):
            out.append(shared.sql(f"BEGIN; UPDATE {t} SET v = v + 1 WHERE id = 1; COMMIT;"))
        return out
    results = [res for chunk in _parallel(8, work) for res in chunk]
    assert all(x["ok"] for res in results for x in res), [res for res in results if not all(x["ok"] for x in res)][:3]
    assert shared.sql(f"SELECT v FROM {t};")[0]["rows"] == [[160]]


@stage(0)
def test_concurrent_inserts_survive_a_crash(server):  # noqa: F811
    server.sql("CREATE TABLE ins (w INTEGER, i INTEGER);")

    def work(w):
        for i in range(25):
            assert server.sql(f"INSERT INTO ins VALUES ({w}, {i});")[0] == {"ok": True, "rowcount": 1}
    _parallel(8, work)
    server.restart(crash=True)
    assert server.sql("SELECT COUNT(*), COUNT(DISTINCT w * 100 + i) FROM ins;")[0]["rows"] == [[200, 200]]


@stage(0)
def test_many_simultaneous_connections_are_served(shared):  # noqa: F811
    res = _parallel(48, lambda i: shared.post("/v1/sql", {"sql": f"SELECT {i};"}, timeout=60))
    assert [r.status for r in res] == [200] * 48
    assert [r.json()["results"][0]["rows"] for r in res] == [[[i]] for i in range(48)]


@stage(0)
def test_ddl_and_queries_interleave_safely(shared):  # noqa: F811
    def work(i):
        t = unique(f"w{i}")
        out = shared.sql(f"CREATE TABLE {t} (a INTEGER); INSERT INTO {t} VALUES ({i}); SELECT a FROM {t}; DROP TABLE {t};")
        return [x["ok"] for x in out], out[2]["rows"]
    for i, (oks, rows) in enumerate(_parallel(12, work)):
        assert oks == [True] * 4 and rows == [[i]]
