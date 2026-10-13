# ASTRA Handoff Document

**Date**: 2026-10-10  
**Branch**: main  
**Remote**: astra → piyush-genai/Astra.git  
**Last commit**: see `git log --oneline -5`

---

## 1. Purpose

This document enables any engineer (or future Claude Code session) to resume ASTRA work immediately without re-reading the full commit history or experiment records. It captures the current state of research, the validated strategy stack, what was tried, what was rejected, and what comes next.

ASTRA is a research platform for compounded-capital algorithmic trading on NSE NIFTY Index weekly options. The baseline trading system is ATLAS (PivotCPR momentum breakout). ASTRA wraps it with regime filtering, dynamic pricing, position sizing, and a compounding engine.

**Mission**: Build a research machine. Let the compounding happen from a working strategy. Do not distort research to hit a return target.

---

## 2. Current State

**Phase gate**: `RESEARCH → BACKTEST → WALK_FORWARD ✓ → MONTE_CARLO ✓ → OPTION_SIGNALS ✓ → PAPER_TRADING ← NEXT`

**Validated strategy stack** (ready for paper trading):
1. Signal: PivotCPR momentum breakout (ATLAS baseline)
2. Regime filter: P70_L40d adaptive ATR — current 10-bar ATR > 70th pctile of trailing 3000-bar ATR
3. IV pricing: VIX×1.1 dynamic (not flat 14%) — backward-compatible `iv_fn` param in OptionsPricer
4. Position sizing: VIX tilt — sweet spot (50-60th pctile) 1.5x, danger zone (60-75th pctile) 0.5x, else 1x
5. Drawdown management: Step-down 4-tier lot multiplier (EXP-0017 winner)

**Compounding engine formula (validated EXP-0017):**
```
net_capital  = gross_capital - tax_reserve
dd           = max(0, (HWM - net_capital) / HWM)
dd_mult      = 1.00 if dd < 0.15
             = 0.65 if 0.15 ≤ dd < 0.25
             = 0.35 if 0.25 ≤ dd < 0.40
             = 0.12 if dd ≥ 0.40
lots         = min(floor(net_capital × 0.30 / premium_per_lot × dd_mult), max_lots_cap)
max_lots_cap starts 10 (paper) / 20 (live); +5 every 3 consecutive profitable months AT dd_mult=1.00 tier only
tax_reserve  = 30% of each profitable month's P&L withheld (NOT available for lot sizing)
```

**3-year backtest result (after 30% tax + slippage, 2023-2025):**
- ₹20,000 start → ₹48,09,113 net (+23,946%)
- ₹50,000 start → ₹49,20,067 net (+9,740%)

**Test suite**: 92 tests, all passing.

---

## 3. Reproduction

### Environment setup

```bash
cd <repo-root>                     # the clone directory; no absolute path is baked in anymore
python3.13 -m venv .venv           # any Python 3.11+ (AGENTS.md section 10)
source .venv/bin/activate
pip install -r requirements.txt
```

On Python 3.13, `requirements.txt` resolves numpy to 2.x — 1.26.4 has no cp313 wheels and
cannot build from source. **The version boundary introduces no drift**: EXP-0001, 0009, 0010,
0011 and 0012 all reproduce bit-identically under numpy 2.5.4 (EXP-0018 FINDING-2).
EXP-0013..0017 remain unverified, pending the VIX file rather than for any version reason.

### Required environment variables (names only — never commit values)

**Corrected 2026-10-13.** The list previously given here named variables that no Python file
reads (`UPSTOX_API_KEY`, `UPSTOX_API_SECRET`, `UPSTOX_REDIRECT_URI`) and pointed at
`scripts/auth_upstox.py`, which does not exist — the script is `scripts/auth.py`. Copy
`.env.example` instead; it is generated from the actual source and annotates which script
consumes each name.

```
UPSTOX_ANALYTICS_TOKEN       # scripts/data_001_fetch_historical.py — rebuilds the 2023-2025 CSV
UPSTOX_LIVE_API_KEY          # scripts/auth.py OAuth flow
UPSTOX_LIVE_API_SECRET
UPSTOX_LIVE_REDIRECT_URI
UPSTOX_ACCESS_TOKEN          # refreshed daily by scripts/auth.py
UPSTOX_SANDBOX_API_KEY       # scripts/run_backtest.py, export_ohlcv_data.py, test_sandbox.py
UPSTOX_SANDBOX_API_SECRET
UPSTOX_SANDBOX_REDIRECT_URI
UPSTOX_SANDBOX_ACCESS_TOKEN
TELEGRAM_BOT_TOKEN           # scripts/telegram_bot.py, live/monitor.py
TELEGRAM_CHAT_ID
```

