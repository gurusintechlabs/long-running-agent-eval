"""Performance benchmark (sections 13, 15 and 16), measured as a client sees it.

Drives ``python -m minidb`` over stdin/stdout: each statement's time runs from writing it to
reading its JSON line (process startup excluded). Prints each operation with its limit.

    python benchmarks/bench.py              # in memory
    python benchmarks/bench.py --db DIR     # with a database file in DIR (section 16 limits)
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]


class Client:
    def __init__(self, db_path: Optional[str] = None) -> None:
        args = [] if db_path is None else ["--db", db_path]
        self.proc = subprocess.Popen([sys.executable, "-m", "minidb", *args], cwd=ROOT,
                                     text=True, encoding="utf-8", stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE)

    def run(self, sql: str) -> tuple[dict, float]:
        start = time.perf_counter()
        self.proc.stdin.write(sql + ";\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        elapsed = time.perf_counter() - start
        res = json.loads(line)
        if not res["ok"]:
            raise RuntimeError(f"{sql[:80]}: {res['error']}")
        return res, elapsed

    def close(self) -> None:
        self.proc.stdin.close()
        self.proc.wait()


def _open_worst_case(path: str) -> float:
    """A 50,000-row table built by single-row INSERTs, then single-row UPDATEs until the log
    is about to be checkpointed (the most log records to replay); returns the time from
    process start until the first statement is answered."""
    sys.path.insert(0, str(ROOT))
    from minidb.engine import Engine
    engine = Engine(path)
    engine.execute("CREATE TABLE t (id INT PRIMARY KEY, name TEXT, v INT)")
    engine.execute("CREATE INDEX t_v ON t (v)")
    for i in range(50000):
        engine.execute(f"INSERT INTO t VALUES ({i}, 'name {i}', {i % 100})")
    store = engine.storage
    i = 0
    while store.log_bytes < max(1 << 20, store.snapshot_bytes) - 300:
        engine.execute(f"UPDATE t SET v = v + 1 WHERE id = {i % 50000}")
        i += 1
    engine.close()
    start = time.perf_counter()
    client = Client(path)
    client.run("SELECT COUNT(*) FROM t")
    elapsed = time.perf_counter() - start
    client.close()
    return elapsed


def average(client: Client, statements: list[str]) -> float:
    return sum(client.run(s)[1] for s in statements) / len(statements)


def main(db_dir: Optional[str] = None) -> int:
    """Run every benchmark; with ``db_dir``, against a database file in that directory."""
    r = random.Random(1)
    db_path = None if db_dir is None else str(Path(db_dir) / "bench.db")
    c = Client(db_path)
    results: list[tuple[str, float, float]] = []

    def record(name: str, seconds: float, limit: float) -> None:
        results.append((name, seconds, limit))
        flag = "ok " if seconds <= limit else "SLOW"
        print(f"{flag} {seconds * 1000:9.2f} ms  (limit {limit * 1000:7.0f} ms)  {name}",
              flush=True)

    c.run("CREATE TABLE big (id INT PRIMARY KEY, grp INT, val INT, name TEXT, score REAL)")
    c.run("CREATE INDEX big_grp ON big (grp)")
    c.run("CREATE INDEX big_val ON big (val)")
    c.run("CREATE TABLE s1 (a INT)")
    c.run("CREATE TABLE s2 (b INT)")
    c.run("INSERT INTO s1 VALUES " + ", ".join(f"({i})" for i in range(250)))
    c.run("INSERT INTO s2 VALUES " + ", ".join(f"({i})" for i in range(200)))
    _, t = c.run("INSERT INTO big SELECT a * 200 + b, (a * 200 + b) % 1000, "
                 "(a * 200 + b) * 7 % 50000, 'n' || CAST(b AS TEXT), (a + b) * 0.5 "
                 "FROM s1 CROSS JOIN s2")
    record("INSERT ... SELECT 50,000 rows (cross join) into indexed table", t, 10)

    stmts = []
    for k in range(5):
        base = 100000 + k * 1000
        stmts.append("INSERT INTO big VALUES " + ", ".join(
            f"({base + i}, {i % 1000}, {r.randint(0, 50000)}, 'x{i}', {i * 0.25})"
            for i in range(1000)))
    record("INSERT ... VALUES 1,000 rows into 50,000-row indexed table", average(c, stmts), 0.5)
    c.run("DELETE FROM big WHERE id >= 100000")

    record("point query on PRIMARY KEY", average(
        c, [f"SELECT * FROM big WHERE id = {r.randint(0, 49999)}" for _ in range(300)]), 0.005)
    record("point query on explicit index", average(
        c, [f"SELECT id, name FROM big WHERE val = {r.randint(0, 49999)}" for _ in range(300)]),
        0.005)
    stmts = []
    for _ in range(150):
        lo = r.randint(0, 49900)
        stmts.append(f"SELECT * FROM big WHERE id BETWEEN {lo} AND {lo + 99}")
        lo = r.randint(0, 49900)
        stmts.append(f"SELECT id FROM big WHERE val >= {lo} AND val < {lo + 100}")
    record("range query returning <= 100 rows", average(c, stmts), 0.010)

    stmts = []
    for i in range(300):
        stmts.append(f"INSERT INTO big VALUES ({200000 + i}, {i % 1000}, {i}, 'y', 1.5)")
        stmts.append(f"UPDATE big SET score = score + 1 WHERE id = {r.randint(0, 49999)}")
        stmts.append(f"DELETE FROM big WHERE id = {200000 + i}")
    record("single-row INSERT / UPDATE / DELETE by primary key", average(c, stmts),
           0.002 if db_path is None else 0.005)

    stmts = []
    for k in range(100):  # section 15: small transactions on the 50,000-row table
        stmts.append("BEGIN")
        for j in range(3):
            stmts.append(f"UPDATE big SET score = score + 1 WHERE id = {r.randint(0, 49999)}")
            stmts.append(f"INSERT INTO big VALUES ({300000 + k * 10 + j}, 1, 2, 'z', 0.5)")
            stmts.append(f"DELETE FROM big WHERE id = {300000 + k * 10 + j}")
        stmts.append("COMMIT" if k % 2 else "ROLLBACK")
    record("transaction statements incl. BEGIN / COMMIT / ROLLBACK (average)",
           average(c, stmts), 0.005)

    c.run("CREATE TABLE mid (mid INT PRIMARY KEY, ref INT, w INT)")
    c.run("INSERT INTO mid SELECT a * 100 + b, (a * 100 + b) * 3 % 50000, b FROM s1 CROSS JOIN "
          "s2 WHERE b < 100 AND a < 200")
    _, t = c.run("SELECT big.grp, COUNT(*), SUM(mid.w) FROM big JOIN mid ON mid.ref = big.id "
                 "GROUP BY big.grp ORDER BY 2 DESC LIMIT 5")
    record("inner equi-join 50,000 x 20,000 with grouping", t, 3)
    _, t = c.run("SELECT COUNT(*), COUNT(mid.mid), AVG(mid.w) FROM big LEFT JOIN mid "
                 "ON big.val = mid.ref")
    record("left equi-join 50,000 x 20,000 with aggregation", t, 3)
    _, t = c.run("SELECT COUNT(*) FROM big WHERE id IN (SELECT ref FROM mid)")
    record("IN (SELECT ...) 50,000 outer x 20,000 subquery rows", t, 2)
    _, t = c.run("SELECT COUNT(*) FROM big WHERE val NOT IN (SELECT ref FROM mid)")
    record("NOT IN (SELECT ...) 50,000 outer x 20,000 subquery rows", t, 2)
    _, t = c.run("SELECT id, name, score FROM big ORDER BY score DESC, name")
    record("ORDER BY two keys over 50,000 rows", t, 2)
    _, t = c.run("SELECT id FROM big ORDER BY name LIMIT 10")
    record("ORDER BY one key with LIMIT over 50,000 rows", t, 2)
    _, t = c.run("SELECT grp, COUNT(*), SUM(val), AVG(score), MIN(name), MAX(id) FROM big "
                 "GROUP BY grp")
    record("GROUP BY 50,000 rows into 1,000 groups", t, 2)
    _, t = c.run("SELECT id, name FROM big WHERE score > 100.0 AND name LIKE 'n1%' "
                 "OR val % 13 = 0")
    record("full scan with WHERE over 50,000 rows", t, 1)
    if db_path is not None:
        rows = ", ".join(f"({400000 + i}, {i % 1000}, {i}, 'c', 0.5)" for i in range(1000))
        c.run("BEGIN")
        c.run(f"INSERT INTO big VALUES {rows}")
        c.run("UPDATE big SET score = 2.5 WHERE id >= 400000")
        _, t = c.run("COMMIT")
        record("COMMIT of a transaction that changed 1,000 rows", t, 0.2)
    c.close()
    if db_path is not None:
        start = time.perf_counter()
        reopened = Client(db_path)
        res, _ = reopened.run("SELECT COUNT(*) FROM big")
        record(f"open the database ({res['rows'][0][0]} rows) and answer a statement",
               time.perf_counter() - start, 2)
        reopened.close()
    if db_dir is not None:
        record("open a database whose log is full of single-row statements",
               _open_worst_case(str(Path(db_dir) / "worst.db")), 2)
    slow = [name for name, t, limit in results if t > limit]
    print(f"\n{len(results) - len(slow)}/{len(results)} within limits")
    return 1 if slow else 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", metavar="DIR", help="run with a database file in DIR")
    raise SystemExit(main(parser.parse_args().db))
