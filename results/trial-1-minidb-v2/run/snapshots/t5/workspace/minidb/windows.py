"""Window functions (section 20).

A window function is compiled (``minidb.compiler``) into a ``WindowSpec``: closures for its
arguments, its PARTITION BY expressions and its ORDER BY keys, all evaluated on the query's
rows after FROM / WHERE / GROUP BY / HAVING (one row per group in a grouped query). ``compute``
returns one value per row; the query appends these values to its rows, where the select list
and ORDER BY read them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from minidb import values as v
from minidb.protocol import SQLTypeError
from minidb.sorting import sort_entries

Fn = Callable[[tuple], Any]

RANKING = frozenset({"row_number", "rank", "dense_rank"})
OFFSET = frozenset({"lag", "lead"})
AGGREGATE = frozenset({"count", "sum", "avg", "min", "max"})
WINDOW_ONLY = RANKING | OFFSET  # these require OVER


@dataclass
class WindowSpec:
    name: str
    star: bool = False                      # COUNT(*)
    arg: Optional[Fn] = None                # the argument (LAG / LEAD / aggregates)
    offset: int = 1                         # LAG / LEAD
    default: Optional[Fn] = None            # LAG / LEAD
    partition: list[Fn] = field(default_factory=list)
    order: list[tuple[Fn, bool, bool]] = field(default_factory=list)  # (key, desc, nulls 1st)

    def compute(self, envs: list[tuple]) -> list[Any]:
        out: list[Any] = [None] * len(envs)
        if self.partition:
            parts: dict[tuple, list[int]] = {}
            for i, env in enumerate(envs):
                key = tuple(v.value_key(f(env)) for f in self.partition)
                parts.setdefault(key, []).append(i)
            partitions = list(parts.values())
        else:
            partitions = [list(range(len(envs)))] if envs else []
        keys: list[list[Any]] = []
        if self.order:
            keys = [[f(env) for f, _, _ in self.order] for env in envs]
        for rows in partitions:
            if self.order:
                getters = [(lambda i, k=k: keys[i][k], desc, nulls_first)
                           for k, (_, desc, nulls_first) in enumerate(self.order)]
                rows = sort_entries(rows, getters)
            self._fill(rows, envs, keys, out)
        return out

    def _peer_groups(self, rows: list[int], keys: list[list[Any]]) -> list[list[int]]:
        """Consecutive runs of rows that tie on every window ORDER BY item."""
        if not self.order:
            return [rows]
        groups: list[list[int]] = []
        last = None
        for i in rows:
            k = tuple(v.value_key(x) for x in keys[i])
            if groups and k == last:
                groups[-1].append(i)
            else:
                groups.append([i])
                last = k
        return groups

    def _fill(self, rows: list[int], envs: list[tuple], keys: list[list[Any]],
              out: list[Any]) -> None:
        name = self.name
        if name == "row_number":
            for pos, i in enumerate(rows):
                out[i] = pos + 1
        elif name in ("rank", "dense_rank"):
            before = 0
            for dense, group in enumerate(self._peer_groups(rows, keys), start=1):
                for i in group:
                    out[i] = dense if name == "dense_rank" else before + 1
                before += len(group)
        elif name in OFFSET:
            step = -self.offset if name == "lag" else self.offset
            for pos, i in enumerate(rows):
                target = pos + step
                if 0 <= target < len(rows):
                    out[i] = self.arg(envs[rows[target]])
                elif self.default is not None:
                    out[i] = self.default(envs[i])
        else:
            running = RunningAggregate(name, self.star)
            for group in self._peer_groups(rows, keys):
                for i in group:
                    running.add(None if self.star else self.arg(envs[i]))
                value = running.value()
                for i in group:
                    out[i] = value


class RunningAggregate:
    """An aggregate (section 6) over a growing prefix of a partition: add values in partition
    order, read the value of the rows seen so far at any point."""

    def __init__(self, name: str, star: bool) -> None:
        self.name = name
        self.star = star
        self.rows = 0
        self.count = 0          # non-NULL values
        self.int_total = 0      # exact sum while every value is INTEGER
        self.float_total = 0.0  # the values added as doubles, in order, from 0.0
        self.all_int = True
        self.best: Any = None

    def add(self, x: Any) -> None:
        self.rows += 1
        if self.star or x is None:
            return
        self.count += 1
        name = self.name
        if name in ("sum", "avg"):
            if not v.is_number(x):
                raise SQLTypeError(f"{name.upper()} requires numbers, got {v.type_name(x)}")
            if type(x) is int:
                self.int_total += x
            else:
                self.all_int = False
            self.float_total += float(x)
        elif name in ("min", "max"):
            if self.best is None:
                self.best = x
            else:
                v.check_comparable(self.best, x)
                if (x < self.best) if name == "min" else (x > self.best):
                    self.best = x

    def value(self) -> Any:
        name = self.name
        if name == "count":
            return self.rows if self.star else self.count
        if name in ("min", "max"):
            return self.best
        if not self.count:
            return None
        if self.all_int:
            total = v.check_int(self.int_total)
            return total if name == "sum" else v.check_real(total / self.count)
        total = v.check_real(self.float_total)
        return total if name == "sum" else v.check_real(total / self.count)
