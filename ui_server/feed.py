"""Display events: one stable shape for the Live feed and the run-detail Events tab (docs/ui-api-live.md §4).

A registry of per-type summarizers turns a raw log envelope into::

    {id, cursor, ts, t_s, seq, source, type, kind, title, summary, severity, level,
     pair, payload_preview, truncated, fold}

* ``cursor`` is the event's *ref* (``<source>:<byte offset of its line>``), unique within a run.
* ``kind`` picks the card the frontend draws (see ``KINDS``); unknown types fall back to ``generic``.
* ``severity``: ``info`` | ``warning`` | ``violation`` | ``kill``.  ``level``: ``info`` | ``debug``
  (debug rows are raw CLI echoes, per-request OTel and scorer internals; hidden by default).
* ``payload_preview`` is a size-capped copy of the payload (long strings cut, lists and depth limited);
  ``truncated`` says whether anything was cut. The whole event is one call away (``/feed/event``).
* All text here is untrusted agent output: ``title`` and ``summary`` are single-line, stripped of
  control and bidi-override characters. The frontend must still render everything as text.
"""
from __future__ import annotations

import re
import unicodedata
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ui_server import store

SCHEMA_VERSION = 1
STR_CAP = 400            # per string in a preview
STR_CAP_FULL = 20_000
LIST_CAP = 20
KEY_CAP = 30
DEPTH_CAP = 4
PREVIEW_JSON_CAP = 6_000      # whole preview, serialised
PREVIEW_JSON_CAP_FULL = 400_000
SUMMARY_CAP = 220
TITLE_CAP = 120

KINDS = {
    "tool_call": "A tool the agent called (name, short input).",
    "tool_result": "The result of a tool call (ok or error, size, duration).",
    "assistant_text": "Text the agent wrote.",
    "session": "Session start, result or context compaction.",
    "test_run": "The agent ran the test suite (passed / failed counts).",
    "checkpoint": "A checkpoint snapshot was taken.",
    "stage": "A task stage (or change request) was delivered to the agent.",
    "turn": "A turn started or ended.",
    "state": "The run changed state.",
    "run": "Run clock, completion, resume, errors, pre-flight and the like.",
    "counterpart": "The simulated colleague / services (ops inbox, requests, fixtures, embed mode).",
    "env": "A planned environment mutation was applied.",
    "budget": "Budget exhausted or extended.",
    "guardrail": "A guardrail rule fired (warning or violation).",
    "kill": "The kill switch froze the agent.",
    "scorer": "Checkpoint scoring, hazards and behaviour signals.",
    "usage": "Per-request token and cost data (OTel).",
    "raw": "A raw CLI stream message (echo of the parsed events).",
    "folded": "Several noisy events folded into one row (telemetry silence).",
    "generic": "Anything else: type, first fields, JSON on expand.",
}
SEVERITIES = ("info", "warning", "violation", "kill")
LEVELS = ("info", "debug")
SOURCE_LABELS = {"agent_stream": "Agent", "orchestrator": "Run", "guardrail": "Guardrails",
                 "counterpart": "Counterpart", "env": "Environment", "scorer": "Scorer", "otel": "Telemetry"}
TERMINAL_BAD = {"KILLED", "BUDGET_EXHAUSTED", "FAILED", "INTERRUPTED"}

_BAD_CHARS = {chr(i) for i in range(0x20)} | {chr(0x7F)}
_BIDI = dict.fromkeys(map(ord, "​‌‍‎‏‪‫‬‭‮"
                          "⁦⁧⁨⁩﻿  "), None)


def sanitize(text: Any, cap: int = SUMMARY_CAP) -> str:
    """One line of plain text: control and bidi characters removed, whitespace collapsed, cut at ``cap``."""
    s = text if isinstance(text, str) else str(text)
    s = s.translate(_BIDI)
    s = "".join(" " if c in _BAD_CHARS else c for c in s if unicodedata.category(c) != "Cc" or c in _BAD_CHARS)
    s = " ".join(s.split())
    return s if len(s) <= cap else s[: cap - 1] + "…"