`ALGO_ID` is **not** an environment variable — nothing reads it. The SEBI Algo-ID belongs in
`config/risk.yaml` under `algo_ids:`, where `pivot_cpr_strategy` is still `null`. Setting an
`ALGO_ID` env var would give no compliance whatsoever; see RISK-4.

These are loaded from `.env` (gitignored) by each script's own `load_env()`, not by
`core/config_loader.py` — that module reads only the YAML in `config/`.

### Required local data files (gitignored — not in repo)

```
data/live_data/nifty_5min_20230101_to_20251231.csv
data/live_data/india_vix_daily_20230101_to_20251231.csv
```

Both files must exist for experiments EXP-0009 through EXP-0017 to run.

### Run the full backtest suite

```bash
python3 -m pytest                  # 92 tests
python3 scripts/run_backtest.py    # full ATLAS baseline
```

### Rerun EXP-0017 (drawdown-adaptive lot sizing — the final compounding experiment)

```bash
cd <repo-root>
python3 -u scripts/exp_0017_drawdown_management.py
```

Expected output: 5 configs (A_cliff through E_sigmoid), ₹20k and ₹50k start each, monthly logs, and a summary table. Runtime: ~4-6 minutes. Winner: D_steps (Step-down 4-tier).

### Rerun any earlier experiment

```bash
python3 -u scripts/exp_0013_vix_filter.py
python3 -u scripts/exp_0014_dynamic_iv.py
python3 -u scripts/exp_0015_vix_sizing.py
python3 -u scripts/exp_0016_compounded_equity.py
python3 -u scripts/exp_0017_drawdown_management.py
```

All scripts are self-contained and must be run from the repo root (their data paths are
relative to the working directory). They derive the repo root from `__file__` for sys.path,
so the clone can live anywhere — up to 2026-10-13 all 17 hardcoded `/workshop/atlas`, which
made every one of them fail on import in a fresh clone.

---

## 4. Experiment Log

| ID | Hypothesis | Status | Result |
|---|---|---|---|
| EXP-0001 | Reproduce ATLAS baseline | COMPLETED | +376% (₹95k from ₹20k). 2 bugs found and corrected. |
| EXP-0002 | March 2026 forensic analysis | COMPLETED | Near-expiry gamma + daily range > 300 pts explains outlier. |
| EXP-0003 | Range filter: prior-day range > 300 pts | COMPLETED | REJECTED. Aggressive filter; +142% but degrades other months. |
| EXP-0004 | Near-expiry sub-strategy: Monday afternoon only | COMPLETED | REJECTED. 13 trades too few; use as sizing signal not filter. |
| EXP-0005 | ATR>30 regime filter | COMPLETED | MAJOR ALPHA. +938% vs +376% baseline (fixed ATR threshold). |
| EXP-0006 | Walk-forward: validate ATR filter OOS | COMPLETED | PASSED 3/4 folds. OOS avg +88%/month vs +49% baseline. |
| EXP-0007 | Near-expiry afternoon sizing on ATR>30 | COMPLETED | REJECTED. ATR filter already absorbs near-expiry edge. |
| EXP-0008 | DTE bucket filtering on ATR>30 | COMPLETED | REJECTED. DTE effects regime-conditional, not structural. |
| EXP-0009 | Multi-year ATR>30 validation (2023-2025, 36 months) | COMPLETED | FAILED. 56% beat rate (needed 65%). Fixed threshold doesn't generalize. |
| EXP-0010 | Adaptive ATR percentile filter | COMPLETED | PASSED. All 6 configs pass. Best: P70_L40d — 72% (26/36 months). |
| EXP-0011 | Walk-forward: P70_L40d on 2025 OOS | COMPLETED | PASSED 8/12 months (67%). OOS avg +74.4%/month vs +56.3% baseline. VALIDATED. |
| EXP-0012 | Monte Carlo stress test (10,000 sims) | COMPLETED | PASSED. Sharpe 3.00, P(loss)=1.6%, P(ruin)=17.8%. Next gate: PAPER. |
| EXP-0013 | India VIX as binary entry filter | COMPLETED | REJECTED as filter (22% beat rate). VIX 50-60th pctile = sweet spot (₹547/trade avg); VIX 60-75th = danger zone (₹47/trade). Use for sizing. |
| EXP-0014 | Dynamic VIX-derived IV vs flat 14% | COMPLETED | ACCEPTED. VIX×1.1 reduces P&L by only 6.9% (not 20-40%). Sharpe stays 2.87. Fully intraday trades not exposed to overnight IV change. |
| EXP-0015 | VIX bucket position sizing | COMPLETED | PASSED. All 4 non-flat configs pass. Tilt (1.5x sweet + 0.5x danger): Sharpe 2.93, +6% P&L, max DD 33.7%. Kelly: danger=0.026 vs sweet=0.181. |
| EXP-0016 | Compounded equity (tax + slippage + cliff brake) | COMPLETED | ₹50k → ₹10L after tax. CRITICAL BUG: cliff brake triggered Dec 2023, locked at 1 lot forever. Step-down needed. |
| EXP-0017 | Drawdown-adaptive lot sizing | COMPLETED | **WINNER: D_steps (Step-down 4-tier)**. See detail below. |

