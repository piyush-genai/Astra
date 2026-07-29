---
inclusion: always
---

# Project Structure

## Directory layout
```
/src
  /engine/              # Core, strategy-agnostic infrastructure
    strategy_registry.py
    position_manager.py
    execution_engine.py
    risk_manager.py
    base_strategy.py     # BaseStrategy interface + Signal dataclass
  /strategies/           # One file per strategy — each is a plug-in
    pivot_cpr_strategy.py
    # future strategies added here, one file each
  /data/
    historical_feed.py
    live_feed.py
    indicators.py         # shared formula library (pivots, CPR, etc.)
  /broker/
    base_adapter.py       # Broker Adapter interface
    upstox_adapter.py     # primary adapter — see tech.md
    kite_adapter.py         # optional secondary/fallback adapter, same interface
  /backtest/
    harness.py
  /config/
    instruments.yaml       # lot sizes, expiry weekdays, per-instrument config
    risk.yaml               # risk-per-trade, circuit breaker thresholds, concurrency limits
/tests
  /engine/
  /strategies/
/scripts
  run_backtest.py
  run_paper.py
  run_live.py
.kiro/
```

## Naming conventions
- Strategy files: `<name>_strategy.py`, exposing exactly one class named `<Name>Strategy` that subclasses `BaseStrategy`.
- Every strategy class implements `evaluate(self, market_data) -> Optional[Signal]` and nothing else public-facing — strategies never place orders, touch the broker, or manage positions directly.
- Config values are referenced by name from `config/*.yaml`, never duplicated as literals inside strategy or engine code.

## Import patterns
- Strategies import from `src.data.indicators` for shared formulas and from `src.engine.base_strategy` for the interface — strategies never import from `src.broker` or `src.engine.execution_engine` directly.
- Only `src/engine/execution_engine.py` is allowed to import from `src/broker/`.

## Architectural decision: engine/strategy separation
This split exists specifically because the user runs multiple strategies concurrently against shared capital and shared risk limits. Any code review or generated code that has a strategy file directly placing orders, tracking its own positions, or checking its own risk limits should be treated as an architecture violation — that logic belongs exclusively in `src/engine/`, shared by all strategies. See `.kiro/specs/trading-engine-core/design.md` for the full rationale.
