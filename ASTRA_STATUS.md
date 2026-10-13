# ASTRA Status Dashboard

**Platform**: ASTRA — Adaptive Strategy, Trading, Risk & Analytics  
**Current Phase**: 0 — ATLAS Preservation + ASTRA Foundation  
**Last Updated**: 2026-10-10

---

## Current Phase Gate

```
[RESEARCH] → [BACKTEST] → [WALK_FORWARD] → [MONTE_CARLO] → [PAPER] → [SHADOW] → [LIVE]
                               ✓ PASSED
                                    ↑
                                  HERE
```

**Next gate**: MONTE_CARLO (EXP-0006 passed — ATR>30 confirmed OOS in 3/4 folds)

**Current best config (OOS validated)**: ATR>30 filter — avg +88.0%/month OOS vs +49.4% baseline, ₹664/trade avg

**Critical caveat**: Only 6 months of data; one clear high-vol cycle. Need 2023-2025 data before production confidence.

**VALIDATED signal**: P70_L40d adaptive ATR filter (current ATR > 70th pctile of trailing 40-day ATR). Confirmed OOS: 67% (8/12 months 2025), avg +74.4%/month vs +56.3% baseline, ₹497/trade avg. Ready for Monte Carlo.

**Phase gate**: WALK_FORWARD ✓ → MONTE_CARLO ✓ → OPTION_SIGNALS ✓ → PAPER_TRADING (next)

**Reproduction audit 2026-10-13 (EXP-0018)**: the 2023-2025 NIFTY dataset was lost (gitignored,
absent from every clone) and has been re-fetched, verified against 11 integrity checks, and
checksummed. EXP-0009/0010/0011/0012 were re-run from scratch on Python 3.13 / numpy 2.5.4 and
**reproduce exactly** — all six filter configs, all three regime breakdowns, the month-by-month
2025 OOS table, and the full Monte Carlo percentile distribution. P70_L40d is auditable again.

**Still blocked**: `india_vix_daily_20230101_to_20251231.csv` has no fetcher and is still
missing, so EXP-0013 through EXP-0017 — VIX IV pricing, VIX tilt sizing, the compounding
engine, and the step-down tiers — remain unreproducible. The ₹49.2L projection sits on that
side of the line, as does the unresolved 6x conflict in EXP-0016.

**Validated strategy stack (ready for paper trading):**
1. Signal: PivotCPR momentum breakout (ATLAS baseline)
2. Regime filter: P70_L40d adaptive ATR (EXP-0010/0011)
3. IV model: VIX×1.1 dynamic pricing (EXP-0014)
4. Position sizing: VIX tilt — sweet spot 1.5x, danger zone 0.5x, else 1x (EXP-0015)

**Monte Carlo summary** (10,000 sims, P70_L40d, ₹20k start):
- Median annual return: +777% | 5th pctile: +354% | P(loss): 1.6%
- Median max drawdown: 29.3% | 95th pctile drawdown: 75.6% (CAUTION)
- Sharpe: 3.00 | Profit factor: 1.89 | Win rate: 30% (avg win 4.4x avg loss)
- Realistic live return estimate: 150-400%/year (after IV, slippage, spread corrections)
- Minimum recommended capital: ₹50,000

---

## Phase 0 Checklist

### Governance
- [x] AGENTS.md created
- [x] CLAUDE.md updated
- [x] DECISION_LOG.md created
- [x] LIVE_TRADING_GATES.md created
- [x] RESEARCH_PROTOCOL.md created
- [x] ATLAS_BASELINE_REPORT.md created

### Infrastructure
- [x] Experiment Registry (`src/astra/experiments/registry.py`)
- [x] ASTRA package scaffold (`src/astra/`)
- [x] Research directory structure (`research/experiments/`)
- [ ] Data versioning (Phase 2)
- [ ] Feature store (Phase 6)

