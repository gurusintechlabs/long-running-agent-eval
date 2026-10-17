"""Access paths: how the rows of a table reference are found (section 12).

The first table reference of a query (and the target of UPDATE / DELETE) is read through an
index when a top-level conjunct of WHERE compares one of its indexed columns with a literal;
a later table reference of an INNER / LEFT join is probed through an index or a hash table when
its ON condition has an equi-join conjunct. The choice is made by the rules of section 12 and is
what EXPLAIN reports.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from minidb import nodes as n
from minidb import values as v
from minidb.catalog import Index, Row, Table
from minidb.compiler import Scope

_FLIP = {"=": "=", "<": ">", "<=": ">=", ">": "<", ">=": "<="}


def conjuncts(expr: Optional[n.Expr]) -> list[n.Expr]:
    """The top-level AND-ed conjuncts of a condition, left to right."""
    if expr is None:
        return []
    if isinstance(expr, n.Binary) and expr.op == "AND":
        return conjuncts(expr.left) + conjuncts(expr.right)
    return [expr]


def literal_value(e: n.Expr) -> tuple[bool, Any]:
    """(True, value) if ``e`` is a literal in the sense of section 12: a number with at most one
    leading sign, a string, TRUE or FALSE (not NULL)."""
    if isinstance(e, n.Literal):
        return e.value is not None, e.value
    if (isinstance(e, n.Unary) and isinstance(e.operand, n.Literal)
            and type(e.operand.value) in (int, float)):
        x = e.operand.value
        return True, -x if e.op == "-" else x
    return False, None


@dataclass
class Condition:
    """A usable conjunct: ``column op value`` (op one of = < <= > >=), or a BETWEEN."""
    column: int
    op: str  # = < <= > >= or BETWEEN
    values: tuple


def _first_table_column(e: n.Expr, scope: Scope) -> Optional[int]:
    if not isinstance(e, n.ColumnRef):
        return None
    found = scope.lookup(e)
    if found is None or found[0] != 0:
        return None
    return found[1]  # the first source starts at offset 0


def usable_conditions(where: Optional[n.Expr], scope: Scope, table: Table) -> list[Condition]:
    out = []
    for c in conjuncts(where):
        cond = None
        if isinstance(c, n.Binary) and c.op in _FLIP:
            col = _first_table_column(c.left, scope)
            ok, val = literal_value(c.right)
            op = c.op
            if col is None or not ok:
                col = _first_table_column(c.right, scope)
                ok, val = literal_value(c.left)
                op = _FLIP[c.op]
            if col is not None and ok:
                cond = Condition(col, op, (val,))
        elif isinstance(c, n.Between) and not c.negated:
            col = _first_table_column(c.operand, scope)
            ok_lo, lo = literal_value(c.low)
            ok_hi, hi = literal_value(c.high)
            if col is not None and ok_lo and ok_hi:
                cond = Condition(col, "BETWEEN", (lo, hi))
        if cond is not None and table.first_index(cond.column) is not None:
            out.append(cond)
    return out


class TableAccess:
    """How the rows of a table (the first table reference, or an UPDATE / DELETE target) are
    found: a full scan or an index lookup."""

    def __init__(self, table: Table, where: Optional[n.Expr], scope: Scope) -> None:
        self.table = table
        conds = usable_conditions(where, scope, table)
        pick = next((c for c in conds if c.op == "="), conds[0] if conds else None)
        self.index: Optional[Index] = None
        self.label = f"SCAN {table.name}"
        self.bounds: Optional[tuple] = None  # (lo, lo_incl, hi, hi_incl) for the lookup
        if pick is None:
            return
        self.index = table.first_index(pick.column)
        col = table.columns[pick.column]
        how = "= ?" if pick.op == "=" else "RANGE"
        self.label = f"SEARCH {table.name} USING INDEX {self.index.name} ({col.name} {how})"
        cls = v.column_class(col.type)
        if not all(v.value_class(x) == cls for x in pick.values):
            return  # incomparable literal: behave exactly like a full scan
        # Narrow by every usable conjunct on the same column with comparable literals.
        lo = hi = None
        lo_incl = hi_incl = True
        for c in conds:
            if c.column != pick.column or not all(v.value_class(x) == cls for x in c.values):
                continue
            for bound, incl, is_lo in _bounds(c):
                if is_lo:
                    if lo is None or bound > lo or (bound == lo and not incl):
                        lo, lo_incl = bound, incl
                elif hi is None or bound < hi or (bound == hi and not incl):
                    hi, hi_incl = bound, incl
        self.bounds = (lo, lo_incl, hi, hi_incl)

    def rowids(self) -> Optional[list[int]]:
        """Rowids found through the index (in table order), or None for a full scan."""
        if self.bounds is None:
            return None
        lo, lo_incl, hi, hi_incl = self.bounds
        if lo is not None and hi is not None and (lo > hi or (lo == hi and not (lo_incl and
                                                                                 hi_incl))):
            return []
        return self.index.lookup(lo, lo_incl, hi, hi_incl)

    def rows(self) -> list[Row]:
        rids = self.rowids()
        if rids is None:
            return list(self.table.rows.values())
        rows = self.table.rows
        return [rows[r] for r in rids]

    def items(self) -> list[tuple[int, Row]]:
        rids = self.rowids()
        if rids is None:
            return list(self.table.rows.items())
        rows = self.table.rows
        return [(r, rows[r]) for r in rids]


def _bounds(c: Condition) -> list[tuple[Any, bool, bool]]:
    """(value, inclusive, is lower bound) for each bound a condition puts on its column."""
    if c.op == "BETWEEN":
        return [(c.values[0], True, True), (c.values[1], True, False)]
    x = c.values[0]
    return {"=": [(x, True, True), (x, True, False)], ">": [(x, False, True)],
            ">=": [(x, True, True)], "<": [(x, False, False)], "<=": [(x, True, False)]}[c.op]


@dataclass
class EquiJoin:
    """The leftmost equi-join conjunct of an ON condition: the joined row's column
    ``left_index`` equals column ``right_column`` of the new table reference."""
    left_index: int
    right_column: int
    only_conjunct: bool  # the ON condition is exactly this equality


def equi_join(on: Optional[n.Expr], scope: Scope, k: int) -> Optional[EquiJoin]:
    """For the k-th table reference (1-based, k >= 2) of ``scope``."""
    parts = conjuncts(on)
    right = scope.sources[k - 1]
    for c in parts:
        if not (isinstance(c, n.Binary) and c.op == "="
                and isinstance(c.left, n.ColumnRef) and isinstance(c.right, n.ColumnRef)):
            continue
        a, b = scope.lookup(c.left), scope.lookup(c.right)
        if a is None or b is None:
            continue  # a reference to an enclosing query
        if a[0] == k - 1 and b[0] < k - 1:
            a, b = b, a
        if b[0] == k - 1 and a[0] < k - 1:
            return EquiJoin(a[1], b[1] - right.offset, len(parts) == 1)
    return None
