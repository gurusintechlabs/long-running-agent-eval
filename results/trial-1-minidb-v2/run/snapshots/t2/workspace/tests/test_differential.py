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


# ---------------------------------------------------------------- stage 1 constructs
# Correlated scalar/IN/EXISTS subqueries, CASE, COALESCE, derived tables and set operations.
# Scalar subqueries are always aggregates, so they return exactly one row in both engines.

def _expr1(r, cols, d=0):
    k = r.random()
    if d > 2 or k < 0.35:
        return r.choice(cols + [str(r.randint(-2, 4)), "NULL"])
    if k < 0.5:
        return f"CASE WHEN {_cond1(r, cols, d + 1)} THEN {_expr1(r, cols, d + 1)} " \
               f"ELSE {_expr1(r, cols, d + 1)} END"
    if k < 0.6:
        return f"CASE {_expr1(r, cols, d + 1)} WHEN {r.randint(0, 3)} THEN " \
               f"{_expr1(r, cols, d + 1)} END"
    if k < 0.7:
        agg = r.choice(["MAX", "MIN", "COUNT", "SUM"])
        op = r.choice(["=", "<", ">"])
        return f"(SELECT {agg}(i{d}.x) FROM b AS i{d} WHERE i{d}.y {op} {r.choice(cols)})"
    if k < 0.75:
        return f"COALESCE({_expr1(r, cols, d + 1)}, {_expr1(r, cols, d + 1)})"
    op = r.choice(["+", "-", "*"])
    return f"({_expr1(r, cols, d + 1)} {op} {_expr1(r, cols, d + 1)})"


def _cond1(r, cols, d=0):
    k = r.random()
    if d > 2 or k < 0.45:
        op = r.choice(["=", "<>", "<", ">="])
        return f"{_expr1(r, cols, 3)} {op} {_expr1(r, cols, 3)}"
    if k < 0.55:
        return f"{r.choice(['', 'NOT '])}EXISTS (SELECT 1 FROM b AS e{d} " \
               f"WHERE e{d}.x = {r.choice(cols)})"
    if k < 0.65:
        return f"{r.choice(cols)} {r.choice(['', 'NOT '])}IN (SELECT {r.choice(['y', 'x'])} " \
               f"FROM b AS n{d} WHERE n{d}.x {r.choice(['<', '>', '<>'])} {r.randint(0, 3)})"
    if k < 0.72:
        return f"{r.choice(cols)} IS {r.choice(['', 'NOT '])}NULL"
    if k < 0.8:
        return f"NOT ({_cond1(r, cols, d + 1)})"
    return f"({_cond1(r, cols, d + 1)} {r.choice(['AND', 'OR'])} {_cond1(r, cols, d + 1)})"


def _select1(r):
    if r.random() < 0.2:
        source = "(SELECT x AS p, y AS q FROM a WHERE x IS NOT NULL) AS d"
        cols = ["d.p", "d.q"]
    else:
        source, cols = "a", ["a.x", "a.y"]
    items = [_expr1(r, cols) for _ in range(r.randint(1, 2))]
    where = f" WHERE {_cond1(r, cols)}" if r.random() < 0.6 else ""
    return f"SELECT {', '.join(items)} FROM {source}{where}", len(items)


def _scenario1(seed):
    r = random.Random(seed)
    setup = []
    for t in ("a", "b"):
        setup.append(f"CREATE TABLE {t} (x INTEGER, y INTEGER)")
        rows = [f"({r.choice(['NULL', r.randint(0, 3)])}, {r.choice(['NULL', r.randint(0, 3)])})"
                for _ in range(r.randint(0, 5))]
        if rows:
            setup.append(f"INSERT INTO {t} VALUES {', '.join(rows)}")
    query, width = _select1(r)
    ordered = True
    if r.random() < 0.3:
        other, other_width = _select1(r)
        if other_width == width:
            op = r.choice(["UNION", "UNION ALL", "INTERSECT", "EXCEPT"])
            query = f"{query} {op} {other}"
            ordered = False  # SQLite may sort set operation results
    return setup, query, ordered


@pytest.mark.parametrize("seed", range(300))
def test_stage1_constructs_match_sqlite(seed):
    setup, query, ordered = _scenario1(seed)
    engine, lite = Engine(), sqlite3.connect(":memory:")
    for sql in setup:
        engine.execute(sql)
        lite.execute(sql)
    expected = [list(row) for row in lite.execute(query).fetchall()]
    got = engine.execute(query)["rows"]
    if ordered:
        assert got == expected, query
    else:
        assert _multiset(got) == _multiset(expected), query
