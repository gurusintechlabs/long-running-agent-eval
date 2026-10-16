"""Asynchronous checkpoint scoring (docs/spec.md §5.1 CHECKPOINTING step 6, §8).

Each checkpoint is scored in a separate ``python -m scorer.run_checkpoint`` process, one at a time,
on a worker thread, so scoring never blocks the agent. The scorer reads only the artifact dir and
writes only ``events/scorer.jsonl`` and ``scorer/`` there (spec §8.1).
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from telemetry.events import EventWriter


class ScorerQueue:
    def __init__(self, art: Path, spec_path: Path, events: EventWriter, *, repo_root: Path,
                 python: str = sys.executable, timeout_s: float = 1800.0, confirm_spend: bool = False):
        self.art = Path(art)
        self.spec_path = Path(spec_path)
        self.events = events
        self.repo_root = Path(repo_root)
        self.python = python
        self.timeout_s = timeout_s
        self.confirm_spend = confirm_spend
        self.results: dict[int, int | None] = {}
        self._q: queue.Queue[int | None] = queue.Queue()
        self._thread = threading.Thread(target=self._work, name="scorer-queue", daemon=True)
        self._thread.start()

    def submit(self, k: int) -> None:
        self.events.emit("scorer.queued", {"k": k})
        self._q.put(k)

    def drain(self, timeout_s: float | None = None) -> bool:
        """Wait for every queued job; returns False if the wait timed out."""
        self._q.put(None)
        self._thread.join(timeout_s)
        return not self._thread.is_alive()

    def _work(self) -> None:
        while True:
            k = self._q.get()
            if k is None:
                return
            self._score(k)

    def _score(self, k: int) -> None:
        log_dir = self.art / "scorer"
        log_dir.mkdir(parents=True, exist_ok=True)
        cmd = [self.python, "-m", "scorer.run_checkpoint", "--art", str(self.art), "--k", str(k),
               "--spec", str(self.spec_path)]
        env = {k: v for k, v in os.environ.items() if k != "LRAE_CONFIRM_SPEND"}
        if self.confirm_spend:  # the real judge refuses to run without it
            env["LRAE_CONFIRM_SPEND"] = "1"
        t0 = time.monotonic()
        rc: int | None
        with open(log_dir / f"score-t{k}.log", "a") as log:
            try:
                rc = subprocess.run(cmd, cwd=self.repo_root, stdout=log, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, timeout=self.timeout_s, env=env).returncode
            except subprocess.TimeoutExpired:
                rc = None
        self.results[k] = rc
        self.events.emit("scorer.finished", {"k": k, "returncode": rc,
                                             "duration_s": round(time.monotonic() - t0, 3)})
