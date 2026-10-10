# CLAUDE.md — Astra Trading Platform

> **This file is mandatory reading before touching any code in this repo.**
> This system trades REAL MONEY on Indian stock markets. One wrong change to a
> risk limit, one broken import path, one off-by-one in position sizing can
> cause direct financial loss. Every rule in this document exists for a reason.
> When in doubt, stop and ask the human operator before proceeding.

---

## 1. What Is Astra

Astra is a personal algorithmic trading platform for NSE (India) built in two layers. **Atlas** is the trading engine — it handles risk enforcement, order execution, position tracking, and strategy evaluation. **Astra** is the ML orchestration layer built on top of Atlas — it detects market regimes, selects the best strategy for current conditions, and scans multiple instruments simultaneously for opportunities. The system connects to Upstox (primary broker) and optionally Zerodha Kite (backup) via their REST/WebSocket APIs. It runs on AWS EC2 with a static IP (SEBI compliance requirement). It trades Nifty 50 index options, BankNifty options, equity options, and direct equities.

---

## 2. Architecture Map

```
┌──────────────────────────────────────────────────────────────────┐
│                          ASTRA                                   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   ML Layer                               │   │
│  │   RegimeDetector ──► StrategySelector ──► Sizer         │   │
│  │   (ml/regime_detector.py)  (ml/strategy_selector.py)    │   │
│  └─────────────────────────┬────────────────────────────────┘   │
│                             │ regime + selected strategy         │
│  ┌──────────────────────────▼────────────────────────────────┐  │
│  │                 Universe Scanner                          │  │
│  │         (universe/scanner.py + opportunity_ranker.py)    │  │
│  └─────────────────────────┬────────────────────────────────┘  │
│                             │ ranked ScanResult list             │
│  ┌──────────────────────────▼────────────────────────────────┐  │
│  │              ATLAS — Core Engine                          │  │
│  │                                                           │  │
│  │  StrategyRegistry ──► ExecutionEngine                    │  │
│  │                            │                             │  │
│  │              ┌─────────────┴──────────────┐              │  │
│  │         RiskManager              PositionManager         │  │
│  │  (core/engine/risk_manager.py) (core/engine/position_…)  │  │
│  └─────────────────────────┬────────────────────────────────┘  │
│                             │ BrokerAdapter calls only           │
│  ┌──────────────────────────▼────────────────────────────────┐  │
│  │              Broker Adapter Layer                         │  │
│  │   UpstoxAdapter (primary)   KiteAdapter (backup)         │  │
│  │              (core/broker/)                               │  │
│  └─────────────────────────┬────────────────────────────────┘  │
│                             │                                    │
│                    Upstox / Kite API                            │
└──────────────────────────────────────────────────────────────────┘

Persistence:  live/state_manager.py  (SQLite — single source of truth)
Alerts:       live/monitor.py        (Telegram bot + heartbeat)
Entry point:  live/orchestrator.py   (wires all components together)
```

### Module Responsibility Table

| Directory | Owns | Must NEVER |
|---|---|---|
| `core/engine/` | Risk enforcement, order routing, position tracking, strategy interface | Import from `core.broker` except in `execution_engine.py`; contain strategy logic |
| `core/broker/` | Broker API calls, auth, contract resolution, market data | Be imported by anything except `core.engine.execution_engine` |
| `core/data/` | OHLCV feeds, indicator formulas (pivots, CPR, ATR, ADX) | Place orders, track positions, call broker execution methods |
| `strategies/` | Signal generation — return a Signal or None | Place orders, call broker, track positions, read capital, check risk limits directly |
| `ml/` | Regime classification, strategy selection, model training | Import from `core.broker`; execute trades; modify strategy parameters at runtime |
| `universe/` | Scan instruments for signals, rank opportunities | Call broker execution methods directly; bypass ExecutionEngine |
| `live/` | Production orchestration, SQLite state, Telegram monitoring | Contain strategy logic or indicator formulas |
| `backtest/` | Historical simulation, walk-forward validation, strategy comparison | Connect to live broker; modify production state |

---

## 3. Import Rules — Architecture Boundaries (ENFORCED)

These are hard rules. Violating them breaks the architecture and can allow strategies to bypass risk controls entirely.

