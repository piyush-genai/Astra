# ASTRA Status Dashboard

**Platform**: ASTRA — Adaptive Strategy, Trading, Risk & Analytics  
**Current Phase**: 0 — ATLAS Preservation + ASTRA Foundation  
**Last Updated**: 2026-10-10

---

## Current Phase Gate

```
[RESEARCH] → [BACKTEST] → [WALK_FORWARD] → [MONTE_CARLO] → [PAPER] → [SHADOW] → [LIVE]
    ↑
  HERE
```

**Next gate**: BACKTEST (requires EXP-0001 completion + leakage verification)

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
- [ ] **EXP-0001**: Reproduce ATLAS backtest result
- [ ] **EXP-0002**: March 2026 forensic analysis
- [x] git tag: `atlas-baseline-v1` (pending commit)

### Tests
- [x] 92 tests passing (0 failures)

---

## Active Experiments

| ID | Hypothesis | Status | Priority |
|---|---|---|---|
| EXP-0001 | Reproduce ATLAS baseline | PROPOSED | CRITICAL |
| EXP-0002 | March 2026 forensic analysis | PROPOSED | HIGH |

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

**Aspiration**: ₹25 Crore by Dec 2028  
**Starting capital**: ₹20,000  
**Current approach**: Build the research machine first; let the edge discovery determine the achievable return

Monthly return scenarios:
| Scenario | Monthly Return | Path to ₹25Cr |
|---|---|---|
| Poor | < 3% | Insufficient — improve strategy |
| Good | 3–8% | Requires additional capital injection |
| Excellent | 8–15% | Achievable with scaling |
| Extraordinary | > 15% | Investigate deeply before trusting |

**Do not optimize ASTRA to hit the ₹25Cr target. Build the research machine.
The capital goal is an aspiration, not a constraint on research integrity.**
