import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from backtest.engine import BacktestEngine
from config import Config

def run_growth_vs_income():
    print("Running Growth vs. Income Simulation (2015-2024)...")
    data_file = "data/nifty_10year_1m.csv"
    if not os.path.exists(data_file):
        print(
            f"Missing '{data_file}'. Run 'python tools/generate_dummy_data.py' "
            "or 'python tools/download_github_data.py' first."
        )
        return
    
    # ---------------------------------------------------------
    # Custom Engine with Compounding & Withdrawal Logic
    # ---------------------------------------------------------
    class WealthEngine(BacktestEngine):
        def __init__(self, data_file, withdrawal_pct=0.0):
            # is_utc=False because data is already formatted in IST by previous scripts
            super().__init__(data_file, None, initial_capital=50000, is_utc=False)
            self.withdrawal_pct = withdrawal_pct
            self.total_withdrawn = 0
            self.monthly_profits = {}
            self.current_month = None
            self.month_start_balance = 50000
            self.recent_prices = []

        def run(self):
            daily_groups = self.data.groupby(self.data['datetime'].dt.date)
            
            for date, day_data in daily_groups:
                # 1. Month Check for Withdrawal
                this_month = date.strftime("%Y-%m")
                if self.current_month != this_month:
                    if self.current_month is not None:
                        # Month changed. Process Withdrawal.
                        profit = self.balance - self.month_start_balance
                        if profit > 0 and self.withdrawal_pct > 0:
                            w_amount = profit * self.withdrawal_pct
                            self.balance -= w_amount
                            self.total_withdrawn += w_amount
                            # print(f"Processing Withdrawal for {self.current_month}: {w_amount:.2f}")
                        
                    self.current_month = this_month
                    self.month_start_balance = self.balance

                # 2. Daily Logic (Shielded + Compounding)
                day_data = day_data.set_index('datetime')
                try:
                    open_row = day_data.between_time('09:15', '09:25').iloc[0]
                    close_row = day_data.between_time('15:10', '15:20').iloc[-1]
                except IndexError:
                    continue 

                # Guard Checks
                if self.recent_prices:
                    prev_close = self.recent_prices[-1]
                    day_open = open_row['open']
                    if abs(day_open - prev_close) / prev_close > 0.015: 
                        self.recent_prices.append(close_row['close']) 
                        continue 
                self.recent_prices.append(close_row['close']) 
                
                # Dynamic Sizing (Compounding)
                lots = int(self.balance / 50000)
                if lots < 1: 
                     if self.balance > 25000: lots = 1 
                     else: break # Ruin
                if lots > 20: lots = 20 # Safety Cap
                
                qty = lots * 50
                
                # Trading PnL
                day_high = day_data['high'].max()
                day_low = day_data['low'].min()
                day_open = open_row['open']
                range_pct = (day_high - day_low) / day_open
                
                if range_pct > 0.035: 
                    # Emergency Exit
                    pnl = -self.balance * 0.01 # Loss on current capital
                else:
                    max_move_pct = max((day_high - day_open)/day_open, (day_open-day_low)/day_open)
                    spot_price = day_open
                    
                    if max_move_pct < 0.008:
                        pnl = spot_price * qty * 0.002 
                    elif max_move_pct < 0.015:
                        scale = (max_move_pct - 0.008) / (0.015 - 0.008)
                        # Risk scales with size? Yes, 'pnl' logic needs to reflect size.
                        # Heuristic: Loss is relative to Capital exposed? 
                        # Let's standardize: 1% loss of allocated capital per lot?
                        # Allocated = lots * 50000. 
                        allocated_cap = lots * 50000
                        pnl = -(allocated_cap * 0.01 * scale)
                    else:
                        allocated_cap = lots * 50000
                        pnl = -(allocated_cap * Config.MAX_DAILY_LOSS_PCT)

                est_premium = day_open * 0.0045 
                charges = self.calculate_charges(est_premium, qty, "SELL") * 2 + self.calculate_charges(est_premium, qty, "BUY") * 2
                
                net_pnl = pnl - charges
                self.balance += net_pnl
                
                self.trades.append({
                    "Date": date,
                    "Lots": lots,
                    "Net PnL": net_pnl,
                    "Balance": self.balance,
                    "Total Withdrawn": self.total_withdrawn
                })
                
            return pd.DataFrame(self.trades)

    # ---------------------------------------------------------
    # SCENARIO 1: MAX GROWTH (0% Withdrawal)
    # ---------------------------------------------------------
    print("\n--- SCENARIO 1: MAX GROWTH (Reinvest Everything) ---")
    engine1 = WealthEngine(data_file, withdrawal_pct=0.0)
    df1 = engine1.run()
    
    bal1 = engine1.balance
    drawn1 = engine1.total_withdrawn
    wealth1 = bal1 + drawn1
    
    print(f"Final Balance:    {bal1:,.2f}")
    print(f"Total Withdrawn:  {drawn1:,.2f}")
    print(f"TOTAL WEALTH:     {wealth1:,.2f}")
    
    # ---------------------------------------------------------
    # SCENARIO 2: INCOME MODE (50% Profit Withdrawal)
    # ---------------------------------------------------------
    print("\n--- SCENARIO 2: INCOME MODE (Withdraw 50% Profits) ---")
    engine2 = WealthEngine(data_file, withdrawal_pct=0.5)
    df2 = engine2.run()
    
    bal2 = engine2.balance
    drawn2 = engine2.total_withdrawn
    wealth2 = bal2 + drawn2
    
    print(f"Final Balance:    {bal2:,.2f}")
    print(f"Total Withdrawn:  {drawn2:,.2f}")
    print(f"TOTAL WEALTH:     {wealth2:,.2f}")
    
    print("\n" + "="*50)
    print("COMPARISON")
    print("="*50)
    print(f"Growth Mode Wealth: {wealth1:,.0f} (Aggressive Compounding)")
    print(f"Income Mode Wealth: {wealth2:,.0f} (Balanced Approach)")
    print(f"Difference:         {wealth1 - wealth2:,.0f}")
    print("="*50)

if __name__ == "__main__":
    run_growth_vs_income()
