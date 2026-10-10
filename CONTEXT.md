# ASTRA Project Context

## Project Evolution: ATLAS → ASTRA

### What Exists Today (ATLAS)
ATLAS is a working Python-based quantitative trading system that has:
- Been developed locally and deployed on AWS EC2
- Integrated with Upstox API for live trading
- Demonstrated profitable NIFTY options backtesting
- Generated approximately ₹70k profit over six months from ₹20k starting capital
- Concentrated approximately ₹50k of profit in March (this anomaly requires investigation)
- Existing strategy, backtesting system, capital compounding, and execution architecture

### What We're Building (ASTRA)
**ASTRA = Adaptive Strategy, Trading, Risk & Analytics**

ASTRA is NOT a replacement—it's an evolution. ATLAS becomes the baseline trading subsystem within a larger research-first platform designed to:
- Discover persistent, statistically defensible sources of market alpha
- Convert discoveries into controlled trading decisions
- Maintain capital preservation as the absolute priority
- Enable systematic research rather than ad-hoc strategy tweaking

---

## Strategic Objectives

### Primary Goal
Build a machine capable of discovering small, repeatable, statistically defensible edges that humans cannot easily see—inspired by Renaissance Technologies' Medallion Fund approach, which achieved ~63% annualized returns over decades through many small edges, not one magic strategy.

### Return Philosophy
**DO NOT optimize for arbitrary return targets like "40% monthly."**

Instead: Maximize risk-adjusted, scalable alpha subject to explicit drawdown, liquidity, capacity, and ruin constraints.

**Understanding Returns:**
- 40% monthly average for years = extremely unlikely, not a planning assumption
- 40% in individual favorable months = plausible with options and volatility regimes
- 5–10% monthly long-term = very strong systematic result
- 10–20% monthly = exceptional
- 20%+ monthly sustained = possible during particular regimes, investigate risk carefully

The goal is to discover what the data can legitimately support, not force a predetermined number.

### Capital Preservation Rules (Non-Negotiable)
**Priority Order:**
1. Capital preservation
2. Research correctness
3. Reproducibility
4. Statistical validity
5. Robustness
6. Risk management
7. Execution correctness
8. Scalability
9. Performance
10. Return maximization ← Notice this is LAST

---

## ASTRA Architecture: Seven Core Planes

```
                              ASTRA
        Adaptive Strategy, Trading, Risk & Analytics
                                   │
        ┌──────────────────────────┼─────────────────────────┐
        │                          │                         │
        ▼                          ▼                         ▼
   DATA PLANE              RESEARCH PLANE              CONTROL PLANE
        │                          │                         │
        ▼                          ▼                         ▼
  Market Data              Experiment Engine          Configuration
  Contract Data            Hypothesis Registry        Governance
  Options Data             Backtest Research          Approvals
  Reference Data           ML Research                Audit
                           Validation

                                   │
                                   ▼
        ┌──────────────────────────────────────────────────┐
        │          ALPHA INTELLIGENCE PLANE                │
        │                                                  │
        │  Feature Engineering                            │
        │  Market-State Representation                    │
        │  Regime Detection                               │
        │  Statistical Pattern Discovery                  │
        │  ML Models (XGBoost, LightGBM, CatBoost)       │
        │                                                  │
        │  "Is there a predictable opportunity?"          │
        └──────────────────┬───────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────────────────┐
        │          SIGNAL INTELLIGENCE PLANE               │
        │                                                  │
        │  Direction / Return Prediction                  │
        │  Outcome Probability                            │
        │  Expected Move, Time Horizon                    │
        │  Entry Level, Stop Level, Target Level          │
        │  Expected R:R, Signal Confidence                │
        │                                                  │
        │  "What trade setup exists?"                     │
        └──────────────────┬───────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────────────────┐
        │              DECISION PLANE                      │
        │                                                  │
        │  Trade / Skip Decision                          │
        │  Strategy Selection                             │
        │  Signal Ranking                                 │
        │  Position Sizing Recommendation                 │
        │                                                  │
        │  "Is this opportunity worth taking?"            │
        └──────────────────┬───────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────────────────┐
        │                RISK PLANE                        │
        │         (ABSOLUTELY DETERMINISTIC)               │
        │                                                  │
        │  Maximum Risk / Trade                           │
        │  Daily Loss Limit, Portfolio Exposure           │
        │  Drawdown Controls, Kill Switch                 │
        │  Data/API Failure Protection                    │
        │                                                  │
        │  "How much are we allowed to risk?"             │
        └──────────────────┬───────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────────────────┐
        │             EXECUTION PLANE                      │
        │          (DETERMINISTIC)                         │
        │                                                  │
        │  Order Construction                             │
        │  Broker Adapter (Upstox primary)                │
        │  Position Reconciliation                        │
        │  Paper → Shadow → Live progression              │
        │                                                  │
        │  "Execute."                                     │
        └──────────────────┬───────────────────────────────┘
                           │
                           ▼
                        UPSTOX
                           │
                           ▼
                    MARKET / EXCHANGE
                           │
                           ▼
                  RESULTS / TRADE OUTCOMES
                           │
                           └──────────► RESEARCH PLANE (feedback loop)
```

