# ASTRA Research Protocol

**Version**: 1.0  
**Applies to**: All experiments on the ASTRA platform

---

## Core Principle

The purpose of research is to discover whether an edge EXISTS, not to produce
impressive-looking numbers. If the data says there is no edge, that is a valid
and valuable result. Never distort research to get a desired outcome.

---

## Experiment Lifecycle

```
1. OBSERVATION     → Notice something interesting in market data or trade results
2. HYPOTHESIS      → Formulate a testable, falsifiable claim
3. REGISTRATION    → Create EXP-NNNN in the experiment registry
4. FEATURE DEF     → Define features using ONLY past data
5. LABEL DEF       → Define outcome labels (barrier/horizon method)
6. SPLITS          → Define train/validation/test chronologically
7. BASELINE        → Establish a simple baseline (e.g., buy-and-hold, random)
8. EXPERIMENT      → Run the strategy/model
9. LEAKAGE CHECK   → Actively try to find data leakage
10. WALK-FORWARD   → Roll train/test window forward chronologically
11. MONTE CARLO    → Resample trades, perturb parameters
12. STRESS TEST    → Test in different regimes, costs, slippage
13. CONCLUSION     → Accept / Reject / Needs more data
14. RECORD         → Update EXP-NNNN with all results including failures
```

---

## Feature Engineering Rules

### Allowed
- Any price/volume/OI data from timestamps strictly BEFORE the decision bar
- Rolling statistics computed over a trailing window
- Options data (IV, Greeks, chain) current AT the decision timestamp

### Forbidden
- Future price data in any form
- Features normalized using the full dataset (use expanding or rolling normalization)
- Outcome-derived features (e.g., "this trade was profitable" as a feature)
- Any data point indexed to a future contract or expiry

### Required Test
Every new feature must pass a leakage test:
```python
# Shift features forward by 1 bar and verify performance degrades
# If performance stays the same → the feature may contain look-ahead
```

---

## Train/Test Split Rules

**NEVER randomly shuffle financial time series.**

Always use chronological splits:

```
Full data:  [Feb --- Apr --- Jun --- Aug]
                  ↑           ↑
               Train        Test
              (in-sample)  (out-of-sample)
```

Walk-forward template:
```
Window 1: Train [Feb–Apr] → Test [May]
Window 2: Train [Mar–May] → Test [Jun]
Window 3: Train [Apr–Jun] → Test [Jul]
...
```

The FINAL test window must be held back until all model decisions are frozen.
Using the final test window for tuning invalidates it.

---

## Baseline Requirement

Every experiment must compare against at least one baseline:

| Strategy type | Suggested baseline |
|---|---|
| Directional | Always-long / always-short |
| Breakout | Buy-on-any-breakout (no zone filter) |
| ML model | Logistic regression with 5 features |
| Regime | Predict yesterday's regime continues |

If the proposed model cannot consistently beat a simple baseline, it is not ready.

---

## Outcome Labeling

Do NOT label trades using the existing strategy's exit rules. That creates
circular definitions. Instead, use **future price barriers**:

```
upper_barrier = entry + k × ATR
lower_barrier = entry - k × ATR
time_horizon  = N bars

label:
  +1 if upper_barrier reached before lower_barrier and within horizon
  -1 if lower_barrier reached first
   0 if neither reached within horizon
```

Test multiple horizons: 5m, 15m, 30m, 60m, 120m, EOD.
Do not assume a single horizon is optimal.

---

## Statistical Rigor

### Minimum sample size
- At least 100 out-of-sample trades for meaningful statistics
- At least 3 walk-forward windows to assess consistency
- Never report results on fewer than 30 trades in any period

### Required metrics
- Total return, CAGR
- Sharpe ratio (annualized), Sortino ratio
- Max drawdown, drawdown duration
- Win rate, profit factor, expectancy
- Average win, average loss, win/loss ratio
- Number of trades, average hold time
- Results by regime (trending, ranging, volatile)

### Significance testing
For binary outcomes (target reached / stop hit):
- Minimum: binomial test vs 50% base rate
- Better: bootstrap confidence interval on Sharpe ratio
- Report p-values; do not claim significance without testing

---

## Multiple-Testing Problem

Every time we test a new hypothesis or parameter combination, we increase the
probability of finding a "significant" result by chance.

**Mitigation rules:**
1. Record every hypothesis tested (including failures) in the registry
2. If testing N configurations, use Bonferroni correction or similar
3. If selecting the best of many experiments, hold a separate final test period
4. Report the total number of experiments tried alongside the winner

---

## When to Stop Research

Stop and record a **REJECTED** result when:
- Out-of-sample performance is negative after 3+ walk-forward windows
- Leakage found that cannot be eliminated
- Strategy requires too many parameters (overfitting risk)
- Result disappears with realistic transaction costs
- Walk-forward variance is too high to rely on
- Better explanation found (the "edge" was actually a market artifact)

**Recording failures is mandatory.** Failed experiments prevent repeating the same mistakes.

---

## The March 2026 Investigation (Priority Research)

**EXP-0002**: Why did ATLAS generate ~₹2,56,000 in March alone?

Analyze:
- [ ] Volatility levels (ATR, realized vol, VIX equivalent)
- [ ] IV percentile during March vs other months
- [ ] OI and OI change patterns
- [ ] Trend characteristics (strong vs choppy)
- [ ] Expiry effects (near-expiry vs far-expiry)
- [ ] Trade direction split (calls vs puts)
- [ ] Time-of-day concentration of profitable trades
- [ ] Breakout vs momentum trade contribution

Determine whether March was:
- A specific regime (high vol + strong trend)
- An expiry effect
- A data artifact
- Genuine edge that is regime-dependent
- A statistical outlier (lucky streak)

This is the most important research question for ASTRA Phase 4.

---

## Alpha Library Concept

As research progresses, build an Alpha Library:

```
A001 — Volatility Expansion Breakout       [PROPOSED]
A002 — IV/RV Divergence                    [PROPOSED]
A003 — OI Dislocation                      [PROPOSED]
A004 — Expiry Momentum                     [PROPOSED]
A005 — VWAP Reversal                       [PROPOSED]
...
```

Each alpha must be:
1. Independently validated (its own EXP-NNNN)
2. Tested for correlation with existing alphas
3. Evaluated for incremental information beyond the baseline

An alpha that is 90% correlated with the baseline adds little value even if it
passes all individual validation gates.
