"""Keep ``metrics.sqlite`` current without a click (owner, 2026-10-25).

A daemon thread polls ``store.ingest_status`` and runs the same ``lrae ingest`` subprocess as the
re-ingest button (one code path, UI-8: only ``lrae ingest`` writes the store):

* **stale** (a run is missing, or a manifest / orchestrator / scorer log is newer than the store, i.e. a
  checkpoint was scored, a stage delivered or a run started or ended): ingest once those inputs have not
  changed for ``settle_s`` (the scorer writes a pass as several lines), at most every ``min_interval_s``;
* **tail** (only live logs such as the agent stream grew): ingest every ``tail_interval_s``, so counters
  and the agent's own test runs follow a live run without rebuilding the store every few seconds;
* after a failure, wait for new inputs or ``retry_s``; the status reports the error and the page shows it.

``tick`` makes one decision and is driven by tests with a fake clock; ``start`` runs it every ``POLL_S``.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

POLL_S = 3.0
SETTLE_S = 3.0
MIN_INTERVAL_S = 20.0
TAIL_INTERVAL_S = 120.0
RETRY_S = 300.0


class AutoIngest:
    def __init__(self, *, status_fn: Callable[[], dict], run_fn: Callable[[], tuple[bool, str]],
                 lock: threading.Lock, clock: Callable[[], float] = time.monotonic, settle_s: float | None = None,
                 min_interval_s: float | None = None, tail_interval_s: float | None = None,
                 retry_s: float | None = None):
        self._status, self._run, self._lock, self._clock = status_fn, run_fn, lock, clock
        self.settle_s = SETTLE_S if settle_s is None else settle_s
        self.min_interval_s = MIN_INTERVAL_S if min_interval_s is None else min_interval_s
        self.tail_interval_s = TAIL_INTERVAL_S if tail_interval_s is None else tail_interval_s
        self.retry_s = RETRY_S if retry_s is None else retry_s
        self._mark = None              # last seen fingerprint of the key inputs
        self._mark_since = 0.0         # when it last changed
        self._last_at: float | None = None
        self._failed_mark = None       # key inputs of the last failed ingest
        self._state = {"enabled": True, "running": False, "ingests": 0, "last_ok": None, "last_error": None,
                       "last_epoch": None, "last_reason": None}
        self._state_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- one decision ---------------------------------------------------------------------------
    def tick(self) -> str | None:
        """Ingest if due; returns why (``"stale"`` / ``"tail"``) or None."""
        now = self._clock()
        st = self._status()
        mark = tuple(st.get("key_mark") or ())
        if mark != self._mark:
            self._mark, self._mark_since = mark, now
        since_last = None if self._last_at is None else now - self._last_at
        if self._failed_mark is not None:
            if mark == self._failed_mark and since_last is not None and since_last < self.retry_s:
                return None
        if st.get("stale"):
            if now - self._mark_since < self.settle_s:
                return None
            if since_last is not None and since_last < self.min_interval_s:
                return None
            reason = "stale"
        elif st.get("tail_newer") and (since_last is None or since_last >= self.tail_interval_s):
            reason = "tail"
        else:
            return None
        if not self._lock.acquire(blocking=False):
            return None                # a manual ingest is running; look again next tick
        try:
            self._set(running=True)
            ok, out = self._run()
        finally:
            self._lock.release()
        self._last_at = now
        self._failed_mark = None if ok else mark
        with self._state_lock:
            self._state.update(running=False, last_ok=ok, last_error=None if ok else (out or "ingest failed"),
                               last_epoch=time.time(), last_reason=reason, ingests=self._state["ingests"] + 1)
        return reason

    def _set(self, **kw) -> None:
        with self._state_lock:
            self._state.update(kw)

    def state(self) -> dict:
        with self._state_lock:
            return dict(self._state)

    # -- background thread ------------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="lrae-auto-ingest", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:   # never let the thread die; the status shows what went wrong
                self._set(running=False, last_ok=False, last_error=f"auto-ingest: {exc}")
            self._stop.wait(POLL_S)
