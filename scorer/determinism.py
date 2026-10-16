"""Determinism check (docs/plan.md Phase 4 task 4): re-scoring must reproduce every metric.

Compares, per checkpoint, the metric values of the two most recent ok scoring passes in
``events/scorer.jsonl``. X(t) is reproducible because the judge's raw outputs are cached.
"""
from __future__ import annotations

import math
from pathlib import Path

from scorer.run_checkpoint import read_events


def ok_passes(events: list[dict]) -> dict[int, list[dict[str, float | None]]]:
    """``{k: [ {metric: value}, ... ]}`` for every ok pass, oldest first."""
    metrics: dict[str, dict[str, float | None]] = {}
    out: dict[int, list[dict[str, float | None]]] = {}
    for ev in events:
        p, t = ev.get("payload") or {}, ev.get("type")
        if t == "scorer.start":
            metrics[p["pass_id"]] = {}
        elif t == "scorer.metric" and p.get("pass_id") in metrics:
            metrics[p["pass_id"]][p["name"]] = p.get("value")
        elif t == "scorer.done" and p.get("ok") and p.get("pass_id") in metrics:
            out.setdefault(p["k"], []).append(metrics[p["pass_id"]])
    return out


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-12)


def compare_last_two(art: Path) -> dict[int, dict[str, tuple]]:
    """``{k: {metric: (previous, latest)}}`` for every metric that changed; ``{}`` = deterministic.
    A checkpoint with fewer than two ok passes is reported as ``{"_passes": (n, 2)}``."""
    diffs: dict[int, dict[str, tuple]] = {}
    for k, passes in sorted(ok_passes(read_events(Path(art) / "events" / "scorer.jsonl")).items()):
        if len(passes) < 2:
            diffs[k] = {"_passes": (len(passes), 2)}
            continue
        prev, last = passes[-2], passes[-1]
        changed = {n: (prev.get(n), last.get(n)) for n in sorted(set(prev) | set(last))
                   if not _same(prev.get(n), last.get(n))}
        if changed:
            diffs[k] = changed
    return diffs
