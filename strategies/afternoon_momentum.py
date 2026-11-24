"""
Strategy 5: Wartime Afternoon Momentum Scalper
Operates strictly in the afternoon. Tracks midday consolidation (12:30 - 13:30).
Buys ATM options upon breakout (13:30 - 15:00) with strict trailing stop-losses.
Buying options caps catastrophic risk from sudden wartime news.
"""
import time
import datetime
from strategies.base_strategy import BaseStrategy
from core.logger import get_logger
from core.events import CleanTickEvent, FillEvent, OrderEvent
from core.symbols import is_india_vix, is_nifty50

logger = get_logger(__name__, strategy_name="MiddayScalp")

class AfternoonMomentumScalper(BaseStrategy):
    def get_name(self) -> str:
        return "MiddayScalp"

    def __init__(self, broker, risk_manager, event_bus, config, state_manager=None, telegram=None, staging_manager=None):
        super().__init__(broker, risk_manager, event_bus)
        self.config = config
        self.state_manager = state_manager
        self.telegram = telegram
        
        # Timing parameters
        self.consolidation_start = datetime.time(12, 30)
        self.consolidation_end = datetime.time(13, 30)
        self.trading_end = datetime.time(15, 0)
        self.exit_time = datetime.time(15, 15)
        
        # State
        self.traded_today = False
        self.range_high = -float('inf')
        self.range_low = float('inf')
        
        self.position = None  # None, 'CE', 'PE'
        self.entry_price = 0.0
        self.trailing_sl = 0.0
        self.target_symbol = None
        self.order_tag = None
        
        self.vix_now = 0.0

        # Recover state
        if self.state_manager:
            saved = self.state_manager.get_strategy_state(self.get_state_key())
            if saved.get("traded_today"):
                self.traded_today = True
                self.position = saved.get("position")
                self.entry_price = saved.get("entry_price", 0.0)
                self.trailing_sl = saved.get("trailing_sl", 0.0)
                self.target_symbol = saved.get("target_symbol")
                self.order_tag = saved.get("order_tag")
                logger.info(f"🔄 MiddayScalp recovered active {self.position} position")

    def should_run(self) -> bool:
        """Runs in the afternoon session."""
        now = datetime.datetime.now().time()
        return self.consolidation_start <= now <= datetime.time(15, 20)

    def on_tick(self, event: CleanTickEvent):
        """Reactive engine triggered by raw market ticks."""
        try:
            if is_india_vix(event.symbol):
                self.vix_now = event.ltp

            # We strictly track NIFTY 50 for breakouts
            if is_nifty50(event.symbol):
                now = datetime.datetime.now().time()

                # Phase 1: Range Building (12:30 - 13:30)
                if self.consolidation_start <= now <= self.consolidation_end and not self.traded_today:
                    if event.ltp > self.range_high: self.range_high = event.ltp
                    if event.ltp < self.range_low: self.range_low = event.ltp

                # Phase 2: Breakout Hunting (13:30 - 15:00)
                elif self.consolidation_end < now <= self.trading_end and not self.traded_today:
                    # Validate we actually built a sane range 
                    if self.range_high == -float('inf') or self.range_low == float('inf'):
                        return
                    range_size = self.range_high - self.range_low
                    if range_size < 30: return # Meaningless narrow range, skip
                    if range_size > 300: return # Extreme volatility already happened
                    
                    if event.ltp > self.range_high:
                        logger.info(f"🚀 Upside Breakout Detected > {self.range_high}")
                        if self.telegram: self.telegram.send_message(f"🚀 **Midday Upside Breakout**\nNifty crossed {self.range_high}. Buying CE to cap risk.")
                        self._execute_breakout(event.ltp, "CE")
                        
                    elif event.ltp < self.range_low:
                        logger.info(f"🩸 Downside Breakout Detected < {self.range_low}")
                        if self.telegram: self.telegram.send_message(f"🩸 **Midday Downside Breakout**\nNifty plunged below {self.range_low}. Buying PE to cap risk.")
                        self._execute_breakout(event.ltp, "PE")

            # Phase 3: Trailing SL / Target monitoring
            if self.target_symbol and event.symbol == self.target_symbol:
                self._monitor_position(event.ltp)

            # Phase 4: EOD Square-off
            now = datetime.datetime.now().time()
            if now >= self.exit_time and self.position is not None:
                self.square_off_all()
                self._reset_daily()

        except Exception as e:
            logger.error(f"MiddayScalp on_tick error: {e}")

    def _execute_breakout(self, nifty_ltp, option_type):
        """Buys the ATM option."""
        if not self.check_risk(): return
        
        step = 50
        atm_strike = step * round(nifty_ltp / step)
        
        self.target_symbol = self.broker.get_option_symbol("NIFTY", atm_strike, option_type)
        if not self.target_symbol: return
        
        opt_price = self.broker.get_quote(self.target_symbol)
        if opt_price <= 0: return
        
        qty = 50  # Fixed 1 lot for extremely tight strict risk control initially
        
        self.order_tag = self.broker.generate_order_tag(self.get_name(), self.target_symbol, "BUY")
        self.position = option_type
        self.traded_today = True  # Fire once per day purely
        
        # We process entry via OMS through the Event Bus
        event = OrderEvent(
            symbol=self.target_symbol,
            qty=qty,
            side="BUY",
            order_type="MARKET",
            order_tag=self.order_tag,
            price=opt_price
        )
        self.event_bus.publish(event)
        
        if self.state_manager:
            self._save_state()

    def on_fill(self, event: FillEvent):
        """Called by EventBus when OMS executes the order."""
        if event.order_tag == self.order_tag and event.side == "BUY":
            self.entry_price = event.fill_price
            # Strict 20% Initial SL on the long premium
            self.trailing_sl = self.entry_price * 0.80
            msg = f"✅ Wartime Scalp Filled: {event.symbol} @ {self.entry_price:.2f}\nStrict Initial SL: {self.trailing_sl:.2f}"
            logger.info(msg)
            if self.telegram: self.telegram.send_message(msg)
            if self.state_manager: self._save_state()

        elif event.order_tag and self.order_tag and event.order_tag.startswith(self.order_tag) and event.side == "SELL":
            # Exit order filled
            pnl = event.fill_price - self.entry_price
            pnl_pct = (pnl / self.entry_price) * 100
            msg = f"🏁 Wartime Scalp Closed: {event.symbol} @ {event.fill_price:.2f}\nTrade PnL: {pnl_pct:+.2f}%"
            logger.info(msg)
            if self.telegram: self.telegram.send_message(msg)
            self._reset_daily()

    def _monitor_position(self, opt_ltp):
        """Aggressively trails SL on the long option."""
        if self.entry_price <= 0: return

        # 1. Check SL Hit
        if opt_ltp <= self.trailing_sl:
            logger.warning(f"🛡️ Midday Scalp Trailing SL Hit! LTP {opt_ltp} <= SL {self.trailing_sl}")
            self.square_off_all()
            return
            
        # 2. Trail SL Aggressively
        pnl_pct = (opt_ltp - self.entry_price) / self.entry_price
        
        new_sl = self.trailing_sl
        if pnl_pct >= 0.15: 
            # 15% profit -> Trail to +5%
            target = self.entry_price * 1.05
            if target > new_sl: new_sl = target
        if pnl_pct >= 0.30:
            # 30% profit -> Trail to +15%
            target = self.entry_price * 1.15
            if target > new_sl: new_sl = target
        if pnl_pct >= 0.50:
            # 50% profit -> Trail 20% behind current price
            target = opt_ltp * 0.80
            if target > new_sl: new_sl = target
            
        if new_sl > self.trailing_sl:
            self.trailing_sl = new_sl
            logger.info(f"🚀 Scalp SL Trailed to {self.trailing_sl:.2f} (LTP: {opt_ltp})")
            if self.state_manager: self._save_state()

    def activate_hedge_mode(self):
        """
        Omni-Market Resilience Trigger:
        Since this is a BUY strategy, structural volatility is mathematically safe (max loss is premium),
        but we still tighten the trailing SL aggressively to capture any profits instantly before 
        the market violently whipsaws.
        """
        if self.position is not None and self.target_symbol:
            try:
                current_ltp = self.broker.get_quote(self.target_symbol)
                if current_ltp and current_ltp > 0:
                    # Snaps the SL up right underneath current price (-3%) or breakeven
                    tight_sl = max(self.entry_price, current_ltp * 0.97)
                    if tight_sl > self.trailing_sl:
                        self.trailing_sl = tight_sl
                        logger.warning(f"🛡️ Hedge Mode: {self.position} (Long) SL violently raised to ₹{tight_sl:.1f} (LTP: ₹{current_ltp:.1f})")
                        if self.state_manager: self._save_state()
            except Exception as e:
                logger.warning(f"Error during momentum SL update logic: {e}")

    def square_off_all(self, reason_msg=None):
        if self.position is not None and self.target_symbol:
            exit_tag = self.order_tag + "_EXIT" if self.order_tag else "MIDDAY_EXIT"
            event = OrderEvent(
                symbol=self.target_symbol,
                qty=50,
                side="SELL",
                order_type="MARKET",
                order_tag=exit_tag,
                price=0.0
            )
            self.event_bus.publish(event)
            if reason_msg:
                logger.warning(f"Squaring off Scalper: {reason_msg}")

    def _reset_daily(self):
        self.position = None
        self.target_symbol = None
        self.entry_price = 0.0
        self.trailing_sl = 0.0
        self.order_tag = None
        if self.state_manager:
            self.state_manager.clear_strategy_state(self.get_state_key())

    def _save_state(self):
        if self.state_manager:
            self.state_manager.save_strategy_state(self.get_state_key(), {
                "traded_today": self.traded_today,
                "position": self.position,
                "entry_price": self.entry_price,
                "trailing_sl": self.trailing_sl,
                "target_symbol": self.target_symbol,
                "order_tag": self.order_tag,
                "timestamp": str(datetime.datetime.now())
            })

    def get_state_key(self) -> str:
        return "midday_scalp"
