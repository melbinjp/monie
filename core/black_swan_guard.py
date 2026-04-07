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
        
    # --- New Omni-Market Resilient Rolling Buffer ---
    
    def check_flash_crash_rolling(self, current_price, current_vix=15.0):
        """
        Ultra-fast rolling check using recent ticks (180-seconds window).
        Returns:
            "VELOCITY_SHOCK" = Vertical drop (<5 seconds). Fire Market Liquidation instantly.
            "HEDGE_MODE" = Structural move (>3 mins) exceeding dynamic VIX limits. Tighten SL gracefully.
            False = Market is normal.
        """
        if current_price is None or current_price <= 0:
            return False
            
        now = _time.time()
        
        # Initialize deque if not exists
        if not hasattr(self, '_price_buffer'):
            from collections import deque
            self._price_buffer = deque()
            
        self._price_buffer.append((now, current_price))
        
        # Evict old prices (> 180 seconds, i.e., 3 mins for ultra-fast structural detection)
        while self._price_buffer and self._price_buffer[0][0] < now - 180:
            self._price_buffer.popleft()
            
        if len(self._price_buffer) < 5:  # Need minimum datapoints
            return False
            
        # O(K) Hot-path optimization: avoid recreating lists cleanly over reverse iteration
        high_5s, low_5s = current_price, current_price
        high_180s, low_180s = current_price, current_price
        has_5s = False
        
        for ts, p in reversed(self._price_buffer):
            if p > high_180s: high_180s = p
            if p < low_180s: low_180s = p
            if ts >= now - 5:
                if p > high_5s: high_5s = p
                if p < low_5s: low_5s = p
                has_5s = True
                
        if has_5s:
            drop_5s = (high_5s - current_price) / high_5s
            rise_5s = (current_price - low_5s) / low_5s
            
            shock_limit = 0.005 
            if drop_5s > shock_limit or rise_5s > shock_limit:
                logger.critical(f"🛑 VELOCITY SHOCK: Vertical 5-Sec Move Activating Instant Liquidation Protocol!")
                return "VELOCITY_SHOCK"
            
        v = current_vix if current_vix and current_vix > 0 else 15.0
        dynamic_roc_limit = max(0.005, (v / 100) * 0.040)
        
        drop_180s = (high_180s - current_price) / high_180s
        rise_180s = (current_price - low_180s) / low_180s
        
        if drop_180s > dynamic_roc_limit or rise_180s > dynamic_roc_limit:
            logger.critical(f"⚠️ STRUCTURAL VOLATILITY: 3-Min Move > Dynamic VIX Limit {dynamic_roc_limit*100:.2f}%. Activating Hedge Mode.")
            return "HEDGE_MODE"
            
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
