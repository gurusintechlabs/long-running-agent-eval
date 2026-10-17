"""Section 13 (stage 2): performance limits on 50,000-row tables (and correctness of the answers).

Every test loads its data through one long-lived process (``Session``); only the statements named
in the brief's table are timed, with the limits of the brief. Pipelined batches are timed from
the first write to the last answer, divided by the number of statements.
"""
from _support import DIGITS, Session, assert_rows, big_table_sql, stage

N = 50_000
INV = pow(7919, -1, N)          # id = (k * INV) % N, since k = (id * 7919) % N


def loaded(session: Session, *extra: str) -> None:
    """DIGITS, ``big`` (50,000 rows) and ``extra`` tables; the bulk INSERT ... SELECTs are timed."""
    session.ok(DIGITS)
    for sql in (big_table_sql("big", 5), *extra):
        for stmt in (x.strip() for x in sql.split(";\n")):
            if stmt.startswith("INSERT"):
                t, r = session.timed(stmt, timeout=60)
                assert r.ok, r
                within(t, 10.0, f"INSERT ... SELECT of {r.rowcount} rows")
            elif stmt:
                assert session.execute(stmt).ok


def per_statement(elapsed: float, n: int, limit_ms: float, what: str) -> None:
    avg_ms = elapsed / n * 1000
    assert avg_ms <= limit_ms, f"{what}: {avg_ms:.2f} ms per statement on average (limit {limit_ms} ms)"


def within(t: float, limit_s: float, what: str) -> None:
    assert t <= limit_s, f"{what} took {t:.2f}s (limit {limit_s}s)"


@stage(2)
def test_bulk_inserts():
    with Session() as s:
        loaded(s)
        stmts = []
        for b in range(5):
            base = N + b * 1000
            vals = ", ".join(f"({base + i}, {(base + i) * 3}, {i % 1000}, 'v{i}', {i}.5)"
                             for i in range(1000))
            stmts.append(f"INSERT INTO big VALUES {vals}")
        for st in stmts:
            t, r = s.timed(st)
            assert r.ok and r.rowcount == 1000, r
            within(t, 0.5, "INSERT ... VALUES with 1,000 rows")
        assert_rows(s.execute("SELECT COUNT(*), MAX(id), SUM(k) FROM big WHERE id >= 50000"),
                    [[5000, 54999, sum((N + i) * 3 for i in range(5000))]])


@stage(2)
def test_point_queries_on_secondary_and_primary_key_indexes():
    with Session() as s:
        loaded(s)
        keys = [(i * 7717 + 13) % N for i in range(1000)]
        t, res = s.pipeline([f"SELECT id, tag FROM big WHERE k = {k}" for k in keys])
        per_statement(t, len(keys), 5, "point query on an explicit index")
        for k, r in zip(keys, res):
            i = (k * INV) % N
            assert_rows(r, [[i, f"t{i % 97}"]])
        t, res = s.pipeline([f"SELECT k FROM big WHERE id = {k}" for k in keys])
        per_statement(t, len(keys), 5, "point query on the primary key")
        for k, r in zip(keys, res):
            assert_rows(r, [[(k * 7919) % N]])


@stage(2)
def test_range_queries():
    with Session() as s:
        loaded(s)
        starts = [(i * 997) % (N - 100) for i in range(200)]
        t, res = s.pipeline([f"SELECT COUNT(*), MIN(k), MAX(k) FROM big WHERE k BETWEEN {a} AND {a + 99}"
                             for a in starts])
        per_statement(t, len(starts), 10, "range query returning 100 rows")
        for a, r in zip(starts, res):
            assert_rows(r, [[100, a, a + 99]])
        t, res = s.pipeline([f"SELECT id FROM big WHERE id >= {a} AND id < {a + 50}" for a in starts])
        per_statement(t, len(starts), 10, "range query on the primary key")
        assert res[7].rows == [[x] for x in range(starts[7], starts[7] + 50)]


@stage(2)
def test_single_row_insert_update_delete():
    with Session() as s:
        loaded(s)
        ins = [f"INSERT INTO big VALUES ({N + i}, {N + i}, 7, 'new', 1.5)" for i in range(1000)]
        t, res = s.pipeline(ins)
        assert all(r.ok and r.rowcount == 1 for r in res), [r for r in res if not r.ok][:3]
        per_statement(t, len(ins), 2, "single-row INSERT")
        upd = [f"UPDATE big SET tag = 'upd', k = k + {N * 2} WHERE id = {(i * 37) % N}" for i in range(500)]
        t, res = s.pipeline(upd)
        assert all(r.ok and r.rowcount == 1 for r in res), [r for r in res if not r.ok][:3]
        per_statement(t, len(upd), 2, "single-row UPDATE by primary key")
        dele = [f"DELETE FROM big WHERE id = {(i * 41 + 5) % N}" for i in range(500)]
        t, res = s.pipeline(dele)
        assert all(r.ok and r.rowcount == 1 for r in res), [r for r in res if not r.ok][:3]
        per_statement(t, len(dele), 2, "single-row DELETE by primary key")
        updated = {(i * 37) % N for i in range(500)}
        deleted = {(i * 41 + 5) % N for i in range(500)}
        assert_rows(s.execute("SELECT COUNT(*) FROM big"), [[N + 1000 - 500]])
        assert_rows(s.execute("SELECT COUNT(*) FROM big WHERE tag = 'upd'"), [[len(updated - deleted)]])
        assert_rows(s.execute(f"SELECT COUNT(*) FROM big WHERE k >= {N * 2}"), [[len(updated - deleted)]])
        probe = sorted(updated - deleted)[3]
        assert_rows(s.execute(f"SELECT id FROM big WHERE k = {(probe * 7919) % N + N * 2}"), [[probe]])


