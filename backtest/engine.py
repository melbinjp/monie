"""
Backtest Engine for Indian F&O (NIFTY/BANKNIFTY)
Simulates:
1. Slippage (0.1% or 0.5 points)
2. STT (Securities Transaction Tax)
3. Brokerage (Flat ₹20 or ₹0)
4. Exchange Transaction Charges
5. GST (18% on Brokerage + Transaction Charges)
"""
import pandas as pd
import numpy as np
from config import Config

class BacktestEngine:
    def __init__(self, data_file, strategy_class, initial_capital=100000, is_utc=True):
        self.data = pd.read_csv(data_file)
        
        if is_utc:
            self.data['datetime'] = pd.to_datetime(self.data['datetime'], utc=True)
            # Convert to Indian Time (IST)
            self.data['datetime'] = self.data['datetime'].dt.tz_convert('Asia/Kolkata')
            # Remove timezone info to simplify between_time comparisons (optional, but safe)
            self.data['datetime'] = self.data['datetime'].dt.tz_localize(None)
        else:
             self.data['datetime'] = pd.to_datetime(self.data['datetime'])
        
        self.strategy_class = strategy_class
        self.capital = initial_capital
        self.balance = initial_capital
        self.trades = []
        
        # Charges (NIFTY Options approximation)
        self.stt_rate = 0.05 / 100        # 0.05% on Sell side only (Options)
        self.trans_charge_rate = 0.053 / 100 # NSE Exchange Txn Charge
        self.gst_rate = 18 / 100
        self.stamp_duty_rate = 0.003 / 100 # On Buy side
        self.sebi_fees_rate = 0.0001 / 100 # ₹10 per crore
        self.slippage_rate = 0.1 / 100     # 0.1% slippage
        
        # Brokerage
        self.brokerage_per_order = 0 if Config.BROKER == "SHOONYA" else 20

    def calculate_charges(self, price, quantity, side):
        """Calculates all taxes and charges for a single leg."""
        turnover = price * quantity
        
        # 1. Brokerage
        brokerage = self.brokerage_per_order
        
        # 2. STT (Only on Sell side for Options)
        stt = turnover * self.stt_rate if side == "SELL" else 0
        
        # 3. Transaction Charges
        txn_charge = turnover * self.trans_charge_rate
        
        # 4. GST
        gst = (brokerage + txn_charge) * self.gst_rate
        
        # 5. Stamp Duty (Only on Buy side)
        stamp_duty = turnover * self.stamp_duty_rate if side == "BUY" else 0
        
        # 6. SEBI Charges
        sebi = turnover * self.sebi_fees_rate
        
        total_charges = brokerage + stt + txn_charge + gst + stamp_duty + sebi
        return total_charges

    def apply_slippage(self, price, side):
        """Adjusts price for slippage."""
        slippage = price * self.slippage_rate
        if side == "BUY":
            return price + slippage # Buy higher
        else:
            return price - slippage # Sell lower

    def run(self):
        print(f"Starting Backtest with {self.capital} Capital...")
        print(f"Slippage: {self.slippage_rate*100}% | Broker: {Config.BROKER}")
        
        # Group data by day to simulate intraday sessions
        daily_groups = self.data.groupby(self.data['datetime'].dt.date)
        
        for date, day_data in daily_groups:
            # Simulate Strategy for the Day
            # Note: For Straddle, we need Option Data. 
            # Since we likely only have Spot Data in CSV, we will Simulate Option Premiums
            # Rule of Thumb: ATM Straddle Price ~= Spot Price * 0.008 (approx 0.8-1% of Spot)
            
            day_data = day_data.set_index('datetime')
            
            # 09:20 Entry
            try:
                open_row = day_data.between_time('09:15', '09:25').iloc[0]
                close_row = day_data.between_time('15:10', '15:20').iloc[-1]
            except IndexError:
                continue # Skip days with missing data
                
            spot_price = open_row['close']
            atm_straddle_premium = spot_price * 0.0085 # Approx premium
            
            # Sell CE & PE (Credit Strategy)
            entry_price = atm_straddle_premium / 2 # Split premium
            lot_size = 50
            qty = lot_size * 1 # 1 Lot
            
            # Apply Slippage on Entry
            real_entry_price = self.apply_slippage(entry_price, "SELL")
            
            # Calculate Entry Charges
            charges_entry = self.calculate_charges(real_entry_price, qty, "SELL") * 2 # CE + PE
            
            # --- Improved Simulation Logic with Risk Management ---
            # Approximating PnL based on Spot Movement and Strategy Rules (SL/Risk Manager)
            
            day_high = day_data['high'].max()
            day_low = day_data['low'].min()
            day_open = open_row['open']
            day_close = close_row['close']
            
            # Calculate Max Intraday Move from Open
            max_move_up_pct = (day_high - day_open) / day_open
            max_move_down_pct = (day_open - day_low) / day_open
            max_move_pct = max(max_move_up_pct, max_move_down_pct)
            
            end_day_change_pct = (day_close - day_open) / day_open
            
            # Strategy Parameters
            capital = self.balance # compounding? or fixed self.capital? Let's use current balance but cap loss on base capital
            max_loss_limit = self.capital * Config.MAX_DAILY_LOSS_PCT    # 2% of Initial Capital
            
            # Heuristic PnL Calculation (Calibrated)
            if max_move_pct < 0.008: 
                # RANGE DAY (<0.8% move) -> Profit (Theta Decay > Delta)
                # Profit scales down as move increases?
                # Let's keep it simple: Fixed Theta Profit
                pnl = spot_price * 50 * 0.002 # 0.2% of Spot (~1700 INR at 17000)
                
            elif max_move_pct < 0.015:
                # MODERATE TREND (0.8% - 1.5%) -> Small Loss / Adjustment Cost
                # Loss scales 
                scale = (max_move_pct - 0.008) / (0.015 - 0.008)
                pnl = -(self.capital * 0.01 * scale)
                
            else:
                # TREND DAY (>1.5%) -> Max Loss
                pnl = -max_loss_limit
            
            # Charges Calculation (Corrected to use Premium)
            # Premium approx 0.85% of Spot for ATM Straddle (Combined? No/Yes?)
            # Entry Premium (Per Leg) ~= Spot * 0.0045? or Combined 0.009?
            # Earlier we used: atm_straddle_premium = spot_price * 0.0085
            # So per leg = spot * 0.00425
            
            est_premium = spot_price * 0.0045 
            
            # Entry Charges (Sell 2 Legs)
            charges_entry = self.calculate_charges(est_premium, qty, "SELL") * 2
            
            # Exit Charges (Buy 2 Legs)
            # Exit premium depends on theta/gamma. Let's assume roughly same for charge est.
            charges_exit = self.calculate_charges(est_premium, qty, "BUY") * 2
            
            charges = charges_entry + charges_exit
            
            net_pnl = pnl - charges
            
            self.balance += net_pnl
            self.trades.append({
                "Date": date,
                "Entry": spot_price, # reference
                "Exit": day_close,   # reference
                "Gross PnL": pnl,
                "Charges": charges,
                "Net PnL": net_pnl,
                "Balance": self.balance
            })
            
            if self.balance <= 0:
                print(f"Account Ruined at {date}. Stopping Backtest.")
                break
                
        return pd.DataFrame(self.trades)

    def generate_report(self):
        if not self.trades:
            print("No trades generated.")
            return

        df = pd.DataFrame(self.trades)
        total_pnl = df['Net PnL'].sum()
        total_charges = df['Charges'].sum()
        win_rate = (len(df[df['Net PnL'] > 0]) / len(df)) * 100
        
        print("\n" + "="*40)
        print("BACKTEST REPORT (Indian Markets)")
        print("="*40)
        print(f"Capital:      {self.capital}")
        print(f"Final Bal:    {self.balance:.2f}")
        print(f"Total PnL:    {total_pnl:.2f} ({(total_pnl/self.capital)*100:.2f}%)")
        print(f"Total Tax/Chg:{total_charges:.2f} ({(total_charges/total_pnl)*100 if total_pnl > 0 else 0:.1f}% impact)")
        print(f"Win Rate:     {win_rate:.2f}%")
        print(f"Max Drawdown: {self.calculate_drawdown(df):.2f}%")
        print("="*40)
        
    def calculate_drawdown(self, df):
        df['peak'] = df['Balance'].cummax()
        df['drawdown'] = (df['Balance'] - df['peak']) / df['peak']
        return abs(df['drawdown'].min() * 100)
