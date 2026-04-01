"""
Token Bucket Rate Limiter — Calibrated to Upstox API Limits
Enforces three tiers simultaneously:
  - Per Second:    50 requests (hard burst cap)
  - Per Minute:   500 requests (sliding window)
  - Per 30 Minutes: 2,000 requests (sliding window)

Separate bucket for Multi-Order APIs:
  - Per Second:     4 requests
  - Per Minute:    40 requests

Thread-safe. WebSocket traffic is exempt per Upstox docs.
"""
import time
import threading
from collections import deque
from core.logger import get_logger

logger = get_logger(__name__)


class _SlidingWindowCounter:
    """A single sliding-window counter for one rate-limit tier."""

    def __init__(self, max_requests: int, window_seconds: float, tier_name: str):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.tier_name = tier_name
        self._timestamps: deque = deque()
        self._warned = False  # Prevent log spam for 80% warning

    def _purge(self, now: float):
        """Remove timestamps older than the window."""
        cutoff = now - self.window_seconds
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    def can_acquire(self, now: float) -> bool:
        """Returns True if a request can be made without exceeding the limit."""
        self._purge(now)
        return len(self._timestamps) < self.max_requests

    def record(self, now: float):
        """Records a request timestamp."""
        self._timestamps.append(now)
        # Early warning at 80% capacity
        usage = len(self._timestamps)
        threshold = int(self.max_requests * 0.80)
        if usage >= threshold and not self._warned:
            self._warned = True
            logger.warning(
                f"⚠️ Rate Limiter [{self.tier_name}]: {usage}/{self.max_requests} "
                f"({usage / self.max_requests * 100:.0f}% capacity)"
            )
        elif usage < threshold:
            self._warned = False  # Reset warning when usage drops

    def time_until_available(self, now: float) -> float:
        """Returns seconds to wait until a slot opens. 0.0 if available now."""
        self._purge(now)
        if len(self._timestamps) < self.max_requests:
            return 0.0
        # Oldest request will expire at: oldest_ts + window_seconds
        return max(0.0, self._timestamps[0] + self.window_seconds - now)

    @property
    def current_usage(self) -> int:
        self._purge(time.time())
        return len(self._timestamps)


class RateLimiter:
    """
    Multi-tier token bucket rate limiter for Upstox API.

    Usage:
        limiter = RateLimiter()

        # Blocking — waits until a slot is available
        limiter.acquire()
        broker.place_order(...)

        # Non-blocking — for REST poller to skip cycles
        if limiter.try_acquire():
            broker.get_market_quote(...)
    """

    def __init__(
        self,
        per_second: int = 50,
        per_minute: int = 500,
        per_30_min: int = 2000,
    ):
        self._lock = threading.Lock()
        self._tiers = [
            _SlidingWindowCounter(per_second, 1.0, "1s"),
            _SlidingWindowCounter(per_minute, 60.0, "1m"),
            _SlidingWindowCounter(per_30_min, 1800.0, "30m"),
        ]

    def acquire(self, timeout: float = 60.0):
        """
        Blocking call. Waits until all tiers have capacity, then records the request.
        Raises TimeoutError if unable to acquire within `timeout` seconds.
        """
        deadline = time.time() + timeout
        while True:
            now = time.time()
            if now > deadline:
                raise TimeoutError(
                    f"Rate limiter could not acquire a slot within {timeout}s. "
                    f"Usage: {self.get_usage_summary()}"
                )

            with self._lock:
                # Check all tiers
                max_wait = 0.0
                for tier in self._tiers:
                    wait = tier.time_until_available(now)
                    if wait > max_wait:
                        max_wait = wait

                if max_wait == 0.0:
                    # All tiers have capacity — record and return
                    for tier in self._tiers:
                        tier.record(now)
                    return

            # Wait outside the lock
            sleep_time = min(max_wait + 0.01, deadline - time.time())
            if sleep_time > 0:
                time.sleep(sleep_time)

    def try_acquire(self) -> bool:
        """
        Non-blocking. Returns True if request was recorded, False if any tier is full.
        Used by the REST poller to gracefully skip cycles.
        """
        now = time.time()
        with self._lock:
            for tier in self._tiers:
                if not tier.can_acquire(now):
                    return False
            # All clear — record
            for tier in self._tiers:
                tier.record(now)
            return True

    def get_usage_summary(self) -> str:
        """Returns a human-readable summary of current usage across all tiers."""
        with self._lock:
            parts = []
            for tier in self._tiers:
                parts.append(f"{tier.tier_name}: {tier.current_usage}/{tier.max_requests}")
            return " | ".join(parts)

    def get_stats(self) -> dict:
        """Returns structured stats for monitoring (e.g., Telegram /bus command)."""
        with self._lock:
            return {
                tier.tier_name: {
                    "usage": tier.current_usage,
                    "limit": tier.max_requests,
                    "pct": round(tier.current_usage / tier.max_requests * 100, 1)
                        if tier.max_requests > 0 else 0,
                }
                for tier in self._tiers
            }


class MultiOrderRateLimiter(RateLimiter):
    """
    Stricter rate limiter for Upstox Multi-Order APIs.
    4 requests/sec, 40 requests/min.
    """

    def __init__(self):
        super().__init__(
            per_second=4,
            per_minute=40,
            per_30_min=2000,  # Same 30-min global cap applies
        )
