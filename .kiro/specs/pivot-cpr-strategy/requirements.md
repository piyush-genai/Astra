# Requirements: Pivot + CPR Confluence Strategy

## Overview
The first concrete strategy plugin for the engine (depends on `trading-engine-core`). Generates LONG/SHORT signals on Nifty 50 using multi-timeframe pivot points and Daily CPR confluence, on a 15-minute chart. This spec intentionally leaves two parameters marked **TBD** — they must be filled in (from the source video's stated rules) and calibrated via backtesting before this strategy can graduate past the engine's testing gate.

## User Story 1 — Indicator computation
As the strategy module, I want to compute Daily/Weekly/Monthly pivot levels and Daily CPR from underlying OHLC data, so that confluence zones can be detected mechanically.

**Acceptance Criteria**
- WHEN a new trading day/week/month begins THEN the module SHALL compute Pivot, R1, S1, R2, S2 for that period using the prior period's High, Low, and Close: `P=(H+L+C)/3`, `R1=2P−L`, `S1=2P−H`, `R2=P+(H−L)`, `S2=P−(H−L)`
- WHEN a new trading day begins THEN the module SHALL also compute Daily CPR: `BC=(H+L)/2`, `TC=2P−BC`, using the prior day's High and Low
- WHEN computed against the sample values from the source chart (Daily Pivot ≈ 23,910.17, Daily TC ≈ 23,932.38, Daily BC ≈ 23,887.96) THEN the unit test SHALL confirm the formulas reproduce these values from the corresponding H/L/C inputs

## User Story 2 — Confluence detection
As the strategy module, I want to flag zones where multiple pivot levels from different groups cluster together, so that only higher-conviction levels are considered for entries.

**Acceptance Criteria**
- WHEN 2 or more levels from at least 2 different groups (Daily pivot-set, Weekly pivot-set, Daily CPR) fall within `confluence_tolerance_pct` of each other THEN the module SHALL flag that price region as a confluence zone
- **TBD:** `confluence_tolerance_pct` starting value — proposed starting point 0.15%, to be calibrated against backtest results before being treated as final
- WHEN Monthly pivot levels are computed THEN they SHALL be used only as a directional bias filter (price above Monthly Pivot → long-bias only; below → short-bias only), NOT as inputs to the confluence-zone detection itself

## User Story 3 — Entry & exit signal generation
As the strategy module, I want to emit a Signal only when a confluence zone, a directional trigger, and the Monthly bias agree, so that the engine receives a fully-formed, mechanical trade decision.

**Acceptance Criteria**
- **TBD:** exact entry trigger condition (candle close beyond the zone / rejection wick / other) — must be filled in from the source video's stated rules before implementation proceeds; until specified, this module SHALL NOT emit live signals, only flagged confluence zones for manual review
- WHEN an entry trigger fires inside a confluence zone AND the Monthly bias filter agrees with the trigger's direction THEN the module SHALL emit a `Signal` with `direction`, `stop_points` (placed beyond the confluence zone by a configured margin), and `target_points` (next relevant pivot/CPR level in the trigger's direction)
- WHEN the entry trigger's direction conflicts with the Monthly bias filter THEN the module SHALL emit no signal
- **TBD:** session filter — whether this strategy trades the full session or only specific windows (e.g. avoiding the last 15 minutes before close) — must be specified before live/paper trading begins

## User Story 4 — Engine compliance
As the strategy module, I want to conform strictly to the `BaseStrategy` interface, so that it integrates with the shared engine without special-casing.

**Acceptance Criteria**
- WHEN `evaluate()` is called THEN the module SHALL return either a `Signal` or `None`, and SHALL NOT place orders, check open positions, or perform any risk calculation itself
- WHEN this strategy and any future strategy are both registered THEN neither SHALL require changes to the other's code

## Out of scope for this spec
- Contract/strike/expiry selection (handled entirely by `trading-engine-core`'s Execution Engine)
- Position sizing and concurrency rules (handled entirely by the Position Manager)
- Options-specific backtesting — this strategy is validated on underlying index points first (see design.md's testing note)