### Baseline
- [x] **EXP-0001**: Reproduce ATLAS backtest result — COMPLETED (2026-10-10)
- [x] **EXP-0002**: March 2026 forensic analysis — COMPLETED (2026-10-10)
- [x] git tag: `atlas-baseline-v1`

### Tests
- [x] 92 tests passing (0 failures)

---

## Active Experiments

| ID | Hypothesis | Status | Priority | Result |
|---|---|---|---|---|
| EXP-0001 | Reproduce ATLAS baseline | COMPLETED | CRITICAL | +376% (₹95k) — 2 bugs found, baseline corrected |
| EXP-0002 | March 2026 forensic analysis | COMPLETED | HIGH | Near-expiry gamma + daily range > 300 pts |
| EXP-0003 | Range filter: prior-day range > 300 pts | COMPLETED | HIGH | +142% (better avg, but too aggressive) |
| EXP-0004 | Near-expiry sub-strategy: Monday afternoon only | COMPLETED | HIGH | 13 trades too few; use as sizing signal instead |
| **EXP-0005** | **ATR>30 regime filter** | **COMPLETED** | **HIGH** | **+938% vs +376% baseline — major alpha found** |
| **EXP-0006** | **Walk-forward: validate ATR filter OOS** | **COMPLETED** | **CRITICAL** | **PASSED 3/4 folds — OOS avg +88% vs +49% baseline** |
| EXP-0007 | Near-expiry AFTERNOON position sizing on ATR>30 | COMPLETED | HIGH | REJECTED — ATR filter absorbs near-expiry edge; inconsistent 3/6 months |
| EXP-0008 | DTE bucket filtering and sizing within ATR>30 | COMPLETED | HIGH | REJECTED — DTE effects regime-conditional, not structural; DATA-001 blocked |
| **EXP-0009** | **Multi-year ATR>30 validation (2023-2025, 36 months)** | **COMPLETED** | **CRITICAL** | **FAILED 56% (needed 65%) — fixed threshold doesn't generalize across regimes** |
| **EXP-0010** | **Adaptive ATR percentile filter** | **COMPLETED** | **CRITICAL** | **ALL 6 configs PASS — best P70_L40d: 72% (26/36), avg +52.7%/mo (IN-SAMPLE)** |
| **EXP-0011** | **Walk-forward: P70_L40d on 2025 OOS** | **COMPLETED** | **CRITICAL** | **PASSED 8/12 (67%) — OOS avg +74.4%/mo vs +56.3% baseline. VALIDATED.** |
| **EXP-0012** | **Monte Carlo stress test (10,000 sims)** | **COMPLETED** | **CRITICAL** | **PASSED — Sharpe 3.00, P(ruin)=17.8%, P(loss)=1.6%. Next gate: PAPER** |
| EXP-0013 | India VIX as binary entry filter on P70_L40d | COMPLETED | HIGH | REJECTED — VIX filter reduces monthly return (22% beat rate, needed 65%). PARTIAL SIGNAL: VIX 60-75th pctile is danger zone (₹47/trade); VIX 50-60th is sweet spot (₹547/trade). Use for sizing not filtering. |
| **EXP-0014** | **Dynamic VIX-derived IV vs flat 14%** | **COMPLETED** | **HIGH** | **EXP-0012 CAVEAT-3 REVISED: flat IV only inflated by 2-11% (not 20-40%). Intraday trades not exposed to overnight IV change. VIX×1.1 recommended. Sharpe stays 2.87.** |
| **EXP-0015** | **VIX bucket position sizing** | **COMPLETED** | **HIGH** | **ALL 4 configs PASS. Tilt (sweet 1.5x + danger 0.5x): Sharpe 2.93 (+0.06), +6% P&L, max DD 33.7% (was 39.4%). Gradient: +15.6% P&L. Kelly confirms danger zone (0.026) vs sweet spot (0.181).** |
| **EXP-0016** | **Compounded equity (tax + slippage + brake)** | **COMPLETED** | **CRITICAL** | **₹50k → ₹10L (after tax, 3yr). Cliff-edge brake trapped at 1 lot for 22 months. Fix needed: gradual lot reduction.** |
| **EXP-0017** | **Drawdown-adaptive lot sizing** | **COMPLETED** | **CRITICAL** | **Step-down 4-tier wins: ₹50k → ₹49.2L (+9740%) after 30% tax, 3yr. 72% better than cliff. RECOMMENDED for paper trading.** |

