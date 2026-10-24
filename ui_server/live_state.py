"""Incremental run status computed from the event logs only (docs/ui-api-live.md §3).

``RunLive`` keeps one byte offset per ``events/*.jsonl`` and folds only the new lines into its
counters, so ``/live`` can be polled every second or two on a run with tens of MB of logs. Hidden-heavy
lines (raw CLI echoes) are skipped by their envelope prefix and never parsed. Nothing is written.
Numbers come from the OTel ``api_request`` events (tokens, cost, context fill), the parsed agent
stream (tool calls) and the orchestrator log (state, checkpoints, stages), never from the agent's text.
"""
from __future__ import annotations

import json
import math
import threading
import time
from collections import Counter, OrderedDict, deque
from pathlib import Path

from telemetry.counters import context_window, load_models
from ui_server import safefs, store
from ui_server.feed import RunClock, ts_epoch
from ui_server.tailer import MAX_LINE, FileTail, list_event_files, peek

MAX_BYTES_PER_UPDATE = 48 << 20      # a first call on a huge log catches up over several calls
AMBER, RED = 0.75, 0.90
SERIES_MAX = 20_000
SERIES_OUT = 240
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens")
_MODELS = None


def _models():
    global _MODELS
    if _MODELS is None:
        _MODELS = load_models()
    return _MODELS


def num(v):
    """Float for numbers and numeric strings (OTel sends strings); None otherwise (NaN/inf too)."""
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def level_for(fraction: float | None) -> str:
    if fraction is None:
        return "ok"
    return "red" if fraction >= RED else "amber" if fraction >= AMBER else "ok"


def decimate(points: list, n: int = SERIES_OUT) -> list:
    if len(points) <= n:
        return list(points)
    step = len(points) / n
    out = [points[int(i * step)] for i in range(n - 1)]
    out.append(points[-1])
    return out


