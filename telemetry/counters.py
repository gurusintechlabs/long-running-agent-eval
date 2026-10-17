"""Counters derived from the event logs (docs/spec.md §6.3, docs/interfaces.md §6).

Every metric comes from the JSONL logs: OTel ``api_request`` events (tokens, cost, context fill),
the parsed agent stream (tool calls, compactions) and the orchestrator log (interval boundaries).
OTel numeric attributes may arrive as strings; non-numeric values are skipped, never fatal.
"""
from __future__ import annotations

import bisect
import json
import math
from pathlib import Path

import yaml

API_REQUEST = "claude_code.api_request"
DEFAULT_MODELS_YAML = Path(__file__).with_name("models.yaml")
FALLBACK_WINDOW = 200_000
COMPACTION_DROP = 0.5  # heuristic: prompt tokens fall by more than this fraction

_TOKEN_FIELDS = {"tokens_in": "input_tokens", "tokens_out": "output_tokens",
                 "tokens_cache_read": "cache_read_tokens", "tokens_cache_creation": "cache_creation_tokens"}
_CUM = ("tokens_in", "tokens_out", "tokens_cache_read", "tokens_cache_creation", "cost_usd",
        "tool_calls", "compactions", "turns")


def _read(path: Path) -> list[dict]:
    out = []
    try:
        with open(path) as fh:
            for line in fh:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict):
                    out.append(ev)
    except OSError:
        pass
    return out


def _num(v) -> float | None:
    """Float for a number or numeric string; ``None`` for anything else (including NaN/inf)."""
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _api_requests(otel_events: Path) -> list[dict]:
    return [ev for ev in _read(otel_events) if ev.get("type") == API_REQUEST]


def cumulative_cost(otel_events: Path) -> float:
    """Σ ``cost_usd`` over ``claude_code.api_request`` events in an ``otel.jsonl`` file."""
    return sum(_num((ev.get("payload") or {}).get("cost_usd")) or 0.0 for ev in _api_requests(otel_events))


def cumulative_tokens(otel_events: Path) -> int:
    """Σ input + output + cache read + cache creation tokens over ``api_request`` events."""
    total = 0.0
    for ev in _api_requests(otel_events):
        p = ev.get("payload") or {}
        total += sum(_num(p.get(f)) or 0.0 for f in _TOKEN_FIELDS.values())
    return int(total)


# -- context windows -------------------------------------------------------------------------

def load_models(models_yaml: Path | None = None) -> tuple[dict[str, int], int]:
    """``(model id -> window, default window)`` from ``models.yaml``; tolerant of a bad file."""
    try:
        doc = yaml.safe_load(Path(models_yaml or DEFAULT_MODELS_YAML).read_text()) or {}
    except (OSError, yaml.YAMLError):
        doc = {}
    models = {str(k): int(v) for k, v in (doc.get("models") or {}).items() if _num(v)}
    return models, int(_num(doc.get("default_context_window")) or FALLBACK_WINDOW)


def _stream_windows(stream_events: list[dict]) -> dict[str, int]:
    """Context windows reported in ``result.modelUsage`` (parsed or raw result events)."""
    out: dict[str, int] = {}
    for ev in stream_events:
        if ev.get("type") in ("session.result", "stream.result"):
            for model, mu in ((ev.get("payload") or {}).get("modelUsage") or {}).items():
                w = _num((mu or {}).get("contextWindow")) if isinstance(mu, dict) else None
                if w:
                    out[model] = int(w)
    return out


def context_window(model, table: dict[str, int], stream: dict[str, int], default: int) -> int:
    """Window for ``model``: the CLI's own report (stream ``modelUsage[*].contextWindow``) first, since
    it is instrumentation and follows the account's actual window; then the table (exact, then
    longest prefix), then default. (The table said 200k for claude-opus-5-5 while CLI 2.1.301
    reported 1,000,000, which put context fill at 350%.)"""
    model = str(model or "")
    base = model[:-4] if model.endswith("[1m]") else model
    if stream.get(model) or stream.get(base):
        return stream.get(model) or stream.get(base)
    if base in table or model in table:
        return table.get(model, table.get(base, default))
    if model.endswith("[1m]"):
        return 1_000_000
    prefixes = [k for k in table if base.startswith(k)]
    if prefixes:
        return table[max(prefixes, key=len)]
    return stream.get(model) or stream.get(base) or default


# -- interval boundaries ----------------------------------------------------------------------

def interval_boundaries(orchestrator_events: list[dict]) -> list[int]:
    """``[start, end_1, ..., end_n]`` in mono_ns (docs/interfaces.md §1).

    ``start`` is the RUNNING state event after the first ``run.clock`` (the clock event itself if
    that is missing); each ``checkpoint`` closes an interval. A repeated ``k`` (replayed after a
    resume) replaces the earlier one.
    """
    clock, start, ends = None, None, {}
    for ev in orchestrator_events:
        t, mono = ev.get("type"), ev.get("mono_ns")
        if not isinstance(mono, int):
            continue
        if t == "run.clock" and clock is None:
            clock = mono
        elif t == "state" and clock is not None and start is None \
                and (ev.get("payload") or {}).get("to") == "RUNNING":
            start = mono
        elif t == "checkpoint":
            k = (ev.get("payload") or {}).get("k", len(ends) + 1)
            ends[k] = mono
    start = start if start is not None else clock
    if start is None:
        return []
    return [start, *[ends[k] for k in sorted(ends)]]