```
Rule: "A may import B" matrix

                      core.engine  core.broker  core.data  strategies  ml  universe  live  backtest
core.engine.execution_engine  ✅           ✅          ✅          ✅       ✗     ✗        ✗     ✗
core.engine.* (other)         ✅           ✗           ✅          ✅       ✗     ✗        ✗     ✗
core.broker.*                 ✗            ✅          ✗           ✗       ✗     ✗        ✗     ✗
core.data.*                   ✗            ✗           ✅          ✗       ✗     ✗        ✗     ✗
strategies.*                  core.engine.base_strategy + core.data.indicators ONLY
ml.*                          core.data + strategies (read-only, no execution)
universe.*                    core.data + strategies + ml (no broker, no execution)
live.*                        everything except backtest
backtest.*                    core.engine + core.data + strategies (no live broker)
scripts/*                     everything (entry points)
tests/*                       everything (test only)
```

**The one absolute rule:** `core/engine/execution_engine.py` is the ONLY file in the entire codebase allowed to import from `core.broker`. If you find any other file importing from `core.broker`, that is an architecture violation — fix it, do not work around it.

---

## 4. Money Flow — How Capital Moves Through the System

This flow must be preserved exactly. Any shortcut risks corrupting capital state.

```
1. Session start
   └─► live/state_manager.py loads current capital from SQLite (atomic read)
   └─► core/engine/risk_manager.py receives capital → computes per-trade limit
       (RiskManager is READ-ONLY on capital — it never writes to StateManager)

2. Signal received → ExecutionEngine.process_signal(signal)
   ├─► Check #1: Algo-ID configured? (legal requirement since 1 Apr 2026)
   ├─► Check #2: Signal direction → always BUY a call or BUY a put (never sell/write)
   ├─► Check #3: Contract resolved? LTP valid?
   ├─► Check #4: max_loss = premium × lot_size computed
   ├─► Check #5: PositionManager.can_open() — concurrency limits
   └─► Check #6: RiskManager.check_pre_trade() — per-trade + circuit breaker
       If ALL pass → place order via BrokerAdapter

3. Order filled
   └─► PositionManager.open_position() records position in memory
   └─► live/state_manager.py.record_trade() — atomic SQLite INSERT (not JSON)

4. Position closed (stop hit, structural invalidation, EOD, reversal)
   └─► RiskManager.record_realized_loss(pnl) — updates daily loss accumulator
   └─► PositionManager closes position
   └─► live/state_manager.py.update_capital(pnl) — atomic SQLite UPDATE

5. Each bar (every 5 minutes during market hours)
   └─► RiskManager.update_unrealized_check(total_unrealized_pnl)
       If cumulative loss ≥ daily_loss_limit → circuit breaker trips
       Circuit breaker = no new orders for rest of session (NOT reversible intraday)
```

**Capital state MUST be SQLite with transactions.** `capital_state.json` (the old approach) is unsafe for live trading — a crash between the read and write corrupts state permanently. The replacement is `live/state_manager.py`. Do not reintroduce JSON-based state.

---

## 5. Risk Rules — NEVER VIOLATE

These rules come directly from `.kiro/steering/trading-risk-rules.md` and `config/risk.yaml`. They are non-negotiable. If an implementation would require violating one, stop and flag it to the human operator.

1. **NEVER write or sell naked options.** The system only BUYs calls and puts (defined-risk, limited max loss = premium paid). Any code path that calls `OrderSide.SELL` as an opening trade must be rejected. The `SELL` side exists only for closing existing long positions.

2. **NEVER exceed 2.5% of current capital at risk on a single trade.** `max_loss_per_trade_pct: 2.5` in `risk.yaml`. Max loss = `premium × lot_size`. This is checked by `RiskManager.check_pre_trade()` before every order — do not bypass it.

3. **NEVER deploy more than 25% of capital across all open positions combined.** `max_capital_deployed_pct: 25.0` in `risk.yaml`. Checked by `PositionManager.can_open()`.

4. **NEVER exceed 10 lots on a single order.** `hard_cap_lots: 10` in `risk.yaml`. This is an exchange protection limit — exceeding it risks order rejection or regulatory scrutiny.

5. **NEVER place an order if the circuit breaker is tripped.** `RiskManager.circuit_breaker_tripped` must be checked before every order. A tripped circuit breaker means daily loss limit is hit — no new trades for the rest of the session. It resets at the start of the next session via `reset_session()`.