def ts_epoch(ts: Any) -> float | None:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class RunClock:
    """Run-offset seconds from wall time, from the ``run.clock`` events (``offset_s`` > 0 after a resume)."""

    def __init__(self):
        self.marks: list[tuple[float, float]] = []   # (start_epoch, offset_s), in order

    def add(self, start_epoch: Any, offset_s: Any = 0.0) -> None:
        if isinstance(start_epoch, (int, float)) and not isinstance(start_epoch, bool):
            off = offset_s if isinstance(offset_s, (int, float)) and not isinstance(offset_s, bool) else 0.0
            mark = (float(start_epoch), float(off))
            if mark not in self.marks:
                self.marks.append(mark)
                self.marks.sort()

    def t_s(self, epoch: float | None) -> float | None:
        if epoch is None or not self.marks:
            return None
        cur = None
        for start, off in self.marks:
            if start <= epoch + 0.5:
                cur = (start, off)
        if cur is None:
            return None
        return round(epoch - cur[0] + cur[1], 3)

    @classmethod
    def from_events(cls, events) -> RunClock:
        c = cls()
        for ev in events:
            if ev.get("type") == "run.clock":
                p = ev.get("payload") or {}
                c.add(p.get("start_epoch"), p.get("offset_s"))
        return c


_CLOCK_CACHE: dict[str, tuple[tuple[int, int], RunClock]] = {}


def load_clock(run_dir: Path) -> RunClock:
    """Clock of a run from its orchestrator log (cached by size and mtime)."""
    path = Path(run_dir) / "events" / "orchestrator.jsonl"
    try:
        st = path.stat()
    except OSError:
        return RunClock()
    key = (st.st_size, st.st_mtime_ns)
    hit = _CLOCK_CACHE.get(str(path))
    if hit and hit[0] == key:
        return hit[1]
    clock = RunClock.from_events(e for e in store.read_jsonl(path) if e.get("type") == "run.clock")
    if len(_CLOCK_CACHE) > 32:
        _CLOCK_CACHE.pop(next(iter(_CLOCK_CACHE)))
    _CLOCK_CACHE[str(path)] = (key, clock)
    return clock


class FeedContext:
    """State a stream needs between events: the run clock and the open tool calls."""

    def __init__(self, clock: RunClock | None = None, *, full: bool = False):
        self.clock = clock or RunClock()
        self.full = full
        self.calls: OrderedDict[str, tuple[float | None, str]] = OrderedDict()

    def remember_call(self, tool_use_id: Any, epoch: float | None, tool: str) -> None:
        if isinstance(tool_use_id, str) and tool_use_id:
            self.calls[tool_use_id] = (epoch, tool)
            while len(self.calls) > 1000:
                self.calls.popitem(last=False)


# ---- preview ----------------------------------------------------------------------------------

def preview(obj: Any, *, full: bool = False) -> tuple[Any, bool]:
    """``(capped copy, truncated)``: strings cut at ``STR_CAP``, lists/dicts/depth limited."""
    cut = [False]
    scap = STR_CAP_FULL if full else STR_CAP
    lcap = 10_000 if full else LIST_CAP
    kcap = 500 if full else KEY_CAP
    dcap = 12 if full else DEPTH_CAP

    def go(v: Any, depth: int) -> Any:
        if isinstance(v, str):
            if len(v) > scap:
                cut[0] = True
                return v[:scap] + f"…[+{len(v) - scap} chars]"
            return v
        if isinstance(v, (int, float, bool)) or v is None:
            return v
        if depth >= dcap:
            cut[0] = True
            return "…[nested]"
        if isinstance(v, list):
            if len(v) > lcap:
                cut[0] = True
            return [go(x, depth + 1) for x in v[:lcap]] + ([f"…[+{len(v) - lcap} items]"] if len(v) > lcap else [])
        if isinstance(v, dict):
            items = list(v.items())
            if len(items) > kcap:
                cut[0] = True
            out = {str(k)[:80]: go(x, depth + 1) for k, x in items[:kcap]}
            if len(items) > kcap:
                out["…"] = f"[+{len(items) - kcap} keys]"
            return out
        cut[0] = True
        return str(v)[:scap]

    out = go(obj, 0)
    import json
    try:
        size = len(json.dumps(out, ensure_ascii=False))
    except (TypeError, ValueError):
        size = PREVIEW_JSON_CAP + 1
    if size > (PREVIEW_JSON_CAP_FULL if full else PREVIEW_JSON_CAP):
        text = json.dumps(out, ensure_ascii=False, default=str)[: (PREVIEW_JSON_CAP_FULL if full else 2000)]
        return {"_json_prefix": text}, True
    return out, cut[0]


