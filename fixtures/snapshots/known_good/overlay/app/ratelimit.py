"""Per-user fixed-window rate limiter (in memory, thread-safe)."""
from __future__ import annotations

import math
import threading
import time
from typing import Callable, Dict, Tuple


class RateLimiter:
    """Allow at most ``limit`` hits per user in each ``window_s``-second window.

    The window for a user starts at that user's first counted hit.
    """

    def __init__(
        self,
        limit: int,
        window_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._lock = threading.Lock()
        self._state: Dict[int, Tuple[float, int]] = {}  # user -> (window_start, count)

    def hit(self, user_id: int) -> Tuple[bool, int]:
        """Count a hit. Return ``(allowed, retry_after_s)``; a denied hit is not counted."""
        now = self._clock()
        with self._lock:
            start, count = self._state.get(user_id, (now, 0))
            if now - start >= self.window_s:
                start, count = now, 0
            if count >= self.limit:
                return False, max(1, math.ceil(start + self.window_s - now))
            self._state[user_id] = (start, count + 1)
            return True, 0