### EXP-0017 Detail — Exact Numbers

**Setup**: 1,522 trades, P70_L40d + VIX×1.1 IV + VIX tilt. 30% tax, slippage. ₹20k and ₹50k starts. 5 drawdown functions tested.

| Config | Function | ₹20k net | Return | ₹50k net | Return | Max DD | Months reduced |
|---|---|---|---|---|---|---|---|
| A_cliff | 1 lot if DD ≥ 35% | ₹18.3L | +9,046% | ₹28.6L | +5,631% | 60.5% | 18/34 |
| B_linear | max(0.10, 1−2×dd) | ₹38.7L | +19,233% | ₹40.1L | +7,923% | 44.1% | 34/34 |
| C_quadratic | max(0.10, (1−dd)²) | ₹40.7L | +20,248% | ₹42.3L | +8,360% | 48.9% | 34/34 |
| **D_steps** | **4-tier step-down** | **₹48.1L** | **+23,946%** | **₹49.2L** | **+9,740%** | **44.1%** | **17/34** |
| E_sigmoid | 1/(1+exp(10×(dd−0.25))) | ₹39.1L | +19,471% | ₹39.5L | +7,800% | 41.4% | 34/34 |

**Why D_steps wins**: The only config (besides cliff) that achieves exactly 1.00x multiplier when DD < 15%. Linear/sigmoid/quadratic always in reduced mode because they need dd=0% for 1.0x — even ₹1 below HWM triggers reduction. Step-down allows full operation through normal P&L variance (0-15% DD), which is most of the time.

**Recovery story (Oct 2023 – Jul 2024)**: Peak ₹92.6L in Sep 2023. Oct-Dec 2023 drawdown: 7 lots at 0.35x tier. Jan-Jun 2024: 2-8 lots at 0.12x tier. Jul 2024: DD dropped to 13.3% → fully recovered to 1.00x → 20 lots restored. Apr 2025: +₹16L in one month at 25 lots. The cliff config stayed frozen at 1 lot the entire time.

---

## 5. Decisions Made and Alternatives Rejected

### D1: P70_L40d as the regime filter (not fixed ATR>30)

**Chosen**: Rolling 70th-percentile ATR threshold on trailing 3000 bars (≈40 trading days lookback for percentile calculation).  
**Rejected**: Fixed ATR>30 threshold.  
**Why**: Fixed threshold fails across regimes (EXP-0009: 56% beat rate). Adaptive percentile generalizes because it defines "high ATR" relative to recent history, not an absolute number that made sense only in 2023 market conditions.

### D2: VIX×1.1 as IV scaling factor (not VIX/100 flat)

**Chosen**: VIX × 1.1 / 100 as annualized IV.  
**Rejected**: VIX/100 (under-prices short-dated options), VIX×1.2/100 (over-prices).  
**Why**: Weekly NIFTY options have ~10% tenor premium over 30-day VIX. 1.1 is the best-fit scale factor from EXP-0014. VIX×1.2 inflated premiums by 11% above current levels — too aggressive.

