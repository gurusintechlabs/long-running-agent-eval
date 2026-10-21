"""Per-key rate limiting (stage 5): a token bucket per key id, refilled at ``rate`` tokens a second
with a burst of ``rate``. Keyed by the authenticated key only, never by address or headers."""
from __future__ import annotations

import math
import threading
import time


class RateLimiter:
    def __init__(self, rate: float) -> None:
        self.rate = float(rate)
        self.lock = threading.Lock()
        self.buckets: dict[str, tuple[float, float]] = {}      # key id -> (tokens, last refill)

    def take(self, key_id: str) -> int | None:
        """None if the request may proceed, else the seconds to wait (``Retry-After``, at least 1)."""
        now = time.monotonic()
        with self.lock:
            tokens, last = self.buckets.get(key_id, (self.rate, now))
            tokens = min(self.rate, tokens + (now - last) * self.rate)
            if tokens >= 1.0:
                self.buckets[key_id] = (tokens - 1.0, now)
                return None
            self.buckets[key_id] = (tokens, now)
            return max(1, math.ceil((1.0 - tokens) / self.rate))
