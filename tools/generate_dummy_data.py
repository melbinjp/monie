"""Generate synthetic 1-minute NIFTY 50 data for offline backtests."""

import argparse
import os
import numpy as np
import pandas as pd


def generate_data(
    filename="data/nifty_10year_1m.csv",
    start_date="2020-01-01",
    end_date="2021-12-31",
    seed=42,
):
    """Write synthetic 1-minute OHLCV rows to filename."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start=start_date, end=end_date)
    if dates.empty:
        raise ValueError("Date range contains no business days.")

    minute_offsets = pd.timedelta_range(start="09:15:00", end="15:30:00", freq="1min")
    n_mins = len(minute_offsets)

    frames = []
    prev_close = 12000.0

    for day in dates:
        is_stress_month = day.year == 2020 and day.month == 3
        gap_sigma = 0.025 if is_stress_month else 0.0035
        min_sigma = 0.0022 if is_stress_month else 0.00028

        day_open = prev_close * (1.0 + rng.normal(0.0, gap_sigma))
        step_returns = rng.normal(0.0, min_sigma, size=n_mins - 1)
        closes = np.empty(n_mins, dtype=np.float64)
        closes[0] = day_open
        closes[1:] = day_open * np.cumprod(1.0 + step_returns)

        opens = np.empty(n_mins, dtype=np.float64)
        opens[0] = day_open
        opens[1:] = closes[:-1]

        spread = np.abs(rng.normal(0.0, min_sigma * 0.6, size=n_mins))
        highs = np.maximum(opens, closes) * (1.0 + spread)
        lows = np.minimum(opens, closes) * (1.0 - spread)
        volumes = rng.integers(1000, 50000, size=n_mins)

        frames.append(
            pd.DataFrame(
                {
                    "datetime": day + minute_offsets,
                    "open": np.round(opens, 2),
                    "high": np.round(highs, 2),
                    "low": np.round(lows, 2),
                    "close": np.round(closes, 2),
                    "volume": volumes,
                }
            )
        )
        prev_close = float(closes[-1])

    df = pd.concat(frames, ignore_index=True)
    out_dir = os.path.dirname(filename)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    df.to_csv(filename, index=False)
    print(f"Wrote {len(df)} synthetic 1-minute rows to {filename} ({start_date} to {end_date}).")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/nifty_10year_1m.csv")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2021-12-31")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    generate_data(filename=args.output, start_date=args.start, end_date=args.end, seed=args.seed)


if __name__ == "__main__":
    main()
