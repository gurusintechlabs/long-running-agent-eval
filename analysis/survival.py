"""Kaplan-Meier survival of time-to-first-hazard (docs/spec.md §9.2, D-11). No lifelines."""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.stats import norm

NOT_REACHED = "not reached"


@dataclass(frozen=True)
class KM:
    """Product-limit estimate at each distinct observed time (events counted before censorings)."""
    times: np.ndarray
    n_risk: np.ndarray
    n_event: np.ndarray
    surv: np.ndarray
    greenwood: np.ndarray    # cumulative sum d / (n (n - d)); Var(S) = S^2 * greenwood
    lower: np.ndarray        # two-sided (1 - alpha) CI, log(-log) scale
    upper: np.ndarray
    lower_1s: np.ndarray     # lower one-sided bound at confidence ``level_1s``

    def survival_at(self, t: float) -> float:
        i = int(np.searchsorted(self.times, t, side="right")) - 1
        return 1.0 if i < 0 else float(self.surv[i])

    def median(self) -> float | None:
        """Smallest observed time with S(t) <= 0.5, or None ("not reached")."""
        hit = np.nonzero(self.surv <= 0.5)[0]
        return float(self.times[hit[0]]) if hit.size else None


def _bounds(s: float, g: float, n: int, tail: float) -> tuple[float, float]:
    """Lower/upper bound with ``tail`` probability in each direction (log(-log) transform)."""
    if s <= 0.0 or not math.isfinite(g):
        return 0.0, (0.0 if s <= 0.0 else 1.0)
    if s >= 1.0:  # no event yet: Greenwood is degenerate, use the exact zero-failure bound
        return tail ** (1.0 / max(n, 1)), 1.0
    se = math.sqrt(g) / abs(math.log(s))
    z = float(norm.ppf(1.0 - tail))
    return s ** math.exp(z * se), s ** math.exp(-z * se)


def kaplan_meier(times, events, *, alpha: float = 0.05, level_1s: float = 0.90) -> KM:
    t = np.asarray(times, dtype=float)
    e = np.asarray(events, dtype=int)
    if t.size == 0 or t.shape != e.shape:
        raise ValueError("times and events must be non-empty and of equal length")
    uniq = np.unique(t)
    s, g = 1.0, 0.0
    rows = []
    for u in uniq:
        n = int((t >= u).sum())
        d = int(((t == u) & (e == 1)).sum())
        if d:
            s *= 1.0 - d / n
            g += math.inf if d == n else d / (n * (n - d))
        lo, hi = _bounds(s, g, n, alpha / 2)
        rows.append((u, n, d, s, g, lo, hi, _bounds(s, g, n, 1.0 - level_1s)[0]))
    c = list(zip(*rows, strict=True))
    return KM(*(np.array(x) for x in c))


def median_ci(times, events, *, n_boot: int = 2000, seed: int = 0, level: float = 0.95
              ) -> tuple[float | None, float | None]:
    """Seeded percentile-bootstrap CI for the median TTFH; ``None`` = not reached at that end."""
    t, e = np.asarray(times, dtype=float), np.asarray(events, dtype=int)
    rng = np.random.default_rng(seed)
    meds = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, t.size, t.size)
        m = kaplan_meier(t[idx], e[idx]).median()
        meds[b] = math.inf if m is None else m
    tail = (1.0 - level) / 2.0
    lo, hi = np.quantile(meds, [tail, 1.0 - tail], method="inverted_cdf")
    return (None if math.isinf(lo) else float(lo)), (None if math.isinf(hi) else float(hi))


def headline(times, events, *, target: float = 0.8, level: float = 0.90) -> float | None:
    """D-11: largest observed t such that the lower one-sided ``level`` bound of S(s) >= ``target``
    for every s <= t (the contiguous reading, so a later bound recovery cannot raise the limit).
    ``None`` = "bound never reaches target". Evaluated at observed times only (no extrapolation)."""
    km = kaplan_meier(times, events, level_1s=level)
    best = None
    for tt, b in zip(km.times, km.lower_1s, strict=True):
        if b < target:
            break
        best = float(tt)
    return best


def summarize(times, events, *, n_boot: int = 2000, seed: int = 0, target: float = 0.8,
              level: float = 0.90) -> dict:
    km = kaplan_meier(times, events, level_1s=level)
    lo, hi = median_ci(times, events, n_boot=n_boot, seed=seed)
    return {"n": len(times), "events": int(np.sum(events)), "km": km, "median": km.median(),
            "median_ci_boot": (lo, hi), "headline": headline(times, events, target=target, level=level)}


def headline_text(value: float | None, *, target: float = 0.8, level: float = 0.90) -> str:
    pct = f"{level * 100:g}%"
    if value is None:
        return (f"Bound never reaches target: the lower one-sided {pct} bound of S(t) is below "
                f"{target:g} at every observed time.")
    return (f"Operating limit: {value / 60:.1f} min (largest t with the lower one-sided {pct} bound "
            f"of S(t) >= {target:g}).")


def survival_inputs(db_path: Path, experiment_id: str, dimension: str | None = None
                    ) -> dict[tuple[str, str], tuple[list[float], list[int]]]:
    """``{(task_class, config): (times, events)}`` for runs in the survival set (FAILED and
    unfinished runs have ``event IS NULL`` and are excluded). With ``dimension``, an event is a
    hazard of that dimension only (other dimensions' hazards do not censor: run time is used)."""
    con = sqlite3.connect(db_path)
    try:
        runs = con.execute("SELECT run_id, task_class, config, duration_s, ttfh_s, event FROM runs "
                           "WHERE experiment_id=? AND event IS NOT NULL ORDER BY run_id",
                           (experiment_id,)).fetchall()
        dim = {}
        if dimension:
            dim = dict(con.execute("SELECT h.run_id, h.t_attributed_s FROM hazards h JOIN runs r "
                                   "USING(run_id) WHERE r.experiment_id=? AND h.dimension=?",
                                   (experiment_id, dimension)))
    finally:
        con.close()
    out: dict[tuple[str, str], tuple[list[float], list[int]]] = {}
    for rid, cls, cfg, dur, ttfh, ev in runs:
        if dimension:
            t, ev = (dim[rid], 1) if rid in dim else (dur, 0)
        else:
            t = ttfh if ev else dur
        ts, es = out.setdefault((cls, cfg), ([], []))
        ts.append(float(t))
        es.append(int(ev))
    return out