6. **NEVER place an order if the kill switch is active.** `RiskManager.kill_switch_active` is checked first in `check_pre_trade()`. The kill switch is activated via Telegram bot or CLI and can only be deactivated by an explicit operator action.

7. **NEVER hold a position overnight.** All positions MUST be closed by **15:20 IST** (the EOD close logic fires at 15:20, market closes at 15:30). Overnight option exposure incurs theta decay and gap risk that the strategy is not designed to handle.

8. **NEVER modify `risk.yaml` values without a full backtest.** Every number in that file was calibrated against backtest data. Changing `max_loss_per_trade_pct` from 2.5% to 5% doubles the loss exposure per trade — this requires a full re-backtest and walk-forward validation before the change can be used in paper or live trading. **Get explicit human confirmation before changing risk.yaml.**

9. **NEVER place an order without a valid Algo-ID.** Mandatory since 1 April 2026 (SEBI regulation). `ExecutionEngine._get_algo_id()` returns `None` if unconfigured, and the engine refuses to place the order. Do not work around this check.

10. **NEVER run `dry_run=False` (live mode) without completing all paper trading gates.** Gates in order: (1) unit tests pass, (2) backtest passes kill-criteria, (3) walk-forward out-of-sample validation, (4) minimum 2 weeks paper trading. Skipping gates is not allowed even if the operator asks — surface the missing gates explicitly.

11. **NEVER allow a strategy file to import from `core.broker` or call `ExecutionEngine` directly.** Strategy files emit `Signal` objects. The engine decides what to do with them. If a strategy is trying to place orders itself, it is an architecture violation.

12. **NEVER remove or shorten the zone cooldown.** `cooldown_minutes: 15` prevents trading the same price zone repeatedly after a loss. The prior "optimized" config removed this protection and caused compounding losses. It stays at 15 minutes minimum.

13. **NEVER change lot sizes or expiry weekdays as literals in Python code.** These live in `config/instruments.yaml` and change with NSE circulars. NSE has already revised Nifty lot size multiple times (75 → 25 → 65). All code reads from config — no hardcoded numbers.

---

## 6. The Strategy Interface Contract

Every strategy in this codebase must:

1. **Subclass `BaseStrategy`** from `core/engine/base_strategy.py`
2. **Define `STRATEGY_ID`** as a non-empty class attribute (string, unique across all strategies)
3. **Implement `evaluate(self, market_data: MarketData) -> Optional[Signal]`** — return a Signal when a trade condition is met, or None when there is no trade

That's the entire public interface. Everything else is internal to the strategy.

### What strategies MUST NOT do

- Call any broker method (no `self._broker.place_order()` or similar)
- Track open positions or capital levels
- Check risk limits directly
- Import from `core.broker` or `core.engine.execution_engine`
- Modify their own parameters at runtime based on trade outcomes

The `on_trade_result()` hook (in the Astra `strategies/base.py`) is for learning/analytics only — strategies that modify their own entry/exit thresholds based on live results are doing live parameter optimization, which is how the original Atlas config was broken and went to −₹131.

### Critical Warning: Do NOT "Optimize" Strategy Parameters

A prior AI session "optimized" the PivotCPR strategy parameters. The result: capital went from ₹20,000 to **−₹131** (below zero). The correct, empirically tested parameters are frozen in `CURRENT_STRATEGY.md`. Any change to strategy entry/exit thresholds requires:

1. Running `backtest/harness.py` with the new parameters
2. Verifying the result matches or exceeds the reference numbers in `CURRENT_STRATEGY.md §9`
3. Running walk-forward validation via `backtest/walk_forward.py`
4. Getting explicit human approval

**Do not touch these numbers without completing all of the above:**
- Momentum range explosion threshold: `1.8×`
- Momentum body requirement: `50%` of range
- Momentum penetration threshold: `1.5×` zone width
- Trailing stop lookback: `2 bars`
- Zone cooldown: `15 minutes`

---

## 7. The PivotCPR Strategy — Current Live Strategy

**File:** `strategies/pivot_cpr_strategy.py`
**Status:** Paper-trading live. Live trading blocked until execution stubs are implemented.
**Reference:** `CURRENT_STRATEGY.md` is the authoritative parameter document.

### Locked Parameters (do not modify without full backtest)

