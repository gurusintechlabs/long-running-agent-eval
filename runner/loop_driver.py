"""Loop driver: one ``claude -p`` turn per piece of work (docs/spec.md §4.3 config A, D-4).

A turn ends when the agent considers its current work finished. Then the driver gives it the next
piece of work, which for a staged task is the next stage (runner/stages.py); when there is none
left, the run is done. The agent is never told to "keep working" on something it has declared
finished. A turn that fails (non-zero exit: crash, API error) is resumed once more with the
recovery prompt, so the agent can finish what it was doing; three failed turns in a row stop the run.
A turn whose background subagents the CLI stopped when the reply ended has not finished either: the
orchestrator's ``next_prompt`` then continues the current stage (``unfinished_prompt``).

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
                 initial_prompt: str, recovery_prompt: str, snap_lock: threading.Lock,
                 first_turn: bool = True, poll_s: float = 0.05,
                 on_turn: Callable[[int, int | None], None] | None = None,
                 next_prompt: Callable[[], str | None] | None = None):
        self.spawn_turn = spawn_turn
        self.stop = stop
        self.initial_prompt = initial_prompt
        self.recovery_prompt = recovery_prompt
        self.snap_lock = snap_lock
        self.first_turn = first_turn
        self.poll_s = poll_s
        self.on_turn = on_turn
        # The next piece of work after a successful turn: a stage prompt, or None when the task is
        # complete. Without it (an unstaged task) the run is done after the first successful turn.
        self.next_prompt = next_prompt or (lambda: None)
        self.turns = 0
        self.finished = False  # True when the agent completed all of its work (not the deadline)

    def run(self) -> None:
        # A resumed run restarts mid-work, so it continues the current stage first.
        prompt = self.initial_prompt if self.first_turn else self.recovery_prompt
        first = self.first_turn
        failures = 0
        while not self.stop.is_set():
            started = time.monotonic()
            with self.snap_lock:  # never spawn while a snapshot is being taken
                if self.stop.is_set():
                    return
                handle = self.spawn_turn(prompt, first)
            self.turns += 1
            while handle.alive() and not self.stop.is_set():
                time.sleep(self.poll_s)
            if handle.alive():  # stop requested mid-turn; the orchestrator terminates it
                return
            handle.join()
            rc = handle.returncode
            if self.on_turn:
                self.on_turn(self.turns, rc)
            first = False
            if rc == 0:
                failures = 0
                prompt = self.next_prompt()
                if prompt is None:  # the agent finished the last piece of work
                    self.finished = True
                    return
            else:
                failures += 1
                if failures >= self.MAX_CONSECUTIVE_FAILURES:
                    raise TurnFailure(f"{failures} consecutive turns exited non-zero (last rc={rc})")
                prompt = self.recovery_prompt
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
