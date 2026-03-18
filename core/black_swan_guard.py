"""
Black Swan Guard
Protects the bot from extreme market events using Rate of Change (ROC) and Gap analysis.
Integrated with: Logger primitive, time-based stale detection.
"""
import pandas as pd
import numpy as np
import time as _time
from core.logger import get_logger

logger = get_logger(__name__)


class BlackSwanGuard:
    def __init__(self, data_feed=None):
        self.data_feed = data_feed
        self.max_gap_pct = 0.015
        self.max_intraday_roc = 0.01
        self.active_halt = False
        
        # Stale quote detection — TIME-BASED (Primitive-correct)
        self.last_seen_price = None
        self.last_price_change_time = _time.time()
        self.stale_seconds = 600  # 10 minutes of identical quotes
        
    def check_stale_quotes(self, current_price):
        """Detects if market has halted using wall-clock time."""
        if current_price is None or current_price <= 0:
            return False
            
        if self.last_seen_price != current_price:
            self.last_seen_price = current_price
            self.last_price_change_time = _time.time()
            return False
            
        elapsed = _time.time() - self.last_price_change_time
        if elapsed >= self.stale_seconds:
            logger.warning(f"🛑 HEARTBEAT: Quotes stale for {elapsed:.0f}s. Market may be halted.")
            return True
        return False
        
    def check_gap(self, open_price, prev_close):
        """Checks for extreme gap openings."""
        if prev_close is None:
            return False
            
        gap_pct = abs(open_price - prev_close) / prev_close
        if gap_pct > self.max_gap_pct:
            logger.warning(f"🛑 BLACK SWAN: Extreme Gap Detected ({gap_pct*100:.2f}%)")
            return True
        return False
        
    def check_flash_crash(self, current_price, prices_last_15_mins):
        """Checks for extreme volatility in the last 15 minutes."""
        if not prices_last_15_mins or len(prices_last_15_mins) < 5:
            return False
            
        high = max(prices_last_15_mins)
        low = min(prices_last_15_mins)
        
        drop_pct = (high - current_price) / high
        rise_pct = (current_price - low) / low
        
        if drop_pct > self.max_intraday_roc:
            logger.warning(f"🛑 BLACK SWAN: Flash Crash Detected (Drop {drop_pct*100:.2f}%)")
            return True
            
        if rise_pct > self.max_intraday_roc:
            logger.warning(f"🛑 BLACK SWAN: Flash Spike Detected (Rise {rise_pct*100:.2f}%)")
            return True
            
        return False
            
    def check_vix(self, current_vix):
        """Checks if India VIX is too high."""
        if current_vix > 30.0:
            logger.warning(f"🛑 BLACK SWAN: VIX Alert ({current_vix} > 30.0)")
            return True
        return False

    def monitor(self, time, open_price, high, low, close, prev_close, current_vix=None):
        """Comprehensive check for critical market events."""
        if time == "09:15":
             if self.check_gap(open_price, prev_close):
                 return False, "Gap Risk"
        
        if current_vix and self.check_vix(current_vix):
            return False, f"High VIX ({current_vix})"
        
        return True, "Safe"