| Parameter | Value | Notes |
|---|---|---|
| Timeframe | 5-minute bars | All signals computed on 5-min OHLCV |
| Instrument | Nifty 50 | `NIFTY` in instruments.yaml |
| Lot size | 65 | Read from `instruments.yaml` — verify each expiry series rollover |
| Strike step | 50 points | ATM/near-OTM rounding |
| Entry — Regular | 2-bar confirmation, enter bar 3 | Both candles must close beyond zone |
| Entry — Momentum | Immediate, 2 of 3 criteria required | No waiting for confirmation |
| — Range explosion | ≥ 1.8× average range of last 10 bars | **LOCKED** |
| — Body requirement | ≥ 50% of total range | **LOCKED** |
| — Penetration | ≥ 1.5× zone width | **LOCKED** |
| Initial stop — Regular | Zone edge or breakout candle extreme | Whichever is further from entry |
| Initial stop — Momentum | 50% retracement of breakout candle | Tighter than regular |
| Trailing stop | Low/high of candle 2 bars ago | Activates after 2 bars in trade |
| Structural exit | Any candle closing back through broken zone | Immediate exit, ignore stop level |
| EOD exit | 15:20 IST (15:25 latest) | No overnight positions |
| Zone cooldown | 15 minutes per zone after any exit | **LOCKED — prevents whipsaw** |
| Max concurrent | 1 position (exception: reversal signal flips direction) | |
| Compounding | Monthly (capital resets at month start, no mid-month injections) | |

### Backtest Reference (in-sample, Feb–Jul 2026)

| Metric | Value |
|---|---|
| Starting capital | ₹20,000 |
| Ending capital | ₹8,25,266 |
| Return | +4,026% |
| Win rate | 25.4% (331/1,302) |
| Avg trades/day | 9.9 |

**These numbers are in-sample only.** Walk-forward out-of-sample validation has not been run. Do not treat these as guaranteed future performance.

---

## 8. Development Workflow

### Before changing any code

1. Read this file completely
2. Run `python3 -m pytest tests/ -q` — baseline is **46 pass / 6 fail** (as of Oct 2026; 6 failures are pre-existing mock signature mismatches, not production bugs)
3. Identify which risk rules the change touches (see §5)
4. If the change affects a risk rule, strategy parameter, or execution path — **stop and confirm with the human operator before proceeding**

### After any change

1. Run `python3 -m pytest tests/ -q` — zero new failures allowed
2. For strategy parameter changes: run full backtest, compare to reference numbers in `CURRENT_STRATEGY.md §9`
3. For risk rule changes: get explicit human confirmation + backtest before committing

### Commands

```bash
# Testing
python3 -m pytest tests/ -q                   # all tests
python3 -m pytest tests/engine/ -v            # engine tests only
python3 -m pytest tests/strategies/ -v        # strategy tests only

# Backtesting
python3 scripts/run_backtest.py               # full backtest on historical CSV data

# Paper trading (safe — no real orders)
python3 scripts/run_paper.py                  # paper mode, Upstox live data, no real orders

# ML training
python3 scripts/train_models.py               # retrain regime detector on fresh data

# Live trading (DANGEROUS — confirm with human first)
python3 scripts/run_live.py --no-dry-run      # requires explicit flag; default is dry-run
```

### Actions requiring human confirmation before proceeding

| Action | Why |
|---|---|
| Any change to `config/risk.yaml` | Changes max loss, circuit breaker, lot caps |
| Any change to strategy entry/exit thresholds | Needs backtest validation (see the −₹131 incident) |
| Any change to `core/engine/execution_engine.py` order logic | Core safety path |
| Switching `dry_run=False` in any script | Enables real orders |
| Any database schema change in `live/state_manager.py` | Could corrupt position state |
| Deploying to EC2 | Production environment, real money |
| Changing the Algo-ID in `risk.yaml` | SEBI compliance — wrong ID = regulatory issue |

---

## 9. Current Development Status

