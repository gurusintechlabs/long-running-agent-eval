"""Degradation analysis from ``metrics.sqlite`` (docs/interfaces.md §8, §9).

Pure, deterministic functions over a sqlite path; they read the ``test_outcomes``, ``stages``,
``agent_test_runs``, ``checkpoints`` and ``counters`` tables written by ``analysis.ingest`` and
return plain dataclasses/dicts. Every function returns an empty result (never raises) for stores
or runs without the per-commit tables, so older runs simply show "no per-commit data".

Definitions (all on one ``suite``, default ``hidden``; times are run-time seconds):

* **Point**: one scoring of the code, either a commit (``scorer.commit``) or a checkpoint working
  tree. Points are ordered by ``(t_s, commits before checkpoints, k)``.
* **Outcome**: ``passed | failed | error | skipped``. ``failing`` = failed or error. ``skipped`` means
  "not active at this stage": it is excluded from every denominator and never starts or ends a flip
  (the test keeps its last non-skipped state across skipped points).
* **Regression** of a test: a transition passed -> failing between two consecutive non-skipped
  points; its time is the ``t_s`` of the later point. **Recovery**: failing -> passed. **Relapsing**
  test: >= 2 regressions. **first_pass_t**: ``t_s`` of the first passed point. **Time to first
  regression** (ttfr_s): first regression time - first_pass_t (None if it never regressed).
* **Established test** at point i: a test that passed at some point j < i. The **established pass
  rate** at i = passed / (non-skipped) among established tests; it cannot drop because a feature has
  not been implemented yet, so a fall is genuine degradation. (None while nothing is established.)
* **Per-tier pass rate** at i: passed / non-skipped among the tests of that tier (not-yet-implemented
  features do lower it).
* **Regression rate per hour** of a window = regressions with ``t_s`` in the window / window hours
  (windows ``[a, a+w)`` from 0 to the run end = max(duration, last point), the last one clipped).
  Against context fill, the unit is a checkpoint interval ``(t_{k-1}, t_k]`` whose fill is the
  ``context_fill_max`` counter of k; rate = regressions in it / interval hours. Compactions are only
  known per interval (the ``compactions`` counter): intervals are classed ``compaction`` (counter > 0),
  ``after_compaction`` (the next interval) or ``other``.
* **Belief gap**: for each ``agent.test_run`` (the agent's own pytest output), the state is the
  nearest preceding commit point (checkpoint points if the run has no commit points). The agent
  saw *green* if it reported no failures/errors and >= 1 passed. ``gap`` = green while >= 1
  established test was failing at that state. The agent may have run only a subset of tests, and
  the working tree can be ahead of the last commit; the gap is a signal, not proof of a false belief.
* **Status per point** (staged tasks): each test is ``passing``, ``inactive`` (skipped), ``regressed``
  (failing after having passed at an earlier point) or ``not_yet_implemented`` (failing, never
  passed before). **Stage effects**: for each delivered stage s > 0, tests active before (at the
  last point of an earlier stage) vs. at stage s split into carried / retired / introduced, with
  the carried pass rate before, right after delivery (first point of stage s) and at the end of the
  stage, and the number of regressions of carried tests during the stage.
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

PASSED, SKIPPED = "passed", "skipped"
FAILING = ("failed", "error")
FILL_BINS = ((0.0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, math.inf))


@dataclass
class Point:
    idx: int
    t_s: float
    point: str          # 'commit' | 'checkpoint'
    k: int
    sha: str | None
    stage: int


@dataclass
class Matrix:
    run_id: str
    suite: str
    points: list[Point] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)            # ordered by tier, then id
    tier: dict[str, str] = field(default_factory=dict)
    outcome: dict[str, list[str | None]] = field(default_factory=dict)   # per test, aligned to points

    def __bool__(self) -> bool:
        return bool(self.points)


@dataclass
class TestTimeline:
    __test__ = False  # not a pytest class
    test_id: str
    tier: str
    first_pass_t: float | None
    regressions: list[float]
    recoveries: list[float]
    ttfr_s: float | None
    final_outcome: str | None

    @property
    def relapsed(self) -> bool:
        return len(self.regressions) >= 2


@dataclass
class Flip:
    t_s: float
    test_id: str
    tier: str
    kind: str           # 'regression' | 'recovery'


@dataclass
class RatePoint:
    t_s: float
    point: str
    k: int
    stage: int
    passed: int
    active: int
    tiers: dict[str, tuple[int, int]]       # tier -> (passed, active)
    est_passed: int
    est_active: int

    @property
    def overall(self) -> float | None:
        return self.passed / self.active if self.active else None

    @property
    def established(self) -> float | None:
        return self.est_passed / self.est_active if self.est_active else None


def _connect(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


def _rows(db_path: Path, sql: str, args: tuple = ()) -> list[tuple]:
    con = _connect(db_path)
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.OperationalError:     # table missing: a store from before the degradation tables
        return []
    finally:
        con.close()


def _tier_key(t: str) -> tuple:
    return (0, int(t), "") if t.isdigit() else (1, 0, t)


def runs_with_data(db_path: Path, experiment_id: str | None = None) -> list[str]:
    """Run ids that have per-test outcomes (optionally of one experiment), ordered by config, repeat, id."""
    sql = ("SELECT r.run_id FROM runs r WHERE EXISTS (SELECT 1 FROM test_outcomes t WHERE t.run_id = r.run_id)"
           + (" AND r.experiment_id = ?" if experiment_id else "") + " ORDER BY r.config, r.repeat, r.run_id")
    return [r[0] for r in _rows(db_path, sql, (experiment_id,) if experiment_id else ())]


def load_matrix(db_path: Path, run_id: str, suite: str = "hidden") -> Matrix:
    rows = _rows(db_path, "SELECT point, k, seq, sha, t_s, stage, test_id, tier, outcome FROM test_outcomes "
                          "WHERE run_id=? AND suite=? AND t_s IS NOT NULL", (run_id, suite))
    m = Matrix(run_id, suite)
    if not rows:
        return m
    # Points in time order; commits of one interval keep the scorer's oldest-first order (seq), since
    # their times can tie (scripted runs commit with a fixed date).
    keys = sorted({(r[4], r[0] != "commit", r[1], r[2], r[0], r[3], r[5]) for r in rows})
    index = {}
    for i, (t, _nc, k, sq, pt, sha, stage) in enumerate(keys):
        m.points.append(Point(i, t, pt, k, sha, stage or 0))
        index[(t, pt, k, sq)] = i
    for pt_, k, sq, _sha, t, _stage, tid, tier, out in rows:
        m.tier.setdefault(tid, tier or "?")
        m.outcome.setdefault(tid, [None] * len(m.points))[index[(t, pt_, k, sq)]] = out
    m.tests = sorted(m.outcome, key=lambda t: (_tier_key(m.tier[t]), t))
    return m


# ---------------------------------------------------------------------------- per-test timelines

def _timeline(m: Matrix, tid: str) -> tuple[TestTimeline, list[Flip]]:
    first_pass, regs, recs, flips = None, [], [], []
    state, final = None, None
    for p, out in zip(m.points, m.outcome[tid], strict=True):
        if out is None or out == SKIPPED:
            continue
        final = out
        now = PASSED if out == PASSED else "failing"
        if now == PASSED and first_pass is None:
            first_pass = p.t_s
        if state == PASSED and now == "failing":
            regs.append(p.t_s)
            flips.append(Flip(p.t_s, tid, m.tier[tid], "regression"))
        elif state == "failing" and now == PASSED:
            recs.append(p.t_s)
            flips.append(Flip(p.t_s, tid, m.tier[tid], "recovery"))
        state = now
    ttfr = regs[0] - first_pass if regs and first_pass is not None else None
    return TestTimeline(tid, m.tier[tid], first_pass, regs, recs, ttfr, final), flips


def timelines(db_path: Path, run_id: str, suite: str = "hidden") -> list[TestTimeline]:
    m = load_matrix(db_path, run_id, suite)
    return [_timeline(m, t)[0] for t in m.tests]


def flip_events(db_path: Path, run_id: str, suite: str = "hidden") -> list[Flip]:
    m = load_matrix(db_path, run_id, suite)
    out = [f for t in m.tests for f in _timeline(m, t)[1]]
    return sorted(out, key=lambda f: (f.t_s, f.kind, f.test_id))


# ---------------------------------------------------------------------------- pass rates over time

def _rate_points(m: Matrix) -> list[RatePoint]:
    ever: set[str] = set()
    out = []
    for p in m.points:
        passed = active = ep = ea = 0
        tiers: dict[str, list[int]] = {}
        now_passed = []
        for tid in m.tests:
            o = m.outcome[tid][p.idx]
            if o is None or o == SKIPPED:
                continue
            active += 1
            t = tiers.setdefault(m.tier[tid], [0, 0])
            t[1] += 1
            if tid in ever:
                ea += 1
            if o == PASSED:
                passed += 1
                t[0] += 1
                ep += tid in ever
                now_passed.append(tid)
        out.append(RatePoint(p.t_s, p.point, p.k, p.stage, passed, active,
                             {t: (v[0], v[1]) for t, v in sorted(tiers.items(), key=lambda kv: _tier_key(kv[0]))},
                             ep, ea))
        ever.update(now_passed)
    return out


def pass_rates(db_path: Path, run_id: str, suite: str = "hidden") -> list[RatePoint]:
    """Per point: overall, per-tier and established-test pass counts (see module docstring)."""
    return _rate_points(load_matrix(db_path, run_id, suite))


# ---------------------------------------------------------------------------- regression rates

def run_end(db_path: Path, run_id: str, m: Matrix | None = None) -> float:
    r = _rows(db_path, "SELECT duration_s FROM runs WHERE run_id=?", (run_id,))
    last = m.points[-1].t_s if m else 0.0
    return max(float(r[0][0]) if r and r[0][0] is not None else 0.0, last)


def window_rates(db_path: Path, run_id: str, window_s: float = 3600.0, suite: str = "hidden") -> list[dict]:
    """``[{window, t0, t1, regressions, hours, per_hour}]`` by run-time window."""
    m = load_matrix(db_path, run_id, suite)
    if not m:
        return []
    times = [f.t_s for f in flip_events(db_path, run_id, suite) if f.kind == "regression"]
    end = run_end(db_path, run_id, m)
    out = []
    for w in range(max(1, math.ceil(end / window_s - 1e-9))):
        t0, t1 = w * window_s, min((w + 1) * window_s, end)
        n = sum(1 for t in times if t0 <= t < (t1 if t1 < end else math.inf))
        hours = (t1 - t0) / 3600.0
        out.append({"window": w, "t0": t0, "t1": t1, "regressions": n, "hours": hours,
                    "per_hour": n / hours if hours > 0 else None})
    return out


def fill_intervals(db_path: Path, run_id: str, suite: str = "hidden") -> list[dict]:
    """Per checkpoint interval ``(t_{k-1}, t_k]``: fill, compaction class, regressions and rate per hour."""
    m = load_matrix(db_path, run_id, suite)
    cps = _rows(db_path, "SELECT k, t_s FROM checkpoints WHERE run_id=? AND t_s IS NOT NULL ORDER BY k", (run_id,))
    if not m or not cps:
        return []
    ctr = {(k, n): v for k, n, v in _rows(db_path, "SELECT k, name, value FROM counters WHERE run_id=? AND "
                                          "name IN ('context_fill_max','compactions')", (run_id,))}
    times = [f.t_s for f in flip_events(db_path, run_id, suite) if f.kind == "regression"]
    out, prev, after = [], 0.0, False
    for k, t in cps:
        n = sum(1 for x in times if prev < x <= t or (prev == 0.0 and x == 0.0))
        comp = ctr.get((k, "compactions")) or 0
        cls = "compaction" if comp > 0 else "after_compaction" if after else "other"
        hours = (t - prev) / 3600.0
        out.append({"k": k, "t0": prev, "t1": t, "fill": ctr.get((k, "context_fill_max")),
                    "compactions": comp, "class": cls, "regressions": n, "hours": hours,
                    "per_hour": n / hours if hours > 0 else None})
        after, prev = comp > 0, t
    return out


def fill_bins(intervals: list[dict]) -> list[dict]:
    """Pool intervals (any number of runs) into context-fill bins: regressions, hours, rate per hour."""
    out = []
    for lo, hi in FILL_BINS:
        sel = [i for i in intervals if i["fill"] is not None and lo <= i["fill"] < hi]
        n, h = sum(i["regressions"] for i in sel), sum(i["hours"] for i in sel)
        out.append({"lo": lo, "hi": None if hi == math.inf else hi, "intervals": len(sel), "regressions": n,
                    "hours": h, "per_hour": n / h if h > 0 else None})
    return out


def compaction_effect(intervals: list[dict]) -> list[dict]:
    """Pool intervals by compaction class (compaction / after_compaction / other)."""
    out = []
    for cls in ("compaction", "after_compaction", "other"):
        sel = [i for i in intervals if i["class"] == cls]
        n, h = sum(i["regressions"] for i in sel), sum(i["hours"] for i in sel)
        out.append({"class": cls, "intervals": len(sel), "regressions": n, "hours": h,
                    "per_hour": n / h if h > 0 else None})
    return out


# ---------------------------------------------------------------------------- belief gap

def belief_gap(db_path: Path, run_id: str, suite: str = "hidden") -> list[dict]:
    """One row per ``agent.test_run`` that has a preceding scored point (see module docstring)."""
    runs = _rows(db_path, "SELECT t_s, passed, failed, errors, skipped FROM agent_test_runs WHERE run_id=? "
                          "ORDER BY t_s", (run_id,))
    m = load_matrix(db_path, run_id, suite)
    if not runs or not m:
        return []
    rates = _rate_points(m)
    kind = "commit" if any(p.point == "commit" for p in m.points) else "checkpoint"
    cand = [p for p in m.points if p.point == kind]
    ever: dict[int, set[str]] = {}
    seen: set[str] = set()
    for p in m.points:
        ever[p.idx] = set(seen)
        seen.update(t for t in m.tests if m.outcome[t][p.idx] == PASSED)
    out = []
    for t, passed, failed, errors, _skipped in runs:
        prev = [p for p in cand if p.t_s <= t]
        if not prev:
            continue
        p = prev[-1]
        est_fail = [tid for tid in m.tests if tid in ever[p.idx] and m.outcome[tid][p.idx] in FAILING]
        all_fail = sum(1 for tid in m.tests if m.outcome[tid][p.idx] in FAILING)
        green = failed + errors == 0 and passed > 0
        out.append({"t_s": t, "agent_passed": passed, "agent_failed": failed + errors, "agent_green": green,
                    "state_t_s": p.t_s, "state_passed": rates[p.idx].passed, "state_failing": all_fail,
                    "established_failing": len(est_fail), "gap": green and bool(est_fail)})
    return out


def belief_summary(rows: list[dict]) -> dict:
    green = [r for r in rows if r["agent_green"]]
    gaps = [r for r in rows if r["gap"]]
    return {"test_runs": len(rows), "green": len(green), "gaps": len(gaps),
            "gap_frac": len(gaps) / len(green) if green else None}


# ---------------------------------------------------------------------------- staged tasks

def stage_deliveries(db_path: Path, run_id: str) -> list[tuple[int, float, bool]]:
    return [(s, t, bool(i)) for s, t, i in _rows(
        db_path, "SELECT stage, t_s, interrupted FROM stages WHERE run_id=? ORDER BY stage", (run_id,))]


def status_counts(db_path: Path, run_id: str, suite: str = "hidden") -> list[dict]:
    """Per point: counts of passing / regressed / not_yet_implemented / inactive tests."""
    m = load_matrix(db_path, run_id, suite)
    ever: set[str] = set()
    out = []
    for p in m.points:
        c = {"passing": 0, "regressed": 0, "not_yet_implemented": 0, "inactive": 0}
        now = []
        for tid in m.tests:
            o = m.outcome[tid][p.idx]
            if o is None or o == SKIPPED:
                c["inactive"] += 1
            elif o == PASSED:
                c["passing"] += 1
                now.append(tid)
            else:
                c["regressed" if tid in ever else "not_yet_implemented"] += 1
        ever.update(now)
        out.append({"t_s": p.t_s, "point": p.point, "k": p.k, "stage": p.stage, **c})
    return out


def _active(m: Matrix, idx: int) -> set[str]:
    return {t for t in m.tests if m.outcome[t][idx] not in (None, SKIPPED)}


def _rate(m: Matrix, idx: int, tests: set[str]) -> float | None:
    act = [t for t in tests if m.outcome[t][idx] not in (None, SKIPPED)]
    return sum(1 for t in act if m.outcome[t][idx] == PASSED) / len(act) if act else None


def stage_effects(db_path: Path, run_id: str, suite: str = "hidden") -> list[dict]:
    """One dict per delivered stage s > 0 (see module docstring)."""
    m = load_matrix(db_path, run_id, suite)
    dels = stage_deliveries(db_path, run_id)
    if not m or len(dels) < 2:
        return []
    flips = [f for f in flip_events(db_path, run_id, suite) if f.kind == "regression"]
    out = []
    for i, (s, t_d, _intr) in enumerate(dels):
        if s == 0:
            continue
        before = [p for p in m.points if p.stage < s]
        during = [p for p in m.points if p.stage == s]
        if not before or not during:
            continue
        b, first, last = before[-1].idx, during[0].idx, during[-1].idx
        act_b, act_a = _active(m, b), _active(m, first)
        carried, retired, introduced = act_b & act_a, act_b - act_a, act_a - act_b
        t_next = dels[i + 1][1] if i + 1 < len(dels) else math.inf
        out.append({"stage": s, "t_s": t_d, "carried": len(carried), "retired": len(retired),
                    "introduced": len(introduced), "carried_before": _rate(m, b, carried),
                    "carried_after": _rate(m, first, carried), "carried_end": _rate(m, last, carried),
                    "retired_before": _rate(m, b, retired), "introduced_end": _rate(m, last, introduced),
                    "carried_regressions": sum(1 for f in flips if f.test_id in carried and t_d <= f.t_s < t_next)})
    return out


# ---------------------------------------------------------------------------- summaries

def run_summary(db_path: Path, run_id: str, suite: str = "hidden") -> dict | None:
    """Headline degradation numbers of one run (None without per-test data)."""
    m = load_matrix(db_path, run_id, suite)
    if not m:
        return None
    tls = [_timeline(m, t)[0] for t in m.tests]
    rp = _rate_points(m)
    est = [r.established for r in rp if r.established is not None]
    ttfr = [t.ttfr_s for t in tls if t.ttfr_s is not None]
    return {"run_id": run_id, "points": len(m.points), "commits": sum(p.point == "commit" for p in m.points),
            "tests": len(m.tests), "ever_passed": sum(t.first_pass_t is not None for t in tls),
            "regressions": sum(len(t.regressions) for t in tls),
            "regressed_tests": sum(bool(t.regressions) for t in tls),
            "relapsing_tests": sum(t.relapsed for t in tls),
            "mean_ttfr_s": sum(ttfr) / len(ttfr) if ttfr else None,
            "established_min": min(est) if est else None, "established_final": est[-1] if est else None,
            "overall_final": rp[-1].overall}


def top_relapsers(db_path: Path, run_ids: list[str], n: int = 15, suite: str = "hidden") -> list[dict]:
    """Tests with the most regressions over the given runs (ties: more recoveries last, then ids)."""
    rows = []
    for rid in run_ids:
        for t in timelines(db_path, rid, suite):
            if t.regressions:
                rows.append({"run_id": rid, "test_id": t.test_id, "tier": t.tier,
                             "regressions": len(t.regressions), "recoveries": len(t.recoveries),
                             "first_pass_t": t.first_pass_t, "ttfr_s": t.ttfr_s, "final": t.final_outcome})
    rows.sort(key=lambda r: (-r["regressions"], r["run_id"], r["test_id"]))
    return rows[:n]
