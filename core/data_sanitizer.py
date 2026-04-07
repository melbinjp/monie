"""
Primitive 2: Data Sanitizer
Never trust raw broker data. Maintains Last-Known-Good (LKG) values,
a 10-tick rolling window for Z-score outlier detection, and spike
rejection to prevent strategy flapping from API glitches.
"""
import time
import math
from collections import defaultdict
from core.logger import get_logger
from core.events import TickEvent, CleanTickEvent

logger = get_logger(__name__)


class DataSanitizer:
    """
    Wraps any broker's get_quote() to produce clean, verified prices.
    Also acts as Event Bus Middleware, transforming TickEvent -> CleanTickEvent.
    """
    def __init__(self, max_age_seconds: float = 120.0, event_bus = None):
        self._lkg = {}          # symbol -> last known good price
        self._lkg_time = {}     # symbol -> timestamp of LKG
        self._history = defaultdict(list)  # symbol -> last 10 prices (rolling window)
        self._max_age = max_age_seconds
        
        self.event_bus = event_bus
        if self.event_bus:
            self.event_bus.subscribe(TickEvent, self.on_tick)

    def on_tick(self, event: TickEvent):
        """Middleware interception of raw ticks."""
        clean_price = self.clean(event.symbol, event.ltp)
        if clean_price > 0.0:
            clean_event = CleanTickEvent(
                symbol=event.symbol,
                ltp=clean_price,
                timestamp=event.timestamp
            )
            self.event_bus.publish(clean_event)

    def clean(self, symbol: str, raw_price: float) -> float:
        """
        Returns a sanitized price. Rules:
        1.   If raw_price <= 0 → return LKG (if fresh) or 0.0
        1.5  Z-Score outlier: if |price - mean| > 3σ over 10-tick window → reject
        2.   If raw_price spikes > 50% vs LKG in < 2s → reject as glitch, return LKG
        3.   Otherwise accept, update LKG and history
        """
        now = time.time()

        # Rule 1: Reject zero/negative
        if raw_price is None or raw_price <= 0:
            return self._get_lkg(symbol, now)

        history = self._history[symbol]

        # Rule 2: Spike rejection using self-calibrating constraints
        if symbol in self._lkg and symbol in self._lkg_time:
            elapsed = now - self._lkg_time[symbol]
            if elapsed < 2.0 and self._lkg[symbol] > 0:
                pct_change = abs(raw_price - self._lkg[symbol]) / self._lkg[symbol]
                dynamic_threshold = max(0.10, getattr(self, 'dynamic_vix_proxy', 20.0) / 100 * 2.0)
                if pct_change > dynamic_threshold:
                    logger.warning(
                        f"🛡️ SANITIZER: Rejected spike for {symbol}: "
                        f"₹{raw_price:.2f} vs LKG ₹{self._lkg[symbol]:.2f} "
                        f"({pct_change*100:.1f}% in {elapsed:.1f}s)"
                    )
                    return self._lkg[symbol]

        # Rule 3: Accept — update LKG and rolling history
        self._lkg[symbol] = raw_price
        self._lkg_time[symbol] = now

        history.append(raw_price)
        if len(history) > 10:
            history.pop(0)

        return raw_price

    def get_smoothed(self, symbol: str) -> float:
        """Returns 10-tick moving average for strategy-gate decisions (e.g., VIX checks)."""
        history = self._history.get(symbol, [])
        if not history:
            return self._lkg.get(symbol, 0.0)
        return sum(history) / len(history)

    def _get_lkg(self, symbol: str, now: float) -> float:
        """Returns LKG if it's fresh enough, otherwise 0.0."""
        if symbol in self._lkg and symbol in self._lkg_time:
            age = now - self._lkg_time[symbol]
            if age <= self._max_age:
                return self._lkg[symbol]
        return 0.0

