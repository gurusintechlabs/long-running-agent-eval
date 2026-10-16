"""Access paths: which rows of a table to read (index SEARCH or SCAN) and how to join (index
nested loop, hash join or nested loop), following the plan rules of section 12.

The plan of the first table reference is chosen from one conjunct (the label of EXPLAIN), but
execution narrows the index range with every usable conjunct on the same column. Results never
depend on the plan: index lookups return row ids in table order, and every candidate row is still
checked against the whole condition.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from minidb import nodes as n
from minidb.protocol import SQLNameError, SQLTypeError
from minidb.storage import Database, Index
from minidb.values import family, is_number

_FLIP = {"<": ">", "<=": ">=", ">": "<", ">=": "<=", "=": "="}
COLUMN_FAMILY = {"INTEGER": "num", "REAL": "num", "TEXT": "text", "BOOLEAN": "bool", "DATE": "date"}


def flatten_and(e: Any) -> list:
    if isinstance(e, n.Binary) and e.op == "AND":
        return flatten_and(e.left) + flatten_and(e.right)
    return [e]


def literal_value(e: Any) -> tuple[bool, Any]:
    """(True, value) for a non-NULL literal; numbers may carry one leading sign."""
    if isinstance(e, n.Literal) and e.value is not None:
        return True, e.value
    if (isinstance(e, n.Unary) and e.op in ("-", "+") and isinstance(e.operand, n.Literal)
            and is_number(e.operand.value)):
        return True, -e.operand.value if e.op == "-" else e.operand.value
    return False, None


def usable_conjunct(c: Any, col_of: Callable[[Any], str | None]):
    """``(column, op, values)`` if ``c`` is usable for an index on the column ``col_of`` finds."""
    if isinstance(c, n.Binary) and c.op in _FLIP:
        col = col_of(c.left)
        ok, v = literal_value(c.right)
        if col is not None and ok:
            return col, c.op, (v,)
        col = col_of(c.right)
        ok, v = literal_value(c.left)
        if col is not None and ok:
            return col, _FLIP[c.op], (v,)
    if isinstance(c, n.Between) and not c.negated:
        col = col_of(c.operand)
        ok1, lo = literal_value(c.low)
        ok2, hi = literal_value(c.high)
        if col is not None and ok1 and ok2:
            return col, "between", (lo, hi)
    return None


@dataclass
class AccessPlan:
    """SEARCH through ``index`` on ``column``; ``conjuncts`` are all usable ones on it."""
    index: Index
    column: str
    col_type: str
    equality: bool
    chosen: tuple
    conjuncts: list

    @property
    def label(self) -> str:
        return f"({self.column} = ?)" if self.equality else f"({self.column} RANGE)"

    def rowids(self) -> list[int] | None:
        """Candidate row ids in table order, or None if the chosen literal cannot be compared with
        the column (then the caller scans, which raises the TypeError a scan would)."""
        fam = COLUMN_FAMILY[self.col_type]
        if any(family(v) != fam for v in self.chosen[2]):
            return None
        low = high = None
        low_incl = high_incl = True
        for _, op, vals in self.conjuncts:
            if any(family(v) != fam for v in vals):
                continue
            bounds = []
            if op in ("=", ">", ">="):
                bounds.append(("low", vals[0], op != ">"))
            if op in ("=", "<", "<="):
                bounds.append(("high", vals[0], op != "<"))
            if op == "between":
                bounds += [("low", vals[0], True), ("high", vals[1], True)]
            for side, v, incl in bounds:
                if side == "low":
                    if low is None or v > low or (v == low and not incl):
                        low, low_incl = v, incl
                elif high is None or v < high or (v == high and not incl):
                    high, high_incl = v, incl
        if low is not None and high is not None and (low > high or (
                low == high and not (low_incl and high_incl))):
            return []
        if low is not None and low == high:
            return self.index.eq(low)
        return self.index.range(low, low_incl, high, high_incl)


def choose_access(db: Database, table: str, where: Any,
                  col_of: Callable[[Any], str | None]) -> AccessPlan | None:
    if where is None:
        return None
    t = db.tables[table]
    eq = rng = None
    found = []
    for c in flatten_and(where):
        m = usable_conjunct(c, col_of)
        if m is None:
            continue
        ix = db.index_for(table, m[0])
        if ix is None:
            continue
        found.append(m)
        if m[1] == "=" and eq is None:
            eq = (ix, m)
        elif m[1] != "=" and rng is None:
            rng = (ix, m)
    pick = eq or rng
    if pick is None:
        return None
    ix, m = pick
    col_type = t.columns[t.col_index(m[0])].type
    return AccessPlan(ix, m[0], col_type, pick is eq, m, [x for x in found if x[0] == m[0]])


@dataclass
class JoinPlan:
    """How table reference ``i`` is joined: 'search' (index nested loop), 'hash' or 'scan'."""
    kind: str
    column: str | None = None
    right_ci: int | None = None
    left: tuple[int, int] | None = None   # (source index, column index) of the other side
    index: Index | None = None


def choose_join(db: Database, source, i: int, on: Any, resolve: Callable[[n.ColumnRef], tuple]) -> JoinPlan:
    """Plan for joined reference number ``i``; ``resolve`` gives (depth, si, ci) in the ON scope."""
    if on is None:
        return JoinPlan("scan")
    for c in flatten_and(on):
        if not (isinstance(c, n.Binary) and c.op == "=" and isinstance(c.left, n.ColumnRef)
                and isinstance(c.right, n.ColumnRef)):
            continue
        try:
            a, b = resolve(c.left), resolve(c.right)
        except SQLNameError:
            continue
        if a[0] != 0 or b[0] != 0:
            continue
        if a[1] == i and b[1] < i:
            mine, other = a, b
        elif b[1] == i and a[1] < i:
            mine, other = b, a
        else:
            continue
        col = source.columns[mine[2]]
        ix = db.index_for(source.table, col) if source.table is not None else None
        return JoinPlan("search" if ix is not None else "hash", col, mine[2], (other[1], other[2]), ix)
    return JoinPlan("scan")


def check_key_families(left: set, right: set) -> None:
    """An equi-join between incomparable key types is a TypeError once both sides have keys."""
    if left and right and len(left | right) > 1:
        raise SQLTypeError("join keys of incomparable types: " + " and ".join(sorted(left | right)))
