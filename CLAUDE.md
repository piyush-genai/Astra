# CLAUDE.md — ASTRA Engineering Guide

> This file governs Claude Code's behavior in this repository.
> Read AGENTS.md first for the full mission and governance rules.

---

## Project Identity

**ASTRA: Adaptive Strategy, Trading, Risk & Analytics**
**Baseline system**: ATLAS (Nifty 50 options, Pivot+CPR strategy)
**Broker**: Upstox V2/V3 API
**Instrument**: NSE NIFTY Index Options (weekly expiry, Tuesdays)
**Capital start**: ₹20,000–₹50,000
**Capital model**: Compounding — profits reinvested into more lots every month
**Target**: ₹15-20 crore by Dec 2028 via compounded lot scaling (aspiration, not constraint)

**Compounding engine design (validated EXP-0016/0017):**
- effective_cap = max(1, floor(max_lots_cap × dd_mult))   ← multiplier scales the CAP
- lots = min(max(1, floor(net_capital × 0.30 / premium_per_lot)), effective_cap)
  (corrected 2026-10-13 — see DECISION-008; the previous form applied dd_mult to the
   capital term and could not reproduce EXP-0017's own recorded lot counts)
- max_lots_cap starts at 10 (paper) / 20 (live); +5 every 3 consecutive profitable months AT 1.0x tier
- 30% tax reserve withheld each month from net_capital for sizing
- Drawdown management: Step-down 4-tier (validated EXP-0017, best outcome ₹50k→₹49.2L after tax)
    0-15% DD from HWM → 1.00x lots (full operation)
    15-25% DD         → 0.65x lots (caution)
    25-40% DD         → 0.35x lots (defense)
    >40% DD           → 0.12x lots (crisis minimum)

---

## Repository Layout

```
<repo-root>/                  ← clone location is not baked in anywhere
│
├── AGENTS.md              ← Agent constitution (read first)
├── CLAUDE.md              ← This file
├── ASTRA_STATUS.md        ← Current phase/gate status (update as work progresses)
│
├── core/                  ← Current engine (ATLAS production code)
│   ├── broker/            ← BrokerAdapter, UpstoxAdapter, KiteAdapter
│   ├── data/              ← Indicators, live feed, historical feed
│   ├── engine/            ← RiskManager, PositionManager, ExecutionEngine,
│   │                         BaseStrategy, StrategyRegistry
│   ├── config_loader.py
│   └── kill_switch.py
│
├── strategies/            ← PivotCprStrategy (ATLAS baseline)
├── live/                  ← Orchestrator, StateManager, Monitor
├── ml/                    ← RegimeDetector, ModelTrainer stubs (Phase 7)
├── universe/              ← Scanner, OpportunityRanker, Instruments
├── backtest/              ← Harness, WalkForward, OptionsPricer, Reports
├── scripts/               ← Paper trading, live trading, auth, analysis
│
├── src/astra/             ← NEW: ASTRA platform (built alongside core/)
│   ├── experiments/       ← Experiment registry (active)
│   ├── features/          ← Feature engineering (Phase 6)
│   ├── alpha/             ← Alpha discovery (Phase 7)
│   ├── signals/           ← Signal intelligence (Phase 8)
│   ├── risk/              ← Risk engine (Phase 11)
│   └── execution/         ← Execution plane (Phase 12)
│
├── research/
│   ├── experiments/       ← EXP-NNNN experiment records
│   ├── hypotheses/        ← Proposed but untested hypotheses
│   ├── reports/           ← Completed research reports
│   └── discoveries/       ← Confirmed alpha findings
│
├── docs/
│   ├── architecture/      ← System design documents
│   ├── research/          ← Protocol + baseline reports
│   ├── risk/              ← Risk policy + live trading gates
│   └── decisions/         ← Architecture decision log
│
├── config/                ← ACTUAL: three flat YAMLs, no env separation yet
│   ├── instruments.yaml
│   ├── risk.yaml          ← read by BOTH paper and live paths
│   └── ml.yaml
│
└── tests/                 ← 92 tests, all passing
```

**Config layout is aspirational in AGENTS.md and not yet built.** AGENTS.md section 6 names
`configs/production/risk.yaml` as the home of risk limits; no `configs/` directory exists.
`core/config_loader.py` reads the flat `config/` shown above, so there is currently no
separation between paper and production risk limits. Creating that separation is an
architecture change — AGENTS.md section 13 requires human approval before it is made.

---

## Development Commands

All commands assume the venv is active and are run from the repo root.

```bash
# Tests (always run before committing)
python3 -m pytest                    # full suite (92 tests)
python3 -m pytest tests/test_run_paper.py -v   # paper engine tests
python3 -m pytest tests/broker/ -v  # broker adapter tests

# Paper trading (dry run — no real orders)
python3 scripts/run_paper.py --strategy pivot_cpr --duration 390

# Backtest
python3 scripts/run_backtest.py

# Data integrity (run before any experiment or paper session)
python3 scripts/verify_data.py              # exit 0 only if all datasets pass
python3 scripts/verify_data.py --record-checksums   # stamp trusted files into the manifest

# Type checking (if mypy is installed)
mypy core/ strategies/ --ignore-missing-imports
```

---

## Architecture Rules (enforced)

### Import Boundaries
```
strategies/     → imports from core/data, core/engine/base_strategy ONLY
core/engine/    → imports from core/broker ONLY via ExecutionEngine
scripts/        → may import from any core/ or live/ module
src/astra/      → new home for ASTRA; imports from core/ during migration
```

**Strategies never call the broker.**
**ExecutionEngine is the ONLY module that imports from core/broker.**
**Risk limits live in config/ YAML — never hardcoded.**

### Money Safety Rules
1. `dry_run=True` is the default in ExecutionEngine — must be explicitly overridden
2. ALGO_ID (SEBI requirement, April 2026) must be set before any live order
3. Kill switch file (`KILL_SWITCH.txt`) overrides everything
4. Circuit breaker (daily loss limit) is checked before every new entry
5. Never place naked short options — only long calls and puts

---

## Current Component Status

| Component | Status | Tests |
|---|---|---|
| RiskManager | ✅ Complete | 12 tests |
| PositionManager | ✅ Complete | 7 tests |
| ExecutionEngine | ✅ Complete | - |
| UpstoxAdapter (market data) | ✅ Complete | 20 tests |
| UpstoxAdapter (execution) | ✅ Complete | 20 tests |
| StateManager (SQLite) | ✅ Complete | - |
| PaperTradingEngine | ✅ Refactored | 19 tests |
| PivotCprStrategy | ✅ Working | 27 tests |
| Experiment Registry | 🔧 Phase 0 | - |
| StrategyRegistry | ⚠️ Stubbed | - |
| LiveOrchestrator | ⚠️ 6 TODOs | - |
| ML/RegimeDetector (rule-based) | ✅ Fallback works | - |
| ML/ModelTrainer | ❌ Stubs only | - |
| Alpha Discovery | ❌ Phase 7 | - |
| Signal Intelligence | ❌ Phase 8 | - |

---

## Research Protocol (brief)

Full protocol: `docs/research/RESEARCH_PROTOCOL.md`

```
Observation → Hypothesis → Feature Definition → Label Definition →
Train/Val/Test → Baseline → Experiment → Out-of-Sample →
Walk-Forward → Monte Carlo → Stress Test → Conclusion
```

Key rules:
- **Every experiment gets an EXP-NNNN ID** (see `src/astra/experiments/registry.py`)
- **Never randomly shuffle time series** — always chronological splits
- **Record every hypothesis including failures** — selection bias accounting
- **Final test set is untouched** until walk-forward is ready

---

## Known Design Debts

1. `scripts/run_paper.py` injects `strategy._daily_ohlc` (private attr) — TODO: add `set_daily_ohlc()` public method to strategy
2. `live/orchestrator.py` has 6 `TODO Phase 1:` stubs — wire up in Phase 12
3. `core/engine/strategy_registry.py` not yet wired to PivotCprStrategy
4. Walk-forward backtest (`backtest/walk_forward.py`) not yet validated
5. ML trainer stubs (`ml/trainer.py`) — Phase 7

---

## Always Document Non-Obvious Logic

When making a non-obvious change, add a brief comment explaining WHY.
Do not document what the code does — document constraints that would surprise a reader.

Example:
```python
# cancel_order returns False (not raises) on 400 — order filled before cancel arrived
```

---

## The One Rule Above All Others

**Never distort research to hit a return target.**

If a backtest result looks too good, investigate harder — don't celebrate.
A result that survives look-ahead checks, walk-forward, Monte Carlo, and paper trading
is worth trusting. A result that only looks good in-sample is worthless.
