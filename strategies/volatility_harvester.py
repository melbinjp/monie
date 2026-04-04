"""
Strategy 2: Volatility Harvester
Profits on HIGH VIX days (18-30) that the main Straddle skips.
Sells wider strangles (OTM options) where 2-3× richer premiums compensate for wider strikes.
"""
import time
import datetime
from strategies.base_strategy import BaseStrategy
from core.logger import get_logger
from core.events import CleanTickEvent, FillEvent, OrderEvent
from core.event_bus import EventBus

logger = get_logger(__name__, strategy_name="VolHarvest")


class VolatilityHarvester(BaseStrategy):
    def get_name(self) -> str:
        return "VolHarvest"

    def __init__(self, broker, risk_manager, event_bus: EventBus, config, state_manager=None, telegram=None, staging_manager=None):
        super().__init__(broker, risk_manager, event_bus)
        self.config = config
        self.state_manager = state_manager
        self.telegram = telegram
        self.staging_manager = staging_manager
        self.entry_time = datetime.time(9, 30)
        self.max_entry_time = datetime.time(10, 30)
        self.exit_time = datetime.time(15, 15)
        
        self.traded_today = False
        self.ce_leg = None
        self.pe_leg = None
        self.current_vix = 0.0
        self.pending_orders = set()

        # Recover state
        if self.state_manager:
            saved = self.state_manager.get_strategy_state(self.get_state_key())
            if saved.get("traded_today"):
                self.traded_today = True
                self.ce_leg = saved.get("ce_leg")
                self.pe_leg = saved.get("pe_leg")
                logger.info("🔄 VolatilityHarvester recovered active positions from state")

    def should_run(self) -> bool:
        """Returns True if eligible to receive ticks based on time window."""
        now = datetime.datetime.now().time()
        if not (datetime.time(9, 15) <= now <= datetime.time(15, 20)):
            return False
        return True

    def on_tick(self, event: CleanTickEvent):
        """Reactive engine triggered by raw market ticks."""
        try:
            # Organically capture VIX updates from the feed
            if event.symbol == "NSE_INDEX|India VIX" or event.symbol == "NSE|INDIA VIX":
                self.current_vix = event.ltp

            now = datetime.datetime.now().time()

            # ENTRY
            if self.entry_time <= now <= self.max_entry_time and not self.traded_today:
                if len(self.pending_orders) == 0:
                    # Gate check via organic VIX tracking
                    if 18.0 <= self.current_vix <= 30.0:
                        self._execute_strangle()

            # MONITOR
            elif self.traded_today and now < self.exit_time:
                self._monitor(event)

            # EXIT
            elif now >= self.exit_time and self.traded_today:
                self.square_off_all()
                self.traded_today = False

        except Exception as e:
            logger.error(f"VolatilityHarvester on_tick error: {e}")

    def _execute_strangle(self):
        """Calculates entry strikes and emits OrderEvents for wider strangle."""
        if not self.check_risk():
            return
            
        nifty_ltp = self.broker.get_quote("NSE|Nifty 50")
        if nifty_ltp <= 0: return

        vix = self.current_vix
        if vix < 18 or vix > 30: return

        # Statistically correct OTM distance: 1.3σ (ensures >90% OTM expiry probability)
        # 1σ daily move = Nifty * VIX / sqrt(252) / 100
        import math
        sigma_1 = nifty_ltp * (vix / 100) / math.sqrt(252)
        otm_distance = int(math.ceil(1.3 * sigma_1 / 50) * 50)  # Round up to nearest 50
        otm_distance = max(250, min(500, otm_distance))  # Safety clamp

        step = 50
        atm_strike = step * round(nifty_ltp / step)
        ce_strike = atm_strike + otm_distance
        pe_strike = atm_strike - otm_distance

        ce_sym = self.broker.get_option_symbol("NIFTY", ce_strike, "CE")
        pe_sym = self.broker.get_option_symbol("NIFTY", pe_strike, "PE")

        if not ce_sym or not pe_sym: return

        lots = max(1, int(self.risk_manager.capital / 75000))
        qty = min(lots, 5) * 50

        ce_price = self.broker.get_quote(ce_sym)
        pe_price = self.broker.get_quote(pe_sym)
        # Use fallback estimates if illiquid pre-market
        if ce_price <= 0: ce_price = 50.0
        if pe_price <= 0: pe_price = 50.0

        ce_tag = self.broker.generate_order_tag(self.get_name(), ce_sym, "SELL")
        pe_tag = self.broker.generate_order_tag(self.get_name(), pe_sym, "SELL")
        
        self.pending_orders.add(ce_tag)
        self.pending_orders.add(pe_tag)

        # Emit orders to Event Bus
        self.event_bus.publish(OrderEvent(order_tag=ce_tag, strategy_id=self.get_name(), symbol=ce_sym, qty=qty, side="SELL", price=ce_price))
        self.event_bus.publish(OrderEvent(order_tag=pe_tag, strategy_id=self.get_name(), symbol=pe_sym, qty=qty, side="SELL", price=pe_price))

        msg = (f"🌪️ VolHarvest: Emitted SELL Orders for OTM Strangle\n"
               f"VIX: {vix:.1f} | OTM Distance: {otm_distance}pt\n"
               f"CE: {ce_sym} | PE: {pe_sym} | Qty: {qty}")
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
                logger.warning(f"⚠️ VolHarvest Order REJECTED: {event.order_tag}")
                return
            
            if event.side == "SELL":
                 # Entry fill
                 # VIX-scaled SL: higher VIX = wider SL allowed
                 vix = self.current_vix if self.current_vix > 0 else 20.0
                 sl_pct = min(0.50, 0.25 + (vix - 18) * 0.02)
                 
                 sl_pct_amount = event.fill_price * sl_pct
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
                 logger.info(f"✅ VolHarvest Confirmed Entry Fill: {event.symbol} @ ₹{event.fill_price} (SL: +{sl_pct*100:.0f}%)")
                 
            else:
                 # Exit fill
                 if self.ce_leg and self.ce_leg.get("symbol") == event.symbol:
                     self.ce_leg['active'] = False
                 elif self.pe_leg and self.pe_leg.get("symbol") == event.symbol:
                     self.pe_leg['active'] = False
                 self._save_state()
                 logger.info(f"✅ VolHarvest Confirmed Exit Fill: {event.symbol}")

    def _monitor(self, event: CleanTickEvent):
        """Multi-tier trailing SL + profit-target early exit."""
        if not self.ce_leg and not self.pe_leg: return

        both_high_decay = True  # Track if both legs have decayed > 70%

        for leg, name in [(self.ce_leg, "CE"), (self.pe_leg, "PE")]:
            if not leg or not leg['active']:
                continue
            if event.symbol != leg['symbol']:
                # Can't evaluate this leg from this tick
                if leg['active']:
                    both_high_decay = False
                continue
                
            ltp = event.ltp
            profit_pct = (leg['entry_price'] - ltp) / leg['entry_price'] if leg['entry_price'] > 0 else 0

            # Track decay for profit-target exit
            if profit_pct < 0.70:
                both_high_decay = False

            # Tier 1: +20% decay → breakeven lock
            if profit_pct >= 0.20:
                breakeven_sl = leg['entry_price']
                if breakeven_sl < leg['sl_price']:
                    leg['sl_price'] = breakeven_sl
                    logger.info(f"🔒 VolHarvest {name} Breakeven Lock: SL → ₹{breakeven_sl:.1f}")

            # Tier 2: +40% decay → lock +15% of entry
            if profit_pct >= 0.40:
                lock_sl = leg['entry_price'] * 0.85
                if lock_sl < leg['sl_price']:
                    leg['sl_price'] = lock_sl
                    logger.info(f"💰 VolHarvest {name} Profit Lock: SL → ₹{lock_sl:.1f}")

            # Tier 3: +60% decay → lock +30% of entry
            if profit_pct >= 0.60:
                lock_sl = leg['entry_price'] * 0.70
                if lock_sl < leg['sl_price']:
                    leg['sl_price'] = lock_sl
                    logger.info(f"💰 VolHarvest {name} Deep Lock: SL → ₹{lock_sl:.1f}")

            # SL hit check
            if ltp >= leg['sl_price']:
                msg = f"🛑 VolHarvest {name} SL Hit @ ₹{ltp:.1f}"
                logger.warning(msg)
                if self.telegram: self.telegram.send_message(msg)
                
                exit_tag = self.broker.generate_order_tag(self.get_name(), leg['symbol'], "BUY")
                self.pending_orders.add(exit_tag)
                self.event_bus.publish(OrderEvent(order_tag=exit_tag, strategy_id=self.get_name(), symbol=leg['symbol'], qty=leg['qty'], side="BUY"))
                
                leg['active'] = False
                self._save_state()

        # Profit-target exit: both legs decayed > 70%, lock guaranteed profit
        if both_high_decay and self.ce_leg and self.pe_leg:
            if self.ce_leg.get('active') and self.pe_leg.get('active'):
                msg = "🎯 VolHarvest: Both legs decayed >70%. Locking profit early."
                logger.info(msg)
                if self.telegram: self.telegram.send_message(msg)
                self.square_off_all(reason_msg=msg)

    def square_off_all(self, reason_msg=None):
        msg = reason_msg or "⏰ VolHarvest EOD: Squaring off strangle"
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
