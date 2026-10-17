"""Differential test against sqlite3 on a subset where both engines agree.

Only INTEGER columns and operators whose semantics match (minidb's DIV is registered in SQLite
as a function, % takes the dividend's sign, three-valued logic) are generated. SQLite returns
NULL for division by zero where minidb raises a RuntimeError, so those queries are skipped. SQLite may reorder join
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
    op = r.choice(["+", "-", "*", "DIV", "%"])
    a, b = _expr(r, cols, depth + 1), _expr(r, cols, depth + 1)
    return f"DIV({a}, {b})" if op == "DIV" else f"({a} {op} {b})"


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
        on = _cond(r, cols)
        if r.random() < 0.6:  # an equi-join conjunct: hash join or index probe
            on = f"{r.choice(['a.x', 'a.y'])} = {r.choice(['b.x', 'b.y'])}" + (
                f" AND {on}" if r.random() < 0.5 else "")
        source = f"a {'LEFT ' if kind == 'left' else ''}JOIN b ON {on}"
    else:
        cols = ["x", "y"]
        source = "a"
    where = f" WHERE {_cond(r, cols)}" if r.random() < 0.7 else ""
    if r.random() < 0.4:  # a conjunct an index on the first table can serve
        where = f" WHERE {_index_conjunct(r, cols[:2])}" + (
            f" AND {where[7:]}" if where else "")
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


def _index_conjunct(r, cols):
    col, lo, hi = r.choice(cols), r.randint(-1, 4), r.randint(0, 5)
    return r.choice([f"{col} = {lo}", f"{col} > {lo}", f"{lo} >= {col}",
                     f"{col} BETWEEN {lo} AND {hi}", f"{col} >= {lo} AND {col} < {hi}"])


def _sqlite_div(a, b):
    """minidb's DIV(a, b) (truncating integer division) for SQLite, whose integer / is the
    same; division by zero gives NULL there (minidb raises, and such queries are skipped)."""
    if a is None or b is None or b == 0:
        return None
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def _sqlite():
    lite = sqlite3.connect(":memory:")
    lite.create_function("DIV", 2, _sqlite_div, deterministic=True)
    return lite


def _add_indexes(engine, seed):
    """Indexes on minidb's side only: results must not depend on them (section 12), so
    queries whose WHERE / ON can use them must still match SQLite."""
    r = random.Random(seed + 1_000_000)
    for t in ("a", "b"):
        for col in ("x", "y"):
            if r.random() < 0.5:
                engine.execute(f"CREATE INDEX {t}_{col}_ix ON {t} ({col})")


def _multiset(rows):
    return sorted(rows, key=lambda row: [(v is not None, v or 0) for v in row])


@pytest.mark.parametrize("seed", SEEDS)
def test_matches_sqlite(seed):
    setup, query, ordered = _scenario(seed)
    engine, lite = Engine(), _sqlite()
    for sql in setup:
        engine.execute(sql)
        lite.execute(sql)
    _add_indexes(engine, seed)
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
    if r.random() < 0.4 and source == "a":
        where = f" WHERE {_index_conjunct(r, cols)}" + (f" AND {where[7:]}" if where else "")
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
    engine, lite = Engine(), _sqlite()
    for sql in setup:
        engine.execute(sql)
        lite.execute(sql)
    _add_indexes(engine, seed)
    expected = [list(row) for row in lite.execute(query).fetchall()]
    got = engine.execute(query)["rows"]
    if ordered:
        assert got == expected, query
    else:
        assert _multiset(got) == _multiset(expected), query


# ---------------------------------------------------------------- TEXT and REAL data
# Comparisons (TEXT by code point), ||, REPLACE, LENGTH, REAL arithmetic, joins on TEXT keys
# (with or without indexes), grouping, DISTINCT and ordering agree with SQLite on this subset.

_TEXTS = ["'a'", "'b'", "'ab'", "'B'", "''", "'é'", "'a b'", "'zz'", "NULL"]
_REALS = ["0.5", "1.5", "-2.25", "3.0", "0.1", "NULL", "2.5"]


def _texpr(r, d=0):
    k = r.random()
    if d > 1 or k < 0.4:
        return r.choice(["s", "s", "t2.u", "'x'", "'b'"])
    if k < 0.6:
        return f"({_texpr(r, d + 1)} || {_texpr(r, d + 1)})"
    if k < 0.75:
        return f"REPLACE({_texpr(r, d + 1)}, 'a', 'q')"
    return f"COALESCE({_texpr(r, d + 1)}, 'n')"


def _rexpr(r, d=0):
    k = r.random()
    if d > 1 or k < 0.4:
        return r.choice(["v", "v", "t2.w", "0.5", "2.0", "-1.5"])
    if k < 0.6:
        return f"({_rexpr(r, d + 1)} {r.choice(['+', '-', '*'])} {_rexpr(r, d + 1)})"
    if k < 0.7:
        return f"CAST(LENGTH({_texpr(r, d + 1)}) AS REAL)"
    return f"ABS({_rexpr(r, d + 1)})"


def _cond2(r):
    k = r.random()
    if k < 0.4:
        return f"{_texpr(r)} {r.choice(['=', '<', '>=', '<>'])} {_texpr(r)}"
    if k < 0.75:
        return f"{_rexpr(r)} {r.choice(['=', '<', '>='])} {_rexpr(r)}"
    if k < 0.85:
        return f"s IS {r.choice(['', 'NOT '])}NULL"
    return f"({_cond2(r)} {r.choice(['AND', 'OR'])} {_cond2(r)})"


def _typed_multiset(rows):
    """Order-insensitive, and 'a' / 1 / 1.0 / NULL kept apart (except INTEGER vs REAL)."""
    def cell(x):
        kind = "null" if x is None else "num" if type(x) in (int, float) else type(x).__name__
        return kind, x if x is not None else 0
    return sorted(([cell(x) for x in row] for row in rows), key=repr)


@pytest.mark.parametrize("seed", range(200))
def test_text_and_real_match_sqlite(seed):
    r = random.Random(seed)
    engine, lite = Engine(), _sqlite()
    for sql in ("CREATE TABLE t1 (s TEXT, v REAL)", "CREATE TABLE t2 (u TEXT, w REAL)"):
        engine.execute(sql)
        lite.execute(sql)
    for t in ("t1", "t2"):
        rows = ", ".join(f"({r.choice(_TEXTS)}, {r.choice(_REALS)})"
                         for _ in range(r.randint(0, 7)))
        if rows:
            engine.execute(f"INSERT INTO {t} VALUES {rows}")
            lite.execute(f"INSERT INTO {t} VALUES {rows}")
    for name, table, col in (("t2u", "t2", "u"), ("t1s", "t1", "s")):
        if r.random() < 0.5:
            engine.execute(f"CREATE INDEX {name} ON {table} ({col})")
    source = (f"t1 {r.choice(['JOIN', 'LEFT JOIN'])} t2 ON t2.u = t1.s" if r.random() < 0.5
              else "t1 CROSS JOIN t2")
    where = f" WHERE {_cond2(r)}" if r.random() < 0.7 else ""
    kind = r.random()
    ordered = kind >= 0.8
    if kind < 0.35:
        query = f"SELECT {_texpr(r)}, {_rexpr(r)} FROM {source}{where}"
    elif kind < 0.6:
        query = (f"SELECT s, COUNT(*), MIN({_texpr(r)}), MAX({_rexpr(r)}), "
                 f"COUNT(DISTINCT {_texpr(r)}) FROM {source}{where} GROUP BY s")
    elif kind < 0.8:
        query = f"SELECT DISTINCT {_texpr(r)} FROM {source}{where}"
    else:
        # minidb's default NULL placement, spelled out because SQLite's default differs
        query = (f"SELECT {_texpr(r)}, {_rexpr(r)} FROM {source}{where} "
                 "ORDER BY 1 DESC NULLS FIRST, 2 ASC NULLS LAST")
    expected = [list(row) for row in lite.execute(query).fetchall()]
    try:
        got = engine.execute(query)["rows"]
    except SQLRuntimeError:
        return  # REAL overflow is an error in minidb, inf in SQLite
    assert _typed_multiset(got) == _typed_multiset(expected), query
    if ordered:  # ORDER BY covers both columns, so the order is fully determined
        assert got == expected, query
