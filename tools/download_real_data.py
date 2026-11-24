"""Download recent 1-minute NIFTY 50 candles with yfinance."""

import os
import pandas as pd
import yfinance as yf


def download_nifty_data(symbol="^NSEI", interval="1m", period="5d"):
    """Fetch recent candles from Yahoo Finance and save them under data/."""
    print(f"Downloading {symbol} ({interval}, {period})...")
    try:
        data = yf.download(tickers=symbol, period=period, interval=interval)
        if data.empty:
            print("No data returned.")
            return 1

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        data.reset_index(inplace=True)
        data.rename(
            columns={
                "Date": "datetime",
                "Datetime": "datetime",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            },
            inplace=True,
        )
        data.columns = [c.lower() for c in data.columns]

        os.makedirs("data", exist_ok=True)
        filename = os.path.join("data", f"nifty_real_{interval}.csv")
        data.to_csv(filename, index=False)
        print(f"Saved {len(data)} rows to {filename} ({data['datetime'].min()} to {data['datetime'].max()}).")
        return 0
    except Exception as exc:
        print(f"Download error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(download_nifty_data())