### Critical Architectural Boundary

```
        ┌─────────────────────────────────────────────┐
        │          AI RESEARCH SYSTEM                 │
        │                                             │
        │  - Agentic / adaptive                      │
        │  - Exploratory                             │
        │  - Generates hypotheses                    │
        │  - Can fail safely                         │
        │                                             │
        └───────────────┬─────────────────────────────┘
                        │
                        │ GOVERNANCE GATE
                        │ (Validation, Approval)
                        │
        ┌───────────────▼─────────────────────────────┐
        │          TRADING SYSTEM                     │
        │                                             │
        │  - Deterministic                           │
        │  - Controlled                              │
        │  - Executes validated logic only           │
        │  - Real money at risk                      │
        │                                             │
        └─────────────────────────────────────────────┘
```

**Never allow LLMs to directly control live trading.**

---

## Alpha Intelligence: The Real Breakthrough

### Not This:
```
RSI + MACD + EMA + ATR → Trade Signal
```

### Instead This:
```
Historical Market Data
       ↓
Feature Universe (300+ candidates)
       ↓
Statistical Analysis
       ↓
Feature Selection
       ↓
Market-State Discovery (Regime Detection)
       ↓
Pattern Discovery
       ↓
ML / Statistical Models
       ↓
Future Outcome Distribution
       ↓
Potential Alpha
```

### Feature Families to Explore

**Price:** returns, momentum, acceleration, range, gap, candle structure, market structure

**Volatility:** ATR, realized volatility, volatility percentile, expansion/contraction

**Options:** IV, IV percentile, IV change, skew, OI, OI change, volume, volume/OI, moneyness, delta, gamma, theta, vega, time-to-expiry

**Market Structure:** VWAP, distance from VWAP, support/resistance, breakout/compression, multi-timeframe structure

**Context:** time of day, expiry proximity, overnight gap, market regime, event regime

### Alpha Library Concept

Eventually ASTRA should NOT have "the strategy." It should have an Alpha Library:

```
A001  Volatility Expansion
A002  Momentum
A003  Mean Reversion
A004  OI Dislocation
A005  IV/RV Divergence
A006  Price/Volume Imbalance
A007  Expiry Structure
A008  Intraday Momentum
...
```

Then at each market state:
```
Current Market State
        ↓
Which alpha signals are active?
        ↓
A001 = +0.42
A004 = +0.73
A008 = +0.31
        ↓
Combined Signal
```

This is much closer to how quantitative firms like Renaissance operate.

---

## Signal Intelligence vs Alpha Discovery

**Alpha Discovery says:** "This market state has an exploitable relationship."

**Signal Intelligence says:** "Given the current market state, this is the trade setup."

Example output from Signal Intelligence:
```
NIFTY: 24,500

Predicted direction:    LONG
Probability (target):   72%
Expected move:          +0.82%
Optimal horizon:        35 minutes
Entry:                  24,500
Stop:                   24,375
Target:                 24,750
Expected R:R:           2.0
Signal confidence:      HIGH
```

### Important: Do NOT let ML directly output arbitrary entry/SL/target initially

Instead:
```
ML predicts:
  - P(target reached)
  - P(stop reached)
  - Expected return
  - Expected volatility
  - Expected horizon

       ↓

Deterministic Trade Setup Engine derives:
  - Entry
  - Stop
  - Target
  - R:R
  - Position size
```

This makes the system easier to validate.

---

## Machine Learning Stack

### Start Simple, Add Complexity Only When Justified

**Baselines (always test first):**
- Logistic Regression
- Linear models
- Random Forest

**Primary Candidates:**
- **XGBoost** ← Start here
- **LightGBM**
- **CatBoost**

**Advanced Research (only after basics proven):**
- Temporal models (LSTM, temporal CNN)
- Transformers
- Probabilistic models

