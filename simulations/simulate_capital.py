import pandas as pd
from backtest.engine import BacktestEngine
from config import Config

def simulate_capital(capital):
    print(f"\nrunning Simulation for Capital: {capital}...")
    
    # Dynamic Position Sizing: 1 Lot per 50k
    # Floor division to ensure safety. 
    # 50k -> 1, 75k -> 1, 99k -> 1, 100k -> 2.
    lots = int(capital / 50000)
    if lots < 1: lots = 1
    qty = lots * 50
    
    print(f"Position Size: {lots} Lots ({qty} Qty)")
    
    data_file = "data/nifty_10year_1m.csv"
    
    class ScaledEngine(BacktestEngine):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.recent_prices = []
            
        def run(self):
            daily_groups = self.data.groupby(self.data['datetime'].dt.date)
            
            for date, day_data in daily_groups:
                day_data = day_data.set_index('datetime')
                try:
                    open_row = day_data.between_time('09:15', '09:25').iloc[0]
                    close_row = day_data.between_time('15:10', '15:20').iloc[-1]
                except IndexError:
                    continue 

                # --- GUARD CHECKS (Simplified from GuardedEngine) ---
                if self.recent_prices:
                    prev_close = self.recent_prices[-1]
                    day_open = open_row['open']
                    if abs(day_open - prev_close) / prev_close > 0.015: 
                        self.recent_prices.append(close_row['close']) 
                        continue 

                self.recent_prices.append(close_row['close']) 
                
                day_high = day_data['high'].max()
                day_low = day_data['low'].min()
                day_open = open_row['open']
                range_pct = (day_high - day_low) / day_open
                
                if range_pct > 0.035: 
                    # Emergency Exit
                    pnl = -self.capital * 0.01 
                else:
                    # Strategy Logic
                    max_move_pct = max((day_high - day_open)/day_open, (day_open-day_low)/day_open)
                    spot_price = day_open
                    
                    if max_move_pct < 0.008:
                        pnl = spot_price * qty * 0.002 # Profit depends on Qty now
                    elif max_move_pct < 0.015:
                        scale = (max_move_pct - 0.008) / (0.015 - 0.008)
                        pnl = -(self.capital * 0.01 * scale) # Loss still cap based on capital? 
                        # Ideally Loss should be proportional to Lots too?
                        # If we used 2 lots, our risk is higher.
                        # Let's define risk per lot.
                        # Capital-based risk: 2% of 100k = 2k. 2% of 50k = 1k.
                        # So correctly scales with capital.
                        pass
                    else:
                        pnl = -(self.capital * Config.MAX_DAILY_LOSS_PCT)

                est_premium = day_open * 0.0045 
                charges = self.calculate_charges(est_premium, qty, "SELL") * 2 + self.calculate_charges(est_premium, qty, "BUY") * 2
                
                net_pnl = pnl - charges
                self.balance += net_pnl
                
                self.trades.append({
                    "Date": date,
                    "Net PnL": net_pnl,
                    "Balance": self.balance
                })
                
                if self.balance <= 0: break
            return pd.DataFrame(self.trades)

    engine = ScaledEngine(data_file, None, capital, is_utc=False)
    df = engine.run()
    
    # Analyze Monthly
    df['Date'] = pd.to_datetime(df['Date'])
    df['Month_Year'] = df['Date'].dt.to_period('M')
    monthly = df.groupby('Month_Year')['Net PnL'].sum().reset_index()
    
    total_pnl = df['Net PnL'].sum()
    max_month = monthly['Net PnL'].max()
    min_month = monthly['Net PnL'].min()
    
    print("-" * 40)
    print(f"RESULT FOR {capital}:")
    print(f"Total Profit: {total_pnl:,.2f}")
    print(f"Best Month:   {max_month:,.2f}")
    print(f"Worst Month:  {min_month:,.2f}")
    print("-" * 40)
    
    return monthly

if __name__ == "__main__":
    print("COMPARATIVE CAPITAL ANALYSIS")
    
    # Scenario 1: 50k
    m1 = simulate_capital(50000)
    
    # Scenario 2: 75k (Still 1 Lot usually, but let's see if user implies scaling?)
    # If we stick to int(cap/50000), 75k is 1 lot.
    m2 = simulate_capital(75000)
    
    # Scenario 3: 100k (2 Lots)
    m3 = simulate_capital(100000)
    
    print("\n\nDETAILED MONTHLY (Scenario: 100,000 - 2 Lots)")
    print(m3.tail(12))
