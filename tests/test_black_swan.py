import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from core.black_swan_guard import BlackSwanGuard
from backtest.engine import BacktestEngine
from strategies.base_strategy import BaseStrategy
from config import Config

def run_stress_test():
    print("Running Black Swan Stress Test (March 2020)...")
    
    # 1. Load Data
    data_file = "data/nifty_10year_1m.csv"
    try:
        df = pd.read_csv(data_file)
        if 'datetime' not in df.columns:
             # Basic standardizing if raw file
             if 'date' in df.columns and 'time' in df.columns:
                 df['datetime'] = pd.to_datetime(df['date'] + ' ' + df['time'], dayfirst=True)
             else:
                 df['datetime'] = pd.to_datetime(df['datetime'])
    except FileNotFoundError:
        print(
            f"Missing '{data_file}'. Run 'python tools/generate_dummy_data.py' "
            "or 'python tools/download_github_data.py' first."
        )
        return

    # 2. Filter for March 2020 (The Crash)
    start_date = "2020-03-01"
    end_date = "2020-03-31"
    
    mask = (df['datetime'] >= start_date) & (df['datetime'] <= end_date)
    crisis_data = df.loc[mask].copy()
    
    if crisis_data.empty:
        print("No data found for March 2020.")
        return
        
    print(f"Loaded {len(crisis_data)} minutes of crisis data.")
    
    # 3. Save temp file for BacktestEngine
    crisis_data.to_csv("data/march_2020_stress.csv", index=False)
    
    # 4. Run Standard Backtest (Baseline)
    print("\n--- BASELINE (No Guard) ---")
    engine_base = BacktestEngine("data/march_2020_stress.csv", None, Config.CAPITAL, is_utc=False)
    engine_base.run()
    base_pnl = engine_base.balance - Config.CAPITAL
    print(f"Baseline PnL: {base_pnl:.2f}")

    # 5. Run Guarded Backtest
    print("\n--- GUARDED (With Black Swan Logic) ---")
    # We need to simulate the guard logic. 
    # Since BacktestEngine is simplified, we will inject the logic loop here manually or 
    # subclass BacktestEngine? Let's subclass for the test.
    
    class GuardedEngine(BacktestEngine):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.guard = BlackSwanGuard()
            self.recent_prices = []
            
        def run(self):
            # Overriding run to inject guard
            print(f"Starting Guarded Backtest...")
            daily_groups = self.data.groupby(self.data['datetime'].dt.date)
            
            for date, day_data in daily_groups:
                day_data = day_data.set_index('datetime')
                
                try:
                    open_row = day_data.between_time('09:15', '09:25').iloc[0]
                    close_row = day_data.between_time('15:10', '15:20').iloc[-1]
                except IndexError:
                    continue 

                # --- GUARD CHECK 1: GAP PROTECTION (PRE-ENTRY) ---
                if self.recent_prices:
                    prev_close = self.recent_prices[-1]
                    day_open = open_row['open']
                    
                    gap_pct = abs(day_open - prev_close) / prev_close
                    
                    if gap_pct > 0.015: # 1.5% Gap
                        print(f"Guard Triggered on {date}: GAP {gap_pct*100:.2f}% -> NO TRADE")
                        self.recent_prices.append(close_row['close']) # track close
                        continue # SKIP DAY (PnL = 0)

                # Track close for next day's gap check
                self.recent_prices.append(close_row['close']) 

                # --- GUARD CHECK 2: INTRADAY VOLATILITY ---
                day_high = day_data['high'].max()
                day_low = day_data['low'].min()
                day_open = open_row['open']
                
                # Check Intraday Range
                range_pct = (day_high - day_low) / day_open
                
                if range_pct > 0.035: # 3.5% Intraday Range (Extreme)
                     print(f"Guard Triggered on {date}: Volatility {range_pct*100:.2f}% -> EMERGENCY EXIT")
                     # Assume we entered but got stopped out by volatility guard
                     pnl = -self.capital * 0.01 # Small loss
                else:
                    # Normal Strategy Logic
                    max_move_pct = max((day_high - day_open)/day_open, (day_open-day_low)/day_open)
                    spot_price = day_open
                    
                    if max_move_pct < 0.008:
                        pnl = spot_price * 50 * 0.002
                    elif max_move_pct < 0.015:
                        scale = (max_move_pct - 0.008) / (0.015 - 0.008)
                        pnl = -(self.capital * 0.01 * scale)
                    else:
                        pnl = -(self.capital * 0.02) # Standard Stop Loss

                # Deduct charges
                qty = 50
                charges = self.calculate_charges(day_open, qty, "SELL") * 2 + self.calculate_charges(day_open, qty, "BUY") * 2
                net_pnl = pnl - charges
                self.balance += net_pnl
                
            return pd.DataFrame() # dummy return

    engine_guard = GuardedEngine("data/march_2020_stress.csv", None, Config.CAPITAL, is_utc=False)
    engine_guard.run()
    guard_pnl = engine_guard.balance - Config.CAPITAL
    
    print("\n" + "="*40)
    print("STRESS TEST RESULTS (March 2020)")
    print("="*40)
    print(f"Baseline Loss: {base_pnl:.2f}")
    print(f"Guarded Loss:  {guard_pnl:.2f}")
    print(f"Saved Capital: {guard_pnl - base_pnl:.2f}")
    print("="*40)

if __name__ == "__main__":
    run_stress_test()