### D3: VIX as sizing signal, not binary entry filter

**Chosen**: Multiplier (1.5x sweet, 0.5x danger, 1x else) applied to lot count.  
**Rejected**: Binary "skip trade when VIX > 60th pctile" filter.  
**Why**: VIX and ATR are correlated. Binary filtering with both conditions collapsed trade count from ~33/month to 6-15/month. EXP-0013: 22% beat rate (needed 65%). Sizing modulation preserves trade count while tilting capital.

### D4: Step-down 4-tier for drawdown management

**Chosen**: 0-15% DD: 1.00x | 15-25%: 0.65x | 25-40%: 0.35x | >40%: 0.12x.  
**Rejected**: Cliff brake (hard freeze at 1 lot), linear, quadratic, sigmoid.  
**Why**: Cliff traps the system in crisis mode permanently (EXP-0016: locked at 1 lot for 22 months, unable to recover). Linear/sigmoid/quadratic always reduce because they require dd=0 for 1.0x — a hidden permanent friction. Step-down is the only design that grants full operation during normal variance and permits natural recovery.

### D5: 30% tax reserve withheld monthly from sizing capital

**Chosen**: Reserve = 30% of each profitable month's P&L; not available for lot sizing.  
**Rejected**: Modeling tax only at year-end.  
**Why**: Using pre-tax capital for sizing and paying taxes annually would overstate compounding. Monthly withholding is conservative but avoids a year-end capital shock. Actual tax liability (ITR filing) may differ; model errs toward safety.

### D6: Post-hoc sizing simulation (not re-running full backtest per config)

**Chosen**: Collect 1,522 trades at 1-lot baseline, then replay each trade with sizing multiplier applied.  
**Rejected**: Re-running the full BacktestHarness for every sizing config.  
**Why**: Full re-run for 5×36 months = 180 harness runs, ~3 hours. Post-hoc replay takes seconds. Valid for sizing research because signal quality (entry/exit timing, P&L per lot) is independent of position size. Not valid if sizing affects entry decisions.

---

## 6. Open Problems and Risks (Ranked by Severity)

### CRITICAL

**RISK-0 (added 2026-10-13; NIFTY half RESOLVED same day): research dataset absent**  
Both 2023-2025 CSVs were gitignored and present on no machine reachable from a fresh clone,
making every experiment from EXP-0009 onward unreproducible and unauditable.

**NIFTY: resolved.** Re-fetched via `scripts/data_001_fetch_historical.py` (55,513 rows, 744
sessions), passes all 11 checks in `verify_data.py`, and is checksummed in
`data/live_data/CHECKSUMS.json`. EXP-0009/0010/0011/0012 were re-run and **reproduce exactly**
— see EXP-0018. The validated regime filter P70_L40d is auditable from a clean clone again.

**India VIX: still absent.** `india_vix_daily_20230101_to_20251231.csv` has no fetcher in the
repo and must be sourced manually (columns `date,vix`, ~740 rows). Until it exists,
**EXP-0013 through EXP-0017 cannot be run** — that is the VIX×1.1 IV model, VIX tilt sizing,
the compounding engine, and the step-down drawdown tiers. The ₹49.2L projection and the
EXP-0016 results conflict both sit on that side of the line.

**RISK-1: Strategy degradation in live conditions (unquantified)**  
Backtest covers 2023-2025. Future market structure may differ (option market depth, new participants, VIX regime). Historical performance is not a guarantee. Minimum 3 months paper trading before any live capital. No model accounts for this.

**RISK-2 (CORRECTED 2026-10-13): P(ruin) = 17.8%, where "ruin" means a 50% drawdown**  
This entry previously described the 17.8% figure as simulations that "hit a 90%+ capital loss
scenario", and claimed a ₹50k start reduces it. Both are wrong, verified against the script:

- `scripts/exp_0012_monte_carlo.py` sets `RUIN_THRESHOLD = 0.50` and labels the output
  "Probability of ruin (DD>50%)". A 50% drawdown is a far milder event than a 90% loss.
- EXP-0012 reports **identical** percentile returns for ₹20k, ₹50k, ₹1L and ₹5L starts
  (+778%, +778%, +779%, +781% median). It models percentage returns and is scale-invariant,
  so it cannot show a start-size effect on P(ruin) at all.