**Experimental (much later):**
- Symbolic regression
- Genetic programming
- Reinforcement learning

**If XGBoost with 25 carefully selected features beats a Transformer on robust out-of-sample data, use XGBoost.**

The goal is alpha, not technological sophistication.

---

## Research Protocol (Mandatory Gates)

### Every Strategy Must Pass These Gates IN ORDER:

```
1. RESEARCH
      ↓
2. BACKTEST
      ↓
3. WALK-FORWARD VALIDATION
      ↓
4. MONTE CARLO SIMULATION
      ↓
5. PAPER TRADING
      ↓
6. SHADOW TRADING
      ↓
7. LIVE CANDIDATE STATUS
      ↓
8. HUMAN APPROVAL
      ↓
9. SMALL LIVE CAPITAL
      ↓
10. CONTROLLED SCALING
```

**Skipping a gate is not an option. Ever.**

### Experiment Registry (Mandatory)

Every research experiment gets a unique immutable ID:
```
EXP-0001
EXP-0002
EXP-0003
...
```

Each must record:
- Hypothesis
- Dataset version
- Date range (train/validation/test)
- Model version
- Configuration
- Results
- Git commit
- Why it succeeded or failed

**Never hide failed experiments.** The more hypotheses tested, the stronger validation must become.

### Walk-Forward Validation

Never randomly shuffle financial time series.

Use chronological splits:
```
TRAIN → VALIDATION → TEST
       ↓
roll forward
       ↓
TRAIN → VALIDATION → TEST
```

Maintain a final untouched out-of-sample period.

### Robustness Testing

For promising strategies:
- Resample trades
- Perturb parameters
- Vary slippage
- Vary costs
- Vary execution delay
- Test different periods
- Test different regimes

**If a strategy is suspiciously good, investigate why rather than celebrating.**

---

## Risk Management (Absolutely Non-Negotiable)

### Every Stage Can Veto:

```
MARKET DATA
    ↓
DATA QUALITY CHECK
    ↓
ALPHA MODEL      → Can say NO
    ↓
SIGNAL MODEL     → Can say NO
    ↓
DECISION ENGINE  → Can say NO
    ↓
RISK ENGINE      → Can say NO ← ALWAYS WINS
    ↓
POSITION SIZE
    ↓
EXECUTION
```

### Risk Engine Must Enforce:

- ✓ Capital available?
- ✓ Daily loss limit not breached?
- ✓ Exposure limit respected?
- ✓ Drawdown limit respected?
- ✓ Liquidity acceptable?
- ✓ Data fresh (no stale data)?
- ✓ Broker API healthy?
- ✓ Kill switch not activated?

**All limits must be configuration-driven, never hardcoded.**

### Manual Kill Switch

Must exist and be reachable within seconds (Telegram bot / CLI command), independent of automated circuit breakers.

---

## Backtesting: Avoiding Fantasy Results

### Common Pitfalls to Prevent:

**Look-Ahead Bias:** Using future information to make past decisions
- Every feature must use ONLY information available at decision timestamp
- No future candle data
- No future option-chain data
- No future-derived normalization

**Execution Fantasy:**
- Model realistic slippage
- Include all transaction costs (brokerage, STT, exchange charges)
- Use correct lot sizes from config (not hardcoded)
- Model realistic fill behavior
- Account for liquidity constraints

**Selection Bias:**
- Record how many hypotheses were tested
- If strategy selected from large search, account for multiple testing

**Capital Compounding:**
- Verify existing compounding mechanism
- Ensure it matches realistic trading behavior

### March Forensic Analysis (Critical First Research Task)

**Primary Question:** Why did ATLAS make ₹50k in March but perform differently in other months?

Analyze by:
- Volatility regime
- IV percentile
- OI behavior
- Trend characteristics
- Time of day patterns
- Expiry proximity
- Trade duration
- Entry/exit conditions

**Determine whether the edge is:**
- Regime-dependent ← Most likely
- Volatility-dependent
- Accidental
- Overfit
- Robust and persistent

This analysis will reveal whether ATLAS captured a genuine regime-specific edge or got lucky.

---

## Multi-Agent Architecture (Future Enhancement)

### Current Multi-Agent Trend

Many systems claim "350 bots" or similar. This is often over-engineered marketing.

**Our Approach:**

```
NOT THIS:
  350 AI bots talking to each other
       ↓
  AI decides everything
       ↓
  Money at risk

INSTEAD:
  6–8 Specialized Research Agents
       ↓
  Research Orchestrator
       ↓
  Quantitative Validation
       ↓
  Human/Policy Approval
       ↓
  Deterministic Trading System
```