---

## Component Status

### Production-ready (ATLAS baseline)
| Component | Status |
|---|---|
| RiskManager | ✅ 12 tests |
| PositionManager | ✅ 7 tests |
| ExecutionEngine | ✅ Wired |
| UpstoxAdapter (market + execution) | ✅ 20 tests |
| StateManager (SQLite) | ✅ WAL mode |
| PaperTradingEngine | ✅ 19 tests |
| PivotCprStrategy | ✅ 27 tests |

### In progress
| Component | Status | Phase |
|---|---|---|
| Experiment Registry | ✅ Complete | 0 |
| LiveOrchestrator | ⚠️ 6 TODOs | 12 |
| StrategyRegistry | ⚠️ Stubbed | 12 |

### Not started
| Component | Phase |
|---|---|
| Feature Engineering | 6 |
| Alpha Discovery (ML) | 7 |
| Signal Intelligence | 8 |
| Decision Engine | 9 |
| Portfolio Engine | 10 |
| Multi-instrument support | 16+ |

---

## Development Roadmap

| Phase | Focus | Gate |
|---|---|---|
| **0** | ATLAS preservation + ASTRA foundation | Now |
| 1 | Research/Experiment infrastructure | EXP-0001 complete |
| 2 | Data Plane (ingestion, validation, versioning) | Clean data pipeline |
| 3 | Backtest hardening (costs, slippage, contracts) | Realistic execution model |
| 4 | ATLAS forensic analysis (March explanation) | EXP-0002 conclusion |
| 5 | Walk-forward + Monte Carlo baseline | Gate 3 pass |
| 6 | Feature Engineering (price, vol, options, structure) | Feature store live |
| 7 | Alpha Discovery (statistical + ML) | First EV+ alpha found |
| 8 | Signal Intelligence (direction, probability, setup) | Signal quality > baseline |
| 9 | Decision Engine | Trade selection validated |
| 10 | Portfolio Engine | Capital allocation working |
| 11 | Risk Engine (enhanced) | All gates configurable |
| 12 | Paper Trading (wired orchestrator) | Gate 5 pass |
| 13 | Shadow Trading | Gate 6 pass |
| **14** | **First live capital (NIFTY)** | **Gate 7 pass + human approval** |
| 15 | NIFTY scaling | Consistent live performance |
| 16 | SENSEX | Instrument model validated |
| 17 | Liquid equity options | Universe filtering working |
| 18 | Multi-strategy portfolio | Portfolio engine live |
| 19+ | Agentic research, continuous adaptation | Long-term roadmap |

---

## Key Research Questions

1. **Is the ATLAS backtest result reproducible?** (EXP-0001)
2. **Why did March generate 50% of total profit?** (EXP-0002)
3. **Is the edge regime-dependent?** (Post EXP-0002)
4. **What features predict the favorable regime?** (Phase 6-7)
5. **Can we identify high-alpha periods in advance?** (Phase 7-8)
6. **Does trading less (25 high-quality trades) outperform 100 trades?** (Phase 9)

---

## Capital Goal Context

**Aspiration**: ₹15-20 Crore by Dec 2028  
**Starting capital**: ₹20,000–₹50,000  
**Current approach**: Compound capital — reinvest profits into more lots as capital grows

**❌ REFUTED AND REPLACED (2026-10-13, EXP-0019 FINDING-1).** The table formerly here claimed
₹88,48,311 gross / ~₹60 lakh after tax for the ₹50k scenario, and listed a ₹20k/50-lot case.
EXP-0016 was re-run against the restored, checksummed dataset and **neither holds**. The real
figures, reproduced from `scripts/exp_0016_compounded_equity.py`:

| Start | Lot cap | 3-yr gross | Tax reserve | **Net after tax** | Return |
|---|---|---|---|---|---|
| ₹20,000 | 10 lots | ₹10,40,333 | ₹4,51,597 | **₹5,88,737** | +2,844% |
| ₹50,000 | 20 lots | ₹16,24,817 | ₹6,20,639 | **₹10,04,178** | +1,908% |
| ₹20,000 | 25 lots | ₹16,90,238 | ₹6,75,556 | **₹10,14,682** | +4,973% |

So the ₹50k scenario yields ~₹10 lakh, confirming line 89 of this file, and the old table
overstated it by about 6x. The third scenario is 25 lots, not 50 — there is no 50-lot run.
These are the **cliff-brake** figures; EXP-0017's step-down design supersedes them, which is
why its ₹49.2L result is the one to cite.

**The compounding engine (how lots scale with capital) — Step-down 4-tier (validated EXP-0017):**
```
net_capital  = gross_capital - tax_reserve
dd           = max(0, (HWM - net_capital) / HWM)   ← high-water-mark tracking
dd_mult      = 1.00 if dd < 0.15        ← normal, full operation
             = 0.65 if 0.15 ≤ dd < 0.25 ← caution
             = 0.35 if 0.25 ≤ dd < 0.40 ← defense
             = 0.12 if dd ≥ 0.40         ← crisis minimum
effective_cap = max(1, floor(max_lots_cap × dd_mult))  ← dd_mult scales the CAP, not capital
lots          = min(max(1, floor(net_capital × 0.30 / premium_per_lot)), effective_cap)
max_lots_cap = 10 (paper) / 20 (live); +5 every 3 profitable months AT dd_mult=1.00
tax_reserve  = 30% of each month's net profit withheld (not available for sizing)
```
Corrected 2026-10-13 (DECISION-008, EXP-0019 FINDING-2). The previous form applied dd_mult to
the capital term; that clamps to the unscaled cap and cannot reproduce EXP-0017's own recorded
lot counts (0.35x at a base of 20 gives 7 lots, which only the cap-scaled form produces).
```
```

**Compounded projection (after 30% tax, slippage, step-down brake, 3 years 2023-2025):**
- ₹20,000 start → ₹48,09,113 net (+23,946%)
- ₹50,000 start → ₹49,20,067 net (+9,740%)

**⚠️ These figures describe a configuration that has never been permitted to run** (EXP-0020).
They assume 30% capital deployment and lot caps growing to 35, while `config/risk.yaml`
permits 25% and `hard_cap_lots: 10`. Under the limits as configured the three-year result is
**₹28,23,528 from ₹50k** — 42.6% lower. The entire gap is the 10-lot cap; the 25% deployment
limit costs nothing. A staged 35-lot ceiling returns ₹41,55,673 at 23.7% max drawdown versus
the validated config's 31.9%. See DECISION-010 for the pending limit decision.

**Path to ₹15-20 crore:**
- Requires starting capital ₹5-10 lakh OR ₹50k + 3 years of reinvestment + lot cap of 100+
- ₹15 crore from ₹50k requires ~180x return, achievable in theory at 50+ lots over 3 years
- BUT: every drawdown month at large capital is psychologically severe (May 2024 = -30.8%)
- Strategy must be validated in paper trading for 3 months before any capital increase

Monthly return scenarios (at scale):
| Scenario | Monthly Return | Notes |
|---|---|---|
| Poor | < 3% | ATR regime not active — reduce exposure |
| Good | 5–15% | Standard operating mode |
| Excellent | 15–40% | High-regime months (Apr 2025: +28.5%) |
| Extraordinary | > 40% | Investigate — could be data anomaly |

**Do not optimize ASTRA to hit the ₹15-20Cr target. Build the research machine.
The compounding happens automatically from a working strategy — force it and you distort the research.**