The real reason to prefer a larger start is one the model omits entirely: lot indivisibility.
A ₹20k account cannot buy a lot at many premiums, so it skips trades a larger account takes —
a penalty invisible to a percentage-return bootstrap. Treat "minimum recommended capital
₹50,000" as resting on that, not on a measured ruin difference.

17.8% remains high, and 1% of simulations reach a 100% max drawdown. The step-down drawdown
brake is the primary mitigation. See EXP-0018 FINDING-4.

**RISK-3: LiveOrchestrator has 8 TODO Phase stubs (not wired)**  
`live/orchestrator.py` is not production-ready. Paper trading engine exists (`PaperTradingEngine`, 19 tests), but the live path from VIX-adjusted signal → lot count → SEBI Algo-ID → Upstox order is not a complete code path.

### HIGH

**RISK-4: SEBI Algo-ID requirement (mandatory April 2026)**  
Any automated order placement requires ALGO_ID registered with NSE/SEBI. Must be configured via `ALGO_ID` env var. Not required for paper trading. A live system without this is non-compliant.

**RISK-5: Slippage model is conservative but unvalidated at scale**  
₹2/unit extra per lot above 10 is a rule-of-thumb. NIFTY ATM options at 25-35 lots may have wider spreads, especially during fast markets. The actual live P&L may be 5-15% below backtest at 20+ lots.

**RISK-6 (REVISED 2026-10-13): EXP-0016's numbers are unrecoverable, and two records disagree**  
`research/experiments/EXP-0016.json` now exists, but it is a reconstruction from documentation
rather than from a run — the 2023-2025 CSVs are absent, so the script cannot be re-executed.
Writing it surfaced a worse problem than the missing file: the two surviving records disagree
about the ₹50k scenario by roughly 6x. This file and ASTRA_STATUS.md line 89 say ₹10 lakh net
after tax; the ASTRA_STATUS.md capital-goal table says ₹88,48,311 gross / ~₹60 lakh after tax
for the same scenario. The scenario lists disagree too — the committed script defines ₹20k at
25 lots, the table lists ₹20k at 50 lots.

**Do not quote any EXP-0016 capital figure until the script is re-run.** The qualitative
cliff-brake finding is unaffected and is corroborated by both sources. See the
`results_conflict` block in EXP-0016.json.

### MEDIUM

**RISK-7 (PARTIALLY ADDRESSED 2026-10-13): data quality was unverifiable**  
`scripts/verify_data.py` now exists and checks row counts, column presence, chronological
ordering, duplicate timestamps, date-range coverage, unexplained business-day gaps, OHLC
internal consistency, bars-per-session, VIX plausibility, and VIX↔NIFTY session alignment.
It also maintains a SHA-256 manifest (`--record-checksums`) so a re-download can be compared
against the copy that produced the recorded results — the gap this risk originally described.

**Largely closed for NIFTY (2026-10-13).** There is still no checksum of the *original* file,
so byte-identity remains unprovable in principle. But equivalence was established a better
way: the re-downloaded dataset reproduces EXP-0009, 0010, 0011 and 0012 **exactly**, including
all six filter configs, all three regime breakdowns and the full Monte Carlo distribution. A
dataset differing in any material way would have perturbed at least one of those figures. See
EXP-0018 FINDING-1. The file is now hashed, so future drift will be caught.

Still open for the VIX file, which does not yet exist.

**RISK-8: HWM tracking is post-trade, not intraday**  
In the simulation, HWM is updated after each trade closes. In live trading, intraday drawdown during an open position is not tracked. A fast adverse move could technically breach the DD tier without triggering the lot reduction. This is acceptable for paper trading; revisit before scaling to 20+ lots live.

**RISK-9 (added 2026-10-13): EXP-0005's script was never committed**  
`research/experiments/EXP-0005.json` records the ATR>30 filter as "MAJOR ALPHA" (+938% vs
+376% baseline) — the result that started the entire regime-filter line of research leading to
P70_L40d. There is no `scripts/exp_0005_*.py`; the scripts jump from 0004 to 0006. The finding
was later superseded by EXP-0010's adaptive percentile, and EXP-0009 showed the fixed ATR>30
threshold fails out-of-sample, so nothing in the current stack depends on it. But the
foundational experiment of the research programme is not reproducible, which violates the
reproducibility requirement in AGENTS.md section 1 item 3.

