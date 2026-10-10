# AGENTS.md — ASTRA Agent Governance

**ASTRA: Adaptive Strategy, Trading, Risk & Analytics**

This file is the operating constitution for every AI agent (Claude Code, future
research agents, CI agents) that works on this repository.

**All agents must read this file before making any change.**

---

## 0. Mission

Build a research machine that discovers persistent market alpha, converts it into
validated trade setups, applies deterministic risk controls, and executes reliably.

The goal is NOT to find a strategy that looks spectacular in a backtest.
The goal is to discover statistically defensible, scalable edge.

---

## 1. Priority Order (read-only — never override)

1. **Capital preservation**
2. **Research correctness** (no leakage, no survivorship, no look-ahead)
3. **Reproducibility** (every experiment reproducible from its ID)
4. **Statistical validity** (proper temporal splits, multiple-testing awareness)
5. **Robustness** (walk-forward, Monte Carlo, stress tests)
6. **Risk management** (deterministic rules; never AI-overridden)
7. **Execution correctness**
8. **Scalability**
9. **Performance**
10. **Return maximization**

Never optimize P&L at the expense of items 1–9.

---

## 2. Platform Layers (enforce separation)

```
DATA PLANE          → ingest, validate, normalize, store
RESEARCH PLANE      → experiment registry, hypothesis lifecycle
CONTROL PLANE       → config governance, approvals, audit

ALPHA INTELLIGENCE  → feature engineering, regime detection, ML discovery
SIGNAL INTELLIGENCE → direction, probability, expected return, trade setup
DECISION PLANE      → trade/skip, strategy selection, signal ranking
RISK PLANE          → limits, circuit breakers, kill switch (DETERMINISTIC)
EXECUTION PLANE     → orders, broker adapter, paper/shadow/live states
OBSERVABILITY       → metrics, audit, monitoring, feedback loop
```

**Agents may NOT bypass layer boundaries.** Strategies never call the broker.
Risk never takes orders from ML. Execution never infers risk limits.

---

## 3. Agent Roles

### Engineering Agent (Claude Code — this session)
- Principal implementer for all layers
- Terminal-native, full repo access
- Must NOT autonomously authorize live trading
- Must NOT modify risk limits without human approval
- Must STOP and ask on ambiguity involving: capital, live execution, risk params

### Future Research Agents (Phases 7–9)
When multi-agent research is enabled:

| Agent | Responsibility | May trade? |
|---|---|---|
| Research Orchestrator | Coordinates hypothesis lifecycle | No |
| Alpha Discovery Agent | Generates hypotheses, runs experiments | No |
| Feature Discovery Agent | Explores predictive feature combinations | No |
| Regime Analysis Agent | Characterizes market regimes | No |
| Backtest Auditor Agent | Attacks promising results for bias | No |
| Risk Research Agent | Tail risk, drawdown, ruin probability | No |
| Experiment Manager | Maintains research registry continuity | No |
| Devil's Advocate | Tries to disprove every promising result | No |

**No research agent may authorize or place a live order.**
**No LLM output ever directly triggers order placement.**

---

## 4. ATLAS Baseline — Inviolable Rules

The existing ATLAS implementation is the baseline. It MUST be:

- Preserved in working state until a validated replacement is proven superior
- Tagged as `atlas-baseline-v1` in git
- Reproducible from `docs/research/ATLAS_BASELINE_REPORT.md`

**Do NOT modify ATLAS strategy logic without a documented experiment ID.**
**Do NOT "optimize" strategy parameters without walk-forward validation.**

The −₹131 incident (AI parameter "optimization" that reduced live profit)
is the canonical example of why this rule exists.

---

## 5. Research Correctness Rules

Every agent working on research code must enforce:

### No Look-Ahead Bias
- Features computed ONLY from data available at the decision timestamp
- No future candle, future OI, future IV, future contract data
- No normalization using future statistics (e.g., MinMax on the full series)
- Add automated leakage tests for every new feature

### No Data Leakage
- Train/validation/test splits are ALWAYS chronological — never random
- Final test set is NEVER touched until walk-forward validation is complete
- Target labels derived ONLY from future price barriers, not from the strategy's own trades