# ---- summarizers ------------------------------------------------------------------------------

Summary = dict   # {kind, title, summary, severity?, level?, pair?}
_REG: dict[str, tuple[Callable[[dict, dict, FeedContext], Summary], str]] = {}
_PREFIX_REG: list[tuple[str, Callable[[dict, dict, FeedContext], Summary], str]] = []


def summarizer(*types: str, doc: str = ""):
    def deco(fn):
        for t in types:
            _REG[t] = (fn, doc)
        return fn
    return deco


def _s(kind, title, summary="", severity="info", level="info", pair=None) -> Summary:
    return {"kind": kind, "title": title, "summary": summary, "severity": severity, "level": level, "pair": pair}


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _short_input(tool: str, inp: Any) -> str:
    if not isinstance(inp, dict):
        return sanitize(inp) if inp else ""
    for key in ("command", "file_path", "notebook_path", "path", "pattern", "query", "url", "description",
                "text", "message", "prompt"):
        v = inp.get(key)
        if isinstance(v, str) and v:
            extra = ""
            if tool in ("Grep", "Glob") and key == "pattern" and isinstance(inp.get("path"), str):
                extra = f"  in {inp['path']}"
            return sanitize(v + extra)
    for k, v in inp.items():
        if isinstance(v, (str, int, float, bool)):
            return sanitize(f"{k}={v}")
    return sanitize(", ".join(map(str, inp))[:SUMMARY_CAP]) if inp else "(no input)"


@summarizer("tool.call", doc="Tool name and the most telling input field (command, path, pattern).")
def _tool_call(p, ev, ctx):
    tool = str(p.get("tool") or "tool")
    ctx.remember_call(p.get("tool_use_id"), ts_epoch(ev.get("ts")), tool)
    return _s("tool_call", sanitize(tool, TITLE_CAP), _short_input(tool, p.get("input")),
              pair=p.get("tool_use_id"))


@summarizer("tool.result", doc="ok/error, size in bytes and the duration when the call was seen.")
def _tool_result(p, ev, ctx):
    t0, tool = ctx.calls.pop(p.get("tool_use_id"), (None, ""))
    dur = None
    t1 = ts_epoch(ev.get("ts"))
    if t0 is not None and t1 is not None:
        dur = max(0.0, t1 - t0)
    bad = bool(p.get("is_error"))
    bits = [f"{p['size']} B"] if _num(p.get("size")) is not None else []
    if dur is not None:
        bits.append(f"{dur:.1f} s")
    tail = p.get("text_tail")
    if isinstance(tail, str) and tail:
        bits.append(sanitize(tail, 140))
    return _s("tool_result", f"{sanitize(tool or 'tool', 60)} {'error' if bad else 'ok'}", " · ".join(bits),
              "warning" if bad else "info", pair=p.get("tool_use_id"))


@summarizer("assistant.text", doc="The agent's text, first 220 characters.")
def _assistant(p, ev, ctx):
    return _s("assistant_text", "Agent", sanitize(p.get("text") or ""))


@summarizer("session.init")
def _init(p, ev, ctx):
    tools = p.get("tools") if isinstance(p.get("tools"), list) else []
    return _s("session", "Session started", sanitize(f"{p.get('model', '?')}, {len(tools)} tools"))


@summarizer("session.result")
def _result(p, ev, ctx):
    bad = bool(p.get("is_error"))
    cost = _num(p.get("total_cost_usd"))
    return _s("session", "Session result" + (" (error)" if bad else ""),
              sanitize(f"{p.get('subtype', '')}, {p.get('num_turns', '?')} turns"
                       + (f", ${cost:.2f}" if cost is not None else "")), "warning" if bad else "info")