---

## 7. Local-Only Files (Gitignored — Not in Repo)

The following files exist only on the local machine and must be re-sourced manually if the repo is cloned on a new machine:

| File | Contents | Source |
|---|---|---|
| `.env` | Upstox API credentials, ALGO_ID | Upstox developer portal + SEBI registration |
| `data/live_data/nifty_5min_20230101_to_20251231.csv` | 5-minute NIFTY OHLCV, Jan 2023–Dec 2025 | NSE historical data download |
| `data/live_data/india_vix_daily_20230101_to_20251231.csv` | India VIX daily close values | NSE VIX historical CSV |

Without the two data CSVs, experiments EXP-0009 through EXP-0017 will exit immediately with "Missing data file" errors. The `.env` file is not required for backtests — only for live/paper trading that connects to Upstox.

To verify data files are present:
```bash
ls -lh data/live_data/
```

Expected: two files, ~100MB and ~50KB respectively.

---

## 8. Next 5 Tasks

**TASK-1 (PAPER-001)**: Wire the full validated strategy stack to paper trading mode.

Implement in `scripts/run_paper_astra.py`:
- Load P70_L40d ATR regime filter
- Wire `iv_fn=vix_iv_fn` to `OptionsPricer` (already implemented in `backtest/options_pricer.py`)
- Apply VIX tilt sizing before order submission
- Implement step-down 4-tier HWM tracking in `PaperTradingEngine` or a wrapper
- Start with `max_lots=10` (conservative paper mode)
- Run for minimum 3 months before any live capital decision

**TASK-2 (EXP-0016-JSON)**: ~~Write the missing experiment record.~~ **DONE 2026-10-13, with a caveat.**

`research/experiments/EXP-0016.json` is written and the registry is now contiguous
EXP-0001..EXP-0017. It records the design (read from the committed script, reliable), the
cliff-brake trap finding, the caveats, and the pointer to EXP-0017. It does **not** record
trustworthy capital figures: the script could not be re-run without the data, and the two
written sources conflict by ~6x. See revised RISK-6. The record is explicitly marked
`"reconstructed": true` / `"reproduced": false` so it cannot be mistaken for a real run.

**TASK-3 (DATA-INTEGRITY)**: ~~Add a data verification script.~~ **DONE 2026-10-13.**

`scripts/verify_data.py` is written and passes all 11 checks against the one dataset present
(`nifty_5min_20260201_to_20260731.csv`), and correctly reports the two 2023-2025 files as
ABSENT. Run `--record-checksums` once the files are restored and trusted.

Two corrections to this task as originally specified:
- The expected row count of **~220,000 is wrong by about 4x.** The NSE cash session is
  09:15–15:30 = 375 minutes = 75 five-minute bars per day, so three years at ~740 trading
  days is **~55,000 rows**, not 220,000. Confirmed against the 2026 file, which holds exactly
  9,225 rows = 123 sessions × 75. The script derives this from the date range instead of
  hardcoding it.
- "No gaps > 1 business day" would flag every NSE holiday as corruption. The script treats
  gaps of up to 3 business days as benign holiday clusters and fails only beyond that.

**TASK-4 (LIVE-ORCHESTRATOR)**: Resolve the 8 Phase stubs in `live/orchestrator.py`.

Currently there are 8 `TODO Phase` stubs (6 are `TODO Phase 1:`, 2 are `TODO Phase 2:`). These must be wired before shadow trading. Relevant items: strategy registry lookup, live feed subscription, order placement via ExecutionEngine, kill switch file polling, ALGO_ID injection.

**TASK-5 (LOT-CAP-GROWTH-RULE)**: ~~Implement and test the lot-cap growth rule.~~
**IMPLEMENTED 2026-10-13 — deliberately NOT wired.**

`src/astra/risk/lot_manager.py` implements the step-down 4-tier multiplier, the +5-lots-per-
3-consecutive-profitable-months cap growth gated on the 1.00x tier, the 30% monthly tax
reserve, the ₹500 premium floor, and HWM tracking. 41 tests in `tests/risk/test_lot_manager.py`.

**Nothing imports it.** Wiring position sizing into an order-capable path needs human approval
(AGENTS.md section 13), so activation is a separate step — see DECISION-007.

