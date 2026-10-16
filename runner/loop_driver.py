"""Loop driver: run ``claude -p`` turns back to back until the deadline (docs/spec.md §4.3 config A).

Configs B-E (gates, resets, interval caps) are Phase 5; enabling them here raises.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

from spec.schema import HarnessConfig


class TurnFailure(RuntimeError):
    pass


def ensure_supported(config: HarnessConfig) -> None:
    if config.gate.enabled or config.reset.enabled or config.interval_cap.enabled:
        raise NotImplementedError(f"harness config {config.name} needs gates/resets/caps (Phase 5)")


class LoopDriver:
    MAX_CONSECUTIVE_FAILURES = 3
    MIN_TURN_GAP_S = 0.2

    def __init__(self, *, spawn_turn: Callable[[str, bool], TurnHandle], stop: threading.Event,
                 initial_prompt: str, continuation_prompt: str, snap_lock: threading.Lock,
                 first_turn: bool = True, poll_s: float = 0.05,
                 on_turn: Callable[[int, int | None], None] | None = None,
                 next_prompt: Callable[[], str] | None = None,
                 should_interrupt: Callable[[], bool] | None = None,
                 interrupt_grace_s: float = 15.0):
        self.spawn_turn = spawn_turn
        self.stop = stop
        self.initial_prompt = initial_prompt
        self.continuation_prompt = continuation_prompt
        self.snap_lock = snap_lock
        self.first_turn = first_turn
        self.poll_s = poll_s
        self.on_turn = on_turn
        # Staged briefs (runner/stages.py): the prompt for each later turn comes from next_prompt
        # (a stage prompt when one is due, else the continuation prompt), and a turn that runs past
        # a stage's grace window is interrupted so the stage can be delivered.
        self.next_prompt = next_prompt
        self.should_interrupt = should_interrupt
        self.interrupt_grace_s = interrupt_grace_s
        self.turns = 0
        self.interrupted_turns = 0

    def run(self) -> None:
        if self.first_turn:
            prompt = self.initial_prompt
        else:  # resumed run: a stage may already be due
            prompt = self.next_prompt() if self.next_prompt else self.continuation_prompt
        first = self.first_turn
        failures = 0
        while not self.stop.is_set():
            started = time.monotonic()
            with self.snap_lock:  # never spawn while a snapshot is being taken
                if self.stop.is_set():
                    return
                handle = self.spawn_turn(prompt, first)
            self.turns += 1
            interrupted = False
            while handle.alive() and not self.stop.is_set():
                if self.should_interrupt and self.should_interrupt():
                    handle.proc.terminate(grace_s=self.interrupt_grace_s)
                    interrupted = True
                    self.interrupted_turns += 1
                    break
                time.sleep(self.poll_s)
            if handle.alive() and not interrupted:  # stop requested mid-turn; the orchestrator terminates it
                return
            handle.join()
            rc = handle.returncode
            if self.on_turn:
                self.on_turn(self.turns, rc)
            if interrupted:  # a deliberate interruption is not a failing turn
                failures = 0
            else:
                failures = 0 if rc == 0 else failures + 1
            if failures >= self.MAX_CONSECUTIVE_FAILURES:
                raise TurnFailure(f"{failures} consecutive turns exited non-zero (last rc={rc})")
            first = False
            prompt = self.next_prompt() if self.next_prompt else self.continuation_prompt
            gap = self.MIN_TURN_GAP_S - (time.monotonic() - started)
            if gap > 0 and self.stop.wait(gap):
                return


class TurnHandle:
    """One running ``claude -p`` turn: the process plus the thread pumping its stdout."""

    def __init__(self, proc, pump: threading.Thread):
        self.proc = proc
        self.pump = pump

    def alive(self) -> bool:
        return self.proc.alive()

    @property
    def returncode(self) -> int | None:
        return self.proc.popen.returncode

    def join(self, timeout: float = 5.0) -> None:
        self.pump.join(timeout)