class RunLive:
    """Counters for one run, updated incrementally."""

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.lock = threading.RLock()
        self.reset()

    def reset(self) -> None:
        self.tails: dict[str, FileTail] = {}
        self.sizes: dict[str, int] = {}
        self.last_ts: dict[str, str] = {}
        self.clock = RunClock()
        self.state: str | None = None
        self.checkpoints: dict[int, dict] = {}
        self.stages: list[dict] = []
        self.turns = {"started": 0, "ended": 0, "failed": 0}
        self.queued: set[int] = set()
        self.finished: set[int] = set()
        self.scored_ok: set[int] = set()
        self.run_done: dict | None = None
        self.run_error: str | None = None
        self.interruptions: list[dict] = []
        self.requests = 0
        self.api_errors = 0
        self.tok = Counter()
        self.cost = 0.0
        self.last_request_ts: str | None = None
        self.last_model: str | None = None
        self.last_prompt: float | None = None
        self.max_prompt = 0.0
        self.stream_windows: dict[str, int] = {}
        self.compactions = 0
        self.cost_series: deque = deque(maxlen=SERIES_MAX)
        self.fill_series: deque = deque(maxlen=SERIES_MAX)
        self.tool_calls = 0
        self.tool_by: Counter = Counter()
        self.tool_errors = 0
        self.last_tool: dict | None = None
        self.test_runs = 0
        self.last_test_run: dict | None = None
        self.last_agent_ts: str | None = None
        self.last_tool_ts: str | None = None
        self.guard = {"violations": 0, "warnings": 0, "kills": 0, "kill": None, "budget": None,
                      "stall_pairs": 0, "stalled": False, "monitor": None}
        self.scorer = {"done": 0, "failed": 0, "hazards": 0, "behavior": 0}
        self.invalid_lines = 0
        self.oversize_lines = 0
        self.catching_up = False

    # -- reading ---------------------------------------------------------------------------
    def update(self) -> None:
        with self.lock:
            budget = MAX_BYTES_PER_UPDATE
            self.catching_up = False
            files = list_event_files(self.run_dir / "events")
            order = sorted(files, key=lambda x: (_ORDER.index(x) if x in _ORDER else len(_ORDER), x))
            for src in order:      # the run clock (orchestrator) and stream windows must be known first
                path = files[src]
                tail = self.tails.get(src)
                if tail is None:
                    tail = self.tails[src] = FileTail(path)
                while budget > 0:
                    before = tail.offset
                    lines, at_eof = tail.read(4 << 20)
                    if tail.restarted:        # the file was replaced: start the whole fold again
                        self.reset()
                        return self.update()
                    budget -= max(1, tail.offset - before)
                    for ln in lines:
                        self._line(src, ln)
                    st = safefs.stat_file(path)
                    if st is not None:
                        self.sizes[src] = st.st_size
                    if at_eof:
                        break
                else:
                    self.catching_up = True

    def _line(self, src: str, ln) -> None:
        if ln.data is None:
            self.oversize_lines += 1
            return
        pk = peek(ln.data)
        if pk is None:
            self.invalid_lines += 1
            return
        ts, typ = pk
        if ts and ts > self.last_ts.get(src, ""):
            self.last_ts[src] = ts
        if typ in ("tool.call", "tool.result", "assistant.text"):
            if ts and ts > (self.last_agent_ts or ""):
                self.last_agent_ts = ts
        want = _WANT.get(src)
        if want is None or typ not in want:
            return
        if len(ln.data) > MAX_LINE:
            return
        try:
            ev = json.loads(ln.data)
        except ValueError:
            self.invalid_lines += 1
            return
        p = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
        getattr(self, "_on_" + src)(typ, p, ev, ts)

    # -- per source ------------------------------------------------------------------------
    def _on_orchestrator(self, typ, p, ev, ts):
        if typ == "run.clock":
            self.clock.add(p.get("start_epoch"), p.get("offset_s"))
        elif typ == "state" and isinstance(p.get("to"), str):
            self.state = p["to"]
        elif typ == "checkpoint" and isinstance(p.get("k"), int):
            self.checkpoints[p["k"]] = p
        elif typ == "stage.delivered":
            self.stages.append({"stage": p.get("stage"), "t_s": num(p.get("t_s")), "kind": p.get("kind")})
        elif typ == "turn.start":
            self.turns["started"] += 1
        elif typ == "turn.end":
            self.turns["ended"] += 1
            if p.get("returncode") != 0:
                self.turns["failed"] += 1
        elif typ == "scorer.queued" and isinstance(p.get("k"), int):
            self.queued.add(p["k"])
        elif typ == "scorer.finished" and isinstance(p.get("k"), int):
            self.finished.add(p["k"])
        elif typ == "run.done":
            self.run_done = {"t_s": num(p.get("t_s")), "turns": p.get("turns")}
        elif typ == "run.error":
            self.run_error = str(p.get("error"))[:500]
        elif typ == "platform.interruption":
            self.interruptions.append({"kind": p.get("kind"), "detail": str(p.get("detail"))[:300], "ts": ts})
            del self.interruptions[:-20]

    def _on_agent_stream(self, typ, p, ev, ts):
        if typ == "tool.call":
            self.tool_calls += 1
            tool = str(p.get("tool") or "?")
            self.tool_by[tool] += 1
            self.last_tool_ts = ts
            self.last_tool = {"tool": tool[:80], "ts": ts}
        elif typ == "tool.result":
            if p.get("is_error"):
                self.tool_errors += 1
        elif typ == "agent.test_run":
            self.test_runs += 1
            self.last_test_run = {"passed": p.get("passed"), "failed": p.get("failed"), "errors": p.get("errors"),
                                  "ts": ts}
        elif typ == "context.compaction":
            self.compactions += 1
        elif typ in ("stream.result", "session.result"):
            for model, mu in (p.get("modelUsage") or {}).items():
                w = num(mu.get("contextWindow")) if isinstance(mu, dict) else None
                if w:
                    self.stream_windows[str(model)] = int(w)

    def _on_otel(self, typ, p, ev, ts):
        if typ == "claude_code.api_error":
            self.api_errors += 1
            return
        self.requests += 1
        self.last_request_ts = ts
        c = num(p.get("cost_usd")) or 0.0
        self.cost += c
        prompt = 0.0
        for f in TOKEN_FIELDS:
            v = num(p.get(f)) or 0.0
            self.tok[f] += v
            if f != "output_tokens":
                prompt += v
        model = p.get("model")
        self.last_model = str(model) if model else self.last_model
        self.last_prompt = prompt
        self.max_prompt = max(self.max_prompt, prompt)
        t = self.clock.t_s(ts_epoch(ts))
        if t is not None:
            self.cost_series.append((t, round(self.cost, 6)))
            self.fill_series.append((t, prompt))   # tokens; divided by the window at snapshot time

    def _on_guardrail(self, typ, p, ev, ts):
        g = self.guard
        if typ == "guardrail.violation":
            if p.get("severity") == "violation":
                g["violations"] += 1
            else:
                g["warnings"] += 1
        elif typ == "guardrail.kill":
            g["kills"] += 1
            g["kill"] = {"rule_id": p.get("rule_id"), "reason": p.get("reason"),
                         "freeze_latency_ms": num(p.get("freeze_latency_ms")), "ts": ts}
        elif typ == "guardrail.budget":
            g["budget"] = {k: p.get(k) for k in ("cost_usd", "tokens", "per_run_usd", "per_run_tokens")}
        elif typ == "guardrail.telemetry_stalled":
            g["stalled"] = True
        elif typ == "guardrail.telemetry_resumed":
            g["stalled"] = False
            g["stall_pairs"] += 1
        elif typ == "guardrail.monitor":
            g["monitor"] = p.get("status")

    def _on_scorer(self, typ, p, ev, ts):
        if typ == "scorer.done":
            if p.get("ok"):
                self.scorer["done"] += 1
                if isinstance(p.get("k"), int):
                    self.scored_ok.add(p["k"])
            else:
                self.scorer["failed"] += 1
        elif typ == "scorer.hazard":
            self.scorer["hazards"] += 1
        elif typ == "scorer.behavior":
            self.scorer["behavior"] += 1

    # -- snapshot --------------------------------------------------------------------------
    def snapshot(self, mf: dict, *, now: float | None = None, series: bool = True) -> dict:
        self.update()
        with self.lock:
            return self._snapshot(mf, time.time() if now is None else now, series)

    def _snapshot(self, mf: dict, now: float, series: bool) -> dict:
        spec = mf.get("spec") if isinstance(mf.get("spec"), dict) else {}
        budget = spec.get("budget") if isinstance(spec.get("budget"), dict) else {}
        runspec = spec.get("run") if isinstance(spec.get("run"), dict) else {}
        end = mf.get("end") if isinstance(mf.get("end"), dict) else None
        alive = store.pid_alive(mf.get("harness_pid"))
        live = end is None and alive
        state = end.get("state") if end else (self.state if live else "UNFINISHED")
        # clock
        marks = self.clock.marks
        started = bool(marks)
        ref = (end.get("end_epoch") if end and num(end.get("end_epoch")) else None) if end else now
        elapsed = self.clock.t_s(ref) if started and ref is not None else None
        elapsed = max(0.0, elapsed) if elapsed is not None else 0.0
        dur_min = num(runspec.get("duration_min"))
        interval_min = num(runspec.get("checkpoint_interval_min"))
        dur_s = dur_min * 60 if dur_min else None
        # checkpoints
        interval_s = interval_min * 60 if interval_min else None
        planned = round(dur_min / interval_min) if dur_min and interval_min else None
        taken = max(self.checkpoints) if self.checkpoints else 0
        last_cp = self.checkpoints.get(taken)
        nxt = None
        if planned and interval_s and taken < planned and not end:
            nk = taken + 1
            nxt = {"k": nk, "t_s": nk * interval_s, "due_in_s": round(nk * interval_s - elapsed, 1)}
        inflight = sorted(self.queued - self.finished)
        # cost / tokens
        cost = self.cost
        cost_source = "otel"
        if not self.requests and last_cp and num(last_cp.get("cumulative_cost_usd")) is not None:
            cost, cost_source = num(last_cp["cumulative_cost_usd"]), "checkpoint"
        if not self.requests and end and num(end.get("cost_usd")) is not None:
            cost, cost_source = num(end["cost_usd"]), "manifest"
        tokens_total = int(sum(self.tok.values())) if self.requests else (
            end.get("tokens") if end and isinstance(end.get("tokens"), int) else 0)
        cap_usd, cap_tok = num(budget.get("per_run_usd")), num(budget.get("per_run_tokens"))
        f_usd = cost / cap_usd if cap_usd else None
        f_tok = tokens_total / cap_tok if cap_tok else None
        f_time = elapsed / dur_s if dur_s else None
        pts = list(self.cost_series)
        recent = None
        if len(pts) >= 2:
            t1, c1 = pts[-1]
            base = next((p for p in pts if p[0] >= t1 - 300), pts[0])
            if t1 > base[0]:
                recent = (c1 - base[1]) / ((t1 - base[0]) / 60)
        avg = cost / (elapsed / 60) if elapsed > 0 else None
        cap_eta = None
        if cap_usd and recent and recent > 0 and cost < cap_usd and not end:
            cap_eta = round((cap_usd - cost) / recent * 60)
        table, default = _models()
        window = context_window(self.last_model or mf.get("model"), table, self.stream_windows, default)
        fill = self.last_prompt / window if self.last_prompt is not None and window else None
        max_fill = self.max_prompt / window if self.requests and window else None
        last_event = max(self.last_ts.values(), default=None)
        le = ts_epoch(last_event)
        la = ts_epoch(self.last_agent_ts)
        killed = self.guard["kills"] > 0
        status = ("killed" if killed else "violations" if self.guard["violations"]
                  else "warnings" if self.guard["warnings"] else "clear")
        out = {
            "run_id": mf.get("run_id") or self.run_dir.name,
            "as_of": now, "live": live, "ended": end is not None, "state": state, "end": end,
            "harness_alive": alive, "catching_up": self.catching_up,
            "clock": {"started": started, "start_epoch": marks[-1][0] if marks else None,
                      "elapsed_s": round(elapsed, 1), "duration_limit_s": dur_s,
                      "remaining_s": round(max(0.0, dur_s - elapsed), 1) if dur_s else None,
                      "fraction": f_time, "resumed": len(marks) > 1 or bool(marks and marks[0][1] > 0)},
            "checkpoints": {"taken": taken, "planned": planned, "interval_s": interval_s,
                            "last": ({"k": taken, "t_s": num(last_cp.get("t_s")), "head_sha": last_cp.get("head_sha"),
                                      "final": last_cp.get("final"),
                                      "cumulative_cost_usd": num(last_cp.get("cumulative_cost_usd"))}
                                     if last_cp else None),
                            "next": nxt,
                            "scoring": {"queued": len(self.queued), "finished": len(self.finished),
                                        "in_flight": inflight, "scored_ok": len(self.scored_ok)}},
            "stage": {"current": self.stages[-1]["stage"] if self.stages else None,
                      "delivered": len(self.stages), "last_t_s": self.stages[-1]["t_s"] if self.stages else None},
            "turns": dict(self.turns), "run_done": self.run_done, "run_error": self.run_error,
            "cost": {"usd": round(cost, 6), "source": cost_source, "requests": self.requests,
                     "api_errors": self.api_errors, "last_request_ts": self.last_request_ts,
                     "tokens": {"total": tokens_total, "input": int(self.tok["input_tokens"]),
                                "output": int(self.tok["output_tokens"]),
                                "cache_read": int(self.tok["cache_read_tokens"]),
                                "cache_creation": int(self.tok["cache_creation_tokens"])}},
            "context": {"fill": fill, "max_fill": max_fill, "window": window if self.requests else None, "model": self.last_model or mf.get("model"),
                        "compactions": self.compactions},
            "budget": {"per_run_usd": cap_usd, "per_run_tokens": cap_tok, "duration_min": dur_min,
                       "usd_fraction": f_usd, "tokens_fraction": f_tok, "time_fraction": f_time,
                       "level": level_for(max([f for f in (f_usd, f_tok) if f is not None], default=None)),
                       "time_level": level_for(f_time), "thresholds": {"amber": AMBER, "red": RED},
                       "burn_usd_per_min": avg, "recent_usd_per_min": recent, "cap_eta_s": cap_eta,
                       "exhausted": self.guard["budget"] is not None},
            "activity": {"last_event_ts": last_event,
                         "last_event_age_s": round(now - le, 1) if le is not None and live else None,
                         "last_agent_ts": self.last_agent_ts,
                         "idle_s": round(now - la, 1) if la is not None and live else None,
                         "tool_calls": self.tool_calls, "tool_errors": self.tool_errors,
                         "tool_calls_by_tool": dict(self.tool_by.most_common(15)), "last_tool": self.last_tool,
                         "test_runs": self.test_runs, "last_test_run": self.last_test_run},
            "safety": {"status": status, "violations": self.guard["violations"], "warnings": self.guard["warnings"],
                       "kills": self.guard["kills"], "kill": self.guard["kill"], "budget_event": self.guard["budget"]},
            "telemetry": {"stalled": self.guard["stalled"], "stall_pairs": self.guard["stall_pairs"]},
            "scorer": dict(self.scorer), "interruptions": list(self.interruptions),
            "files": {s: {"size": self.sizes.get(s), "last_ts": self.last_ts.get(s)} for s in sorted(self.tails)},
            "problems": {"invalid_lines": self.invalid_lines, "oversize_lines": self.oversize_lines},
        }
        if series:
            out["series"] = {"cost_usd": decimate(pts), "context_fill": [[t, round(v / window, 5)] for t, v in decimate(list(self.fill_series))]
                if window else []}
        return out