@summarizer("context.compaction", "claude_code.compaction")
def _compaction(p, ev, ctx):
    return _s("session", "Context compacted", sanitize(f"{p.get('trigger', '')} at {p.get('pre_tokens', '?')} tokens"),
              "warning", level="info" if ev.get("source") != "otel" else "debug")


@summarizer("agent.test_run", doc="The agent's own test run: passed / failed / errors.")
def _test_run(p, ev, ctx):
    f, e = _num(p.get("failed")) or 0, _num(p.get("errors")) or 0
    return _s("test_run", "Agent ran tests", sanitize(p.get("raw_summary") or
                                                         f"{p.get('passed', 0)} passed, {f} failed"),
              "warning" if f or e else "info")


@summarizer("checkpoint")
def _checkpoint(p, ev, ctx):
    fin = p.get("final")
    cost = _num(p.get("cumulative_cost_usd"))
    sha = str(p.get("head_sha") or "")[:8]
    return _s("checkpoint", f"Checkpoint {p.get('k', '?')}" + (f" (final: {fin})" if fin else ""),
              sanitize(f"commit {sha or '?'}, {p.get('file_count', '?')} files"
                       + (f", ${cost:.2f} so far" if cost is not None else "")),
              "warning" if fin else "info")


@summarizer("stage.delivered")
def _stage(p, ev, ctx):
    kind = " (change request)" if p.get("kind") == "change_request" else ""
    return _s("stage", f"Stage {p.get('stage', '?')} delivered{kind}", sanitize(f"from {p.get('source', 'task')}"))


@summarizer("turn.start")
def _turn_start(p, ev, ctx):
    return _s("turn", "Turn started", sanitize(f"prompt {p.get('prompt_chars', '?')} chars"
                                               + (", first turn" if p.get("first") else "")))


@summarizer("turn.end")
def _turn_end(p, ev, ctx):
    rc = p.get("returncode")
    return _s("turn", f"Turn {p.get('turn', '?')} ended", f"exit code {rc}", "info" if rc == 0 else "warning")


@summarizer("state")
def _state(p, ev, ctx):
    to = str(p.get("to") or "?")
    return _s("state", f"State: {sanitize(p.get('from') or '?', 40)} to {sanitize(to, 40)}",
              sanitize(p.get("reason") or ""), "warning" if to in TERMINAL_BAD else "info")


@summarizer("run.clock", "run.done", "run.resumed", "run.error", "preflight", "preflight.probe", "guardrails",
            "user_memory", "honey.provisioned", "agent.safe_mode", "directive.issued", "directive.lifted",
            "cleanup.error", "platform.interruption")
def _run_misc(p, ev, ctx):
    t = ev.get("type")
    if t == "run.clock":
        return _s("run", "Run clock started", sanitize(f"offset {p.get('offset_s', 0)} s"))
    if t == "run.done":
        return _s("run", "Agent finished all its work", sanitize(f"{p.get('turns', '?')} turns"))
    if t == "run.resumed":
        return _s("run", "Run resumed", sanitize(f"from checkpoint {p.get('from_k', '?')}"), "warning")
    if t == "run.error":
        return _s("run", "Harness error", sanitize(p.get("error") or ""), "violation")
    if t == "cleanup.error":
        return _s("run", "Cleanup error", sanitize(f"{p.get('step', '')}: {p.get('error', '')}"), "warning")
    if t == "platform.interruption":
        return _s("run", f"Interruption: {sanitize(p.get('kind') or '?', 40)}", sanitize(p.get("detail") or ""), "warning")
    if t in ("preflight", "preflight.probe"):
        bad = [str(c.get("name")) for c in p.get("checks", []) if isinstance(c, dict) and not c.get("ok")]
        return _s("run", "Pre-flight" + (" probe" if t.endswith("probe") else ""),
                  "all checks passed" if not bad else sanitize("FAILED: " + ", ".join(bad)),
                  "violation" if bad else "info", level="info" if bad else "debug")
    if t in ("directive.issued", "directive.lifted"):
        return _s("run", "Directive " + t.split(".")[1], sanitize(f"{p.get('id', '')} freeze {p.get('freeze', '')}"))
    return _s("run", t.replace(".", " ").replace("_", " ").capitalize(), "", level="debug")


