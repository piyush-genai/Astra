# ASTRA Live Trading Gates

**No system enters a higher state without passing all gates for the current state.**

---

## State Machine

```
RESEARCH → BACKTEST → WALK_FORWARD → MONTE_CARLO → PAPER → SHADOW → LIVE
```

Transitions are NOT automatic. Each requires explicit human approval and a documented
decision in `docs/decisions/DECISION_LOG.md`.

---

## Gate 1: Research → Backtest

| Check | Requirement |
|---|---|
| Hypothesis documented | EXP-NNNN record exists |
| No look-ahead bias | Automated leakage test passes |
| Chronological splits | No random shuffling of time series |
| Costs included | Brokerage, STT, slippage modeled |
| Contract selection | Realistic strike/expiry selection confirmed |

---

## Gate 2: Backtest → Walk-Forward

| Check | Requirement |
|---|---|
| In-sample Sharpe | ≥ 0.8 |
| In-sample profit factor | ≥ 1.3 |
| In-sample max drawdown | ≤ 30% |
| Win rate | ≥ 15% (consistent with options strategy mechanics) |
| Min trades (in-sample) | ≥ 100 |
| Cost sensitivity | Result survives 2× transaction costs |

---

## Gate 3: Walk-Forward → Monte Carlo

| Check | Requirement |
|---|---|
| Walk-forward Sharpe (out-of-sample avg) | ≥ 0.5 |
| Walk-forward all periods profitable | ≥ 60% of periods positive |
| Walk-forward max single period DD | ≤ 25% |
| Stability | Results do not collapse at nearby parameter values |
| March anomaly explained | March regime identified and modeled |

---

## Gate 4: Monte Carlo → Paper Trading

| Check | Requirement |
|---|---|
| MC 5th percentile return | Positive (not capital-destroying) |
| MC ruin probability | P(drawdown > 50%) < 5% |
| Parameter sensitivity | ±20% parameter perturbation keeps positive expectancy |
| Stress test | Performance in high-volatility and low-volatility regimes separately assessed |
| Multiple-testing bias | Number of hypotheses tested documented; result adjusted if large search |

---

## Gate 5: Paper → Shadow Trading

| Check | Requirement |
|---|---|
| Paper trading duration | ≥ 10 trading days |
| Paper vs backtest signal timing | Signals match within 1 bar |
| Paper trade count | ≥ 20 trades |
| Paper win rate | Within 10% of backtest win rate |
| No data/API failures | Fewer than 2 missed signals due to technical issues |
| Telegram alerts | Working and accurate |

---

## Gate 6: Shadow → Live (Small Capital)

| Check | Requirement |
|---|---|
| Shadow trading duration | ≥ 5 trading days |
| Slippage measured | Actual fill vs expected price documented |
| Latency measured | Signal-to-order latency acceptable |
| Order rejection rate | < 5% |
| Position reconciliation | Live positions match system state 100% |
| Kill switch tested | File-based kill switch verified working |
| Algo-ID registered | SEBI Algo-ID configured (mandatory April 2026) |
| Human approval | Explicit go/no-go decision in DECISION_LOG.md |

---

## Gate 7: Small Live → Scaled Capital

| Check | Requirement |
|---|---|
| Live trading duration | ≥ 20 trading days |
| Live trade count | ≥ 40 trades |
| Live win rate | Within 15% of walk-forward expectation |
| Live drawdown | Does not exceed paper/shadow worst case |
| P&L matches expectation | Live monthly return within 2σ of predicted distribution |
| No runaway behavior | No single-day loss > circuit breaker limit |
| Human approval | Explicit scaling decision with capital amount |

---

## Hard Stops (any state → halt immediately)

| Condition | Action |
|---|---|
| Capital drops below 50% of starting value | HALT + human review required |
| Daily loss > 10% of capital | Auto-halt via circuit breaker |
| Win rate < 10% over 2 consecutive weeks | HALT + research review |
| API/broker failure during market hours | Auto-halt + alert |
| Look-ahead bias found in production strategy | IMMEDIATE halt + investigate |
| KILL_SWITCH.txt exists | IMMEDIATE halt (no override) |

---

## Who Can Authorize Transitions

| Transition | Authority |
|---|---|
| Research → Paper | System owner (you) |
| Paper → Shadow | System owner |
| Shadow → Live | System owner (with documented decision) |
| Scaling capital | System owner (with documented decision) |
| Changing risk limits | System owner only |

**AI agents (including Claude Code) may NEVER authorize a live trading transition.**