### Useful Agent Roles (For Future Phases):

**1. Research Orchestrator**
- Breaks research questions into tasks
- Assigns to specialists
- Merges findings
- Proposes next experiments

**2. Market Regime Research Agent**
- Analyzes volatility patterns
- Identifies trend characteristics
- Studies regime transitions

**3. Alpha Discovery Agent**
- Searches for statistical relationships
- Proposes testable hypotheses
- Does NOT declare strategies profitable

**4. Feature Discovery Agent**
- Explores feature combinations
- Identifies predictive information
- Tests feature interactions

**5. Backtest Auditor Agent** ← CRITICAL
- Attacks promising results
- Looks for look-ahead bias
- Checks execution realism
- Validates cost assumptions
- May save more money than Alpha Discovery

**6. Risk Research Agent**
- Analyzes drawdown characteristics
- Studies tail risk
- Calculates ruin probability

**7. Experiment Manager Agent**
- Maintains research continuity
- Prevents duplicate testing
- Tracks what was already disproven

**8. Research Critic / Devil's Advocate Agent**
- Tries to prove discoveries are wrong
- Challenges selection bias
- Enforces validation rigor

**DO NOT BUILD THESE YET.** Build the deterministic foundation first.

---

## Technology Stack

### Language & Core Libraries
- **Python 3.11+** for all code
- **pandas** for OHLC/indicator data handling
- **backtrader** or **vectorbt** for backtesting (pick one, stay consistent)
- **pytest** for all tests

### ML Stack
- **scikit-learn** for baselines
- **XGBoost / LightGBM / CatBoost** for primary models
- Later: temporal models, LSTM, Transformers (only if justified)

### Broker Integration
- **Broker Adapter interface** (abstraction layer)
- **Upstox** as primary adapter (free data + execution APIs)
- Future: Zerodha Kite, Angel One SmartAPI (same interface)
- Strategies NEVER import from broker directly

### Infrastructure
- AWS EC2 with static IP (required for API whitelisting)
- **SQLite** for local development
- **PostgreSQL** for live trading (trade logs, performance tracking)
- **Telegram bot** for alerts and kill-switch

### Configuration NOT Hardcoding
These MUST live in `config/*.yaml`, never as constants:
- Lot sizes (NIFTY 50 = 65 as of Jan 2026, subject to revision)
- Weekly/monthly expiry weekdays (NIFTY weekly = Tuesday as of Sept 2025, subject to revision)
- Risk parameters
- Circuit breaker thresholds
- Max concurrent positions

---

## Deployment Timeline

**~10–14 weeks to first controlled live capital (NIFTY Options)**
**~6–8 weeks to equity intraday paper trading (parallel track)**

### Detailed Phase Breakdown:

**Week 1 — ATLAS Forensic Audit**
- Inspect repository architecture
- Map data flow, strategy flow, execution flow
- Reproduce current backtest
- Identify leakage, cost assumptions, capital compounding
- Output: `ATLAS_BASELINE_REPORT.md`

**Week 2 — Research Foundation**
- Build experiment registry
- Configuration system
- Dataset versioning
- Result storage
- Metric engine
- Output: `EXP-0001`, `EXP-0002`, `EXP-0003`...

**Weeks 3–4 — Backtester Hardening**
- Validate slippage, brokerage, taxes
- Verify lot sizes, contract selection, expiry handling
- Check execution assumptions, latency, liquidity
- Multi-year NIFTY testing ← Major gate

**Week 5 — March Forensic Analysis**
- Answer: Why did March produce ₹50k?
- Break down by volatility, IV, OI, trend, timing
- Discover if actual edge exists

**Weeks 6–7 — Alpha Discovery v1**
- Build Feature Engine
- Test statistical relationships
- Feature importance, correlation, mutual information
- Initial XGBoost / LightGBM / CatBoost models
- Proper temporal validation

**Week 8 — Signal Intelligence**
- Build Expected Return, Probability, Horizon outputs
- Entry/Stop/Target derivation
- Test if outputs improve baseline

**Week 9 — Walk-Forward + Monte Carlo**
- **HARD GATE:** If model fails here, reject it
- No live trading without passing this

**Week 10 — Decision + Risk Engine**
- Trade/Skip logic
- Position sizing
- Exposure controls
- Daily loss limits
- Kill switch

**Week 11 — Paper Trading**
- Connect ASTRA → Upstox → PAPER mode
- Compare backtest vs paper execution

