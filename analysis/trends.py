"""Aligned per-checkpoint series from ``metrics.sqlite`` (docs/spec.md §9.2 Trends)."""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

CORE_METRICS = ("P", "R", "D", "C", "W", "X", "S")


@dataclass
class Series:
    run_id: str
    config: str
    name: str
    k: list[int] = field(default_factory=list)
    t_s: list[float] = field(default_factory=list)
    value: list[float] = field(default_factory=list)   # NaN where the scorer wrote null


def _rows(db_path: Path, sql: str, args: tuple) -> list[tuple]:
    con = sqlite3.connect(db_path)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def metric_series(db_path: Path, experiment_id: str, names=CORE_METRICS) -> list[Series]:
    """One series per (run, metric), ordered by run_id, metric, k; t_s from the checkpoint table."""
    rows = _rows(db_path, """
        SELECT r.run_id, r.config, m.name, m.k, c.t_s, m.value
        FROM metrics m JOIN runs r USING(run_id)
        LEFT JOIN checkpoints c ON c.run_id = m.run_id AND c.k = m.k
        WHERE r.experiment_id = ? AND m.name IN (%s)
        ORDER BY r.run_id, m.name, m.k""" % ",".join("?" * len(names)), (experiment_id, *names))
    out: dict[tuple[str, str], Series] = {}
    for rid, cfg, name, k, t_s, v in rows:
        s = out.setdefault((rid, name), Series(rid, cfg, name))
        s.k.append(k)
        s.t_s.append(math.nan if t_s is None else t_s)
        s.value.append(math.nan if v is None else v)
    return list(out.values())


def median_by_k(series: list[Series], name: str) -> tuple[list[int], list[float], list[float]]:
    """Across-run median of metric ``name`` at each k (nulls ignored); returns (k, median t_s, median)."""
    by_k: dict[int, tuple[list[float], list[float]]] = {}
    for s in series:
        if s.name != name:
            continue
        for k, t, v in zip(s.k, s.t_s, s.value, strict=True):
            ts, vs = by_k.setdefault(k, ([], []))
            ts.append(t)
            vs.append(v)
    ks, tm, vm = [], [], []
    for k in sorted(by_k):
        ts, vs = (np.array(x, dtype=float) for x in by_k[k])
        if np.isnan(vs).all():
            continue
        ks.append(k)
        tm.append(float(np.nanmedian(ts)))
        vm.append(float(np.nanmedian(vs)))
    return ks, tm, vm


def counter_series(db_path: Path, experiment_id: str, name: str) -> dict[str, tuple[list[float], list[float]]]:
    """``{run_id: (t_s, value)}`` for a counter at each checkpoint."""
    rows = _rows(db_path, """
        SELECT c.run_id, cp.t_s, c.value FROM counters c JOIN runs r USING(run_id)
        LEFT JOIN checkpoints cp ON cp.run_id = c.run_id AND cp.k = c.k
        WHERE r.experiment_id = ? AND c.name = ? ORDER BY c.run_id, c.k""", (experiment_id, name))
    out: dict[str, tuple[list[float], list[float]]] = {}
    for rid, t, v in rows:
        ts, vs = out.setdefault(rid, ([], []))
        ts.append(math.nan if t is None else t)
        vs.append(v)
    return out


def fill_pairs(db_path: Path, experiment_id: str, metric: str, fill: str = "context_fill_max"
               ) -> list[tuple[str, int, float, float]]:
    """``(run_id, k, context_fill, metric value)`` for checkpoints where both exist (value not null)."""
    return _rows(db_path, """
        SELECT m.run_id, m.k, c.value, m.value FROM metrics m JOIN runs r USING(run_id)
        JOIN counters c ON c.run_id = m.run_id AND c.k = m.k AND c.name = ?
        WHERE r.experiment_id = ? AND m.name = ? AND m.value IS NOT NULL
        ORDER BY m.run_id, m.k""", (fill, experiment_id, metric))
