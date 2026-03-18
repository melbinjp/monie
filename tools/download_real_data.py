"""
Real Data Downloader (yfinance)
Attempts to fetch max available 1-minute data for NIFTY 50.
"""
import yfinance as yf
import pandas as pd
import datetime

def download_nifty_data(symbol="^NSEI", interval="1m", period="max"):
    print(f"Downloading Real Data for {symbol} (Interval: {interval})...")
    
    try:
        # yfinance limit for 1m is usually 7 days.
        # However, we can fetch larger chunks if we iterate or use 'max' carefully.
        # Let's try to fetch the maximum allowed directly first.
        
        # Note: yfinance 1m data is stricly limited to last 7 days.
        # Requesting period="5d" to be safe.
        
        data = yf.download(tickers=symbol, period="5d", interval=interval)
        
        if data.empty:
            print("No data found. Try a different symbol or interval.")
            return

        # Flatten MultiIndex columns if present
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        # Standardize columns
        data.reset_index(inplace=True)
        data.rename(columns={
            "Date": "datetime", 
            "Datetime": "datetime",
            "Open": "open", 
            "High": "high", 
            "Low": "low", 
            "Close": "close", 
            "Volume": "volume"
        }, inplace=True)
        
        # Lowercase columns check
        data.columns = [c.lower() for c in data.columns]
        
        filename = f"nifty_real_{interval}.csv"
        data.to_csv(filename, index=False)
        print(f"Successfully downloaded {len(data)} rows to {filename}")
        print(f"Date Range: {data['datetime'].min()} to {data['datetime'].max()}")
        
    except Exception as e:
        print(f"Download Error: {e}")

if __name__ == "__main__":
    download_nifty_data()