**Week 12 — Shadow Trading**
- ASTRA produces real-time signals
- ₹0 live capital
- Measure: signal timing, slippage, latency, missed trades, data quality

**Weeks 13–14 — First Real Capital**
- **ONLY IF ALL GATES PASS**
- Small capital to prove live system behaves like validated research system
- NOT to maximize returns

### Expansion Timeline:

**Weeks 3-8 (Parallel):** Equity Intraday Strategy
- Week 3-4: Data pipeline for 1min/5min equity OHLCV
- Week 4-5: Technical pattern detection engine
- Week 5-6: Simple backtesting (pattern-based, not ML)
- Week 6-7: Paper trading equity intraday
- Week 8: Shadow trading (if paper validates)

**Weeks 14–16:** Add SENSEX (if NIFTY validated)
**Weeks 16–20:** Add liquid equity options (if multi-instrument abstraction works)
**Months 4–6:** Agentic Research System (autonomous hypothesis generation)

### Capital Allocation Strategy

**Recommended Initial Split:**
- 60-70% NIFTY Options (primary research focus)
- 30-40% Equity Intraday (parallel diversification)

Each strategy has:
- Independent risk limits
- Independent daily loss circuit breakers
- Independent position sizing
- Shared overall portfolio circuit breaker

This allows one strategy to fail/drawdown without killing the other.

---

## Instrument Scope

### Current Scope - Dual Strategy Launch

**PRIMARY STRATEGY: NIFTY OPTIONS**
- Continue existing ATLAS NIFTY options strategy
- Apply full ASTRA research framework
- This remains the primary focus for ML/Alpha Discovery

**SECONDARY STRATEGY: EQUITY INTRADAY**
- Launch parallel equity intraday cash strategy
- Separate capital allocation
- Separate risk management
- Lower research priority initially
- Simpler technical approach (compared to options ML research)

### Equity Intraday Strategy Specification

**Strategy Type:** Technical breakout/momentum on liquid stocks

**Magic Filter Parameters (from screenshot):**
```
✓ Draw: 5-range filters (eg 0-4% = high volume)
  consecutive 5 red candles on 5-min ⓘ
  stocks at 52 week high ⓘ
```

**Screening Criteria:**
```
Stock passed all of the below filters in cash segment:

[=1] 5 minute Close: Greater than [=1] 5 minute Open: Number [1][2][1][2][3][4][5][6]

[=2] 5 minute High: Greater than equal to [>1] 5 minute High [5][1][2][3][4][5][6]

[=2] 1 minute High: Greater than equal to [>1] 5 minute Close: Greater than: Number [PREVIOUS]
[1][2][3][4][5][6]

[=4] 1 minute Volume: [>3] Last 4 week Close: Greater than: Number [PREVIOUS]
```

**Target Characteristics:**
- 1 minute + 5 minute timeframe combination
- Volume confirmation required
- Consecutive candle patterns
- 52-week high proximity
- Breakout confirmation across timeframes

**Implementation Priority:**
This should be implemented as a **separate, simpler system** alongside NIFTY options research, NOT as part of the complex Alpha Discovery ML pipeline initially.

**Rationale:**
- Different risk profile (intraday cash vs options)
- Different technical approach (breakout patterns vs statistical/ML alpha)
- Separate capital allocation allows portfolio diversification
- Can operate with simpler backtesting initially
- Provides learning opportunity with pure equity mechanics

### Expansion Order:
1. **NIFTY Options** ← Primary focus, full ASTRA framework
2. **Equity Intraday Cash** ← Parallel implementation, simpler technical strategy
3. **SENSEX Options** ← After NIFTY validated
4. **Liquid Equity Options** ← Liquidity-filtered universe only
5. **Multi-strategy portfolio** ← Combine instruments

Each new instrument requires:
- Data adapter
- Contract model
- Cost model
- Execution model
- Risk model
- Validation suite

### Equity Intraday Implementation Notes

**Data Requirements:**
- 1-minute and 5-minute OHLCV data
- 52-week high/low data
- Volume averages (4-week lookback minimum)
- Liquid stocks universe (define liquidity threshold)

**Technical Implementation:**
- Simpler than options: no Greeks, no IV, no expiry management
- Focus on: price action, volume, breakout confirmation
- Pattern recognition: consecutive red candles, volume spikes
- Multi-timeframe coordination (1min + 5min)

