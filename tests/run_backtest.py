import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.engine import BacktestEngine
from strategies.intraday_straddle import IntradayShortStraddle
from config import Config

def run():
    data_file = "data/nifty_10year_1m.csv"

    if not os.path.exists(data_file):
        print(
            f"Missing '{data_file}'. Run 'python tools/generate_dummy_data.py' "
            "or 'python tools/download_github_data.py' first."
        )
        return

    print(f"Running backtest on {data_file}...")
    
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
