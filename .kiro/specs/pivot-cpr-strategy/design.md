# Design: Pivot + CPR Confluence Strategy

## Module shape
`src/strategies/pivot_cpr_strategy.py` — a single class `PivotCprStrategy(BaseStrategy)`. All indicator math lives in `src/data/indicators.py` as shared, reusable functions (`compute_pivot_set(h, l, c)`, `compute_cpr(h, l, c)`), since future strategies may want the same formulas.

## Indicator layer
```python
def compute_pivot_set(high, low, close):
    p = (high + low + close) / 3
    return {
        "pivot": p,
        "r1": 2*p - low,   "s1": 2*p - high,
        "r2": p + (high - low), "s2": p - (high - low),
    }

def compute_cpr(high, low, close):
    p = (high + low + close) / 3
    bc = (high + low) / 2
    tc = 2*p - bc
    return {"pivot": p, "bc": bc, "tc": tc}
```
Daily/Weekly/Monthly pivot sets are computed from the respective prior period's H/L/C, resampled from the underlying 15-minute feed.

## Confluence detection algorithm
1. On each new bar, gather all currently-active levels: Daily set (5), Weekly set (5), Daily CPR (BC, TC — Pivot already counted in Daily set) = 12 levels total (Monthly deliberately excluded here — see below).
2. Group levels by originating indicator group (Daily, Weekly, CPR).
3. For each level, check whether at least one level from a *different* group lies within `confluence_tolerance_pct` of it (as a % of current price). If yes, both levels are part of a confluence zone; record the zone's price range.
4. Monthly Pivot is computed separately and used only to set `monthly_bias = "LONG" if price > monthly_pivot else "SHORT"` — it is never part of the confluence-zone grouping in step 1, per the simplification agreed on with the operator (17 raw levels → 12 for zone detection + Monthly as a pure bias filter).

## Entry/exit logic (pending TBD items)
Until the entry trigger (User Story 3) is specified, `evaluate()` should be implemented in two stages so partial progress is still useful:
- **Stage 1 (buildable now):** compute indicators, detect confluence zones, compute monthly_bias, and expose these as inspectable outputs (e.g. via logging or a debug dashboard) — this alone lets the operator visually/statistically sanity-check zone detection against the source chart before any trigger logic is added.
- **Stage 2 (blocked on TBD):** once the entry trigger and session filter are specified, implement full `Signal` emission per User Story 3.

Do not guess at the entry trigger to unblock Stage 2 — an invented trigger would produce backtest results that validate nothing real. Surface this as a blocking dependency rather than filling it with a plausible-sounding default.

## Testing approach specific to this strategy
1. **Formula unit tests** against the known sample values (see requirements.md User Story 1) — cheap, exact, no market data needed.
2. **Confluence detection unit tests** with synthetic level sets at known distances, verifying the tolerance boundary behaves as configured.
3. **Backtest on underlying index data only** (once Stage 2 is unblocked) — this validates the signal's edge in index points, independent of options mechanics.
4. **Options P&L is approximated, not backtested precisely** — historical intraday option-chain data isn't reliably available. Once the index-point backtest passes its kill-criteria, model expected option P&L via Delta × points-moved minus an estimated theta drag for the typical holding period, as a rough overlay — then validate for real via live paper-trading in `trading-engine-core`'s Execution Engine, per the engine's testing gate.

## Dependency on trading-engine-core
This strategy cannot be executed live or in paper mode until `trading-engine-core`'s `BaseStrategy` interface, `PositionManager`, and `ExecutionEngine` exist. It CAN be developed and unit/backtest-tested against a lightweight stub of `BaseStrategy` in isolation — do not block strategy development entirely on the engine spec being finished first, but do not connect it to real/paper order placement until the engine spec's tasks are complete.
