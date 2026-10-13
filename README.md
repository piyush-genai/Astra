# Astra — Intelligent Trading Platform

> **Atlas** is the trading engine. **Astra** is the brain that runs it.

> **⚠️ This README is partly out of date (reviewed 2026-10-13).** It describes the original
> product vision and is still useful for that, but it is not a reliable guide to the current
> repository. Specifically:
> - The **5-Phase Build Plan** below is superseded by the 18-phase plan in `AGENTS.md`
>   section 8 / `ASTRA_STATUS.md`. The project is at Phase 0 of that plan, with the next
>   gate being PAPER_TRADING.
> - The **Directory Structure** below is wrong: `src/` no longer holds the Atlas engine
>   (it migrated to `core/`), and `src/` now contains only `src/astra/`.
> - The **₹20,000 → ₹8,25,266 (+4,026%)** figure at the bottom does not reproduce. The
>   current code gives **₹95,270 (+376.4%)** on the same data; the higher number came from
>   code with two bugs since fixed. See `research/experiments/EXP-0001.json`.
>
> For current state, read `AGENTS.md` → `CLAUDE.md` → `HANDOFF.md` → `ASTRA_STATUS.md`.

Astra is an ML-powered, fully automated trading platform for NSE (India) markets.
It continuously analyses market conditions, selects the best strategy for the current
regime, scans the full instrument universe for opportunities, and executes trades
with strict risk controls — across index options, equity options, and equities.

---

## Architecture

```
┌───────────────────────────────────────────────────────────────────┐
│                            ASTRA                                  │
│                                                                   │
│   ┌───────────────────────────────────────────────────────────┐   │
│   │                  ML Intelligence Layer                    │   │
│   │                                                           │   │
│   │   RegimeDetector ──► StrategySelector ──► Allocation     │   │
│   │   (trending? ranging? volatile? choppy?)                  │   │
│   └──────────────────────────┬────────────────────────────────┘   │
│                              │ regime + strategy                  │
│   ┌──────────────────────────▼────────────────────────────────┐   │
│   │                  Universe Scanner                         │   │
│   │                                                           │   │
│   │   Nifty50 Options │ BankNifty │ FinNifty │ Equities      │   │
│   │   scan() ──► ScanResult[] ──► OpportunityRanker          │   │
│   └──────────────────────────┬────────────────────────────────┘   │
│                              │ top-N ranked signals              │
│   ┌──────────────────────────▼────────────────────────────────┐   │
│   │              Atlas Core Engine (src/ → core/)             │   │
│   │                                                           │   │
│   │   ExecutionEngine                                         │   │
│   │     ├─ RiskManager   (circuit breaker, kill switch)       │   │
│   │     ├─ PositionManager (concurrency, sizing)              │   │
│   │     └─ StrategyRegistry                                   │   │
│   │                                                           │   │
│   │   Strategies: PivotCPR │ Momentum │ MeanReversion │ ...  │   │
│   └──────────────────────────┬────────────────────────────────┘   │
│                              │ orders                            │
│   ┌──────────────────────────▼────────────────────────────────┐   │
│   │                  Upstox API                               │   │
│   │         (live data + order execution)                     │   │
│   └───────────────────────────────────────────────────────────┘   │
│                                                                   │
│   Persistence: SQLite (trades, positions, capital, regime_log)    │
│   Monitoring:  Telegram alerts + heartbeat                        │
└───────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
astra/                          (this repo — formerly "atlas")
│
├── src/                        ← Original Atlas engine (DO NOT MODIFY)
│   ├── engine/                   RiskManager, PositionManager, ExecutionEngine
│   ├── broker/                   UpstoxAdapter (data working; execution = TODO)
│   ├── strategies/               PivotCPR + Momentum Breakout strategy
│   ├── data/                     Indicators, live/historical feeds
│   └── backtest/                 Original backtest harness
│
├── core/                       ← Phase 1: Atlas engine migrates here
│   ├── engine/
│   ├── broker/
│   └── data/
│
├── strategies/                 ← Strategy library (plugin interface)
│   ├── base.py                   BaseStrategy ABC, Signal, MarketData dataclasses
│   └── pivot_cpr_strategy.py     Original Atlas strategy (wrapper → src/)
│
├── ml/                         ← Astra intelligence layer (NEW)
│   ├── features.py               Feature engineering from OHLCV
│   ├── regime_detector.py        Classifies market regime
│   ├── strategy_selector.py      Picks best strategy per regime
│   ├── trainer.py                Train/retrain ML models
│   └── models/                   Saved model artifacts (.pkl)
│
├── universe/                   ← Multi-instrument scanner (NEW)
│   ├── instruments.py            Instrument registry (Nifty, BankNifty, top-20 equities)
│   ├── scanner.py                Scans all instruments each bar
│   └── opportunity_ranker.py     Scores and ranks signals
│
├── live/                       ← Production orchestration (NEW)
│   ├── orchestrator.py           Main trading loop
│   ├── monitor.py                Telegram alerts + health checks
│   └── state_manager.py          SQLite-backed state (replaces capital_state.json)
│
├── backtest/                   ← Enhanced backtest framework (NEW)
│   ├── walk_forward.py           Out-of-sample validation (Phase 3 gate)
│   ├── regime_backtest.py        Backtest split by market regime
│   └── strategy_comparison.py   Compare strategies head-to-head
│
├── config/
│   ├── instruments.yaml          Lot sizes, expiry weekdays (existing)
│   ├── risk.yaml                 Risk limits, circuit breaker (existing)
│   └── ml.yaml                   ML model config (NEW)
│
├── scripts/
│   ├── run_live.py               ← The end goal (NEW — wraps orchestrator)
│   ├── run_paper.py              Paper trading (existing, needs refactor)
│   ├── run_backtest.py           Backtest runner (existing)
│   └── train_models.py           ML model training (NEW)
│
└── tests/
    ├── engine/                   Existing unit tests (keep)
    └── strategies/               Existing unit tests (keep)
```

