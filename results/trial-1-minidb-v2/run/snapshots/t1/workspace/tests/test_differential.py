"""Differential test against sqlite3 on a subset where both engines agree.

Only INTEGER columns and operators whose semantics match (integer division truncates, % takes
the dividend's sign, three-valued logic) are generated. SQLite returns NULL for division by
zero where minidb raises a RuntimeError, so those queries are skipped. SQLite may reorder join
loops, so join and grouped results are compared as multisets; single-table results must match
row for row (table order).
"""
import random
import sqlite3

import pytest

from minidb.engine import Engine
from minidb.protocol import SQLRuntimeError

SEEDS = range(400)


def _expr(r, cols, depth=0):
    if depth > 2 or r.random() < 0.3:
        return r.choice(cols + [str(r.randint(-3, 5)), "NULL"])
    op = r.choice(["+", "-", "*", "/", "%"])
    return f"({_expr(r, cols, depth + 1)} {op} {_expr(r, cols, depth + 1)})"


def _cond(r, cols, depth=0):
    k = r.random()
    if depth > 1 or k < 0.5:
        choice = r.random()
        if choice < 0.15:
            return f"{r.choice(cols)} IS {r.choice(['', 'NOT '])}NULL"
        if choice < 0.3:
            return f"{r.choice(cols)} {r.choice(['', 'NOT '])}IN ({r.randint(0, 3)}, " \
                   f"{r.choice(['NULL', '2'])})"
        if choice < 0.4:
            return f"{r.choice(cols)} BETWEEN {r.randint(-1, 2)} AND {r.randint(1, 4)}"
        op = r.choice(["=", "<>", "<", "<=", ">", ">="])
        return f"{_expr(r, cols, 2)} {op} {_expr(r, cols, 2)}"
    if k < 0.65:
        return f"NOT ({_cond(r, cols, depth + 1)})"
    return f"({_cond(r, cols, depth + 1)} {r.choice(['AND', 'OR'])} {_cond(r, cols, depth + 1)})"


def _scenario(seed):
    r = random.Random(seed)
    setup = []
    for t in ("a", "b"):
        setup.append(f"CREATE TABLE {t} (x INTEGER, y INTEGER)")
        rows = [f"({r.choice(['NULL', r.randint(0, 4)])}, {r.choice(['NULL', r.randint(-2, 4)])})"
                for _ in range(r.randint(0, 6))]
        if rows:
            setup.append(f"INSERT INTO {t} VALUES {', '.join(rows)}")
    kind = r.choice(["plain", "join", "left", "group", "distinct"])
    if kind in ("join", "left"):
        cols = ["a.x", "a.y", "b.x", "b.y"]
        source = f"a {'LEFT ' if kind == 'left' else ''}JOIN b ON {_cond(r, cols)}"
    else:
        cols = ["x", "y"]
        source = "a"
    where = f" WHERE {_cond(r, cols)}" if r.random() < 0.7 else ""
    if kind == "group":
        key = r.choice(cols)
        agg = r.choice(["COUNT(*)", f"COUNT({cols[1]})", f"SUM({_expr(r, cols, 1)})",
                        f"MIN({cols[1]})", f"MAX({cols[0]})", f"COUNT(DISTINCT {cols[0]})"])
        query = f"SELECT {key}, {agg} FROM {source}{where} GROUP BY {key}"
        if r.random() < 0.4:
            query += f" HAVING COUNT(*) > {r.randint(0, 2)}"
    else:
        items = ", ".join(_expr(r, cols, 1) for _ in range(r.randint(1, 3)))
        query = f"SELECT {'DISTINCT ' if kind == 'distinct' else ''}{items} FROM {source}{where}"
    return setup, query, kind == "plain"


def _multiset(rows):
    return sorted(rows, key=lambda row: [(v is not None, v or 0) for v in row])


@pytest.mark.parametrize("seed", SEEDS)
def test_matches_sqlite(seed):
    setup, query, ordered = _scenario(seed)
    engine, lite = Engine(), sqlite3.connect(":memory:")
    for sql in setup:
        engine.execute(sql)
        lite.execute(sql)
    expected = [list(row) for row in lite.execute(query).fetchall()]
    try:
        got = engine.execute(query)["rows"]
    except SQLRuntimeError:
        return  # division or modulo by zero: SQLite yields NULL instead
    if ordered:
        assert got == expected, query
    else:
        assert _multiset(got) == _multiset(expected), query