_ORDER = ["orchestrator", "agent_stream"]
_WANT = {
    "orchestrator": {"run.clock", "state", "checkpoint", "stage.delivered", "turn.start", "turn.end", "scorer.queued",
                     "scorer.finished", "run.done", "run.error", "platform.interruption"},
    "agent_stream": {"tool.call", "tool.result", "agent.test_run", "context.compaction", "stream.result",
                     "session.result"},
    "otel": {"claude_code.api_request", "claude_code.api_error"},
    "guardrail": {"guardrail.violation", "guardrail.kill", "guardrail.budget", "guardrail.telemetry_stalled",
                  "guardrail.telemetry_resumed", "guardrail.monitor"},
    "scorer": {"scorer.done", "scorer.hazard", "scorer.behavior"},
}


class Registry:
    """A few RunLive objects kept warm (LRU) so repeated polls only read new bytes."""

    def __init__(self, size: int = 8):
        self.size = size
        self._d: OrderedDict[str, RunLive] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, run_dir: Path) -> RunLive:
        key = str(run_dir)
        with self._lock:
            rl = self._d.pop(key, None) or RunLive(run_dir)
            self._d[key] = rl
            while len(self._d) > self.size:
                self._d.popitem(last=False)
            return rl


REGISTRY = Registry()
