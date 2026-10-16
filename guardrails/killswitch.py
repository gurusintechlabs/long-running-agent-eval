"""Kill switch (docs/spec.md §7.3): freeze → log ``guardrail.kill`` → snapshot → kill + sweep.

Callbacks are supplied by the orchestrator, e.g. ``freeze=proc.pause``,
``snapshot=lambda: take_final_snapshot("kill")``, ``kill=lambda: (proc.kill(), sweep(...))``.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from telemetry.events import EventWriter

log = logging.getLogger(__name__)


class KillSwitch:
    def __init__(self, freeze: Callable[[], object], snapshot: Callable[[], object],
                 kill: Callable[[], object], writer: EventWriter,
                 mono: Callable[[], int] = time.monotonic_ns):
        self._freeze, self._snapshot, self._kill = freeze, snapshot, kill
        self.writer = writer
        self.mono = mono
        self._lock = threading.Lock()
        self.triggered = False
        self.rule_id: str | None = None
        self.reason: str | None = None
        self.freeze_latency_ms: float | None = None
        self.errors: list[tuple[str, str]] = []

    def _step(self, name: str, fn: Callable[[], object]) -> None:
        try:
            fn()
        except Exception as exc:  # a failing snapshot must not stop the kill
            log.exception("kill switch step %s failed", name)
            self.errors.append((name, repr(exc)))
            self.writer.emit("guardrail.kill_error", {"step": name, "error": repr(exc)[:500]})

    def trigger(self, rule_id: str, reason: str, detect_mono_ns: int) -> bool:
        """Run the sequence once. Returns False (and does nothing) if already triggered."""
        with self._lock:
            if self.triggered:
                return False
            self.triggered = True
            self.rule_id, self.reason = rule_id, reason
        self._step("freeze", self._freeze)
        frozen = self.mono()
        self.freeze_latency_ms = (frozen - detect_mono_ns) / 1e6
        self.writer.emit("guardrail.kill", {
            "rule_id": rule_id, "reason": reason, "detect_mono_ns": detect_mono_ns,
            "frozen_mono_ns": frozen, "freeze_latency_ms": self.freeze_latency_ms})
        self._step("snapshot", self._snapshot)
        self._step("kill", self._kill)
        return True