@summarizer("scorer.queued", "scorer.start", "scorer.metric", "scorer.commit",
            doc="Scorer internals: hidden by default (level debug).")
def _scorer_debug(p, ev, ctx):
    t = ev["type"]
    if t == "scorer.metric":
        v = _num(p.get("value"))
        return _s("scorer", f"Metric {sanitize(p.get('name') or '?', 40)}", "n/a" if v is None else f"{v:.3f}",
                  level="debug")
    return _s("scorer", t.replace("scorer.", "Scorer ").replace("_", " "), sanitize(f"checkpoint {p.get('k', '?')}"),
              level="debug")


@summarizer("scorer.finished", "scorer.done", doc="A checkpoint finished scoring.")
def _scorer_done(p, ev, ctx):
    ok = p.get("ok", p.get("returncode", 0) == 0)
    dur = _num(p.get("duration_s"))
    return _s("scorer", f"Checkpoint {p.get('k', '?')} " + ("scored" if ok else "scoring FAILED"),
              sanitize((f"{dur:.0f} s" if dur is not None else "") + (f" {p.get('error')}" if p.get("error") else "")),
              "info" if ok else "warning")


@summarizer("scorer.hazard", doc="A hazard (dimension, rule, evidence).")
def _hazard(p, ev, ctx):
    return _s("scorer", f"Hazard: {sanitize(p.get('dimension') or '?', 30)} ({sanitize(p.get('rule') or '', 40)})",
              sanitize(p.get("evidence") or ""), "violation")


@summarizer("scorer.behavior", doc="A behaviour-detector signal (mode, detector, evidence).")
def _behavior(p, ev, ctx):
    hz = bool(p.get("hazard"))
    return _s("scorer", f"Behaviour {sanitize(p.get('mode') or '?', 12)}: {sanitize(p.get('detector') or '?', 60)}",
              sanitize(p.get("evidence") or ""), "violation" if hz else "warning")


@summarizer("guardrail.violation", doc="Rule id, severity, channel and the evidence text.")
def _violation(p, ev, ctx):
    kill = p.get("action") == "kill"
    sev = "kill" if kill else "violation" if p.get("severity") == "violation" else "warning"
    return _s("guardrail", f"{sanitize(p.get('rule_id') or '?', 60)} ({p.get('severity', '?')}, {p.get('action', '?')})",
              sanitize(p.get("evidence") or ""), sev)


@summarizer("guardrail.kill", doc="The kill switch fired: rule, reason and freeze latency.")
def _kill(p, ev, ctx):
    lat = _num(p.get("freeze_latency_ms"))
    return _s("kill", f"KILL SWITCH ({sanitize(p.get('reason') or '?', 20)})",
              sanitize(f"rule {p.get('rule_id', '?')}" + (f", frozen in {lat:.0f} ms" if lat is not None else "")), "kill")


@summarizer("guardrail.budget", doc="The budget cap was reached.")
def _budget(p, ev, ctx):
    usd, cap = _num(p.get("cost_usd")), _num(p.get("per_run_usd"))
    return _s("budget", "Budget exhausted",
              sanitize((f"${usd:.2f}" if usd is not None else "?") + (f" of ${cap:.2f}" if cap is not None else "")
                       + (f", {p.get('tokens'):,} tokens" if isinstance(p.get("tokens"), int) else "")), "violation")


@summarizer("guardrail.budget_extended")
def _budget_ext(p, ev, ctx):
    return _s("budget", "Budget extended", sanitize(f"${p.get('from_usd')} to ${p.get('to_usd')}: {p.get('reason', '')}"),
              "warning")


@summarizer("guardrail.telemetry_stalled", "guardrail.telemetry_resumed",
            doc="Folded: pairs collapse into one 'telemetry silent' row (see Folder).")
def _stall(p, ev, ctx):
    if ev["type"].endswith("stalled"):
        return _s("folded", "Telemetry stalled", sanitize(f"{p.get('reason', '')} {p.get('silence_s', '')}"), level="debug")
    return _s("folded", "Telemetry resumed", sanitize(f"paused {p.get('paused_s', '?')} s"), level="debug")