def _interval_index(bounds: list[int], mono) -> int | None:
    """0-based interval of ``mono`` or ``None`` when outside ``[bounds[0], bounds[-1])``."""
    if not isinstance(mono, int) or not bounds or mono < bounds[0] or mono >= bounds[-1]:
        return None
    return bisect.bisect_right(bounds, mono) - 1


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[max(0, math.ceil(0.95 * len(s)) - 1)]


# -- the counters ------------------------------------------------------------------------------

def _compaction_flags(requests: list[dict], event_sessions: set) -> dict[int, bool]:
    """id(request event) -> heuristic compaction, for sessions with no stream compaction events."""
    prev: dict[str, float] = {}
    flags: dict[int, bool] = {}
    for ev in requests:
        p = ev.get("payload") or {}
        sid = p.get("session.id")
        tokens = sum(_num(p.get(f)) or 0.0 for f in ("input_tokens", "cache_read_tokens", "cache_creation_tokens"))
        if sid is None or sid in event_sessions:
            continue
        before = prev.get(sid)
        if before and tokens < before * (1 - COMPACTION_DROP):
            flags[id(ev)] = True
        prev[sid] = tokens
    return flags


def interval_counters(events_dir: Path, models_yaml: Path | None = None) -> list[dict]:
    """One dict per checkpoint ``k`` (1-based) with the counters of docs/interfaces.md §6.

    Returns ``[]`` when the orchestrator log has no start boundary or no checkpoint.
    """
    events_dir = Path(events_dir)
    bounds = interval_boundaries(_read(events_dir / "orchestrator.jsonl"))
    n = len(bounds) - 1
    if n < 1:
        return []
    orch = _read(events_dir / "orchestrator.jsonl")
    stream = _read(events_dir / "agent_stream.jsonl")
    requests = _api_requests(events_dir / "otel.jsonl")
    otel_all = _read(events_dir / "otel.jsonl")
    table, default = load_models(models_yaml)
    swin = _stream_windows(stream)

    rows = [{"k": i + 1, **{c: 0 for c in _TOKEN_FIELDS}, "cost_usd": 0.0, "tool_calls": 0,
             "compactions": 0, "turns": 0, "api_errors": 0} for i in range(n)]
    fills: list[list[float]] = [[] for _ in range(n)]
    sessions: list[set] = [set() for _ in range(n)]
    lags: list[list[float]] = [[] for _ in range(n)]

    event_sessions = {(e.get("payload") or {}).get("session_id") for e in stream
                      if e.get("type") == "context.compaction"}
    flags = _compaction_flags(requests, event_sessions)
    for ev in requests:
        i = _interval_index(bounds, ev.get("mono_ns"))
        if i is None:
            continue
        p = ev.get("payload") or {}
        for name, field in _TOKEN_FIELDS.items():
            rows[i][name] += int(_num(p.get(field)) or 0)
        rows[i]["cost_usd"] += _num(p.get("cost_usd")) or 0.0
        if p.get("session.id"):
            sessions[i].add(p["session.id"])
        prompt = sum(_num(p.get(f)) or 0.0 for f in ("input_tokens", "cache_read_tokens", "cache_creation_tokens"))
        fills[i].append(prompt / context_window(p.get("model"), table, swin, default))
        rows[i]["compactions"] += flags.get(id(ev), False)
    for ev in otel_all:
        i = _interval_index(bounds, ev.get("mono_ns"))
        if i is None:
            continue
        p = ev.get("payload") or {}
        if ev.get("type") == "claude_code.api_error":
            rows[i]["api_errors"] += 1
        lag = _num(p.get("_otel_lag_ms"))
        if lag is not None:
            lags[i].append(lag)
    for ev in stream:
        i = _interval_index(bounds, ev.get("mono_ns"))
        if i is None:
            continue
        t, p = ev.get("type"), ev.get("payload") or {}
        if t == "tool.call":
            rows[i]["tool_calls"] += 1
        elif t == "context.compaction":
            rows[i]["compactions"] += 1
        elif t == "session.init" and p.get("session_id"):
            sessions[i].add(p["session_id"])
    for ev in orch:
        i = _interval_index(bounds, ev.get("mono_ns"))
        if i is not None and ev.get("type") == "turn.start":
            rows[i]["turns"] += 1

    cum = dict.fromkeys(_CUM, 0)
    for i, row in enumerate(rows):
        row["context_fill_max"] = max(fills[i]) if fills[i] else None
        row["context_fill_last"] = fills[i][-1] if fills[i] else None
        row["sessions"] = len(sessions[i])
        row["otel_lag_ms_p95"] = _p95(lags[i])
        for c in _CUM:
            cum[c] += row[c]
            row[f"cum_{c}"] = cum[c]
    return rows
