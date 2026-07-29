# Tasks: Pivot + CPR Confluence Strategy

- [ ] 1. Implement `compute_pivot_set()` and `compute_cpr()` in `src/data/indicators.py`
  - [ ] 1a. Unit test against the sample values in requirements.md User Story 1
- [ ] 2. Implement resampling of the 15m underlying feed into Daily/Weekly/Monthly prior-period H/L/C for indicator computation
- [ ] 3. Implement confluence-zone detection per design.md algorithm, with `confluence_tolerance_pct` read from strategy config (starting value 0.15%, marked clearly as TBD/calibratable)
  - [ ] 3a. Unit test with synthetic level sets at known distances (inside tolerance, outside tolerance, boundary case)
- [ ] 4. Implement `monthly_bias` computation and confirm it is excluded from confluence-zone grouping
- [ ] 5. Implement Stage 1 of `evaluate()` — indicators + zone detection + bias, exposed via debug logging, no Signal emission yet
- [ ] 6. **BLOCKED — requires operator input:** specify exact entry trigger condition and session filter (from source video), update requirements.md User Story 3 TBD items before proceeding
- [ ] 7. Implement Stage 2 of `evaluate()` — full Signal emission once task 6 is unblocked
- [ ] 8. Backtest harness: run Stage 2 against historical Nifty 15m data, report standard metrics (win rate, profit factor, max drawdown, Sharpe) including realistic transaction costs
- [ ] 9. Compare backtest results against the kill-criteria defined in the operator's build plan; reject/redesign if not met, do not retune on the same data until it passes
- [ ] 10. Build the approximate options P&L overlay (Delta × points moved, minus estimated theta) as a separate reporting layer on top of the index-point backtest — clearly labeled as an approximation
- [ ] 11. Register `PivotCprStrategy` with the Strategy Registry from `trading-engine-core` once that spec's tasks are complete, and proceed to live paper-trading per the engine's testing gate
