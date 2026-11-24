import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from core.black_swan_guard import BlackSwanGuard
from backtest.engine import BacktestEngine
from config import Config

def run_longterm_test():
    print("Running Long-Term Shield Test (2015-2024)...")
    
    data_file = "data/nifty_10year_1m.csv"
    if not os.path.exists(data_file):
        print(
            f"Missing '{data_file}'. Run 'python tools/generate_dummy_data.py' "
            "or 'python tools/download_github_data.py' first."
        )
        return
    
    # --- BASELINE (No Guard) ---
    print("\n1. Running EXPECTED (Baseline) Backtest...")
    engine_base = BacktestEngine(data_file, None, Config.CAPITAL, is_utc=False)
    df_base = engine_base.run()
    base_final_bal = engine_base.balance
    base_pnl = base_final_bal - Config.CAPITAL
    base_dd = engine_base.calculate_drawdown(df_base)
    
    # --- GUARDED (With Black Swan Logic) ---
    print("\n2. Running SHIELDED (Guarded) Backtest...")
    
    class GuardedEngine(BacktestEngine):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.recent_prices = []
            self.triggered_gaps = 0
            self.triggered_volatility = 0
            
        def run(self):
            daily_groups = self.data.groupby(self.data['datetime'].dt.date)
            
            for date, day_data in daily_groups:
                day_data = day_data.set_index('datetime')
                
                try:
                    open_row = day_data.between_time('09:15', '09:25').iloc[0]
                    close_row = day_data.between_time('15:10', '15:20').iloc[-1]
                except IndexError:
                    continue 

                # --- GUARD CHECK 1: PRE-MARKET GAP ---
                if self.recent_prices:
                    prev_close = self.recent_prices[-1]
                    day_open = open_row['open']
                    
                    gap_pct = abs(day_open - prev_close) / prev_close
                    
                    if gap_pct > Config.MAX_GAP_PCT: # 1.5% Gap
                        # print(f"Shield Active on {date}: Gap {gap_pct*100:.2f}%")
                        self.triggered_gaps += 1
                        self.recent_prices.append(close_row['close']) 
                        continue # SKIP DAY

                self.recent_prices.append(close_row['close']) 

                # --- GUARD CHECK 2: INTRADAY VOLATILITY ---
                day_high = day_data['high'].max()
                day_low = day_data['low'].min()
                day_open = open_row['open']
                range_pct = (day_high - day_low) / day_open
                
                if range_pct > 0.035: # 3.5% Intraday
                    # Emergency Exit
                    self.triggered_volatility += 1
                    # print(f"Shield Active on {date}: Volatility {range_pct*100:.2f}%")
                    pnl = -self.capital * 0.01 
                else:
                    # Normal Logic
                    max_move_pct = max((day_high - day_open)/day_open, (day_open-day_low)/day_open)
                    spot_price = day_open
                    
                    if max_move_pct < 0.008:
                        pnl = spot_price * 50 * 0.002
                    elif max_move_pct < 0.015:
                        scale = (max_move_pct - 0.008) / (0.015 - 0.008)
                        pnl = -(self.capital * 0.01 * scale)
                    else:
                        pnl = -(self.capital * Config.MAX_DAILY_LOSS_PCT)

                qty = 50
                est_premium = day_open * 0.0045 
                charges = self.calculate_charges(est_premium, qty, "SELL") * 2 + self.calculate_charges(est_premium, qty, "BUY") * 2
                
                net_pnl = pnl - charges
                self.balance += net_pnl
                
                self.trades.append({
                    "Date": date,
                    "Gross PnL": pnl,
                    "Charges": charges,
                    "Net PnL": net_pnl,
                    "Balance": self.balance
                })
                
                if self.balance <= 0:
                    break
                    
            return pd.DataFrame(self.trades)

    engine_guard = GuardedEngine(data_file, None, Config.CAPITAL, is_utc=False)
    df_guard = engine_guard.run()
    
    # Save Trade Log
    df_guard.to_csv("shielded_trades.csv", index=False)
    print("Shielded trades saved to 'shielded_trades.csv'")
    
    guard_final_bal = engine_guard.balance
    guard_pnl = guard_final_bal - Config.CAPITAL
    guard_dd = engine_guard.calculate_drawdown(df_guard)

    print("\n" + "="*50)
    print("COMPARATIVE RESULTS (2015-2024)")
    print("="*50)
    print(f"{'Metric':<20} | {'Baseline':<12} | {'Shielded':<12}")
    print("-" * 50)
    print(f"{'Final Balance':<20} | {base_final_bal:<12.0f} | {guard_final_bal:<12.0f}")
    print(f"{'Total Return':<20} | {base_pnl/Config.CAPITAL*100:<12.1f}% | {guard_pnl/Config.CAPITAL*100:<12.1f}%")
    print(f"{'Max Drawdown':<20} | {base_dd:<12.2f}% | {guard_dd:<12.2f}%")
    print(f"{'Trades Triggered':<20} | {len(df_base):<12} | {len(df_guard):<12}")
    print("-" * 50)
    print(f"Shield Stats: Skipped {engine_guard.triggered_gaps} days (Gaps), Exited {engine_guard.triggered_volatility} days (Vol).")
    print("="*50)

if __name__ == "__main__":
    run_longterm_test()