| Component | Status | Location |
|---|---|---|
| RiskManager | ✅ Production-ready, fully tested | `core/engine/risk_manager.py` |
| PositionManager | ✅ Production-ready, fully tested | `core/engine/position_manager.py` |
| ExecutionEngine | ✅ Complete (dry_run works) | `core/engine/execution_engine.py` |
| BaseStrategy interface | ✅ Complete | `core/engine/base_strategy.py` |
| StrategyRegistry | ⚠️ Stubbed | `core/engine/strategy_registry.py` |
| Indicators (pivots, CPR, ATR) | ✅ Complete, unit-tested | `core/data/indicators.py` |
| Upstox data adapter | ✅ Working (get_ohlcv, get_ltp) | `core/broker/upstox_adapter.py` |
| **Upstox execution adapter** | **❌ NotImplementedError stubs** | `core/broker/upstox_adapter.py` |
| PivotCPR Strategy | ✅ Paper-trading live | `strategies/pivot_cpr_strategy.py` |
| Backtest harness | ✅ Working | `backtest/harness.py` |
| Options pricer (Black-Scholes) | ✅ Working | `backtest/options_pricer.py` |
| Walk-forward validator | ⚠️ Scaffold only | `backtest/walk_forward.py` |
| Regime backtest | ⚠️ Scaffold only | `backtest/regime_backtest.py` |
| **StateManager (SQLite)** | **❌ Not implemented** | `live/state_manager.py` |
| SystemMonitor (Telegram) | ⚠️ Scaffold only | `live/monitor.py` |
| Orchestrator | ⚠️ Scaffold only | `live/orchestrator.py` |
| RegimeDetector | ⚠️ Scaffold only | `ml/regime_detector.py` |
| StrategySelector | ⚠️ Scaffold only | `ml/strategy_selector.py` |
| UniverseScanner | ⚠️ Scaffold only | `universe/scanner.py` |

**Live trading is currently BLOCKED** by two hard dependencies:
1. Upstox execution stubs (`place_order`, `cancel_order`, `get_option_contract`) → raises `NotImplementedError`
2. StateManager SQLite not implemented → capital state would use unsafe JSON

---

## 10. Known Issues and Dangers

### 1. `scripts/run_paper.py` is a 720-line God Object
It reimplements risk management, position tracking, and capital compounding from scratch instead of delegating to `RiskManager` and `PositionManager`. It works for paper trading but creates divergence: paper trading uses different logic than what the live engine will use. **Phase 1 task: refactor `run_paper.py` to use `core/engine/` modules.**

### 2. `capital_state.json` is unsafe for live trading
A crash between the read and write of this file corrupts the capital state permanently. `live/state_manager.py` (SQLite with atomic transactions) replaces it. **Do not add new reads/writes to `capital_state.json`.**

### 3. The "optimized config" incident — −₹131
A prior session "optimized" the PivotCPR parameters. Capital went from ₹20,000 to −₹131. The parameters in `CURRENT_STRATEGY.md` are the tested, correct ones. Lock them. Any AI assistant that suggests "optimizing" momentum thresholds, cooldown periods, or stop-loss rules without a full backtest must be stopped.

### 4. Upstox execution stubs block live trading
`place_order()`, `cancel_order()`, `get_option_contract()` in `core/broker/upstox_adapter.py` all raise `NotImplementedError`. These must be implemented against the Upstox V2/V3 API and tested in paper mode (using `dry_run=True` first, then sandbox mode) before any live orders are attempted.

### 5. Backtest result is in-sample only
The +4,026% return (Feb–Jul 2026) was computed on the same data used to tune the parameters. It has not been validated out-of-sample. Run `backtest/walk_forward.py` (train on Feb–Apr, test on May–Jul) before trusting the strategy with real capital.

### 6. Algo-ID is null in `risk.yaml`
`algo_ids.pivot_cpr_strategy: null`. The execution engine will refuse all orders until a real Algo-ID is obtained by registering the strategy with Upstox (mandatory SEBI requirement since 1 April 2026).

### 7. Daily 2FA re-authentication
Upstox forces a daily logout. `run_paper.py` handles this via a manual Analytics Token refresh. The production `live/orchestrator.py` must handle this as an automated startup step (see `BrokerAdapter.authenticate()`), not treat it as an error.

---

## 11. File Structure

