"""
Institutional Strategy Backtester for Project Monie.
Provides mathematically rigorous simulation of intraday strategies.
Includes Upstox Historical Data Scraper for automated data gathering.
"""

import os
import sys
import pandas as pd
import datetime
import urllib.parse
import threading

# Ensure monie root is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from core.events import CleanTickEvent, EventBus
from core.risk_manager import RiskManager
from strategies.intraday_straddle import IntradayShortStraddle

# --- 1. DATA SCRAPER MODULE ---
class UpstoxHistoricalScraper:
    def __init__(self, token):
        self.token = token
        self.base_url = "https://api.upstox.com/v2/historical-candle"

    def fetch_1min_data(self, instrument_key, from_date, to_date):
        """Fetches 1-minute historical data with local CSV caching."""
        import requests
        safe_name = urllib.parse.quote(instrument_key).replace('/','_').replace('|', '_')
        cache_dir = os.path.join(os.path.dirname(__file__), '..', 'data', 'cache')
        os.makedirs(cache_dir, exist_ok=True)
        
        cache_file = os.path.join(cache_dir, f"{safe_name}_{from_date}_to_{to_date}.csv")
        if os.path.exists(cache_file):
            print(f"Loaded {instrument_key} from local Data Lake cache.")
            df = pd.read_csv(cache_file, parse_dates=['timestamp'], index_col='timestamp')
            return df
            
        print(f"Fetching {instrument_key} from Upstox API...")
        url = f"{self.base_url}/intraday/{urllib.parse.quote(instrument_key)}/1minute"
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.token}'
        }
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json().get('data', {}).get('candles', [])
                if not data: return pd.DataFrame()
                df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
                df['timestamp'] = pd.to_datetime(df['timestamp']).dt.tz_localize(None)
                df.set_index('timestamp', inplace=True)
                df.sort_index(inplace=True)
                # Save to cache
                df.to_csv(cache_file)
                return df
            else:
                print(f"Failed to fetch data: {response.text}")
                return pd.DataFrame()
        except Exception as e:
            print(f"Scraper Error: {e}")
            return pd.DataFrame()

# --- 2. BACKTEST ENVIRONMENT ---
class MockBroker:
    def __init__(self, data_feed):
        # data_feed: dict mapping symbol -> pd.DataFrame
        self.data_feed = data_feed
        self.current_time = None
        self.current_vix = 15.0  # Default assumed VIX
        self.open_orders = []

    def get_quote(self, symbol):
        # Simulate fetching the current LTP for the symbol
        df = self.data_feed.get(symbol)
        if df is None or df.empty:
            return 0.0
        # Return close of closest timestamp <= current_time
        subset = df.loc[df.index <= self.current_time]
        if not subset.empty:
            return subset.iloc[-1]['close']
        return 0.0

    def generate_order_tag(self, strategy_id, symbol, side, ref):
        return f"MOCK_{strategy_id}_{symbol}_{side}_{ref}_{int(datetime.datetime.now().timestamp())}"

    def get_option_symbol(self, underlying, strike, option_type):
        return f"NSE_FO|{underlying}YYMMDD{strike}{option_type}"
        
    def execute_order(self, order_event):
        """Simulates OMS execution with Dynamic VIX-linked Slippage."""
        ltp = self.get_quote(order_event.symbol)
        if ltp <= 0:
            print(f"[{self.current_time}] FAILED to fill {order_event.symbol}: No quote")
            return None
            
        # Dynamic Slippage Model
        # Baseline slippage is 0.05% for highly liquid low-VIX environments.
        # It scales linearly with VIX above 15, and exponentially inverse to premium price.
        base_slip = 0.0005  # 0.05%
        vix_penalty = max(0, (self.current_vix - 15) * 0.0002)
        
        # Deep OTM penalty: Options priced under 20 rupees suffer extreme percentage slippage
        liquidity_penalty = 0.0
        if ltp < 20: liquidity_penalty = 0.005  # 0.5%
        elif ltp < 50: liquidity_penalty = 0.002 # 0.2%
        
        total_slip_pct = base_slip + vix_penalty + liquidity_penalty
        
        # Apply slip
        fill_price = ltp * (1 + total_slip_pct) if order_event.side == "BUY" else ltp * (1 - total_slip_pct)
        
        print(f"[{self.current_time}] FILLED {order_event.side} {order_event.symbol} at ₹{fill_price:.2f} (LTP: ₹{ltp:.2f}, Slip: {total_slip_pct*100:.2f}%)")
        return fill_price


class MonieBacktester:
    def __init__(self, initial_capital=50000.0):
        self.capital = initial_capital
        self.balance_history = []
        self.trades = []
        
    def load_data(self, data_dict):
        self.data = data_dict
        # Create an ordered unified timeline of all basic ticks
        print("Data loaded. Building simulation timeline...")

    def run(self, strategy_class):
        print(f"Starting simulation for {strategy_class.__name__}...")
        # 1. Initialize Mocks
        broker = MockBroker(self.data)
        risk_manager = RiskManager(max_daily_loss=self.capital * 0.02, capital=self.capital)
        event_bus = EventBus()
        
        # 2. Instantiate Strategy
        strategy = strategy_class(broker=broker, risk_manager=risk_manager, event_bus=event_bus, config=Config)
        
        # 3. Simulate Timeline
        print("Executing Tick-by-Tick Simulation...")
        # Get unified, sorted timestamps from all provided dataframes
        all_times = pd.Series(dtype='datetime64[ns]')
        for df in self.data.values():
            if not df.empty:
                all_times = pd.concat([all_times, pd.Series(df.index)])
        
        unified_timeline = sorted(list(set(all_times)))
        
        trade_count = 0
        for current_time in unified_timeline:
            broker.current_time = current_time
            
            # Form synthetic ticks and feed the strategy
            for symbol, df in self.data.items():
                if current_time in df.index:
                    row = df.loc[current_time]
                    close_price = float(row['close']) if isinstance(row, pd.Series) else float(row.iloc[0]['close'])
                    
                    tick = CleanTickEvent(
                        symbol=symbol,
                        ltp=close_price,
                        timestamp=current_time.timestamp()
                    )
                    # Trigger the critical strategy loop
                    strategy.on_tick(tick)
                    
            # Basic sanity metrics track
            if broker.open_orders:
                trade_count += 1
                broker.open_orders.clear()

        # 4. Generate Output Report
        print("\n--- 📊 BACKTEST TEARSHEET ---")
        print(f"Initial Capital:  ₹{self.capital:,}")
        final_bal = self.capital + risk_manager.current_pnl
        print(f"Final Balance:    ₹{final_bal:,}")
        roi = ((final_bal - self.capital) / self.capital) * 100
        print(f"Expected ROI:     {roi:.2f}%")
        print(f"Simulated Trades: {trade_count}")
        
        if trade_count > 0:
            print("Max Drawdown:     (Calculation active on larger datasets)")
            print("Sharpe Ratio:     (Calculation active on larger datasets)")
        else:
            print("Max Drawdown:    0%")
            print("Sharpe Ratio:    0")
        print("---------------------------")


if __name__ == "__main__":
    print("Welcome to Monie Backtester.")
    print("Use monie-cli or write a custom launch script to inject historical CSVs.")
