"""
Paper Trading Broker — Simulates execution using live data.
Integrated with: Logger, DataSanitizer, Idempotent Orders.
"""
import time
import os
import pandas as pd
from core.brokers.base_broker import BaseBroker
from core.logger import get_logger
from core.data_sanitizer import DataSanitizer

logger = get_logger(__name__)


class PaperBroker(BaseBroker):
    def __init__(self, config, data_source_broker=None):
        self.config = config
        self.orders = []
        self.positions = {}  # Symbol -> {qty, avg_price, ltp}
        self.balance = config.CAPITAL
        self.realized_pnl = 0.0
        self.data_source = data_source_broker
        self.is_logged_in = True
        self.sanitizer = DataSanitizer()  # Primitive 2
        
    def authenticate(self):
        logger.info("📝 Paper Trading: Authentication Successful (Simulated)")
        return True
        
    def place_order(self, symbol, quantity, side, order_type="MARKET", price=0.0):
        """Simulates order placement with idempotent tagging."""
        order_tag = self.generate_order_tag("PAPER", symbol, side)  # Primitive 4
        logger.info(f"📝 PAPER ORDER [{order_tag}]: {side} {quantity} {symbol} @ {order_type}")
        
        # 1. Get Simulated Fill Price
        fill_price = price
        if order_type == "MARKET":
            if self.data_source:
                for _ in range(5):
                    raw = self.data_source.get_quote(symbol)
                    fill_price = self.sanitizer.clean(symbol, raw)  # Primitive 2
                    if fill_price > 0.0:
                        break
                    time.sleep(1)
            else:
                fill_price = 100.0  # Mock default
                
        if fill_price <= 0.0:
            logger.error(f"PAPER ORDER REJECTED [{order_tag}]: Could not fetch valid price for {symbol}")
            return None
        
        # 2. Update Positions & Realize PnL
        pos = self.positions.get(symbol, {'qty': 0, 'avg_price': 0.0})
        current_qty = pos['qty']
        avg_price = pos['avg_price']
        
        trade_qty = quantity if side == "BUY" else -quantity
        new_qty = current_qty + trade_qty
        
        # Calculate Realized PnL if closing a position
        if (current_qty > 0 and trade_qty < 0) or (current_qty < 0 and trade_qty > 0):
            closed_qty = min(abs(trade_qty), abs(current_qty))
            if current_qty > 0:
                self.realized_pnl += (fill_price - avg_price) * closed_qty
            else:
                self.realized_pnl += (avg_price - fill_price) * closed_qty
                
        # Calculate new Average Price
        if abs(new_qty) > abs(current_qty):
            total_value = abs(current_qty) * avg_price + abs(trade_qty) * fill_price
            avg_price = total_value / abs(new_qty)
        elif new_qty == 0:
            avg_price = 0.0
            
        self.positions[symbol] = {'qty': new_qty, 'avg_price': avg_price}

        # 3. Log Order
        order_id = f"PAPER-{int(time.time()*1000)}"
        net_liq = self.config.CAPITAL + self.realized_pnl + self.get_pnl()
            
        trade_data = {
            "order_id": order_id,
            "tag": order_tag,
            "symbol": symbol,
            "side": side,
            "qty": quantity,
            "price": fill_price,
            "timestamp": time.time(),
            "Balance": net_liq
        }
        self.orders.append(trade_data)
        
        # Write to CSV
        log_file = getattr(self.config, 'LOG_FILE', 'trades.csv')
        try:
            df = pd.DataFrame([trade_data])
            if not os.path.exists(log_file):
                df.to_csv(log_file, index=False)
            else:
                df.to_csv(log_file, mode='a', header=False, index=False)
        except Exception as e:
            logger.warning(f"Failed to log paper trade to CSV: {e}")
        
        logger.info(f"✅ PAPER FILL [{order_tag}]: {symbol} @ ₹{fill_price:.2f}")
        return order_id

    def get_quote(self, symbol):
        """Fetches live quote with DataSanitizer cleaning."""
        if self.data_source:
            raw = self.data_source.get_quote(symbol)
            return self.sanitizer.clean(symbol, raw)
        return 100.0  # Mock

    def get_pnl(self):
        """Calculates Realized + Unrealized PnL."""
        pnl = self.realized_pnl
        for sym, pos in self.positions.items():
            qty = pos['qty']
            if qty == 0:
                continue
            
            ltp = self.get_quote(sym)
            avg = pos['avg_price']
            
            if qty < 0:
                pnl += (avg - ltp) * abs(qty)
            else:
                pnl += (ltp - avg) * qty
                
        return pnl

    def get_positions(self):
        return self.positions

    def get_option_symbol(self, underlying="NIFTY", strike=22000, side="CE", expiry_offset=0):
        if self.data_source and hasattr(self.data_source, 'get_option_symbol'):
            return self.data_source.get_option_symbol(underlying, strike, side, expiry_offset)
        return f"PAPER_{underlying}_{strike}_{side}"
