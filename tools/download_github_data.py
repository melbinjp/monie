"""Download historical 1-minute NIFTY 50 data from a public GitHub dataset."""

import io
import os
import pandas as pd
import requests


def download_data(outfile="data/nifty_10year_1m.csv"):
    urls = (
        "https://raw.githubusercontent.com/sandeepkapri/Nifty50-Minute-Data/main/nifty50_candlestick_data.csv",
        "https://raw.githubusercontent.com/sandeepkapri/Nifty50-Minute-Data/master/nifty50_candlestick_data.csv",
    )

    response = None
    for url in urls:
        print(f"Downloading from {url}...")
        try:
            candidate = requests.get(url, timeout=30)
        except requests.RequestException as exc:
            print(f"Request failed: {exc}")
            continue
        if candidate.status_code == 200:
            response = candidate
            break
        print(f"HTTP {candidate.status_code} from {url}")

    if response is None:
        print("Could not download dataset. Run 'python tools/generate_dummy_data.py' for offline synthetic data.")
        return 1

    df = pd.read_csv(io.StringIO(response.text))
    df.columns = [c.strip().lower() for c in df.columns]

    if "date" in df.columns and "time" in df.columns:
        df["datetime"] = pd.to_datetime(df["date"] + " " + df["time"], dayfirst=True)
    elif "date" in df.columns:
        df["datetime"] = pd.to_datetime(df["date"], dayfirst=True)
    elif "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"])

    if "volume" not in df.columns:
        df["volume"] = 0

    final_df = df[["datetime", "open", "high", "low", "close", "volume"]].copy()
    final_df.sort_values("datetime", inplace=True)

    out_dir = os.path.dirname(outfile)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    final_df.to_csv(outfile, index=False)
    print(f"Saved {len(final_df)} rows to {outfile} ({final_df['datetime'].min()} to {final_df['datetime'].max()}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(download_data())
