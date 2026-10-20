"""Guardrail monitor (docs/spec.md §7.2, §7.4): command, effect and budget channels, telemetry stall
detector and platform-interruption detection, all driven by tailing the run's JSONL event files.

Wiring (orchestrator)::

    mon = GuardrailMonitor(events_dir=art / "events", policy=bound_policy, writer=guardrail_writer,
                           on_kill=lambda v: kill_switch.trigger(v.rule_id, "policy", mon.detect_mono_ns),
                           on_budget=lambda cost, tokens: kill_switch.trigger("budget", "budget", mon.detect_mono_ns),
                           on_pause=proc.pause, on_resume=proc.resume,
                           on_interrupt=lambda kind, detail: ..., per_run_usd=15.0,
                           workspace=ws, seed_files=hashes, integrity=integrity_hashes([...], [...]))
    mon.start(); mon.set_agent_active(True)
    ...  mon.check_effects_now()   # at every checkpoint
    mon.stop()

All callbacks run on the monitor thread (or the caller of ``poll_once``). Kill is first-wins:
after the first ``on_kill``/``on_budget`` call further kill-class findings are only logged.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from guardrails.policy import BoundPolicy, Violation, sha256_file
from telemetry.events import EventWriter

log = logging.getLogger(__name__)

API_ERROR_COUNT = 3
API_ERROR_WINDOW_S = 120.0
CLOCK_GAP_S = 30.0
_USAGE_RE = re.compile(r"usage limit|limit reached|rate_limit|rate limit|quota", re.I)
_AUTH_RE = re.compile(r"authentication|oauth|\b401\b|invalid api key|please run /login|token (?:has )?expired",
                      re.I)
_RESET_EPOCH_RE = re.compile(r"limit reached\|(\d{9,11})")
_RESET_TEXT_RE = re.compile(r"resets?(?: at| in|:)?\s+([^\n.|]{1,60})", re.I)
_TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens")


class SystemClock:
    def mono(self) -> float:
        return time.monotonic()

    def wall(self) -> float:
        return time.time()


def parse_ts(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC).timestamp()
    except ValueError:
        return None


def _num(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v if v == v and v not in (float("inf"), float("-inf")) and v >= 0 else 0.0


def integrity_hashes(files: list[Path] = (), dirs: list[Path] = ()) -> dict[str, str]:
    """``{path: sha256}`` for the given files and for every file below each dir (hidden tests)."""
    out: dict[str, str] = {}
    for f in files:
        out[str(f)] = sha256_file(Path(f))
    for d in dirs:
        for f in sorted(p for p in Path(d).rglob("*") if p.is_file() and "__pycache__" not in p.parts):
            out[str(f)] = sha256_file(f)
    return out


class _Tail:
    """Reads complete JSONL lines appended to a file, by byte offset; keeps a partial last line."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.offset = 0
        self.bad_lines = 0

    def read(self) -> list[dict]:
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if size < self.offset:  # truncated / replaced
            self.offset = 0
        if size == self.offset:
            return []
        with open(self.path, "rb") as fh:
            fh.seek(self.offset)
            data = fh.read(size - self.offset)
        end = data.rfind(b"\n")
        if end < 0:
            return []  # only a partial line so far
        self.offset += end + 1
        out = []
        for line in data[:end].split(b"\n"):
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                self.bad_lines += 1
                continue
            if isinstance(ev, dict):
                out.append(ev)
        return out


class CwdModel:
    """The Bash tool's working directory as the command channel sees it.

    ``cwd`` follows the CLI, which resets the shell to the project dir when a command leaves it.
    ``raw`` never resets, which is the stricter older model. A call is checked against ``cwd``; when
    the two differ it is also checked against ``raw``, keeping only kill-severity findings from that
    second check. Kill rules therefore stay as strict as before, while warnings follow the CLI.
    """

    def __init__(self, policy: BoundPolicy, home_cwd: Path | None):
        self.policy = policy
        self.home_cwd = Path(home_cwd) if home_cwd else None
        self.reset()

    def reset(self) -> None:
        self.cwd = self.raw = self.home_cwd

    def check(self, tool: str, tool_input: dict) -> list[Violation]:
        if self.cwd is None:
            return []
        found = self.policy.check_tool_call(tool, tool_input, self.cwd)
        if self.raw != self.cwd:
            seen = {v.rule_id for v in found}
            found += [v for v in self.policy.check_tool_call(tool, tool_input, self.raw)
                      if v.severity == "violation" and v.rule_id not in seen]
        if tool == "Bash" and isinstance(tool_input, dict):
            command = str(tool_input.get("command", ""))
            self.cwd = self.policy.track_cwd(command, self.cwd, reset_to=self.home_cwd)
            self.raw = self.policy.track_cwd(command, self.raw)
        return found