@summarizer("guardrail.monitor", "guardrail.kill_error", "procmon.connection", "procmon.fixture_died")
def _monitor(p, ev, ctx):
    t = ev["type"]
    if t == "guardrail.monitor":
        st = p.get("status")
        return _s("guardrail", f"Guardrail monitor {st}", sanitize(p.get("error") or ""),
                  "warning" if st == "error" else "info", level="info" if st == "error" else "debug")
    if t == "guardrail.kill_error":
        return _s("guardrail", "Kill step failed", sanitize(f"{p.get('step')}: {p.get('error')}"), "violation")
    if t == "procmon.connection":
        return _s("guardrail", "Outbound connection", sanitize(f"{p.get('name')} to {p.get('remote')}"), "warning")
    return _s("guardrail", "Fixture process died", sanitize(f"{p.get('name')} exit {p.get('returncode')}"), "violation")


@summarizer("ops.message", "ops.request", "ops.checkin_queued", "ops.inbox", "ops.started", "embed.mode",
            "fixture.started", "fixture.stopped", doc="What the simulated colleague / services said or did.")
def _counterpart(p, ev, ctx):
    t = ev["type"]
    if t == "ops.message":
        return _s("counterpart", "Ops message", sanitize(p.get("text") or ""))
    if t == "ops.request":
        return _s("counterpart", f"Ops request: {sanitize(p.get('kind') or '?', 40)}",
                  sanitize(p.get("target") or p.get("justification") or ""))
    if t == "ops.checkin_queued":
        return _s("counterpart", "Supervisor check-in queued", sanitize(p.get("text") or ""))
    if t == "ops.inbox":
        n = _num(p.get("delivered")) or 0
        return _s("counterpart", "Ops inbox read", f"{int(n)} delivered", level="info" if n else "debug")
    if t.startswith("fixture."):
        return _s("counterpart", f"Fixture {t.split('.')[1]}", sanitize(f"{p.get('name', '')} {p.get('kind', '')}"))
    if t == "embed.mode":
        return _s("counterpart", "Embedding service mode", sanitize(f"api {p.get('api')}, flaky {p.get('flaky')}"))
    return _s("counterpart", "Ops service started", "", level="debug")


@summarizer("env.mutated", "env.replayed", doc="A planned change to the environment (counterpart mode, files).")
def _env(p, ev, ctx):
    verb = "replayed" if ev["type"] == "env.replayed" else "changed"
    return _s("env", f"Environment {verb}", sanitize(f"stage {p.get('stage', '?')}: {p.get('action', '')} "
                                                   f"{p.get('service', p.get('path', ''))}"), "warning")


@summarizer("claude_code.api_request", doc="One API request: model, tokens, cost (level debug).")
def _api_request(p, ev, ctx):
    cost = _num(_f(p.get("cost_usd")))
    return _s("usage", "API request", sanitize(
        f"{p.get('model', '?')}: in {p.get('input_tokens', '?')}, out {p.get('output_tokens', '?')}, "
        f"cache {p.get('cache_read_tokens', '?')}" + (f", ${cost:.4f}" if cost is not None else "")), level="debug")


@summarizer("claude_code.api_error")
def _api_error(p, ev, ctx):
    return _s("usage", "API error", sanitize(f"{p.get('status_code', '')} {p.get('error', '')}"), "warning")


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _stream_raw(p, ev, ctx):
    t = ev["type"]
    if t in ("stream.invalid", "stream.parse_error"):
        return _s("raw", "Unparseable CLI line", sanitize(p.get("raw") or p.get("error") or ""), "warning")
    return _s("raw", t, sanitize(p.get("subtype") or p.get("type") or ""), level="debug")


_PREFIX_REG.append(("stream.", _stream_raw, "Raw CLI stream messages: echoes of the parsed events, level debug."))


def _otel_other(p, ev, ctx):
    return _s("usage", ev["type"].replace("claude_code.", ""), sanitize(p.get("name") or p.get("value") or ""), level="debug")


_PREFIX_REG.append(("claude_code.", _otel_other, "Other OTel events and metrics, level debug."))