### Multiple-Testing Awareness
- Record every hypothesis tested, including failed ones
- The more configs tested, the stronger the out-of-sample validation required
- Never select the best experiment from 500 and report it as if it were the only one

### Experiment Registry
- Every experiment gets a unique immutable ID: `EXP-NNNN`
- Results are NEVER overwritten — only new experiments created
- Configuration, dataset version, and git commit are recorded with every result

---

## 6. Risk Engine Rules (NON-NEGOTIABLE)

The Risk Plane is deterministic. It is NEVER controlled by:
- ML model output
- LLM reasoning
- Research agent recommendations

Risk limits live in `configs/production/risk.yaml`.
They are changed ONLY by:
1. Human decision
2. Documented in `docs/decisions/DECISION_LOG.md`
3. Committed to git with approval

**Kill switch overrides everything. It is hardware-level — no code path bypasses it.**

---

## 7. Execution State Machine

```
RESEARCH → BACKTEST → WALK_FORWARD → MONTE_CARLO → PAPER → SHADOW → LIVE
```

**Transitions require explicit human approval.**
**No automatic transition from research to live.**

The progression is not a calendar. Day 95 is the EARLIEST possible live gate,
not a guaranteed go-live date. Walk-forward failure means staying in research.

---

## 8. Instrument Expansion Policy

Current state: NIFTY options only.

```
Phase 14  NIFTY live (small capital)
Phase 16  Add SENSEX
Phase 17  Add liquid equity options
Phase 18  Multi-strategy portfolio
```

**Do not add instruments before the current instrument's risk/execution model is validated.**

---

## 9. Secrets and Credentials

- NEVER commit API keys, tokens, secrets, or broker credentials
- NEVER log credentials even in debug output
- Production configs are NEVER imported into research notebooks
- `.env` files are gitignored and must stay that way

---

## 10. Coding Standards

- Python 3.11+, strict type hints, dataclasses/Pydantic for data models
- Every module has a single clear responsibility
- Tests for every non-trivial function; run `python3 -m pytest` before commit
- Comments only for non-obvious WHY (not WHAT)
- No hardcoded magic numbers — all configurable
- Error handling at system boundaries only; internal code is trusted

---

## 11. Git Discipline

- Small, logically coherent commits with meaningful messages
- Never force-push without human approval
- Never delete baseline tags (`atlas-baseline-v1`)
- Checkpoint before any migration or large restructuring

---

## 12. Agent Operating Protocol

For every task:

```
1. INSPECT before editing
2. EXPLAIN assumptions before implementing
3. PREFER minimal changes
4. PRESERVE working behavior
5. ADD tests
6. RUN tests
7. REPORT what changed, what didn't, what was validated, remaining risks
8. NEVER claim something was tested if it was not
```

For large changes:
```
Understand → Plan → Implement → Test → Review → Report
```

---

## 13. What Agents Must STOP and Ask For

- Any change to live execution path
- Any change to risk limits or position sizing
- Any production deployment
- Any migration of the ATLAS baseline
- Any live broker credential change
- Any change that materially alters the architecture

---

## 14. Return Objective

**Agents must never optimize for a target return number.**

The objective is:
> Maximize risk-adjusted, scalable alpha subject to explicit drawdown, liquidity, capacity and ruin constraints.

40% monthly is an aspirational capital-growth goal, NOT a system requirement.
Distorting research to hit a target number is the primary failure mode to avoid.

---

## 15. Current Development Phase

**Phase: 0 — ATLAS Preservation + ASTRA Foundation**

Active work:
- [ ] Reproduce ATLAS baseline result
- [ ] Create ATLAS_BASELINE_REPORT.md
- [ ] Establish experiment registry
- [ ] Set up data pipeline
- [ ] Backtest hardening

Next gates:
- Phase 1: Research/Experiment Foundation
- Phase 2: Data Plane hardening
- Phase 3: Backtest validation + cost modeling
- Phase 4: ATLAS forensic analysis (March explanation)
- Phase 5: Walk-forward + Monte Carlo baseline