Implementing it surfaced three problems that the documented spec hid:

1. **The written sizing formula cannot reproduce the validated results.** All three documents
   apply the drawdown multiplier to the capital term; EXP-0017's own narrative ("0.35x × 20 =
   7 lots max") only works if it scales the lot *cap*. At a 0.35 tier with ample capital the
   two forms give 7 lots vs 20 — a ~3x exposure difference. See DECISION-008.
2. **EXP-0017's recommended per-trade HWM marking introduces a tax artifact.** It was never
   simulated; `exp_0016_compounded_equity.py` marks the peak at month close, after tax. Under
   per-trade marking, a month earning 50% of capital withholds 15% of it and demotes the
   engine a tier with no loss having occurred. See DECISION-009.
3. **The validated sizing is illegal under `config/risk.yaml`.** The design wants 30%
   deployment and 20-35 lots; the config permits 25% and `hard_cap_lots: 10`. The ₹49.2L
   projection therefore does not describe the system as currently configured. The module
   raises `RiskLimitConflict` rather than clamping. **This blocks TASK-1.** See DECISION-010.

---

## 9. Gotchas

**G1: The post-hoc sizing simulation is not a true re-backtest.**  
EXP-0015, EXP-0016, EXP-0017 all replay the same 1,522 trades collected at 1-lot baseline. This is correct for studying sizing behavior, but it assumes signal quality (entry/exit times, per-lot P&L) is independent of position size. At 30+ lots in live markets, your order moves the book — the post-hoc model does not capture this. Treat projections beyond 15-20 lots as directional, not precise.

**G2: `premium_per_lot` has a floor of ₹500 in the compounding simulation.**  
In `exp_0016_compounded_equity.py` and `exp_0017_drawdown_management.py`, there is a line: `prem_per_lot = max(row["premium_per_lot"], 500.0)`. This prevents division-by-zero and unrealistic lot counts when deep OTM options appear. If the live system prices a trade at < ₹500/lot premium, the lot count will be capped lower than expected.

**G3: VIX percentile lookback is 40 trading days, not calendar days.**  
`VIX_LOOKBACK = 40` is the rolling window for computing each trade's VIX percentile. This is 40 trading days (≈8 calendar weeks). A new month starting after a holiday period may have a slightly shorter effective lookback. The boundary effect is negligible but explains occasional percentile discontinuities at month starts.

**G4: The `iv_fn` parameter to OptionsPricer is backward-compatible.**  
`OptionsPricer(iv=0.14, iv_fn=None)` behaves identically to the old interface. Only when `iv_fn` is provided does it override the flat IV. The `price_trade()` method uses `iv_entry` and `iv_exit` separately, so IV change between entry and exit is captured (relevant only for multi-day holds, not intraday).

**G5: "Months in reduced mode" counts any month with at least one trade at < 1.00x dd_mult.**  
For step-down: 17/34 months in reduced mode means 17 months had at least one trade at 0.65x, 0.35x, or 0.12x. It does not mean the whole month was at reduced capacity. The monthly average lots shown in the simulation log is more informative than the binary "reduced" flag.

**G6: EXP-0013 verdict logic had a bug (documented, not code-fixed).**  
The `better = r["win_pct"] > atr_base["win_pct"]` comparison was against a 0% baseline (the baseline compared against itself). The correct comparison is `r["net_pnl"] > atr_base["net_pnl"]`. The script already ran and is not re-run. The correct interpretation is documented in `research/experiments/EXP-0013.json` findings. Do not trust the `beat_count` field — use `net_pnl` comparisons directly.

**G7 (OBSOLETE as of 2026-10-13): remote layout changed.**  
This gotcha warned that `astra` was canonical and `origin` pointed at the old ATLAS repo. A
fresh clone now has exactly one remote: `origin → https://github.com/piyush-genai/Astra.git`,
which is the canonical repo. There is no `astra` remote and no second remote to confuse it
with. Push to `origin`. Kept here rather than deleted because the old instruction to "always
push to `astra`" would now fail outright.

**G8: Kill switch file overrides everything.**  
If `KILL_SWITCH.txt` exists in the repo root, `core/kill_switch.py` halts all order placement regardless of strategy state. This is a manual emergency stop. Do not delete it to fix a paper trading test — investigate why it was triggered.
