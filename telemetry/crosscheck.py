"""Cross-check OTel cost against the stream-json total (docs/spec.md §6.2).

Assumption (to confirm on a real multi-turn run): every ``claude -p`` invocation, including each
``--resume`` one, reports in its ``result`` message the cost of *that invocation only*. The stream
total for a session is therefore the sum of ``total_cost_usd`` over all of its result messages.
If a future CLI reports a running total across resumes, this check will show a large ``rel_diff``
for multi-turn sessions rather than hide it. A session whose invocation was killed has no result
message, so its stream total is lower and ``ok`` is false (that is the correct signal).
"""
from __future__ import annotations

import json
from pathlib import Path

TOLERANCE = 0.01


def _events(path: Path):
    try:
        with open(path) as fh:
            for line in fh:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict):
                    yield ev
    except OSError:
        return


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def otel_cost_by_session(otel_events: Path) -> dict[str, float]:
    """Σ ``cost_usd`` of ``claude_code.api_request`` events per ``session.id``."""
    out: dict[str, float] = {}
    for ev in _events(otel_events):
        if ev.get("type") != "claude_code.api_request":
            continue
        p = ev.get("payload") or {}
        c = _num(p.get("cost_usd"))
        if c is not None and p.get("session.id"):
            out[p["session.id"]] = out.get(p["session.id"], 0.0) + c
    return out


def stream_cost_by_session(stream_events: Path) -> dict[str, float]:
    """Σ ``total_cost_usd`` of result messages per session (see module docstring).

    Parsed ``session.result`` events are used; raw ``stream.result`` events only when the file
    has no parsed ones, so a message is never counted twice.
    """
    parsed: dict[str, float] = {}
    raw: dict[str, float] = {}
    for ev in _events(stream_events):
        target = parsed if ev.get("type") == "session.result" else raw if ev.get("type") == "stream.result" else None
        if target is None:
            continue
        p = ev.get("payload") or {}
        c = _num(p.get("total_cost_usd"))
        if c is not None and p.get("session_id"):
            target[p["session_id"]] = target.get(p["session_id"], 0.0) + c
    return parsed or raw


def cost_crosscheck(otel_events: Path, stream_events: Path) -> dict[str, dict]:
    """Per session ``{"otel_usd", "stream_usd", "rel_diff", "ok"}``; ok when within 1%.

    A session seen on only one side has ``None`` for the other, ``rel_diff`` ``None`` and ok false.
    """
    otel, stream = otel_cost_by_session(otel_events), stream_cost_by_session(stream_events)
    out = {}
    for sid in sorted(set(otel) | set(stream)):
        o, s = otel.get(sid), stream.get(sid)
        if o is None or s is None:
            out[sid] = {"otel_usd": o, "stream_usd": s, "rel_diff": None, "ok": False}
            continue
        top = max(abs(o), abs(s))
        rel = abs(o - s) / top if top else 0.0
        out[sid] = {"otel_usd": o, "stream_usd": s, "rel_diff": rel, "ok": rel <= TOLERANCE}
    return out