---

## Instruments Covered

| Segment | Instruments |
|---|---|
| Index Options | Nifty 50, BankNifty, FinNifty, MidcapNifty |
| Equity Options | RELIANCE, TCS, HDFCBANK, INFY, ICICIBANK + 15 more |
| Equities (future) | Top 20 Nifty 50 large-caps |

---

## The ML Layer — How It Works

The key insight: **ML never modifies strategy parameters**. It only decides *which* strategy to run and *when*.

```
Every trading day at 09:00:
  1. RegimeDetector analyses last 60 days of daily OHLCV
     → classifies today as: TRENDING_UP / TRENDING_DOWN / RANGING / VOLATILE / CHOPPY

  2. StrategySelector asks: "Which strategy has edge in this regime?"
     → based on observed per-regime win rate from live/paper trade history
     → falls back to strategy metadata priors until 50+ trades in the regime

  3. UniverseScanner scans all instruments every 5 min
     → each instrument runs the selected strategy
     → ScanResults collected

  4. OpportunityRanker scores each signal:
     score = confidence × regime_match × liquidity × time_of_day
     → top-3 signals passed to ExecutionEngine

  5. End of day: trade outcomes recorded
     → StrategySelector updates per-regime performance matrix
     → Weekly: ModelTrainer retrains RegimeDetector on fresh data
```

Your original PivotCPR strategy is **preserved exactly as-is**. The ML layer is above it, not inside it.

---

## 5-Phase Build Plan

### Phase 1 — Fix Atlas foundations *(current priority)*
- [ ] Implement Upstox execution adapter (`place_order`, `get_option_contract`, `cancel_order`)
- [ ] Refactor `run_paper.py` to use `RiskManager` + `PositionManager` (remove God Object)
- [ ] Migrate `src/` → `core/` with Astra-compatible `BaseStrategy` interface
- [ ] Replace `capital_state.json` with `live/state_manager.py` (SQLite)
- [ ] Integration test: `FakeBrokerAdapter → ExecutionEngine → PivotCPRStrategy`

### Phase 2 — Universe expansion
- [ ] Wire multi-instrument scanning (BankNifty, FinNifty, top equity options)
- [ ] Complete `universe/scanner.py` with real data feeds
- [ ] Run paper trading on 4 indices simultaneously

### Phase 3 — Walk-forward validation
- [ ] Implement `backtest/walk_forward.py` — train Feb–Apr, test May–Jul
- [ ] Implement `backtest/regime_backtest.py` — identify which regimes have edge
- [ ] Gate: `is_robust=True` required before Phase 4

### Phase 4 — Astra ML layer
- [ ] Implement `ml/features.py` feature computation
- [ ] Implement `ml/regime_detector.py` ML training
- [ ] Implement `ml/strategy_selector.py` per-regime performance tracking
- [ ] Implement `ml/trainer.py` weekly retraining loop
- [ ] Run `scripts/train_models.py` and validate

### Phase 5 — Full live trading
- [ ] Wire `live/orchestrator.py` end-to-end
- [ ] Deploy on EC2 with Telegram monitoring
- [ ] Start live with small capital, ML in shadow mode (observing but not overriding)
- [ ] Promote ML to active control after 4 weeks of validated paper trading

---

## Quick Start

### Paper trading (current state)
```bash
cd <repo-root>
source .venv/bin/activate
python scripts/run_paper.py
```

### Backtest
```bash
python scripts/run_backtest.py
```

### Train ML models (Phase 4+)
```bash
python scripts/train_models.py --data nifty_5min_20260201_to_20260731.csv
```

### Live trading (Phase 5)
```bash
# Dry run (safe — no real orders)
python scripts/run_live.py

# LIVE — places real Upstox orders
python scripts/run_live.py --no-dry-run
```

---

## Risk & Safety

- **Defined risk only** — system only buys options (calls/puts), never writes naked options
- **Circuit breaker** — halts trading if daily loss exceeds configured threshold
- **Kill switch** — Telegram `/kill` command stops all trading immediately
- **Dry-run default** — live trading requires explicit `--no-dry-run` flag
- **SQLite state** — atomic writes; crash-safe (replaces fragile JSON file)
- **1 position max** — no simultaneous open positions per instrument (except reversal)
- **Hard lot cap** — 10 lots maximum per trade regardless of capital

---

## Strategy: Pivot CPR + Momentum Breakout

The original Atlas strategy. Two signal types:

| Type | Frequency | Win Rate | Description |
|---|---|---|---|
| Regular Breakout | ~4.5% of trades | ~30.5% | 2-candle confirmation through pivot/CPR zone |
| Momentum Breakout | ~95.5% of trades | ~20% | Single explosive candle — 2 of 3 criteria met |

**Backtest (Feb–Jul 2026):** ₹20,000 → **₹95,270 (+376.4%)**, 532 trades, 32.1% win rate.
Reproduced 2026-10-13 via `python scripts/exp_0001_reproduce.py`; matches
`research/experiments/EXP-0001.json` exactly.

⚠️ *The previously published ₹8,25,266 (+4,026%) figure was produced by code containing two
bugs (options pricer and stop geometry), both since fixed. Do not cite it.*
⚠️ *Still an in-sample result on 6 months of data — the walk-forward and Monte Carlo gates were
cleared on the separate 2023-2025 dataset, not on this one.*

---

## Environment Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure credentials
cp .env.example .env
# Edit .env: UPSTOX_API_KEY, UPSTOX_API_SECRET, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

# Run tests
pytest tests/
```