def _generic(p, ev, ctx):
    typ = str(ev.get("type") or "(no type)")
    bits = []
    if isinstance(p, dict):
        for k, v in p.items():
            if isinstance(v, (str, int, float, bool)) and len(bits) < 4:
                bits.append(f"{k}={v}")
    return _s("generic", sanitize(typ, TITLE_CAP), sanitize(" ".join(bits)))


def _lookup(typ: str):
    if typ in _REG:
        return _REG[typ][0]
    for pre, fn, _doc in _PREFIX_REG:
        if typ.startswith(pre):
            return fn
    return _generic


def level_of(source: str, typ: str | None) -> str:
    """Visibility class from the envelope alone (no payload), so a tail can skip parsing hidden lines."""
    if not typ:
        return "info"
    if typ.startswith("stream."):
        return "info" if typ in ("stream.invalid", "stream.parse_error") else "debug"
    if source == "otel" or typ.startswith("claude_code."):
        return "info" if typ == "claude_code.api_error" else "debug"
    if typ in _REG or any(typ.startswith(p) for p, _f_, _d in _PREFIX_REG):
        return _DEBUG_TYPES.get(typ, "info")
    return "info"


# types whose summarizer always yields level debug (decidable without the payload). Stall events are not
# listed: the Folder turns them into a visible row.
_DEBUG_TYPES = {t: "debug" for t in ("scorer.queued", "scorer.start", "scorer.metric", "scorer.commit",
                                     "ops.started")}


def display_event(source: str, offset: int, ev: dict, ctx: FeedContext, *, line_end: int | None = None) -> dict:
    """The display event for one parsed envelope. Never raises."""
    typ = ev.get("type") if isinstance(ev.get("type"), str) else "(no type)"
    p = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    try:
        s = _lookup(typ)(p, {**ev, "type": typ, "source": source}, ctx)
    except Exception as exc:   # a summarizer bug must not break the feed
        s = _s("generic", sanitize(typ, TITLE_CAP), sanitize(f"(could not summarise: {exc.__class__.__name__})"))
    ep = ts_epoch(ev.get("ts"))
    prev, cut = preview(p, full=ctx.full)
    ref = f"{source}:{offset}"
    return {
        "id": ref, "cursor": ref, "ts": ev.get("ts") if isinstance(ev.get("ts"), str) else None,
        "t_s": ctx.clock.t_s(ep), "seq": ev.get("seq") if isinstance(ev.get("seq"), int) else None,
        "source": source, "type": typ, "kind": s["kind"] if s["kind"] in KINDS else "generic",
        "title": sanitize(s["title"], TITLE_CAP), "summary": sanitize(s["summary"]),
        "severity": s["severity"] if s["severity"] in SEVERITIES else "info",
        "level": s["level"] if s["level"] in LEVELS else "info",
        "pair": sanitize(s["pair"], 200) if isinstance(s.get("pair"), str) else None,
        "payload_preview": prev, "truncated": cut, "fold": None,
    }


def placeholder_event(source: str, offset: int, ts: str, kind: str, size: int, ctx: FeedContext) -> dict:
    """Stand-in for a line that cannot be shown: longer than the read cap, or not JSON."""
    ref = f"{source}:{offset}"
    big = kind == "oversize"
    return {
        "id": ref, "cursor": ref, "ts": ts or None, "t_s": ctx.clock.t_s(ts_epoch(ts)), "seq": None,
        "source": source, "type": "log.oversize" if big else "log.invalid", "kind": "generic",
        "title": "Event too large to show" if big else "Unreadable log line",
        "summary": f"{size} bytes" + (" (over the 1 MiB read cap; skipped)" if big else " (not valid JSON)"),
        "severity": "warning", "level": "info", "pair": None, "payload_preview": {}, "truncated": True, "fold": None,
    }


# ---- folding ----------------------------------------------------------------------------------

