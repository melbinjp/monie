"""
Strategy 4: Expiry Day Scalper
Profits from extreme gamma acceleration on Nifty weekly expiry (Thursdays).
Options decay at maximum speed on expiry day — this strategy exploits that.
"""
import time
import datetime
from strategies.base_strategy import BaseStrategy
from core.logger import get_logger
from core.events import CleanTickEvent, FillEvent, OrderEvent
from core.event_bus import EventBus

logger = get_logger(__name__, strategy_name="ExpiryScalp")


class ExpirydayScalper(BaseStrategy):
    def get_name(self) -> str:
        return "ExpiryScalp"

    def __init__(self, broker, risk_manager, event_bus: EventBus, config, state_manager=None, telegram=None, staging_manager=None):
        super().__init__(broker, risk_manager, event_bus)
        self.config = config
        self.state_manager = state_manager
        self.telegram = telegram
        self.staging_manager = staging_manager
        self.entry_time = datetime.time(10, 0)
        self.max_entry_time = datetime.time(11, 0)
        self.exit_time = datetime.time(15, 10)
        
        self.traded_today = False
        self.ce_leg = None
        self.pe_leg = None
        self.pending_orders = set()

        # Recover state
        if self.state_manager:
            saved = self.state_manager.get_strategy_state(self.get_state_key())
            if saved.get("traded_today"):
                self.traded_today = True
                self.ce_leg = saved.get("ce_leg")
                self.pe_leg = saved.get("pe_leg")
                logger.info("🔄 ExpirydayScalper recovered active positions from state")

    def should_run(self) -> bool:
        """Returns True if eligible on Nifty weekly expiry day (Thursday)."""
        now = datetime.datetime.now()
        if now.weekday() != 3:  # 3 = Thursday
            return False
        return datetime.time(9, 45) <= now.time() <= datetime.time(15, 15)

    def on_tick(self, event: CleanTickEvent):
        """Reactive engine triggered by raw market ticks."""
        try:
            now = datetime.datetime.now().time()

            if self.entry_time <= now <= self.max_entry_time and not self.traded_today:
                if len(self.pending_orders) == 0:
                    self._execute_expiry_straddle()

            elif self.traded_today and now < self.exit_time:
                self._monitor(event)

            elif now >= self.exit_time and self.traded_today:
                self.square_off_all()
                self.traded_today = False

        except Exception as e:
            logger.error(f"ExpirydayScalper on_tick error: {e}")

    def _execute_expiry_straddle(self):
        """Calculates entry strikes and emits OrderEvents for ATM straddle."""
        if not self.check_risk():
            return
            
        nifty_ltp = self.broker.get_quote("NSE|Nifty 50")
        if nifty_ltp <= 0: return

        step = 50
        atm_strike = step * round(nifty_ltp / step)

        # Expiry day uses current weekly contract (expiry_offset=0)
        ce_sym = self.broker.get_option_symbol("NIFTY", atm_strike, "CE", expiry_offset=0)
        pe_sym = self.broker.get_option_symbol("NIFTY", atm_strike, "PE", expiry_offset=0)

        if not ce_sym or not pe_sym: return

        ce_price = self.broker.get_quote(ce_sym)
        pe_price = self.broker.get_quote(pe_sym)
        if ce_price <= 0 or pe_price <= 0: return

        lots = max(1, int(self.risk_manager.capital / 100000))
        qty = min(lots, 3) * 50

        ce_tag = self.broker.generate_order_tag(self.get_name(), ce_sym, "SELL")
        pe_tag = self.broker.generate_order_tag(self.get_name(), pe_sym, "SELL")
        
        self.pending_orders.add(ce_tag)
        self.pending_orders.add(pe_tag)

        # Emit orders to Event Bus
        self.event_bus.publish(OrderEvent(order_tag=ce_tag, strategy_id=self.get_name(), symbol=ce_sym, qty=qty, side="SELL", price=ce_price))
        self.event_bus.publish(OrderEvent(order_tag=pe_tag, strategy_id=self.get_name(), symbol=pe_sym, qty=qty, side="SELL", price=pe_price))

        sl_pct = 0.30
        msg = (f"📅 ExpirydayScalper: Emitted SELL Orders for Expiry-Day ATM Straddle\n"
               f"CE: {ce_sym} @ ₹{ce_price:.1f} | PE: {pe_sym} @ ₹{pe_price:.1f}\n"
               f"Total Premium: ₹{(ce_price + pe_price) * qty:.0f} | SL: {sl_pct*100:.0f}%")
        logger.info(msg)
        if self.telegram: self.telegram.send_message(msg)

        if hasattr(self.broker, 'subscribe'):
            self.broker.subscribe([ce_sym, pe_sym])

    def on_fill(self, event: FillEvent):
        """Updates internal state strictly based on OMS confirmations."""
        if event.order_tag in self.pending_orders:
            self.pending_orders.remove(event.order_tag)
            
            # Handle OMS rejection (zero-qty FillEvent)
            if event.fill_qty == 0:
                logger.warning(f"⚠️ ExpiryScalp Order REJECTED: {event.order_tag}")
                return
            
            if event.side == "SELL":
                 # Entry fill
                 sl_pct_amount = event.fill_price * 0.30  # 30% SL
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
                 logger.info(f"✅ ExpiryScalp Confirmed Entry Fill: {event.symbol} @ ₹{event.fill_price}")
                 
            else:
                 # Exit fill
                 if self.ce_leg and self.ce_leg.get("symbol") == event.symbol:
                     self.ce_leg['active'] = False
                 elif self.pe_leg and self.pe_leg.get("symbol") == event.symbol:
                     self.pe_leg['active'] = False
                 self._save_state()
                 logger.info(f"✅ ExpiryScalp Confirmed Exit Fill: {event.symbol}")

    def _monitor(self, event: CleanTickEvent):
        """Expiry-day monitoring: multi-tier trailing + time-based SL tightening."""
        if not self.ce_leg and not self.pe_leg: return

        now = datetime.datetime.now().time()
        is_late_session = now >= datetime.time(14, 30)  # Final gamma burst window

        for leg, name in [(self.ce_leg, "CE"), (self.pe_leg, "PE")]:
            if not leg or not leg.get('active') or event.symbol != leg['symbol']:
                continue
                
            ltp = event.ltp
            profit_pct = (leg['entry_price'] - ltp) / leg['entry_price'] if leg['entry_price'] > 0 else 0

            # Tier 1: +20% decay → breakeven lock
            if profit_pct >= 0.20:
                breakeven_sl = leg['entry_price']
                if breakeven_sl < leg['sl_price']:
                    leg['sl_price'] = breakeven_sl
                    logger.info(f"🔒 Expiry {name} Breakeven Lock: SL → ₹{breakeven_sl:.1f}")

            # Tier 2: +35% decay → lock +15% of entry
            if profit_pct >= 0.35:
                lock_sl = leg['entry_price'] * 0.85
                if lock_sl < leg['sl_price']:
                    leg['sl_price'] = lock_sl
                    logger.info(f"💰 Expiry {name} Profit Lock: SL → ₹{lock_sl:.1f}")

            # Tier 3: +50% decay → hyper-aggressive trailing
            if profit_pct >= 0.50:
                new_sl = ltp + (leg['entry_price'] * 0.08)  # Very tight gap on expiry
                if new_sl < leg['sl_price']:
                    leg['sl_price'] = new_sl
                    logger.info(f"📐 Expiry {name} Hyper-Trail SL → ₹{new_sl:.1f} ({profit_pct*100:.0f}% decay)")

            # Time-based tightening: after 14:30, if profitable, clamp SL very tight
            if is_late_session and profit_pct > 0.10:
                time_sl = ltp + (leg['entry_price'] * 0.05)  # 5% gap only
                if time_sl < leg['sl_price']:
                    leg['sl_price'] = time_sl
                    logger.info(f"⏰ Expiry {name} Late-Session Clamp: SL → ₹{time_sl:.1f}")

            # SL hit check
            if ltp >= leg['sl_price']:
                msg = f"🛑 ExpiryScalp {name} SL Hit @ ₹{ltp:.1f}"
                logger.warning(msg)
                if self.telegram: self.telegram.send_message(msg)
                
                exit_tag = self.broker.generate_order_tag(self.get_name(), leg['symbol'], "BUY")
                self.pending_orders.add(exit_tag)
                self.event_bus.publish(OrderEvent(order_tag=exit_tag, strategy_id=self.get_name(), symbol=leg['symbol'], qty=leg['qty'], side="BUY"))
                
                leg['active'] = False
                self._save_state()

    def square_off_all(self, reason_msg=None):
        msg = reason_msg or "⏰ ExpiryScalp EOD: Closing expiry-day positions"
        logger.info(msg)
        if self.telegram and not reason_msg: self.telegram.send_message(msg)
        
        for leg in [self.ce_leg, self.pe_leg]:
            if leg and leg.get('active'):
                exit_tag = self.broker.generate_order_tag(self.get_name(), leg['symbol'], "BUY")
                self.pending_orders.add(exit_tag)
                self.event_bus.publish(OrderEvent(order_tag=exit_tag, strategy_id=self.get_name(), symbol=leg['symbol'], qty=leg['qty'], side="BUY"))
                leg['active'] = False
        self._save_state()

    def _save_state(self):
        if self.state_manager:
            self.state_manager.save_strategy_state(self.get_state_key(), {
                "traded_today": self.traded_today,
                "ce_leg": self.ce_leg,
                "pe_leg": self.pe_leg
            })