```
/workshop/atlas/                   ← repo root (project: Astra)
│
├── CLAUDE.md                      ← THIS FILE — read before touching anything
├── CURRENT_STRATEGY.md            ← authoritative strategy parameters (frozen)
│
├── core/                          ← Atlas trading engine
│   ├── engine/
│   │   ├── base_strategy.py       BaseStrategy ABC, Signal, MarketData dataclasses
│   │   ├── execution_engine.py    Order routing — ONLY file that imports core.broker
│   │   ├── risk_manager.py        Pre-trade checks, circuit breaker, kill switch
│   │   ├── position_manager.py    Concurrency limits, position tracking
│   │   └── strategy_registry.py  Registers + dispatches to strategy instances
│   ├── broker/
│   │   ├── base_adapter.py        BrokerAdapter ABC (interface only)
│   │   ├── upstox_adapter.py      Primary broker (data ✅, execution ❌ stubs)
│   │   ├── kite_adapter.py        Backup broker (mostly stub)
│   │   └── callback.py            OAuth callback handler
│   └── data/
│       ├── indicators.py          Pivot, CPR, ATR, ADX formulas — tested, no look-ahead
│       ├── historical_feed.py     CSV / API historical OHLCV loader
│       └── live_feed.py           Upstox WebSocket live feed
│
├── strategies/                    ← Strategy plugin library
│   ├── base.py                    Extended BaseStrategy ABC with Astra metadata
│   └── pivot_cpr_strategy.py      Current live strategy — DO NOT modify params
│
├── ml/                            ← Astra intelligence layer (all scaffold)
│   ├── features.py                Feature engineering from OHLCV
│   ├── regime_detector.py         Market regime classification
│   ├── strategy_selector.py       Regime → best strategy mapping
│   ├── trainer.py                 Model training + walk-forward
│   └── models/                    Saved model artifacts (.pkl, .onnx)
│
├── universe/                      ← Multi-instrument scanner (all scaffold)
│   ├── instruments.py             InstrumentRegistry (Nifty, BankNifty, equities)
│   ├── scanner.py                 Scan all instruments each 5-min bar
│   └── opportunity_ranker.py      Score + rank signals across instruments
│
├── live/                          ← Production orchestration (all scaffold)
│   ├── orchestrator.py            Main daily loop (pre-market → loop → post-market)
│   ├── monitor.py                 Telegram alerts, heartbeat, health checks
│   └── state_manager.py          SQLite state (capital, positions, trades, regime log)
│
├── backtest/                      ← Backtest framework
│   ├── harness.py                 ✅ Full backtest against historical CSV
│   ├── options_pricer.py          ✅ Black-Scholes premium estimator
│   ├── walk_forward.py            ⚠️ Scaffold — implement before live trading
│   ├── regime_backtest.py         ⚠️ Scaffold
│   └── strategy_comparison.py    ⚠️ Scaffold
│
├── config/
│   ├── instruments.yaml           Lot sizes, expiry weekdays — read at runtime (never hardcode)
│   ├── risk.yaml                  ALL risk limits — CHANGE REQUIRES HUMAN APPROVAL + BACKTEST
│   └── ml.yaml                    ML hyperparameters
│
├── tests/                         All unit tests — must pass before every commit
│   ├── engine/                    RiskManager, PositionManager tests
│   └── strategies/                Indicator formula tests, signal engine tests
│
├── scripts/                       Entry points
│   ├── run_paper.py               Paper trading (safe, no real orders)
│   ├── run_live.py                Live trading (default: dry_run=True)
│   ├── run_backtest.py            Full backtest runner
│   └── train_models.py            ML training pipeline
│
└── docs/                          Historical documentation and setup guides
```

---

## 12. Environment and Deployment

- **Python:** 3.11+
- **Dependencies:** `requirements.txt` — install with `pip install -r requirements.txt`
- **Broker:** Upstox V2/V3 SDK. Authentication requires daily 2FA (handled in `authenticate()`)
- **Secrets:** `.env` file (never commit). Required keys: `UPSTOX_API_KEY`, `UPSTOX_API_SECRET`, `UPSTOX_ACCESS_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- **Production:** AWS EC2 with Elastic IP (static IP is a SEBI compliance requirement — the broker API is whitelisted to this IP only)
- **Market hours:** 09:15–15:30 IST, Monday–Friday (NSE)
- **Strategy runs:** 09:15–15:20 IST (EOD close starts at 15:20)

### Pre-flight checklist before any live session

- [ ] `python3 -m pytest tests/ -q` — zero new failures
- [ ] Upstox access token refreshed (daily 2FA)
- [ ] `risk.yaml` — `algo_ids.pivot_cpr_strategy` is not null
- [ ] `risk.yaml` — `kill_switch_active: false`
- [ ] `live/state_manager.py` SQLite database initialized
- [ ] Telegram bot responding to `/status`
- [ ] EC2 Elastic IP is active and whitelisted with Upstox
- [ ] `dry_run=True` confirmed (or explicit human sign-off to set False)