class GuardrailMonitor:
    def __init__(self, *, events_dir: Path, policy: BoundPolicy, writer: EventWriter,
                 on_kill, on_pause=None, on_resume=None, on_budget=None, on_interrupt=None,
                 per_run_usd: float | None = None, per_run_tokens: int | None = None,
                 workspace: Path | None = None, seed_files: dict[str, str] | None = None,
                 integrity: dict[str, str] | None = None, clock=None, poll_interval: float = 0.2,
                 effect_interval: float = 30.0, lag_threshold_s: float = 10.0,
                 silence_threshold_s: float = 60.0, cwd: Path | None = None,
                 procmon=None, procmon_interval: float = 2.0, honey=None):
        self.events_dir = Path(events_dir)
        self.policy = policy
        self.writer = writer
        self.on_kill, self.on_pause, self.on_resume = on_kill, on_pause, on_resume
        self.on_budget, self.on_interrupt = on_budget, on_interrupt
        self.per_run_usd, self.per_run_tokens = per_run_usd, per_run_tokens
        self.workspace = Path(workspace) if workspace else None
        self.seed_files = seed_files
        self.integrity = dict(integrity or {})
        self.clock = clock or SystemClock()
        self.poll_interval = min(poll_interval, 0.25)
        self.effect_interval = effect_interval
        self.lag_threshold_s = lag_threshold_s
        self.silence_threshold_s = silence_threshold_s
        self.home_cwd = Path(cwd) if cwd else self.workspace
        self._cwd = CwdModel(policy, self.home_cwd)
        self.procmon = procmon            # guardrails.procmon.ProcMon (plan B2), log-only
        self.procmon_interval = procmon_interval
        self.honey = honey                # guardrails.honey.HoneyPot (plan B2), log-only

        self._stream = _Tail(self.events_dir / "agent_stream.jsonl")
        self._otel = _Tail(self.events_dir / "otel.jsonl")
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

        self.cost_usd = 0.0
        self.tokens = 0
        self.killed = False
        self.kill_violation: Violation | None = None
        self.detect_mono_ns: int = 0
        self.violations: list[Violation] = []
        self._seen_effects: set[tuple[str, str]] = set()

        self._active = False
        self._last_otel_mono = self.clock.mono()
        self._last_lag_s: float | None = None
        self._stalled: str | None = None
        self._stalled_since = 0.0
        self._api_errors: deque[float] = deque()
        self._interrupt_kinds: set[str] = set()
        self._prev_mono = self.clock.mono()
        self._prev_wall = self.clock.wall()
        self._last_effects_mono = self._prev_mono
        self._last_procmon_mono = self._prev_mono

    # -- public control ---------------------------------------------------------------------
    def set_agent_active(self, active: bool) -> None:
        with self._lock:
            if active and not self._active:
                self._last_otel_mono = self.clock.mono()  # silence is measured from activation
            self._active = bool(active)

    def start(self) -> None:
        if self._thread is not None:
            return
        self.writer.emit("guardrail.monitor", {"status": "started",
                                               "policy_sha256": self.policy.sha256})
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="guardrail-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=10)
        self._thread = None
        try:
            self.poll_once()  # drain what was appended last
            if self.procmon is not None:
                self.check_procs_now()
        except Exception:
            log.exception("final poll failed")
        self.writer.emit("guardrail.monitor", {"status": "stopped",
                                               "policy_sha256": self.policy.sha256})

    def _run(self) -> None:
        while not self._stop.wait(self.poll_interval):
            try:
                self.poll_once()
            except Exception as exc:  # the monitor must outlive a bad record or callback
                log.exception("monitor poll failed")
                self.writer.emit("guardrail.monitor", {"status": "error", "error": repr(exc)[:500]})

    # -- one polling round -------------------------------------------------------------------
    def poll_once(self) -> int:
        """Read new events and run every check once. Returns the number of events consumed."""
        with self._lock:
            now, wall = self.clock.mono(), self.clock.wall()
            stream = self._stream.read()
            otel = self._otel.read()
            for ev in stream:
                self._on_stream(ev, now)
            for ev in otel:
                self._on_otel(ev, wall)
            self._clock_gap(now, wall)
            self._stall(now, bool(otel))
            if self.workspace is not None or self.integrity:
                if now - self._last_effects_mono >= self.effect_interval:
                    self.check_effects_now()
            if self.procmon is not None and now - self._last_procmon_mono >= self.procmon_interval:
                self.check_procs_now()
            self._prev_mono, self._prev_wall = now, wall
            return len(stream) + len(otel)

    # -- command channel ---------------------------------------------------------------------
    def _on_stream(self, ev: dict, now: float) -> None:
        etype, payload = ev.get("type"), ev.get("payload") or {}
        if etype == "session.init":
            self._cwd.reset()
        elif etype == "tool.call":
            tool, tinput = payload.get("tool", ""), payload.get("input") or {}
            for v in self._cwd.check(tool, tinput):
                self._raise(v, now, stream_seq=ev.get("seq"))
            if self.honey is not None:
                for v in self.honey.check_call(tool, tinput):
                    self._raise(v, now, stream_seq=ev.get("seq"))
        elif etype in ("session.result", "stream.result") and payload.get("is_error"):
            self._error_result(payload)

    def _raise(self, v: Violation, now: float, stream_seq=None) -> None:
        payload = v.to_payload()
        if stream_seq is not None:
            payload["stream_seq"] = stream_seq
        self.violations.append(v)
        self.writer.emit("guardrail.violation", payload)
        if v.action == "kill" and not self.killed:
            self._first_kill(v, now)

    def _first_kill(self, v: Violation | None, now: float) -> None:
        self.killed = True
        self.kill_violation = v
        self.detect_mono_ns = int(now * 1e9)
        if v is not None:
            self._call(self.on_kill, v)

    # -- effect + integrity channel ---------------------------------------------------------
    def check_effects_now(self) -> list[Violation]:
        """Effect channel and integrity hashes. Returns violations that were new in this call."""
        with self._lock:
            now = self.clock.mono()
            self._last_effects_mono = now
            found: list[Violation] = []
            if self.workspace is not None:
                found += self.policy.check_effects(self.workspace, self.seed_files)
                if self.honey is not None:
                    found += self.honey.check_effects(self.workspace)
            for path, want in self.integrity.items():
                try:
                    got = sha256_file(Path(path))
                except OSError:
                    got = "<missing>"
                if got != want:
                    found.append(Violation("integrity", "violation", "kill", "integrity",
                                           f"{path} changed" if got != "<missing>" else f"{path} missing"))
            new = []
            for v in found:
                key = (v.rule_id, v.evidence)
                if key in self._seen_effects:
                    continue
                self._seen_effects.add(key)
                new.append(v)
                self._raise(v, now)
            return new

    # -- process channel (procmon) ------------------------------------------------------------
    def check_procs_now(self) -> None:
        """Poll procmon once: each observation is logged as its own event, and its finding (a
        warning or a log-only violation) goes through the usual violation path."""
        with self._lock:
            now = self.clock.mono()
            self._last_procmon_mono = now
            for etype, payload, v in self.procmon.poll():
                self.writer.emit(etype, payload)
                if v is not None:
                    self._raise(v, now)

    # -- budget channel ----------------------------------------------------------------------
    def _on_otel(self, ev: dict, wall: float) -> None:
        etype, payload = ev.get("type"), ev.get("payload") or {}
        recv, sent = parse_ts(payload.get("_recv_ts")), parse_ts(ev.get("ts"))
        if recv is not None and sent is not None:
            self._last_lag_s = max(0.0, recv - sent)
        if etype == "claude_code.api_request":
            self.cost_usd += _num(payload.get("cost_usd"))
            self.tokens += int(sum(_num(payload.get(k)) for k in _TOKEN_KEYS))
            self._check_budget()
        elif etype == "claude_code.api_error":
            t = sent if sent is not None else wall
            self._api_errors.append(t)
            while self._api_errors and t - self._api_errors[0] > API_ERROR_WINDOW_S:
                self._api_errors.popleft()
            if len(self._api_errors) >= API_ERROR_COUNT:
                self._interrupt("api_error", f"{len(self._api_errors)} claude_code.api_error "
                                f"within {API_ERROR_WINDOW_S:.0f} s: "
                                f"{str(payload.get('error') or payload.get('status_code') or '')[:200]}")

    def _check_budget(self) -> None:
        over_usd = self.per_run_usd is not None and self.cost_usd >= self.per_run_usd
        over_tok = self.per_run_tokens is not None and self.tokens >= self.per_run_tokens
        if not (over_usd or over_tok) or self.killed:
            return
        now = self.clock.mono()
        self.writer.emit("guardrail.budget", {"cost_usd": self.cost_usd, "tokens": self.tokens,
                                              "per_run_usd": self.per_run_usd,
                                              "per_run_tokens": self.per_run_tokens})
        v = Violation("budget", "violation", "kill", "budget",
                      f"cost_usd={self.cost_usd:.4f} tokens={self.tokens} "
                      f"caps usd={self.per_run_usd} tokens={self.per_run_tokens}")
        self.violations.append(v)
        self.writer.emit("guardrail.violation", v.to_payload())
        self._first_kill(None, now)
        self.kill_violation = v
        self._call(self.on_budget, self.cost_usd, self.tokens)

    # -- telemetry stall --------------------------------------------------------------------
    def _stall(self, now: float, got_records: bool) -> None:
        if self.killed:
            return
        if got_records:
            self._last_otel_mono = now
        lag = self._last_lag_s
        if self._stalled is None:
            if lag is not None and got_records and lag > self.lag_threshold_s:
                self._enter_stall("lag", now, otel_lag_ms=int(lag * 1000))
            elif self._active and now - self._last_otel_mono > self.silence_threshold_s:
                self._enter_stall("silence", now, silence_s=round(now - self._last_otel_mono, 3))
        elif got_records and (lag is None or lag <= self.lag_threshold_s):
            self.resume_now()

    def _enter_stall(self, reason: str, now: float, **detail) -> None:
        self._stalled, self._stalled_since = reason, now
        self.writer.emit("guardrail.telemetry_stalled", {"reason": reason, **detail})
        self._call(self.on_pause)

    def resume_now(self) -> None:
        """Leave the stalled state (also usable by the orchestrator, e.g. receiver restarted)."""
        with self._lock:
            if self._stalled is None:
                return
            now = self.clock.mono()
            self.writer.emit("guardrail.telemetry_resumed",
                             {"paused_s": round(now - self._stalled_since, 3)})
            self._stalled = None
            self._last_otel_mono = now
            self._call(self.on_resume)

    @property
    def stalled(self) -> bool:
        return self._stalled is not None

    # -- platform interruptions ---------------------------------------------------------------
    def _clock_gap(self, now: float, wall: float) -> None:
        gap = (wall - self._prev_wall) - (now - self._prev_mono)
        if gap > CLOCK_GAP_S:
            self._interrupt("clock_gap", f"wall clock advanced {gap:.0f} s more than the monotonic "
                            "clock between polls (machine sleep?)", once=False)

    def _error_result(self, payload: dict) -> None:
        text = " ".join(str(payload.get(k) or "") for k in ("result_text", "result", "subtype", "error"))
        if _USAGE_RE.search(text):
            kind = "usage_limit"
        elif _AUTH_RE.search(text):
            kind = "auth"
        else:
            return
        reset = None
        if m := _RESET_EPOCH_RE.search(text):
            reset = datetime.fromtimestamp(int(m.group(1)), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        elif m := _RESET_TEXT_RE.search(text):
            reset = m.group(1).strip()
        self._interrupt(kind, text.strip()[:300], reset_at=reset)

    def _interrupt(self, kind: str, detail: str, reset_at: str | None = None, once: bool = True) -> None:
        if once and kind in self._interrupt_kinds:
            return
        self._interrupt_kinds.add(kind)
        payload = {"kind": kind, "detail": detail}
        if reset_at:
            payload["reset_at"] = reset_at
        self.writer.emit("platform.interruption", payload)
        self._call(self.on_interrupt, kind, detail)

    # -- util -------------------------------------------------------------------------------
    def _call(self, fn, *args) -> None:
        if fn is None:
            return
        try:
            fn(*args)
        except Exception as exc:
            log.exception("guardrail callback failed")
            self.writer.emit("guardrail.monitor", {"status": "error", "error": repr(exc)[:500]})
