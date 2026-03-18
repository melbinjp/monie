from backtest.engine import BacktestEngine
from strategies.intraday_straddle import IntradayShortStraddle
from config import Config
import pandas as pd

def run():
    # Use the real 10-year data
    data_file = "data/nifty_10year_1m.csv"
    
    try:
        # Verify file exists
        pd.read_csv(data_file)
    except FileNotFoundError:
        print(f"❌ '{data_file}' not found. Please run 'python tools/download_github_data.py' first.")
        return

    print(f"Running Backtest on Real Data (10 Years): {data_file}")
    
    engine = BacktestEngine(
        data_file=data_file,
        strategy_class=IntradayShortStraddle,
        initial_capital=Config.CAPITAL,  # ₹50,000 from config
        is_utc=False # Data is already in IST
    )
    
    trades = engine.run()
    engine.generate_report()
    
    # Save trades to CSV for analysis
    trades.to_csv("backtest_trades.csv", index=False)
    print("Trade log saved to 'backtest_trades.csv'")

if __name__ == "__main__":
    run()
