"""
The Guardian: Risk Management Module
Enforces strict rules to prevent account blowups.
Integrated with: Logger primitive, Black Swan Guard, Rate Limiter.
"""
import time
from collections import deque
from core.black_swan_guard import BlackSwanGuard
from core.events import OrderEvent
from core.logger import get_logger

logger = get_logger(__name__)


class RiskManager:
    def __init__(self, max_daily_loss: float, capital: float):
        self.max_daily_loss = max_daily_loss
        self.capital = capital
        self.current_pnl = 0.0
        self.daily_trades = 0
        self.is_circuit_breaker_tripped = False
        self.start_balance = capital
        
        # Initialize Guard
        self.guard = BlackSwanGuard()
        self.guard_active = False
        self.in_hedge_mode = False
        
        # Rate limiter: sliding window of order timestamps
        self._order_timestamps = deque()
        self._max_orders_per_minute = 20
        
        # Exposure tracking: total notional value of active SELL orders
        self._open_exposure = 0.0

    def check_market_health(self, ltp, prev_close, vix=None):
        """
        Delegates to Black Swan Guard to check for crashes.
        Dynamically resets guard_active when conditions normalize.
        """
        is_dangerous = False
        
        if vix and self.guard.check_vix(vix):
            self.guard_active = True
            is_dangerous = True
        elif vix and vix > 0 and self.guard_active:
            # VIX has dropped back below threshold — reset the guard
            self.guard_active = False
            logger.info(f"✅ VIX normalized ({vix:.1f}). Guard reset — trading resumed.")
            
        if prev_close and ltp:
             if self.guard.check_gap(ltp, prev_close):
                 self.guard_active = True
                 is_dangerous = True

        if is_dangerous:
            reason = f"🛑 Event: High VIX ({vix})" if vix and vix > 30 else "🛑 Event: Gap Detected"
            return False, reason

        return True, "Market Normal"

    def update_pnl(self, current_pnl: float):
        """Updates the current PnL and checks circuit breakers."""
        self.current_pnl = current_pnl
        
        if self.guard_active:
             return False, "🛑 Risk Halt: Black Swan Event Active"
        
        if self.current_pnl <= -self.max_daily_loss:
            self.is_circuit_breaker_tripped = True
            logger.critical(f"🚨 CIRCUIT BREAKER: Loss ₹{abs(self.current_pnl):.2f} > Limit ₹{self.max_daily_loss:.2f}")
            return False, f"🚨 CIRCUIT BREAKER: Loss ₹{abs(self.current_pnl):.2f} > Limit ₹{self.max_daily_loss:.2f}"
            
        return True, "Risk Check Passed"

    def reset_circuit_breaker(self):
        """Manually overrides a tripped circuit breaker (e.g. via Telegram /resume)."""
        self.is_circuit_breaker_tripped = False
        self.guard_active = False
        self.in_hedge_mode = False
        logger.info("🟢 Circuit breaker manually reset. Bot is ready to trade.")

    def reset_daily_stats(self):
        """Resets daily tracking counters and circuit breakers for a new trading session."""
        self.current_pnl = 0.0
        self.daily_trades = 0
        self.is_circuit_breaker_tripped = False
        self.guard_active = False
        self.in_hedge_mode = False
        self._order_timestamps.clear()
        self._open_exposure = 0.0
        logger.info("🌅 Daily Risk Manager stats and circuit breakers reset.")

    def can_trade(self):
        """Checks if new trades are permitted."""
        if self.is_circuit_breaker_tripped:
            return False, "Circuit Breaker Active"
        return True, "Go Ahead"
        
    def validate_order(self, event: OrderEvent) -> tuple[bool, str]:
        """
        Pre-trade circuit breaker. Intercepts OrderEvent before execution.
        Checks: can_trade, fat-finger, rate limit, exposure limit.
        """
        can_trade, reason = self.can_trade()
        if not can_trade:
             return False, reason
             
        # 0. Hedge Mode check (Block Entries, Allow Exits)
        if self.in_hedge_mode:
            if not getattr(event, 'is_exit', False):
                return False, "🛑 HEDGE MODE ACTIVE: New entries are suspended due to structural volatility."
        
        # 1. Fat-finger qty check
        if event.qty > 1800:
             logger.critical(f"🛑 REJECTED: Fat-finger qty {event.qty}")
             return False, "Exceeds max generic quantity (1800)"
        
        # 2. Rate limiter: max orders per minute
        now = time.time()
        # Purge timestamps older than 60 seconds
        while self._order_timestamps and self._order_timestamps[0] < now - 60:
            self._order_timestamps.popleft()
        
        if len(self._order_timestamps) >= self._max_orders_per_minute:
            logger.critical(f"🛑 RATE LIMIT: {len(self._order_timestamps)} orders in last 60s (max {self._max_orders_per_minute})")
            return False, f"Rate limit exceeded: {self._max_orders_per_minute}/min"
        
        is_sell_entry = event.side == "SELL" and not getattr(event, 'is_exit', False)

        # 3. Single-order notional value check (max 40% of capital)
        notional = event.qty * event.price if event.price > 0 else 0
        max_single_order = self.capital * 0.40
        if is_sell_entry and notional > max_single_order and notional > 0:
            logger.critical(f"🛑 REJECTED: Single order ₹{notional:.0f} > 40% capital ₹{max_single_order:.0f}")
            return False, f"Single order notional ₹{notional:.0f} exceeds 40% of capital"
        
        # 4. Total exposure check (max 200% of capital for option selling)
        projected_exposure = self._open_exposure + notional if is_sell_entry else self._open_exposure
        max_total_exposure = self.capital * 2.0
        if projected_exposure > max_total_exposure and is_sell_entry and notional > 0:
            logger.critical(f"🛑 REJECTED: Total exposure ₹{projected_exposure:.0f} > 200% capital ₹{max_total_exposure:.0f}")
            return False, f"Total exposure ₹{projected_exposure:.0f} exceeds 200% of capital"
        
        # All checks passed — record the order
        self._order_timestamps.append(now)
        self.daily_trades += 1
        if is_sell_entry and notional > 0:
            self._open_exposure += notional
            
        return True, "Valid Order"
    
    def on_fill_reduce_exposure(self, symbol: str, qty: int, price: float, side: str):
        """Called when a BUY fill closes a SELL position — reduces tracked exposure."""
        if side == "BUY" and price > 0:
            reduction = qty * price
            self._open_exposure = max(0.0, self._open_exposure - reduction)

    def rebuild_exposure_from_positions(self, positions: dict):
        """Rebuilds exposure from live broker positions after restart/reconciliation."""
        exposure = 0.0
        if isinstance(positions, dict):
            for details in positions.values():
                qty = details.get('qty', 0)
                avg_price = details.get('avg_price', 0.0)
                if qty < 0 and avg_price > 0:
                    exposure += abs(qty) * float(avg_price)
        self._open_exposure = exposure
        logger.info(f"🔄 Risk exposure rebuilt from broker positions: ₹{self._open_exposure:.0f}")
    
    def calculate_trailing_stop(self, entry_price, current_price, current_sl, position_type="BUY"):
        """
        Trailing Stop Logic (Fixed reverse math for SHORT positions).
        - If profit > 1%, move SL to Breakeven
        - If profit > 2%, move SL to +1%
        """
        if position_type == "BUY":
            pnl_pct = (current_price - entry_price) / entry_price
            
            if pnl_pct >= 0.01 and current_sl < entry_price:
                return entry_price
                
            target_sl = entry_price * 1.01
            if pnl_pct >= 0.02 and current_sl < target_sl:
                return target_sl
        else: # SELL
            pnl_pct = (entry_price - current_price) / entry_price
            
            if pnl_pct >= 0.01 and current_sl > entry_price:
                return entry_price
                
            target_sl = entry_price * 0.99
            if pnl_pct >= 0.02 and current_sl > target_sl:
                return target_sl
                
        return current_sl
