"""In-process fixed-window rate limiter (M17).

Protects the public QR-code surface (join, preview, submit) from abuse and from
exhausting the YouTube Data API daily quota. The limiter is in-process and
per-worker (decision D9 — no Redis): keys are ``<scope>:<client-ip>``, which
fits the single-worker school deployment. A shared store would only be needed
if the backend runs multiple workers (M20). Buckets are pruned lazily as their
windows expire; the table is bounded by distinct (scope, IP) pairs seen within
one window, which is tiny for a school night.
"""

import time
from collections.abc import Callable

#: HTTP 429 body for every rate-limited request.
RATE_LIMIT_MESSAGE = "too many requests — please slow down"


class RateLimitExceededError(Exception):
    """Raised when a client exceeds the allowed requests for its window."""


class RateLimiter:
    """Fixed-window counter keyed by an arbitrary string.

    ``now`` is injectable for deterministic tests.
    """

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._buckets: dict[str, tuple[float, int]] = {}

    def check(self, key: str, limit: int, window_seconds: float) -> None:
        """Record one request for ``key``; raise ``RateLimitExceededError``
        once ``limit`` requests fall within ``window_seconds``."""
        now = self._now()
        window_start, count = self._buckets.get(key, (0.0, 0))
        if now - window_start >= window_seconds:
            # A fresh window (or the first ever request for this key).
            self._buckets[key] = (now, 1)
            return
        if count >= limit:
            raise RateLimitExceededError()
        self._buckets[key] = (window_start, count + 1)
