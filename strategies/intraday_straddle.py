import time
import datetime
from strategies.base_strategy import BaseStrategy
from core.events import CleanTickEvent, FillEvent, OrderEvent

class IntradayShortStraddle(BaseStrategy):
    def get_name(self) -> str:
        return "Straddle"
    
    def __init__(self, broker, risk_manager, event_bus, config, state_manager=None, telegram=None, staging_manager=None):
        super().__init__(broker, risk_manager, event_bus)
        self.config = config
        self.state_manager = state_manager
        self.telegram = telegram
        self.staging_manager = staging_manager
        self.entry_time = datetime.time(9, 23)
        self.max_entry_time = datetime.time(9, 45)
        self.exit_time = datetime.time(15, 15)
        self.theta_exit_time = datetime.time(14, 0)
        
        self.sl_percentage = 0.25
        self.traded_today = False
        self.ce_leg = None
        self.pe_leg = None
        self.long_ce_leg = None
        self.long_pe_leg = None
        self.hedge_legs = []
        
        self.vix_at_entry = 15.0
        self.entry_timestamp = None
        self.last_vix_check = None
        self.prev_day_vix = None
        self._last_state_save = 0
        self.pending_orders = set()

        # Asynchronous State Machine tracking
        self.waiting_for_pe = False
        self.ce_filled_time = 0
        self.pe_target_sym = None
        self.pe_target_qty = 0
        self.pe_target_price = 0.0

        if self.state_manager and self.state_manager.state.get("traded_today"):
            today_str = str(datetime.datetime.now().date())
            if self.state_manager.state.get("last_trade_date") == today_str:
                self.traded_today = True
                active = self.state_manager.state.get("active_legs", {})
                self.ce_leg = active.get("ce_leg")
                self.pe_leg = active.get("pe_leg")
                self.long_ce_leg = active.get("long_ce_leg")
                self.long_pe_leg = active.get("long_pe_leg")
                self.hedge_legs = active.get("hedge_legs", [])
                
                meta = self.state_manager.state.get("trade_meta", {})
                self.vix_at_entry = meta.get("vix_at_entry", 15.0)
                self.prev_day_vix = meta.get("prev_day_vix", None)
                if meta.get("entry_timestamp"):
                    self.entry_timestamp = datetime.datetime.fromisoformat(meta.get("entry_timestamp"))
                
                msg = f"🔄 System Rebooted. Recovered Live Active Straddle (VIX baseline: {self.vix_at_entry:.1f})."
                self.logger.info(msg)
                if self.telegram: self.telegram.send_message(msg)
                
                if hasattr(self.broker, 'subscribe'):
                    subs = ["NSE|Nifty 50", "NSE|INDIA VIX"]
                    if self.ce_leg: subs.append(self.ce_leg['symbol'])
                    if self.pe_leg: subs.append(self.pe_leg['symbol'])
                    self.broker.subscribe(subs)

    def should_run(self) -> bool:
        """This strategy runs every weekday during market hours."""
        now = datetime.datetime.now().time()
        return datetime.time(9, 15) <= now <= datetime.time(15, 20)

    def get_atm_strike(self, spot_price, step=50):
        return step * round(spot_price / step)

    def on_tick(self, event: CleanTickEvent):
        """Event-Driven Fast Path Triggered by EventBus"""
        try:
            # Organically capture VIX updates
            if event.symbol in ("NSE_INDEX|India VIX", "NSE|INDIA VIX"):
                self.vix_now = event.ltp

            now = datetime.datetime.now().time()

            # 1. ENTRY LOGIC
            if now >= self.entry_time and now <= self.max_entry_time and not self.traded_today:
                if len(self.pending_orders) == 0:
                    if self.waiting_for_pe:
                        # 2-minute stagger wait complete?
                        if time.time() - self.ce_filled_time >= 120:
                            self._execute_delayed_pe()
                    else:
                        # Initial Entry Mode
                        if self.check_risk():
                            self._initiate_straddle_sequence()

            # 2. THETA DECAY EARLY EXIT (After 2:00 PM)
            elif self.traded_today and now >= self.theta_exit_time and now < self.exit_time:
                if self._check_theta_exit(): return
                self._mid_session_vix_check()
                self._monitor_tick(event)
            
            # 3. MONITORING
            elif self.traded_today and now < self.exit_time:
                self._mid_session_vix_check()
                self._monitor_tick(event)
                
            # 4. EOD EXIT
            elif now >= self.exit_time and self.traded_today:
                self.square_off_all()
                self.traded_today = False
                if self.state_manager: self.state_manager.clear_active_legs()
                
        except Exception as e:
            self.logger.error(f"Strategy Error in on_tick: {e}")

    def _initiate_straddle_sequence(self):
        msg = "⚡ 09:23 AM: Executing Holy Trinity Alpha... fetching Spot & VIX."
        self.logger.info(msg)
        if self.telegram: self.telegram.send_message(msg)
        
        nifty_ltp = self.broker.get_quote("NSE|Nifty 50")
        if not nifty_ltp: return

        vix_now = getattr(self, "vix_now", self.broker.get_quote("NSE|INDIA VIX"))
        
        # VIX GATE
        if vix_now > 0 and self.prev_day_vix and self.prev_day_vix > 0:
            vix_change = ((vix_now - self.prev_day_vix) / self.prev_day_vix) * 100
            if vix_change > 15:
                gate_msg = f"🚫 VIX GATE: VIX surged {vix_change:.1f}% overnight. Skipping today."
                self.logger.info(gate_msg)
                if self.telegram: self.telegram.send_message(gate_msg)
                self.traded_today = True
                return
        if vix_now > 0: self.prev_day_vix = vix_now

        vix_ltp = vix_now if vix_now > 0 else 15.0
        raw_sl = (vix_ltp / 100.0) * 1.5
        self.sl_percentage = max(0.15, min(0.35, raw_sl))
        
        atm_strike = self.get_atm_strike(nifty_ltp)
        ce_price = 0.0
        pe_price = 0.0
        atm_ce = None
        atm_pe = None
        
        # --- PHASE 9: Analytics API Integration (O(1) Option Chain Fetch) ---
        if hasattr(self.broker, 'get_option_chain'):
            # Formulate expiry date payload (assuming current weekly expiry logic, but Upstox takes exact date)
            # Instead of guessing expiry, we rely on the _get_instrument_token which auto-fetches master
            # To fetch option chain, we need the underlying instrument key
            underlying_token = self.broker._get_instrument_token("NSE|Nifty 50")
            
            # Use current string date as a fallback, or dynamically parse from master. 
            # Note: Since determining exact weekly expiry string for API format is complex dynamically, 
            # we will grab the master contracts just for the ATM strikes.
            pass
            
        # Fallback/standard mapping (optimized)
        ce_quotes, pe_quotes = {}, {}
        for offset in range(-3, 4):
            strike = atm_strike + (offset * 50)
            c_sym = self.broker.get_option_symbol("NIFTY", strike, "CE")
            p_sym = self.broker.get_option_symbol("NIFTY", strike, "PE")
            if c_sym: ce_quotes[c_sym] = self.broker.get_quote(c_sym)
            if p_sym: pe_quotes[p_sym] = self.broker.get_quote(p_sym)
            
        best_diff = 999999
        atm_ce = self.broker.get_option_symbol("NIFTY", atm_strike, "CE")
        atm_pe = self.broker.get_option_symbol("NIFTY", atm_strike, "PE")
        
        for c_sym, c_prm in ce_quotes.items():
            if c_prm <= 0: continue
            for p_sym, p_prm in pe_quotes.items():
                if p_prm <= 0: continue
                diff = abs(c_prm - p_prm)
                if diff < best_diff:
                    best_diff = diff
                    atm_ce = c_sym
                    atm_pe = p_sym

        ce_price = max(self.broker.get_quote(atm_ce), 20.0) if atm_ce else 20.0
        pe_price = max(self.broker.get_quote(atm_pe), 20.0) if atm_pe else 20.0

        if not atm_ce or not atm_pe:
            self.logger.error("Failed to map ATM options for Straddle. Aborting.")
            return

        # --- PHASE 9: Simulation API Integration (Dynamic Margin Lot Sizing) ---
        current_capital = getattr(self.risk_manager, 'capital', 50000.0)
        
        # Test required margin for 1 NIFTY Lot (25 qty) using Upstox Simulator
        simulated_margin_1_lot = 80000.0 # fallback
        if hasattr(self.broker, 'simulate_margin'):
            sim = self.broker.simulate_margin([{'symbol': atm_ce, 'quantity': 25, 'side': 'SELL'}])
            if sim and sim > 0:
                simulated_margin_1_lot = float(sim)
        
        # Calculate exactly how many lots we can sell without rejection
        max_lots = int((current_capital * 0.90) / simulated_margin_1_lot)
        lots = max(1, min(10, max_lots))
        
        self.vix_at_entry = vix_ltp
        if vix_ltp < 13 and lots < 10: lots += 1
        elif vix_ltp > 20 and lots > 1: lots -= 1
        qty = lots * 25 # Current Nifty Lot Size is 25

        # STAGGERED ENTRY: Sell CE Now, stage PE
        self.pe_target_sym = atm_pe
        self.pe_target_qty = qty
        self.pe_target_price = pe_price
        
        ce_tag = self.broker.generate_order_tag(self.get_name(), atm_ce, "SELL", "Entry")
        self.pending_orders.add(ce_tag)
        self.event_bus.publish(OrderEvent(order_tag=ce_tag, strategy_id=self.get_name(), symbol=atm_ce, qty=qty, side="SELL", price=ce_price))

        msg = f"⚡ Leg 1: Emitting CE Order {atm_ce}. Waiting 2 min for PE."
        self.logger.info(msg)
        self.waiting_for_pe = True

        if hasattr(self.broker, 'subscribe'):
            self.broker.subscribe([atm_ce, atm_pe])

    def _execute_delayed_pe(self):
        """Fires exactly 2 minutes after CE enters via state machine tick."""
        self.waiting_for_pe = False
        
        ce_drift_pct = 0.0
        if self.ce_leg:
            ce_check = self.broker.get_quote(self.ce_leg['symbol'])
            if ce_check > 0 and self.ce_leg['entry_price'] > 0:
                ce_drift_pct = ((ce_check - self.ce_leg['entry_price']) / self.ce_leg['entry_price']) * 100
        
        # Abort if trending hard
        if ce_drift_pct > 10:
            abort_msg = f"🚫 STAGGER ABORT: CE drifted +{ce_drift_pct:.1f}% in 2 min. Market trending. Exiting CE only."
            self.logger.info(abort_msg)
            if self.telegram: self.telegram.send_message(abort_msg)
            
            exit_tag = self.broker.generate_order_tag(self.get_name(), self.ce_leg['symbol'], "BUY", "Abort")
            self.pending_orders.add(exit_tag)
            self.event_bus.publish(OrderEvent(order_tag=exit_tag, strategy_id=self.get_name(), symbol=self.ce_leg['symbol'], qty=self.ce_leg['qty'], side="BUY"))
            self.ce_leg['active'] = False
            self.traded_today = True
            return

        # Proceed with PE
        pe_tag = self.broker.generate_order_tag(self.get_name(), self.pe_target_sym, "SELL", "Entry")
        self.pending_orders.add(pe_tag)
        self.event_bus.publish(OrderEvent(order_tag=pe_tag, strategy_id=self.get_name(), symbol=self.pe_target_sym, qty=self.pe_target_qty, side="SELL", price=self.pe_target_price))
        self.logger.info("⚡ Leg 2: Emitting PE Order...")

    def on_fill(self, event: FillEvent):
        """OMS Callback to record state accurately."""
        if event.order_tag in self.pending_orders:
            self.pending_orders.remove(event.order_tag)
            
            # Handle OMS rejection (zero-qty FillEvent)
            if event.fill_qty == 0:
                self.logger.warning(f"⚠️ Order REJECTED: {event.order_tag} — clearing from pending set")
                # If CE entry was rejected, abort stagger sequence
                if self.waiting_for_pe and event.side == "SELL" and event.symbol.endswith("CE"):
                    self.waiting_for_pe = False
                    self.logger.warning("Stagger sequence aborted due to CE rejection")
                return
            
            # Identify which leg this corresponds to
            if event.side == "SELL":
                # Is it CE Entry?
                if event.symbol.endswith("CE") and self.waiting_for_pe:
                    self.ce_leg = {
                        "symbol": event.symbol, 
                        "entry_price": event.fill_price, 
                        "sl_price": event.fill_price * (1 + self.sl_percentage),
                        "qty": event.fill_qty,
                        "active": True
                    }
                    self.ce_filled_time = time.time()
                    self._save_state()
                    self.logger.info(f"✅ Straddle CE Leg Filled @ ₹{event.fill_price}. Timer for PE started.")
                    
                # Is it PE Entry?
                elif event.symbol == self.pe_target_sym:
                    self.pe_leg = {
                        "symbol": event.symbol, 
                        "entry_price": event.fill_price, 
                        "sl_price": event.fill_price * (1 + self.sl_percentage),
                        "qty": event.fill_qty,
                        "active": True
                    }
                    self.traded_today = True
                    self.entry_timestamp = datetime.datetime.now()
                    self._save_state()
                    self.logger.info(f"✅ Straddle PE Leg Filled @ ₹{event.fill_price}. Straddle Deployed.")
                    
            elif event.side == "BUY":
                # Exit fills or Breakout entries
                if self.ce_leg and self.ce_leg.get("symbol") == event.symbol:
                     self.ce_leg['active'] = False
                     self.logger.info(f"✅ CE Leg Closed @ ₹{event.fill_price}")
                elif self.pe_leg and self.pe_leg.get("symbol") == event.symbol:
                     self.pe_leg['active'] = False
                     self.logger.info(f"✅ PE Leg Closed @ ₹{event.fill_price}")
                     
                self._save_state()

    def _monitor_tick(self, event: CleanTickEvent):
        """Evaluates logic on the exact heartbeat of a tick data point."""
        if not self.ce_leg and not self.pe_leg: return

        active_symbols = set()
        if self.ce_leg and self.ce_leg.get('active'): active_symbols.add(self.ce_leg['symbol'])
        if self.pe_leg and self.pe_leg.get('active'): active_symbols.add(self.pe_leg['symbol'])
        if getattr(self, 'long_ce_leg', None) and self.long_ce_leg.get('active'): active_symbols.add(self.long_ce_leg['symbol'])
        if getattr(self, 'long_pe_leg', None) and self.long_pe_leg.get('active'): active_symbols.add(self.long_pe_leg['symbol'])

        if event.symbol not in active_symbols: return
        ltp = event.ltp

        # --- MULTI-TIER TRAILING STOP LOSS (Short Legs) ---
        for leg, name in [(self.ce_leg, "CE"), (self.pe_leg, "PE")]:
            if leg and leg.get('active') and event.symbol == leg['symbol']:
                profit_pct = (leg['entry_price'] - ltp) / leg['entry_price']
                
                # Tier 1: +15% decay → lock breakeven
                if profit_pct >= 0.15:
                    breakeven_sl = leg['entry_price']
                    if breakeven_sl < leg['sl_price']:
                        leg['sl_price'] = breakeven_sl
                        self.logger.info(f"🔒 {name} Breakeven Lock: SL → ₹{breakeven_sl:.1f} (+{profit_pct*100:.1f}%)")
                
                # Tier 2: +25% decay → lock +10% profit
                if profit_pct >= 0.25:
                    lock_sl = leg['entry_price'] * 0.90  # 10% below entry = 10% guaranteed profit for seller
                    if lock_sl < leg['sl_price']:
                        leg['sl_price'] = lock_sl
                        self.logger.info(f"💰 {name} Profit Lock: SL → ₹{lock_sl:.1f} (+{profit_pct*100:.1f}%)")
                
                # Tier 3: +30% decay → hyper-aggressive trailing
                if profit_pct >= 0.30:
                    gap_pct = max(0.05, 0.15 - ((profit_pct - 0.30) * 0.1))
                    new_sl = ltp + (leg['entry_price'] * gap_pct)
                    if new_sl < leg['sl_price']:
                        leg['sl_price'] = new_sl
                        self.logger.info(f"📐 {name} Hyper-Trail SL → ₹{new_sl:.1f} (+{profit_pct*100:.1f}%)")

        # --- TRAILING STOP LOSS (Long / Breakout Legs) ---
        for leg, name in [(getattr(self, 'long_ce_leg', None), "Long CE"), (getattr(self, 'long_pe_leg', None), "Long PE")]:
            if leg and leg.get('active') and event.symbol == leg['symbol']:
                profit_pct = (ltp - leg['entry_price']) / leg['entry_price']
                if profit_pct >= 0.15:
                    new_sl = max(leg['sl_price'], leg['entry_price'])  # Breakeven lock
                    if new_sl > leg['sl_price']:
                        leg['sl_price'] = new_sl
                        self.logger.info(f"🔒 {name} Breakeven Lock → ₹{new_sl:.1f}")
                if profit_pct >= 0.30:
                    gap_pct = max(0.05, 0.15 - ((profit_pct - 0.30) * 0.05))
                    new_sl = ltp - (leg['entry_price'] * gap_pct)
                    if new_sl > leg['sl_price']:
                        leg['sl_price'] = new_sl
                        self.logger.info(f"📐 {name} Trail SL → ₹{new_sl:.1f} (+{profit_pct*100:.1f}%)")
                
                # Exit Longs
                if ltp <= leg['sl_price']:
                    tag = self.broker.generate_order_tag(self.get_name(), leg['symbol'], "SELL", "TrailExit")
                    self.pending_orders.add(tag)
                    self.event_bus.publish(OrderEvent(order_tag=tag, strategy_id=self.get_name(), symbol=leg['symbol'], qty=leg['qty'], side="SELL"))
                    leg['active'] = False
                    self._save_state()

        # STOP LOSS CHECKS (Defensive -> Breakout Offense)
        if self.ce_leg and self.ce_leg.get('active') and event.symbol == self.ce_leg['symbol'] and ltp >= self.ce_leg['sl_price']:
            msg = f"🛑 CE Stop Loss Hit! {self.ce_leg['symbol']} @ ₹{ltp:.1f}"
            if self.telegram: self.telegram.send_message(msg)
            
            tag = self.broker.generate_order_tag(self.get_name(), self.ce_leg['symbol'], "BUY", "SLExit")
            self.pending_orders.add(tag)
            self.event_bus.publish(OrderEvent(order_tag=tag, strategy_id=self.get_name(), symbol=self.ce_leg['symbol'], qty=self.ce_leg['qty'], side="BUY"))
            self.ce_leg['active'] = False
            
            if self.staging_manager: self.staging_manager.record_sl_exit(self.ce_leg['sl_price'], ltp)
            
            # BREAKOUT OFFENSE — half size, tighter SL
            bo_qty = max(50, (self.ce_leg['qty'] // 2) // 50 * 50)  # 50% qty, rounded to lot
            bo_tag = self.broker.generate_order_tag(self.get_name(), self.ce_leg['symbol'], "BUY", "Breakout")
            self.pending_orders.add(bo_tag)
            self.event_bus.publish(OrderEvent(order_tag=bo_tag, strategy_id=self.get_name(), symbol=self.ce_leg['symbol'], qty=bo_qty, side="BUY"))
            
            self.long_ce_leg = {
                "symbol": self.ce_leg['symbol'], "entry_price": ltp, "sl_price": ltp * 0.85, "qty": bo_qty, "active": True
            }
            # Tighten winning leg SL based on actual decay
            if self.pe_leg and self.pe_leg.get('active'):
                pe_ltp = self.broker.get_quote(self.pe_leg['symbol'])
                if pe_ltp > 0:
                    # Lock at tighter of breakeven or current_ltp + 10% of entry
                    tight_sl = min(self.pe_leg['entry_price'], pe_ltp + (self.pe_leg['entry_price'] * 0.10))
                    self.pe_leg['sl_price'] = tight_sl
                else:
                    self.pe_leg['sl_price'] = self.pe_leg['entry_price']
            self._save_state()

        elif self.pe_leg and self.pe_leg.get('active') and event.symbol == self.pe_leg['symbol'] and ltp >= self.pe_leg['sl_price']:
            msg = f"🛑 PE Stop Loss Hit! {self.pe_leg['symbol']} @ ₹{ltp:.1f}"
            if self.telegram: self.telegram.send_message(msg)
            
            tag = self.broker.generate_order_tag(self.get_name(), self.pe_leg['symbol'], "BUY", "SLExit")
            self.pending_orders.add(tag)
            self.event_bus.publish(OrderEvent(order_tag=tag, strategy_id=self.get_name(), symbol=self.pe_leg['symbol'], qty=self.pe_leg['qty'], side="BUY"))
            self.pe_leg['active'] = False
            
            if self.staging_manager: self.staging_manager.record_sl_exit(self.pe_leg['sl_price'], ltp)
            
            # BREAKOUT OFFENSE — half size, tighter SL
            bo_qty = max(50, (self.pe_leg['qty'] // 2) // 50 * 50)  # 50% qty, rounded to lot
            bo_tag = self.broker.generate_order_tag(self.get_name(), self.pe_leg['symbol'], "BUY", "Breakout")
            self.pending_orders.add(bo_tag)
            self.event_bus.publish(OrderEvent(order_tag=bo_tag, strategy_id=self.get_name(), symbol=self.pe_leg['symbol'], qty=bo_qty, side="BUY"))
            
            self.long_pe_leg = {
                "symbol": self.pe_leg['symbol'], "entry_price": ltp, "sl_price": ltp * 0.85, "qty": bo_qty, "active": True
            }
            # Tighten winning leg SL based on actual decay
            if self.ce_leg and self.ce_leg.get('active'):
                ce_ltp = self.broker.get_quote(self.ce_leg['symbol'])
                if ce_ltp > 0:
                    tight_sl = min(self.ce_leg['entry_price'], ce_ltp + (self.ce_leg['entry_price'] * 0.10))
                    self.ce_leg['sl_price'] = tight_sl
                else:
                    self.ce_leg['sl_price'] = self.ce_leg['entry_price']
            self._save_state()

    def _mid_session_vix_check(self):
        now = datetime.datetime.now()
        if self.last_vix_check and (now - self.last_vix_check).total_seconds() < 300: return
        self.last_vix_check = now
        
        if self.vix_at_entry <= 0: return
        current_vix = getattr(self, "vix_now", self.broker.get_quote("NSE|INDIA VIX"))
        if current_vix <= 0: return
            
        vix_surge = ((current_vix - self.vix_at_entry) / self.vix_at_entry) * 100
        if vix_surge > 25:
            surge_msg = f"🚨 VIX SURGE: {vix_surge:.1f}%. Force-exiting all positions."
            if self.telegram: self.telegram.send_message(surge_msg)
            self.square_off_all(reason_msg=surge_msg)
            self.traded_today = False
            
    def activate_hedge_mode(self):
        """
        Omni-Market Resilience Trigger:
        Severely tightens trailing stops on all active short legs.
        Forces the strategy to rely on price action taking it out near current levels 
        rather than blunt market-selling into a liquidity vacuum.
        """
        for leg, name in [(getattr(self, 'ce_leg', None), "CE"), (getattr(self, 'pe_leg', None), "PE")]:
            if leg and leg.get('active'):
                try:
                    current_ltp = self.broker.get_quote(leg['symbol'])
                    if current_ltp and current_ltp > 0:
                        # Tighten to current price + 5% buffer, overriding the wide 25% SL
                        # Ensuring we are at least locking breakeven if in profit
                        tight_sl = min(leg['entry_price'], current_ltp * 1.05)
                        if tight_sl < leg['sl_price']:
                            leg['sl_price'] = tight_sl
                            self.logger.warning(f"🛡️ Hedge Mode: {name} SL violently tightened to ₹{tight_sl:.1f} (LTP: ₹{current_ltp:.1f})")
                except: pass
        self._save_state()

    def _check_theta_exit(self):
        if not self.ce_leg and not getattr(self, 'pe_leg', None): return False
        
        total_profit = self.broker.get_pnl()
        total_premium = 0.0
        if self.ce_leg: total_premium += self.ce_leg['entry_price'] * self.ce_leg.get('qty', 50)
        if self.pe_leg: total_premium += self.pe_leg['entry_price'] * self.pe_leg.get('qty', 50)
        
        profit_pct = (total_profit / total_premium * 100) if total_premium > 0 else 0
        if total_profit > 500 and profit_pct > 30:
            msg = f"🎯 THETA EXIT (2PM): True Net PnL is +₹{total_profit:.0f} ({profit_pct:.1f}% max decay). Closing early."
            if self.telegram: self.telegram.send_message(msg)
            self.square_off_all()
            self.traded_today = False
            return True
        return False

    def square_off_all(self, reason_msg=None):
        msg = reason_msg or "⏰ 03:15 PM EOD Auto-Liquidation."
        if not reason_msg and self.telegram: self.telegram.send_message(msg)
        
        for leg in [self.ce_leg, self.pe_leg]:
            if leg and leg.get('active'):
                tag = self.broker.generate_order_tag(self.get_name(), leg['symbol'], "BUY", "EOD")
                self.pending_orders.add(tag)
                self.event_bus.publish(OrderEvent(order_tag=tag, strategy_id=self.get_name(), symbol=leg['symbol'], qty=leg['qty'], side="BUY"))
                leg['active'] = False
                
        for leg in [getattr(self, 'long_ce_leg', None), getattr(self, 'long_pe_leg', None)]:
            if leg and leg.get('active'):
                tag = self.broker.generate_order_tag(self.get_name(), leg['symbol'], "SELL", "EOD")
                self.pending_orders.add(tag)
                self.event_bus.publish(OrderEvent(order_tag=tag, strategy_id=self.get_name(), symbol=leg['symbol'], qty=leg['qty'], side="SELL"))
                leg['active'] = False
        self._save_state()

    def _save_state(self):
        if self.state_manager:
            self.state_manager.save_active_legs({
                "ce_leg": getattr(self, "ce_leg", None),
                "pe_leg": getattr(self, "pe_leg", None),
                "long_ce_leg": getattr(self, "long_ce_leg", None),
                "long_pe_leg": getattr(self, "long_pe_leg", None),
                "hedge_legs": getattr(self, "hedge_legs", [])
            })
            self.state_manager.state["trade_meta"] = {
                "vix_at_entry": getattr(self, "vix_at_entry", 15.0),
                "entry_timestamp": self.entry_timestamp.isoformat() if getattr(self, "entry_timestamp", None) else None,
                "prev_day_vix": getattr(self, "prev_day_vix", None)
            }
            self.state_manager.save_state()
