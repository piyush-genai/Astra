# ASTRA Architecture Decision Log

Every significant decision affecting architecture, risk limits, strategy parameters,
live trading transitions, or capital allocation must be recorded here.

Format: `[DATE] [DECISION-NNN] Title`

---

## DECISION-001 — 2026-10-10: Preserve ATLAS as Baseline

**Context**: Considering whether to rewrite ATLAS or preserve it.

**Decision**: Preserve ATLAS in place. New ASTRA code is built alongside in `src/astra/`.
ATLAS is the working, revenue-generating baseline. It is not replaced until a validated
superior system is proven in paper/shadow trading.

**Rationale**: The −₹131 incident demonstrated that AI "optimization" without validation
destroys value. Preserve first, improve second.

**Impact**: All existing `core/`, `strategies/`, `live/`, `backtest/` code is untouched.

**Outcome**: Git tagged as `atlas-baseline-v1`.

---

## DECISION-002 — 2026-10-10: Claude Code + Claude Pro as Primary Agent

**Context**: Choosing between Claude Code, Kiro, Cursor for ASTRA development.

**Decision**: Claude Code (terminal-native) + Claude Pro ($20/month) for Phase 0–5.

**Rationale**:
- Terminal-first workflow matches ASTRA's Python/backtest/data-heavy workload
- Runs tests, backtests, inspects results in actual environment
- Repository-wide engineering context
- Included in Claude Pro
- ChatGPT/similar used as architecture review and research design layer

**Future consideration**: Re-evaluate at Phase 6 (Alpha Discovery) — more compute-heavy
research may benefit from additional tooling.

---

## DECISION-003 — 2026-10-10: NIFTY Options Only for Phase 0–14

**Context**: Temptation to add SENSEX, equity options, futures simultaneously.

**Decision**: NIFTY options only until Phase 14 live trading is validated.

**Rationale**: Each new instrument requires its own data adapter, contract model,
cost model, execution model, and risk model. Adding instruments before the core
architecture is proven creates compounding complexity and risk.

**Expansion order**: NIFTY → SENSEX (Phase 16) → Liquid Equity Options (Phase 17).

---

## DECISION-004 — 2026-10-10: No ML in Live Path Until Phase 9

**Context**: ML stubs exist in ml/ directory.

**Decision**: ML models may not influence live order placement until:
1. Walk-forward validation (Gate 3) is passed
2. Paper trading validation (Gate 5) is passed
3. Human approval is documented in this log

**Rationale**: ML outputs are probabilistic and can fail in regimes not seen in training.
The deterministic risk engine always has final veto regardless of ML output.

---

## DECISION-005 — 2026-10-10: Experiment Registry is Mandatory

**Context**: Research experiments were ad-hoc before.

**Decision**: Every research experiment must have an EXP-NNNN ID created in
`src/astra/experiments/registry.py` BEFORE the experiment runs.

**Rationale**: Multiple-testing bias — if we test 500 variations and only report the
winner, the result is statistically meaningless. Recording all attempts makes the
selection bias visible and quantifiable.

---

## DECISION-006 — 2026-10-10: Return Objective is Risk-Adjusted, Not Fixed

**Context**: ₹25 Crore capital target implies very high monthly returns (~40%).

**Decision**: ASTRA will NOT be optimized for a fixed return target. The objective is:
> Maximize risk-adjusted, scalable alpha subject to drawdown ≤ 20%, P(ruin) < 1%,
> profit factor ≥ 1.3, positive out-of-sample expectancy.

**Rationale**: Optimizing for 40%/month incentivizes leverage, overfitting, concentration,
and ultimately catastrophic drawdown. The path to ₹25Cr goes through sustainable edge
discovery + capital scaling, not through targeting a return number in backtests.

**Return distribution target** (not a guarantee):
- Poor: < 3%/month (insufficient edge)
- Good: 3–8%/month (sustainable, scalable)
- Excellent: 8–15%/month (exceptional, investigate deeply before scaling)
- Extraordinary: > 15%/month (extraordinary skepticism required; survive 3+ untouched test periods)

---

## Template for future decisions

```
## DECISION-NNN — YYYY-MM-DD: Short Title

**Context**: Why this decision was needed.

**Decision**: What was decided.

**Rationale**: Why this option was chosen over alternatives.

**Impact**: What changes as a result.

**Review trigger**: When to revisit this decision.
```