@stage(2)
def test_equi_joins_with_and_without_indexes():
    with Session() as s:
        loaded(s, big_table_sql("small", 2, indexes=False))
        t, r = s.timed("SELECT COUNT(*), SUM(s.id) FROM big b JOIN small s ON s.k = b.k", timeout=60)
        within(t, 3.0, "hash join of 50,000 x 20,000 rows")
        assert_rows(r, [[20000, sum(range(20000))]])
        t, r = s.timed("SELECT b.grp, COUNT(s.id), MAX(b.k) FROM big b LEFT JOIN small s ON s.k = b.id "
                       "WHERE b.grp < 3 GROUP BY b.grp", timeout=60)
        within(t, 3.0, "left hash join with grouping")
        grp_rows = {g: list(range(g, N, 1000)) for g in range(3)}
        expect = [[g, sum(1 for i in ids if i < 20000), max((i * 7919) % N for i in ids)]
                  for g, ids in grp_rows.items()]
        assert_rows(r, expect)
        t, r = s.timed("SELECT COUNT(*), MIN(b.id) FROM small s JOIN big b ON b.k = s.k WHERE s.grp = 5",
                       timeout=60)
        within(t, 3.0, "index nested-loop join")
        ids = [(k * INV) % N for k in ((i * 7919) % 20000 for i in range(5, 20000, 1000))]
        assert_rows(r, [[20, min(ids)]])


@stage(2)
def test_in_and_not_in_with_large_uncorrelated_subqueries():
    with Session() as s:
        loaded(s, big_table_sql("small", 2, indexes=False))
        t, r = s.timed("SELECT COUNT(*) FROM big WHERE k IN (SELECT k FROM small)", timeout=60)
        within(t, 2.0, "IN (SELECT ...) over 50,000 x 20,000 rows")
        assert_rows(r, [[20000]])
        t, r = s.timed("SELECT COUNT(*) FROM big WHERE grp NOT IN (SELECT k FROM small WHERE k >= 500)",
                       timeout=60)
        within(t, 2.0, "NOT IN (SELECT ...)")
        assert_rows(r, [[25000]])
        s.ok("INSERT INTO small (id, k) VALUES (99999, NULL)")
        t, r = s.timed("SELECT COUNT(*) FROM big WHERE grp NOT IN (SELECT k FROM small WHERE k >= 500 OR k IS NULL)",
                       timeout=60)
        within(t, 2.0, "NOT IN (SELECT ...) with a NULL")
        assert_rows(r, [[0]])


@stage(2)
def test_sorting_grouping_and_scanning_50000_rows():
    with Session() as s:
        loaded(s)
        t, r = s.timed("SELECT id, tag FROM big ORDER BY tag DESC, k LIMIT 3", timeout=60)
        within(t, 2.0, "ORDER BY over 50,000 rows")
        top = max(f"t{x}" for x in range(97))  # code point order: 't96' is the largest tag
        top_ids = sorted((i for i in range(N) if f"t{i % 97}" == top), key=lambda i: (i * 7919) % N)
        assert_rows(r, [[i, top] for i in top_ids[:3]])
        t, r = s.timed("SELECT k FROM big ORDER BY val, id DESC LIMIT 3 OFFSET 10", timeout=60)
        within(t, 2.0, "ORDER BY over 50,000 rows")
        zero_val = sorted((i for i in range(N) if i % 1000 == 0), reverse=True)
        assert_rows(r, [[(i * 7919) % N] for i in zero_val[10:13]])
        t, r = s.timed("SELECT grp, COUNT(*), SUM(k), AVG(val), MIN(tag), MAX(id) FROM big GROUP BY grp "
                       "ORDER BY grp DESC LIMIT 2", timeout=60)
        within(t, 2.0, "GROUP BY over 50,000 rows")
        expect = []
        for g in (999, 998):
            ids = list(range(g, N, 1000))
            expect.append([g, 50, sum((i * 7919) % N for i in ids), g * 0.5,
                           min(f"t{i % 97}" for i in ids), max(ids)])
        assert_rows(r, expect)
        t, r = s.timed("SELECT COUNT(*) FROM big WHERE val > 100.0 AND tag LIKE 't1%'", timeout=60)
        within(t, 1.0, "full scan with a WHERE condition")
        assert_rows(r, [[sum(1 for i in range(N) if (i % 1000) * 0.5 > 100.0
                             and str(i % 97).startswith("1"))]])
