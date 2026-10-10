# ATLAS Baseline Report

**Version**: atlas-baseline-v1  
**Date**: 2026-10-10  
**Status**: Active baseline — DO NOT modify strategy parameters without a new EXP-NNNN

---

## 1. System Identity

| Item | Value |
|---|---|
| System name | ATLAS |
| Strategy | Pivot CPR + Momentum Breakout |
| Strategy ID | `pivot_cpr_strategy` |
| Instrument | NIFTY 50 Index Options (NSE) |
| Timeframe | 5-minute bars |
| Direction | Long-only (buy calls / buy puts — never write options) |
| Lot size | 65 |
| Strike step | 50 |
| Weekly expiry | Tuesday |
| Broker | Upstox V2/V3 API |

---

## 2. Strategy Logic Summary

### 2.1 Regular Breakout (4.5% of trades, 30.5% win rate)
1. Map pivot/CPR levels from prior day's OHLC
2. Detect confluence zone (2+ levels within 0.18% tolerance, from ≥2 timeframes)
3. Bar N closes beyond zone → breakout detected
4. Bar N+1 also closes beyond → confirmed
5. Enter at bar N+2 open (buy Call if up, buy Put if down)

### 2.2 Momentum Breakout (95.5% of trades, 20% win rate)
Immediate entry (no confirmation wait) when ≥2 of 3 conditions met:
- Range explosion: candle range ≥ 1.8× 10-bar average range
- Strong body: body ≥ 50% of total range
- Deep penetration: move ≥ 1.5× zone width beyond zone

### 2.3 Exit Rules
1. **Stop loss** (96.5% of exits): initial stop = zone edge or breakout candle extreme
2. **Trailing stop**: after 2 bars, trail to 2-bar-back candle high/low (never loosens)
3. **Structural invalidation**: close back through the broken zone → exit immediately
4. **EOD**: flat by 15:25

### 2.4 Cooldown
Zone locked for 15 minutes after any exit from it.

---

## 3. Position Sizing

```
Lots = MIN(
  Capital × 2% / (Premium × Lot Size),    # risk limit
  Capital × 10% / (Premium × Lot Size),   # capital deployment
  10                                        # hard cap
)
Floor: 1 lot minimum
```

---

## 4. Transaction Costs (included in all backtests)

| Cost | Amount |
|---|---|
| Brokerage | ₹40/lot (₹20 entry + ₹20 exit) |
| STT | 0.15% × premium × lot_size |
| Other (SEBI, GST) | ₹5/lot |

---

## 5. Reported Backtest Performance (user-reported, Feb–Jul 2026)

> ⚠️ These numbers are USER-REPORTED and have not been independently reproduced from data.
> Reproduction task is tracked as EXP-0001.

| Metric | Value |
|---|---|
| Starting capital | ₹20,000 |
| Ending capital | ₹8,25,266 |
| Total return | +4,026% |
| Period | Feb 1 – Jul 31, 2026 (6 months) |
| Total trades | 1,302 |
| Win rate | 25.4% |
| Avg trades/day | 9.9 |

### Monthly breakdown
| Month | Start | End | Return | Note |
|---|---|---|---|---|
| Feb 2026 | ₹20,000 | ₹73,257 | +266% | |
| Mar 2026 | ₹73,257 | ₹3,29,558 | +350% | **Outlier — investigate** |
| Apr 2026 | ₹3,29,558 | ₹4,82,695 | +46% | |
| May 2026 | ₹4,82,695 | ₹5,87,611 | +22% | |
| Jun 2026 | ₹5,87,611 | ₹7,65,254 | +30% | |
| Jul 2026 | ₹7,65,254 | ₹8,25,266 | +8% | Return slowdown |

**Critical observation**: March 2026 generated ~₹2,56,000 (50%+ of total profit in one month).
**Primary research question**: What was different about March?

---

## 6. Known Risk Factors

| Risk | Detail |
|---|---|
| The −₹131 incident | AI "optimized" strategy parameters → profit dropped. Lesson: never modify locked parameters without validation. |
| Backtest inflation risk | +4,026% in backtest may include look-ahead or unrealistic execution |
| Regime dependency | July return (+8%) suggests edge may be regime-dependent |
| Capital compounding | Monthly compounding dramatically amplifies both gains AND losses |
| Momentum trades (95.5%) | High volume, 20% win rate — small edge, high transaction cost sensitivity |
| March outlier | Strategy may have concentrated risk in one favorable regime period |

---

## 7. Code Location

| Component | File |
|---|---|
| Strategy | `strategies/pivot_cpr_strategy.py` |
| Indicators (zones, pivots) | `core/data/indicators.py` |
| Options pricer | `backtest/options_pricer.py` |
| Backtest harness | `backtest/harness.py` |
| Paper trading engine | `scripts/run_paper.py` |
| Risk manager | `core/engine/risk_manager.py` |
| Position manager | `core/engine/position_manager.py` |
| Execution engine | `core/engine/execution_engine.py` |
| Upstox adapter | `core/broker/upstox_adapter.py` |
| State manager | `live/state_manager.py` |
| Config | `config/instruments.yaml`, `config/risk.yaml` |

---

## 8. Reproduction Status

- [ ] **EXP-0001**: Reproduce reported Feb–Jul 2026 backtest result
- [ ] Verify cost assumptions match reported figures
- [ ] Verify contract selection logic (strike, expiry)
- [ ] Verify capital compounding mechanism
- [ ] Identify any look-ahead bias risks

See `research/experiments/EXP-0001.json` for experiment record.

---

## 9. What Must NOT Change Without a New Experiment

The following parameters are LOCKED until replaced by a validated superior config:

```yaml
tolerance_pct: 0.18
min_levels_for_confluence: 2
momentum_enabled: true
momentum_body_pct: 0.50
momentum_accel_multiplier: 1.8
momentum_min_criteria: 2
lot_size: 65
strike_step: 50
weekly_expiry_weekday: 1  # Tuesday
max_loss_per_trade_pct: 2.0
max_capital_deployed_pct: 10.0
hard_cap_lots: 10
daily_loss_limit_pct: varies by session
cooldown_minutes: 15
eod_exit_time: "15:25"
```

Changing any of these requires: new EXP-NNNN + walk-forward validation + human approval.