**Backtesting Differences from Options:**
- Intraday cash: different margin requirements
- Simpler cost structure (no options premium decay)
- Must square off by 3:15 PM (exchange rules)
- Slippage modeling for less liquid stocks
- Circuit breaker awareness (stock-level limits)

**Risk Management Differences:**
- Per-stock position limits
- Sector concentration limits
- Intraday stop-losses (tighter than options)
- No overnight risk (mandatory exit)
- Different capital allocation vs options book

**Separate vs Integrated:**

For Phase 1 implementation, treat as **separate parallel system**:
```
ASTRA
  │
  ├── NIFTY Options Engine (complex, ML-driven)
  │     ↓
  │   Full Alpha Discovery pipeline
  │
  └── Equity Intraday Engine (simpler, technical-driven)
        ↓
      Technical pattern + volume confirmation
```

Later phases can integrate both under unified portfolio/risk management.

**Timeline Adjustment:**
- Equity intraday can start Week 3-4 (simpler backtesting)
- Does NOT delay NIFTY options research timeline
- Parallel development with separate code modules
- Separate validation gates
- Can reach paper trading independently

---

## Critical Operating Principles

### 1. Preserve ATLAS Baseline

**Before changing anything:**
- Create Git checkpoint: `atlas-baseline-v1`
- Create reproducible baseline specification
- Document strategy version, dataset, date range, capital rules, costs

**Never:**
- Overwrite existing strategy without preserving it
- Delete working code before replacement is validated
- Modify behavior to make numbers match user reports

### 2. Research Integrity Over Backtest Beauty

If you discover:
- Current strategy makes less money after realistic costs → **Report honestly**
- New model loses money → **Report honestly**
- Hypothesis is wrong → **Record the failure**
- Backtest is suspiciously good → **Investigate why**
- Change reduces P&L but improves robustness → **Report as positive research result**

**The integrity of ASTRA's research is more important than any individual backtest result.**

### 3. Reproducibility is Mandatory

Every experiment must be exactly reproducible:
- Same dataset → Same features → Same model → Same results

Track:
- Git commit
- Dataset version
- Configuration file
- Random seeds
- Environment dependencies

### 4. Never Assume, Always Verify

Don't assume:
- Current backtest is correct
- Current costs are realistic
- Current execution model is accurate
- User-reported numbers are exact

Verify everything. Document what cannot be verified.

### 5. Fail Loudly, Not Silently

If you encounter:
- Missing data
- Stale data
- API failure
- Configuration error
- Validation failure
- Risk limit breach

**STOP and report. Do not work around it silently.**

---

## What Success Looks Like

### NOT Success:
- "I found a 200% annual backtest!"
- "The strategy always wins!"
- "AI discovered the perfect indicator!"

### Success:
- "I found a statistically significant edge that survives walk-forward validation, has acceptable drawdown, and demonstrates persistent out-of-sample expectancy. Maximum drawdown is 12%. Profit factor is 1.8. It works best during high-volatility regimes. Here's why I think it's real, and here's how we could disprove it."

### Ultimate Success:
```
ASTRA discovers → validates → deploys → monitors → learns → adapts

And the feedback loop makes it progressively better at:
  - Identifying exploitable market states
  - Sizing positions appropriately
  - Protecting capital during unfavorable regimes
  - Scaling during favorable regimes
```

---

## Final Strategic Vision

**You are not building a trading bot.**

**You are building:**

> A system that discovers market states and predictive relationships from data, converts them into trade setups, determines whether those setups have sufficient expected value, applies deterministic risk constraints, executes them, and continuously evaluates whether the discovered edge remains valid.

This is the system worth spending 6–12 months building.

---

## Immediate Next Steps for Claude Code

**Your FIRST action is DISCOVERY MODE:**

1. Complete repository audit
2. Map current ATLAS architecture
3. Understand data flow, strategy flow, execution flow
4. Reproduce baseline if possible
5. Document current state
6. Identify gaps between ATLAS and ASTRA
7. Create migration plan

**DO NOT:**
- Immediately restructure code
- Add ML before understanding baselines
- Change live execution paths
- Delete working components
- Implement Alpha Discovery yet
- Add SENSEX or equity options yet

**Present findings and await approval before major implementation.**

---

## Remember

The market—not the calendar—decides when ASTRA is ready for real capital.

Day 95 is the earliest possible live gate. If validation fails, extend research.

**Capital preservation > Everything else.**

---

*This context document represents the complete strategic, architectural, and operational framework for ASTRA. Refer to it continuously during development. When in doubt, prioritize research integrity, capital preservation, and statistical rigor over apparent profit optimization.*
