"""Window functions (section 20), evaluated over the rows of one query after WHERE / GROUP BY /
HAVING and before DISTINCT / ORDER BY / LIMIT.

The executor compiles each ``f(...) OVER (...)`` into a ``WinSpec`` and reads its value from
``env.win[slot]``; ``compute`` fills ``env.win`` for every row env. Rows keep their order: a
partition is ordered by sorting row positions, never the rows themselves.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from minidb.protocol import SQLTypeError
from minidb.values import check_int, check_real, compare, hash_key, is_number, type_name

RANKING = frozenset({"row_number", "rank", "dense_rank"})
OFFSET = frozenset({"lag", "lead"})
WINDOW_ONLY = RANKING | OFFSET


@dataclass
class WinSpec:
    name: str
    star: bool
    args: list[Callable]
    partition: list[Callable]
    order: list[tuple[Callable, Any]]       # (key function, OrderItem)
    offset: int = 1
    default: Callable | None = None


class Running:
    """An aggregate over a growing frame, with the semantics of section 6."""

    def __init__(self, name: str, star: bool) -> None:
        self.name, self.star = name, star
        self.count = 0
        self.all_int = True
        self.itotal = 0
        self.facc = 0.0
        self.best: Any = None

    def add(self, v: Any) -> None:
        if self.star:
            self.count += 1
            return
        if v is None:
            return
        self.count += 1
        name = self.name
        if name in ("sum", "avg"):
            if not is_number(v):
                raise SQLTypeError(f"{name.upper()} needs numbers, got {type_name(v)}")
            if isinstance(v, int):
                self.itotal += v
            else:
                self.all_int = False
            self.facc += v
        elif name in ("min", "max"):
            if self.best is None:
                self.best = v
            else:
                c = compare(v, self.best)
                if (c < 0 and name == "min") or (c > 0 and name == "max"):
                    self.best = v

    def value(self) -> Any:
        name = self.name
        if name == "count":
            return self.count
        if name in ("min", "max"):
            return self.best
        if self.count == 0:
            return None
        if name == "sum":
            return check_int(self.itotal) if self.all_int else check_real(self.facc)
        if self.all_int:
            return self.itotal / self.count
        return check_real(self.facc / self.count)


def compute(envs: list, specs: list[WinSpec], sort_rows: Callable) -> None:
    """Fill ``env.win`` for every env. ``sort_rows`` is the executor's ORDER BY sort."""
    for env in envs:
        env.win = [None] * len(specs)
    for slot, w in enumerate(specs):
        parts: dict = {}
        for i, env in enumerate(envs):
            key = tuple(hash_key(f(env)) for f in w.partition)
            parts.setdefault(key, []).append(i)
        for idxs in parts.values():
            if w.order:
                keyed = [(i, [f(envs[i]) for f, _ in w.order]) for i in idxs]
                sort_rows(keyed, [(o.desc, o.null_first) for _, o in w.order])
                order = [i for i, _ in keyed]
                keys = [tuple(hash_key(v) for v in k) for _, k in keyed]
            else:
                order, keys = idxs, [()] * len(idxs)
            groups, start = [], 0
            for p in range(1, len(order) + 1):
                if p == len(order) or keys[p] != keys[start]:
                    groups.append((start, p))
                    start = p
            _fill(envs, slot, w, order, groups)


def _fill(envs: list, slot: int, w: WinSpec, order: list[int], groups: list[tuple[int, int]]) -> None:
    name = w.name
    if name == "row_number":
        for p, i in enumerate(order):
            envs[i].win[slot] = p + 1
    elif name in ("rank", "dense_rank"):
        for g, (s, e) in enumerate(groups):
            for p in range(s, e):
                envs[order[p]].win[slot] = s + 1 if name == "rank" else g + 1
    elif name in OFFSET:
        step = -w.offset if name == "lag" else w.offset
        for p, i in enumerate(order):
            q = p + step
            if 0 <= q < len(order):
                envs[i].win[slot] = w.args[0](envs[order[q]])
            else:
                envs[i].win[slot] = w.default(envs[i]) if w.default is not None else None
    else:
        run = Running(name, w.star)
        arg = w.args[0] if w.args else None
        if not w.order:
            for i in order:
                run.add(None if arg is None else arg(envs[i]))
            v = run.value()
            for i in order:
                envs[i].win[slot] = v
            return
        for s, e in groups:
            for p in range(s, e):
                run.add(None if arg is None else arg(envs[order[p]]))
            v = run.value()
            for p in range(s, e):
                envs[order[p]].win[slot] = v