class Folder:
    """Collapses ``guardrail.telemetry_stalled``/``telemetry_resumed`` pairs into one row.

    ``apply(display_event)`` returns the display event to emit, or ``None`` for a suppressed raw event.
    The folded row has a stable ``id`` (``fold:telemetry_stall``); each new pair re-emits it with updated
    counts, and the client replaces the row with the same id. ``cursor`` is the latest member.
    """

    ID = "fold:telemetry_stall"

    def __init__(self):
        self.pairs = 0
        self.open = False
        self.total_paused_s = 0.0
        self.silence: list[float] = []
        self.reasons: dict[str, int] = {}
        self.first: dict | None = None

    def apply(self, d: dict) -> dict | None:
        if d["type"] not in ("guardrail.telemetry_stalled", "guardrail.telemetry_resumed"):
            return d
        p = d["payload_preview"] if isinstance(d["payload_preview"], dict) else {}
        if self.first is None:
            self.first = d
        if d["type"].endswith("stalled"):
            self.open = True
            r = str(p.get("reason") or "?")
            self.reasons[r] = self.reasons.get(r, 0) + 1
            s = _num(p.get("silence_s"))
            if s is not None and len(self.silence) < 5000:
                self.silence.append(float(s))
        else:
            self.open = False
            self.pairs += 1
            self.total_paused_s += _num(p.get("paused_s")) or 0.0
        return self.render(d)

    def render(self, last: dict) -> dict:
        typical = round(sum(self.silence) / len(self.silence)) if self.silence else None
        n = self.pairs + (1 if self.open else 0)
        title = "Telemetry silent" + (f" ~{typical} s" if typical else "") + f" x {n}"
        first = self.first or last
        fold = {"group": "telemetry_stall", "pairs": self.pairs, "open": self.open,
                "total_paused_s": round(self.total_paused_s, 3), "typical_silence_s": typical,
                "reasons": dict(self.reasons), "first_cursor": first["cursor"], "first_t_s": first["t_s"],
                "last_cursor": last["cursor"], "last_t_s": last["t_s"]}
        return {**last, "id": self.ID, "kind": "folded", "type": "telemetry_silent", "title": title,
                "summary": "the OTel stream went quiet; the guardrail paused and resumed the agent"
                + (" (currently silent)" if self.open else ""),
                "severity": "warning" if self.open else "info", "level": "info", "pair": None, "fold": fold}


def fold_all(events: list[dict]) -> list[dict]:
    """Fold a finished list: one folded row at the first occurrence, with the final counts."""
    f = Folder()
    out: list[dict] = []
    idx: int | None = None
    for d in events:
        r = f.apply(d)
        if r is None:
            continue
        if r["id"] == Folder.ID:
            if idx is None:
                idx = len(out)
                out.append(r)
            else:
                out[idx] = r
        else:
            out.append(r)
    return out


def schema() -> dict:
    """Machine-readable description of the display event (served as ``/feed-schema``)."""
    types = []
    for t, (fn, doc) in sorted(_REG.items()):
        types.append({"type": t, "doc": doc or (fn.__doc__ or "").strip(), "level_hint": level_of("", t)})
    for pre, _fn, doc in _PREFIX_REG:
        types.append({"type": pre + "*", "doc": doc, "level_hint": "debug"})
    return {
        "version": SCHEMA_VERSION,
        "fields": {
            "id": "stable key; equals cursor except for folded rows (fold:telemetry_stall)",
            "cursor": "ref of the event: <source>:<byte offset of its line>",
            "ts": "envelope timestamp (UTC ISO) or null", "t_s": "seconds on the run clock, null before the clock starts",
            "seq": "per-file sequence number from the envelope", "source": "log file stem",
            "type": "raw event type", "kind": "card to draw, one of kinds",
            "title": "short single line", "summary": "single line, at most 220 characters",
            "severity": "info | warning | violation | kill", "level": "info | debug (debug hidden by default)",
            "pair": "tool_use_id linking a tool call with its result, else null",
            "payload_preview": "size-capped payload copy", "truncated": "true when anything was cut",
            "fold": "null, or {group, pairs, open, total_paused_s, ...} on a folded row",
        },
        "kinds": [{"kind": k, "doc": v} for k, v in KINDS.items()],
        "severities": list(SEVERITIES), "levels": list(LEVELS),
        "sources": [{"id": k, "label": v, "default_on": True} for k, v in SOURCE_LABELS.items()],
        "limits": {"string_chars": STR_CAP, "list_items": LIST_CAP, "keys": KEY_CAP, "depth": DEPTH_CAP,
                   "summary_chars": SUMMARY_CAP, "line_bytes": 1 << 20},
        "types": types,
    }
