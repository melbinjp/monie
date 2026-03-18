"""
Strategy 3: Theta Crusher
Profits on dead-flat, ultra-low-VIX days by selling far-OTM weekly options.
When markets are completely dead, this scrapes guaranteed theta decay.
"""
import time
import datetime
from strategies.base_strategy import BaseStrategy
from core.logger import get_logger
from core.events import CleanTickEvent, FillEvent, OrderEvent
from core.event_bus import EventBus

logger = get_logger(__name__, strategy_name="ThetaCrush")


class ThetaCrusher(BaseStrategy):
    def get_name(self) -> str:
        return "ThetaCrush"

    def __init__(self, broker, risk_manager, event_bus: EventBus, config, state_manager=None, telegram=None, staging_manager=None):
        super().__init__(broker, risk_manager, event_bus)
        self.config = config
        self.state_manager = state_manager
        self.telegram = telegram
        self.staging_manager = staging_manager
        self.entry_time = datetime.time(11, 0)
        self.max_entry_time = datetime.time(13, 0)
        self.exit_time = datetime.time(15, 10)
        
        self.traded_today = False
        self.ce_leg = None
        self.pe_leg = None
        self.pending_orders = set()
        self.current_vix = 0.0  # Organic VIX tracking

        # Recover state
        if self.state_manager:
            saved = self.state_manager.get_strategy_state(self.get_state_key())
            if saved.get("traded_today"):
                self.traded_today = True
                self.ce_leg = saved.get("ce_leg")
                self.pe_leg = saved.get("pe_leg")
                logger.info("🔄 ThetaCrusher recovered active positions from state")

    def should_run(self) -> bool:
        """Returns True if strategy is eligible to receive ticks."""
        now = datetime.datetime.now().time()
        if not (datetime.time(10, 45) <= now <= datetime.time(15, 15)):
            return False
            
        return True

    def on_tick(self, event: CleanTickEvent):
        """Reactive evaluation triggered by market ticks."""
        try:
            # Organic VIX tracking
            if event.symbol in ("NSE_INDEX|India VIX", "NSE|INDIA VIX"):
                self.current_vix = event.ltp
            
            now = datetime.datetime.now().time()

            # Entry Logic
            if self.entry_time <= now <= self.max_entry_time and not self.traded_today:
                if len(self.pending_orders) == 0:
                    # VIX gate: only enter on ultra-low VIX days
                    if self.current_vix > 0 and self.current_vix >= 13:
                        return  # Too volatile for far-OTM decay play
                    self._execute_far_otm(event)

            # Monitoring/Exit Logic
            elif self.traded_today and now < self.exit_time:
                self._monitor(event)

            # EOD Square-off
            elif now >= self.exit_time and self.traded_today:
                self.square_off_all()
                self.traded_today = False

        except Exception as e:
            logger.error(f"ThetaCrusher on_tick error: {e}")

    def _execute_far_otm(self, event: CleanTickEvent):
        """Calculates entry strikes and emits OrderEvents."""
        if not self.check_risk():
            return
            
        nifty_ltp = self.broker.get_quote("NSE|Nifty 50")
        if nifty_ltp <= 0: return

        step = 50
        atm_strike = step * round(nifty_ltp / step)
        otm_distance = 500
        
        ce_strike = atm_strike + otm_distance
        pe_strike = atm_strike - otm_distance

        ce_sym = self.broker.get_option_symbol("NIFTY", ce_strike, "CE")
        pe_sym = self.broker.get_option_symbol("NIFTY", pe_strike, "PE")

        if not ce_sym or not pe_sym:
            return

        ce_price = self.broker.get_quote(ce_sym)
        pe_price = self.broker.get_quote(pe_sym)
        if ce_price < 2.0 or pe_price < 2.0:
            logger.info(f"ThetaCrush: Premiums too thin (CE: ₹{ce_price}, PE: ₹{pe_price}). Skipping.")
            self.traded_today = True  # Don't retry
            return

        lots = max(1, int(self.risk_manager.capital / 100000))
        qty = min(lots, 3) * 50

        # Emit OrderEvents instead of synchronous execution
        ce_tag = self.broker.generate_order_tag(self.get_name(), ce_sym, "SELL")
        pe_tag = self.broker.generate_order_tag(self.get_name(), pe_sym, "SELL")

        self.pending_orders.add(ce_tag)
        self.pending_orders.add(pe_tag)

        self.event_bus.publish(OrderEvent(order_tag=ce_tag, strategy_id=self.get_name(), symbol=ce_sym, qty=qty, side="SELL", price=ce_price))
        self.event_bus.publish(OrderEvent(order_tag=pe_tag, strategy_id=self.get_name(), symbol=pe_sym, qty=qty, side="SELL", price=pe_price))
        
        msg = f"🧊 ThetaCrusher: Emitted SELL Orders for Far-OTM Strangle (Qty: {qty})"
        logger.info(msg)
        if self.telegram: self.telegram.send_message(msg)

    def on_fill(self, event: FillEvent):
        """Updates internal state strictly based on OMS confirmations."""
        if event.order_tag in self.pending_orders:
            self.pending_orders.remove(event.order_tag)
            
            # Handle OMS rejection (zero-qty FillEvent)
            if event.fill_qty == 0:
                logger.warning(f"⚠️ ThetaCrush Order REJECTED: {event.order_tag}")
                return
            
            # Identify which leg this is
            if event.side == "SELL":
                 # Entry fill
                 sl_pct_amount = event.fill_price * 1.0 # 100% stop loss
                 sl_price = event.fill_price + sl_pct_amount
                 
                 leg_data = {
                     "symbol": event.symbol, 
                     "entry_price": event.fill_price, 
                     "sl_price": sl_price, 
                     "qty": event.fill_qty, 
                     "active": True
                 }
                 
                 if "CE" in event.symbol: self.ce_leg = leg_data
                 else: self.pe_leg = leg_data
                 
                 self.traded_today = True
                 self._save_state()
                 logger.info(f"✅ ThetaCrusher Confirmed Entry Fill: {event.symbol} @ ₹{event.fill_price}")
                 
            else:
                 # Exit fill
                 if self.ce_leg and self.ce_leg.get("symbol") == event.symbol:
                     self.ce_leg['active'] = False
                 elif self.pe_leg and self.pe_leg.get("symbol") == event.symbol:
                     self.pe_leg['active'] = False
                 self._save_state()
                 logger.info(f"✅ ThetaCrusher Confirmed Exit Fill: {event.symbol}")

    def _monitor(self, event: CleanTickEvent):
        """Trailing SL + profit-target exit for far-OTM decay."""
        if not self.ce_leg and not self.pe_leg: return
        
        both_high_decay = True

        for leg, name in [(self.ce_leg, "CE"), (self.pe_leg, "PE")]:
            if not leg or not leg.get('active'):
                continue
            if event.symbol != leg['symbol']:
                if leg['active']:
                    both_high_decay = False
                continue
                
            ltp = event.ltp
            profit_pct = (leg['entry_price'] - ltp) / leg['entry_price'] if leg['entry_price'] > 0 else 0

            if profit_pct < 0.75:
                both_high_decay = False

            # Trailing: +40% decay → breakeven lock
            if profit_pct >= 0.40:
                breakeven_sl = leg['entry_price']
                if breakeven_sl < leg['sl_price']:
                    leg['sl_price'] = breakeven_sl
                    logger.info(f"🔒 ThetaCrush {name} Breakeven Lock: SL → ₹{breakeven_sl:.1f}")

            # Trailing: +60% decay → lock +25%
            if profit_pct >= 0.60:
                lock_sl = leg['entry_price'] * 0.75
                if lock_sl < leg['sl_price']:
                    leg['sl_price'] = lock_sl
                    logger.info(f"💰 ThetaCrush {name} Profit Lock: SL → ₹{lock_sl:.1f}")

            # SL hit
            if ltp >= leg['sl_price']:
                msg = f"🛑 ThetaCrush {name} SL Hit @ ₹{ltp:.1f}"
                logger.warning(msg)
                if self.telegram: self.telegram.send_message(msg)
                
                exit_tag = self.broker.generate_order_tag(self.get_name(), leg['symbol'], "BUY")
                self.pending_orders.add(exit_tag)
                self.event_bus.publish(OrderEvent(order_tag=exit_tag, strategy_id=self.get_name(), symbol=leg['symbol'], qty=leg['qty'], side="BUY"))
                
                leg['active'] = False
                self._save_state()

        # Profit-target: both legs decayed > 75% → lock guaranteed profit
        if both_high_decay and self.ce_leg and self.pe_leg:
            if self.ce_leg.get('active') and self.pe_leg.get('active'):
                msg = "🎯 ThetaCrush: Both legs decayed >75%. Locking profit early."
                logger.info(msg)
                if self.telegram: self.telegram.send_message(msg)
                self.square_off_all(reason_msg=msg)

    def square_off_all(self, reason_msg=None):
        msg = reason_msg or "⏰ ThetaCrush EOD: Closing far-OTM positions"
        logger.info(msg)
        if self.telegram and not reason_msg: self.telegram.send_message(msg)
        
        for leg in [self.ce_leg, self.pe_leg]:
            if leg and leg.get('active'):
                exit_tag = self.broker.generate_order_tag(self.get_name(), leg['symbol'], "BUY")
                self.pending_orders.add(exit_tag)
                self.event_bus.publish(OrderEvent(order_tag=exit_tag, strategy_id=self.get_name(), symbol=leg['symbol'], qty=leg['qty'], side="BUY"))
                leg['active'] = False

    def _save_state(self):
        if self.state_manager:
            self.state_manager.save_strategy_state(self.get_state_key(), {
                "traded_today": self.traded_today,
                "ce_leg": self.ce_leg,
                "pe_leg": self.pe_leg
            })
