# Project Monie — Automated Options Trading Bot (Indian Markets)

An event-driven, multi-strategy options trading bot for Indian equity derivatives (NSE F&O) with institutional-grade risk management and paper-to-live staging pipeline.

## Architecture

```
Upstox V3 SDK
  ├── MarketDataStreamerV3 (real-time WebSocket, auto-reconnect)
  ├── REST API fallback (LTP polling)
  ├── Analytics API (Option Chain + Greeks)
  └── Charges API (margin simulation)
      ↓
EventBus (async, bounded queue)
  ├── DataSanitizer (tick validation)
  ├── StrategyOrchestrator (manages 4 strategies)
  │   ├── IntradayShortStraddle (ATM straddle + breakout)
  │   ├── VolatilityHarvester (high-VIX strangle)
  │   ├── ThetaCrusher (far-OTM decay)
  │   └── ExpirydayScalper (Thursday gamma)
  ├── OMS (order state machine + fill tracking + latency metrics)
  └── RiskManager (circuit breaker + rate limiter + exposure caps)
```

## Key Features

- **Event-Driven**: All components communicate through `EventBus` — no synchronous polling
- **Multi-Strategy**: 4 concurrent strategies, each activating based on market regime
- **Multi-Tier Trailing SL**: Breakeven lock → profit lock → hyper-aggressive trailing
- **Circuit Breakers**: Daily loss limit, single-order cap, exposure cap, rate limiter
- **Staging Pipeline**: 5-level firmware lock — bot must prove profitability in paper mode before live capital is unlocked
- **Dynamic Capital Sync**: Lot sizing auto-adjusts from actual Upstox wallet balance (handles deposits, withdrawals, profit compounding)
- **Atomic State Writes**: `os.replace()` pattern prevents JSON corruption on crashes
- **Telegram Remote Control**: `/status`, `/kill`, `/token`, `/bus`, `/logs` commands
- **Remote Diagnostics**: `/logs` pulls live EC2 terminal output directly to Telegram
- **Analytics API**: Option Chain with native Greeks (Δ, Θ, Γ, Vega, IV)
- **Margin Simulation**: Pre-trade margin validation via Upstox Charges API
- **Graceful Degradation**: Strategies auto-disable after 5 consecutive errors

## Safety Guarantees

1. **PAPER by default** — `Config.BROKER` defaults to `"PAPER"` unless explicitly changed
2. **Staging Lock** — Even if set to `"UPSTOX"`, `StagingManager` forces paper mode until Level 5/5
3. **Kill Switch** — `/kill` via Telegram trips the circuit breaker and squares off all positions
4. **Rejection Handling** — All strategies handle OMS rejection (zero-qty FillEvents) gracefully

## Setup

```bash
# 1. Clone
git clone <repo_url>
cd monie

# 2. Virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure
cp .env.example .env
# Edit .env with your credentials

# 5. Run (paper mode by default)
python main.py
```

## .env Configuration

```env
BROKER=PAPER
CAPITAL=50000
UPSTOX_ACCESS_TOKEN=your_token_here
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

## Daily Operation

| Time | Action |
|------|--------|
| 09:00 | Bot sends token reminder via Telegram |
| 09:15 | Token validated, capital synced from wallet |
| 09:23 | Strategies begin evaluation |
| 15:15 | Straddle positions squared off |
| 15:30 | EOD evaluation, staging level check, capital re-sync |

## Staging Levels

| Level | Requirement | Purpose |
|-------|-------------|---------|
| 1 | 5 crash-free days | Stability |
| 2 | 10 accurate entries | Execution |
| 3 | 5 clean SL exits (<₹2 slippage) | Risk Management |
| 4 | 15-day window: >55% win rate, net PnL > 0 | Profitability |
| 5 | **GRADUATION** — live trading unlocked | Production |

## License

Private. All rights reserved.
