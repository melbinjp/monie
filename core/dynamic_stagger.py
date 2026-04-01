"""
Dynamic Stagger Engine — Multi-Factor PE Leg Delay Calculator
Replaces the hardcoded 120-second stagger in IntradayShortStraddle.

Three decision layers:
  Layer 1: VIX Baseline     — delay inversely proportional to India VIX
  Layer 2: Momentum Override — 1-min RoC > threshold → immediate deployment (0s)
  Layer 3: Liquidity Gate    — checks PE bid-ask spread before firing

Failsafe: any data feed failure → safe 15-second default delay.
All decisions logged to stagger_decisions.log for post-trade forensics.
"""
import time
import os
import logging
from collections import deque
from core.logger import get_logger

logger = get_logger(__name__)


class DynamicStaggerEngine:
    """
    Institutional-grade stagger calculator for options leg deployment.

    Usage:
        engine = DynamicStaggerEngine(config)
        engine.on_tick(nifty_ltp)  # Feed underlying price on every tick

        # When CE leg fills:
        delay = engine.calculate_delay(current_vix)

        # Poll until PE should fire:
        if engine.should_fire_pe(elapsed, delay, pe_bid, pe_ask):
            fire_pe_leg()
    """

    def __init__(self, config=None):
        # Configurable parameters (from Config or sensible defaults)
        self.roc_threshold = getattr(config, 'STAGGER_ROC_THRESHOLD', 0.001)     # 0.1%
        self.max_spread = getattr(config, 'STAGGER_MAX_SPREAD', 2.0)              # points
        self.hard_timeout = getattr(config, 'STAGGER_HARD_TIMEOUT', 180)          # seconds
        self.failsafe_delay = getattr(config, 'STAGGER_FAILSAFE_DELAY', 15)      # seconds

        # Rolling price buffer for 1-minute Rate of Change
        # Stores (timestamp, price) tuples
        self._price_buffer: deque = deque()
        self._buffer_window = 60.0  # 1-minute window

        # Decision audit log
        self._stagger_logger = self._init_stagger_logger()

        # Last computed values (for observability)
        self.last_decision_layer = "NONE"
        self.last_computed_delay = self.failsafe_delay
        self.last_vix = 0.0

    def _init_stagger_logger(self) -> logging.Logger:
        """Creates a dedicated file logger for stagger decisions."""
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)

        stagger_log = logging.getLogger("StaggerEngine")
        stagger_log.setLevel(logging.INFO)

        # Avoid duplicate handlers on re-initialization
        if not stagger_log.handlers:
            fh = logging.FileHandler(os.path.join(log_dir, "stagger_decisions.log"))
            fh.setFormatter(logging.Formatter('%(asctime)s | %(message)s'))
            stagger_log.addHandler(fh)

        return stagger_log

    # --- Layer 1: VIX Baseline Delay ---

    def _vix_delay(self, vix: float) -> float:
        """
        Calculates base delay inversely proportional to India VIX.
        High VIX = shorter delay (get both legs in fast).
        Low VIX = longer delay (calm market, maximum patience).

        VIX 10 → 120s delay
        VIX 20 → ~74s delay
        VIX 35 → 5s delay
        """
        if vix <= 0:
            return self.failsafe_delay
        # Linear interpolation: VIX 10 → 120s, VIX 35 → 5s
        delay = 120.0 - ((vix - 10.0) * (115.0 / 25.0))
        return max(5.0, min(120.0, delay))

    # --- Layer 2: Momentum Override (1-Min RoC) ---

    def on_tick(self, underlying_price: float):
        """
        Feeds the underlying index price (Nifty 50) to the rolling buffer.
        Must be called on every relevant tick for RoC calculation.
        """
        now = time.time()
        self._price_buffer.append((now, underlying_price))

        # Purge entries older than the buffer window
        cutoff = now - self._buffer_window
        while self._price_buffer and self._price_buffer[0][0] < cutoff:
            self._price_buffer.popleft()

    def _check_momentum_override(self) -> bool:
        """
        Returns True if 1-minute Rate of Change exceeds threshold.
        When True, the stagger should be 0 seconds (immediate deployment).
        This prevents the bot from sitting idle while the underlying runs away.
        """
        if len(self._price_buffer) < 2:
            return False

        oldest_ts, oldest_price = self._price_buffer[0]
        newest_ts, newest_price = self._price_buffer[-1]

        # Need at least 10 seconds of data for meaningful RoC
        if (newest_ts - oldest_ts) < 10.0:
            return False

        if oldest_price <= 0:
            return False

        roc = abs(newest_price - oldest_price) / oldest_price
        return roc > self.roc_threshold

    # --- Layer 3: Liquidity Gate (Bid-Ask Spread) ---

    def check_liquidity(self, bid: float, ask: float) -> bool:
        """
        Returns True if the PE option's bid-ask spread is acceptable.
        If data is unavailable (bid/ask <= 0), returns True to avoid blocking.
        """
        if bid <= 0 or ask <= 0:
            return True  # Data unavailable — don't block execution
        spread = ask - bid
        return spread <= self.max_spread

    # --- Main API ---

    def calculate_delay(self, current_vix: float) -> float:
        """
        Returns the computed stagger delay in seconds.
        Checks layers in priority order: Momentum > VIX Baseline.
        """
        try:
            self.last_vix = current_vix

            # Layer 2 overrides Layer 1
            if self._check_momentum_override():
                self.last_decision_layer = "MOMENTUM_OVERRIDE"
                self.last_computed_delay = 0.0
                self._log_decision("MOMENTUM_OVERRIDE", 0.0, current_vix)
                return 0.0

            # Layer 1: VIX-based delay
            delay = self._vix_delay(current_vix)
            self.last_decision_layer = "VIX_BASELINE"
            self.last_computed_delay = delay
            self._log_decision("VIX_BASELINE", delay, current_vix)
            return delay

        except Exception as e:
            logger.error(f"DynamicStagger error: {e}. Using failsafe {self.failsafe_delay}s")
            self.last_decision_layer = "FAILSAFE"
            self.last_computed_delay = self.failsafe_delay
            self._log_decision("FAILSAFE", self.failsafe_delay, current_vix)
            return self.failsafe_delay

    def should_fire_pe(self, elapsed_seconds: float, computed_delay: float,
                       pe_bid: float = 0.0, pe_ask: float = 0.0) -> bool:
        """
        Final gate before firing the PE leg:
        1. Has the computed delay elapsed?
        2. Is the PE option's spread acceptable?
        3. If spread is too wide but hard timeout reached, fire anyway.
        """
        if elapsed_seconds < computed_delay:
            return False

        # Spread check
        if not self.check_liquidity(pe_bid, pe_ask):
            if elapsed_seconds < self.hard_timeout:
                # Wait for spread to tighten
                return False
            else:
                # Hard timeout reached — fire with warning
                spread = pe_ask - pe_bid if pe_bid > 0 and pe_ask > 0 else 0
                logger.warning(
                    f"⚠️ STAGGER: HARD_TIMEOUT ({self.hard_timeout}s) reached. "
                    f"Firing PE despite wide spread (₹{spread:.1f} > ₹{self.max_spread:.1f})"
                )
                self._stagger_logger.warning(
                    f"HARD_TIMEOUT | spread={spread:.1f} | max_spread={self.max_spread} | "
                    f"elapsed={elapsed_seconds:.1f}s"
                )

        return True

    def _log_decision(self, layer: str, delay: float, vix: float):
        """Logs the stagger decision for post-trade forensics."""
        roc_data = "N/A"
        if len(self._price_buffer) >= 2:
            oldest_price = self._price_buffer[0][1]
            newest_price = self._price_buffer[-1][1]
            if oldest_price > 0:
                roc = ((newest_price - oldest_price) / oldest_price) * 100
                roc_data = f"{roc:+.3f}%"

        msg = (
            f"DECISION: {layer} | delay={delay:.1f}s | "
            f"VIX={vix:.1f} | RoC_1m={roc_data} | "
            f"threshold={self.roc_threshold*100:.1f}%"
        )
        self._stagger_logger.info(msg)
        logger.info(f"📐 Stagger: {msg}")

    def get_status(self) -> dict:
        """Returns current engine state for monitoring (e.g., Telegram /status)."""
        return {
            "last_layer": self.last_decision_layer,
            "last_delay": self.last_computed_delay,
            "last_vix": self.last_vix,
            "buffer_size": len(self._price_buffer),
            "roc_threshold": f"{self.roc_threshold*100:.1f}%",
            "max_spread": self.max_spread,
            "hard_timeout": self.hard_timeout,
        }
