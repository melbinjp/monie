# Monie

Monie is an event-driven prototype for options strategies on the National Stock Exchange of India (NSE). It combines strategy rules, an order state machine, pre-trade risk limits, and simulated paper execution.

> [!NOTE]
> **Status: Archived prototype.** This project was planned as a system design exploration and built with AI-assisted code generation. It is published as a read-only reference and is not actively maintained.

> [!WARNING]
> **Disclaimer.** Do not connect this software to live capital without an independent code and compliance audit. Monie is an educational prototype and does not give financial or investment advice. This release verifies only offline paper execution and synthetic backtests. Live broker adapters are unverified against current exchange rules.

## Architecture

| Directory | Responsibility |
|---|---|
| `core/` | Async event bus, order state machine (`oms.py`), pre-trade risk limits, gap and volatility guard, SQLite state store, and five-level staging gate |
| `strategies/` | Intraday short straddle state machine, volatility harvester, theta decay strategy, expiry scalper, and afternoon momentum module |
| `backtest/` | Minute-bar simulation engine with Indian F&O tax, brokerage, and slippage formulas |
| `simulations/` | Comparative capital, drawdown, and monthly PnL analysis scripts |
| `tests/` | Strategy formula checks, March 2020 crash stress test, and multi-year guard comparison |
| `tools/` | Offline synthetic data generator, historical CSV downloaders, and Upstox quote check |

## Run locally

Use Python 3.13. Run these commands from the repository root.

### Windows PowerShell

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -X utf8 main.py
```

### Linux or macOS

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -X utf8 main.py
```

If you already have a local `.env`, keep it and review its settings before you start.

The example starts Monie with `BROKER=PAPER` and `PAPER_DATA_SOURCE=MOCK`. It needs no accounts or network connection. The bot starts with no market tick feed and waits for events. Press `Ctrl+C` to stop it.

## Verify offline

Use the Python executable from your virtual environment to run the formula and backtest checks without credentials.

1. Check the strategy formulas:

   ```sh
   python -X utf8 tests/test_strategy_math.py
   ```

2. Generate synthetic 1-minute data in `data/nifty_10year_1m.csv` and run the backtest and crash stress checks:

   ```sh
   python -X utf8 tools/generate_dummy_data.py
   python -X utf8 tests/run_backtest.py
   python -X utf8 tests/test_black_swan.py
   python -X utf8 tests/test_guard_longterm.py
   ```

## Market data and brokers

Set `PAPER_DATA_SOURCE=UPSTOX` and supply `UPSTOX_ACCESS_TOKEN` to use Upstox market data with simulated orders. Run `python -m tools.check_upstox_connection` to check authentication and quotes.

Monie includes broker adapters for Upstox and Shoonya. The staging gate in `core/staging_manager.py` blocks live Upstox orders until five paper validation levels pass. The Shoonya adapter is legacy.

Set both `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` to enable Telegram alerts and commands. Keep all broker and Telegram credentials in the local `.env` file.

## Run on a server

For Linux `systemd` setup, see [Run Monie on a Linux server](docs/server.md). Use `Asia/Kolkata` as the runtime time zone for scheduled market windows.

## License

Monie's original code is available under the [MIT License](LICENSE). Third-party code and packages keep their respective licenses.
