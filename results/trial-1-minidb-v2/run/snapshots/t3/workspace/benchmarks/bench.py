"""Section 13 performance benchmark, measured as a client sees it.

Drives ``python -m minidb`` over stdin/stdout: each statement's time runs from writing it to
reading its JSON line (process startup excluded). Prints each operation with its limit.

    python benchmarks/bench.py
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Client:
    def __init__(self) -> None:
        self.proc = subprocess.Popen([sys.executable, "-m", "minidb"], cwd=ROOT, text=True,
                                     encoding="utf-8", stdin=subprocess.PIPE,
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


def average(client: Client, statements: list[str]) -> float:
    return sum(client.run(s)[1] for s in statements) / len(statements)


def main() -> int:
    r = random.Random(1)
    c = Client()
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
    record("single-row INSERT / UPDATE / DELETE by primary key", average(c, stmts), 0.002)

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
    c.close()
    slow = [name for name, t, limit in results if t > limit]
    print(f"\n{len(results) - len(slow)}/{len(results)} within limits")
    return 1 if slow else 0


if __name__ == "__main__":
    raise SystemExit(main())
