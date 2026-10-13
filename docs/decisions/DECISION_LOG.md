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

*Correction 2026-10-13*: this outcome was recorded but never carried out — no tags existed in
the repository. The tag now exists, created at `27e6a6c` (the commit `EXP-0001.json` records as
`git_commit`, i.e. the code that produced the reproduced baseline result). It is annotated and
local until pushed.

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

## DECISION-007 — 2026-10-13: Lot Manager Built But Deliberately Unwired

**Context**: TASK-5 (HANDOFF.md section 8) requires the lot-cap growth rule and step-down
drawdown tiers to exist before paper trading, so paper sizing matches the EXP-0017
projections. Implementing it means writing position-sizing logic, which AGENTS.md section 13
puts behind human approval.

**Decision**: Implement the full rule as a pure, deterministic, fully tested module at
`src/astra/risk/lot_manager.py` (41 tests), and wire it into nothing. No execution path
imports it. Activation is a separate, explicit decision.

**Rationale**: Splitting "write the rule" from "let the rule size real orders" delivers the
reviewable artifact without an agent self-authorizing a change to the risk plane. The module
is inert, so it cannot affect a paper or live run until a human connects it. AGENTS.md
section 6 also requires that risk behaviour be deterministic — the module is a pure function
of capital state, with no ML or model input.

**Impact**: TASK-5's logic is available and verified in isolation. It is NOT validated
end-to-end against a backtest, because EXP-0017 cannot be re-run while the 2023-2025 data is
absent (RISK-0). Three open items are now documented in code rather than lost:
- the drawdown multiplier applies to the lot cap, not the capital term (see DECISION-008)
- per-trade HWM marking introduces a tax-withholding artifact (see DECISION-009)
- the validated sizing exceeds config/risk.yaml, so the module refuses to build (DECISION-010)

**Review trigger**: Before the first paper session using ASTRA sizing. Wiring it requires a
new decision entry here.

---

## DECISION-008 — 2026-10-13: Drawdown Multiplier Scales the Lot Cap (**CONFIRMED**)

**Status**: CONFIRMED later the same day by re-running EXP-0017 against the restored dataset
and reading the sizing code directly. The inference below was correct. The actual lines are:

```python
eff_max       = max(1, int(base_max_lots * mult))                      # cap is scaled
lots_from_cap = max(1, int(net_cap * RISK_PER_TRADE / prem_per_lot))
lots          = min(lots_from_cap, eff_max)
```

The reproduced D_steps monthly log confirms the effective caps at a base of 20: 1.00x → 20,
0.65x → 13, 0.35x → 7, 0.12x → 2. `lot_manager.py`'s `CAP_SCALED` default is therefore
faithful to the validated run, and **all three documented formulas are wrong** and should be
corrected to the form above.

**Context**: The sizing formula is written three times in the docs, and all three forms apply
the drawdown multiplier to the capital term:

    HANDOFF/ASTRA_STATUS:  lots = min(floor(net_capital × 0.30 / premium × dd_mult), cap)
    CLAUDE.md:             lots = min(floor(net_capital × 0.30 / premium) × dd_mult, cap)

Neither reproduces EXP-0017's own recorded narrative, which states "7 lots at 0.35x tier
(step-down: 0.35x × 20 = 7 lots max)" and "recovered to 1.00x → 20 lots restored". When the
capital term exceeds the cap, both written forms clamp to the unscaled cap and return 20.
They can never return 7.

**Decision (proposed)**: The implementation that produced the validated results must have
applied the multiplier to the cap: `effective_cap = floor(max_lots_cap × dd_mult)`, then
`lots = min(capital_lots, effective_cap)`. This reconciles 0.35 × 20 = 7, the 0.12x tier
bottoming at 2, and April 2025 running at 25 lots. `lot_manager.py` defaults to this
(`DrawdownApplication.CAP_SCALED`) and retains the documented form as `CAPITAL_SCALED` so the
two can be compared directly.

**Rationale**: Between a formula written in prose and a numeric result recorded from a run,
the recorded result is the better evidence of what the code did. The difference is not
cosmetic: at a 0.35 tier with ample capital it is 7 lots versus 20, a ~3x exposure gap.

**Impact**: All three documents state a formula that cannot reproduce the validated results
and should be corrected once this is confirmed. Until then, no document should be treated as
authoritative on the formula.

**Review trigger**: Immediately after the 2023-2025 data is restored and EXP-0017 is re-run.

---

## DECISION-009 — 2026-10-13: HWM Marked Per Trade, and It Carries a Real Tax Artifact (**REVISED**)

**Status**: REVISED the same day. My first version of this entry was wrong, and the correction
matters more than the original claim.

**What I got wrong**: I read `exp_0016_compounded_equity.py`, saw the peak updated only inside
`close_month()`, and concluded that EXP-0017.json's "updated after every trade" recommendation
had never been simulated. I set `MONTH_CLOSE` as the default on that basis. But EXP-0017 is a
*different script*, and it marks per trade — `if net_cap > hwm: hwm = net_cap`, inside the
trade loop (line 201). EXP-0016 marks at month close; EXP-0017 changed it. EXP-0017 is the run
the ₹49.2L projection and the production recommendation rest on, so `PER_TRADE` is the faithful
default. Corrected.

**What survived the correction**: the tax artifact is real — and it is present in the validated
results, not avoided by them. The HWM is marked on capital that has not yet had the month's tax
withheld; at close, 30% of the month's profit moves to the reserve, net capital falls below the
peak, and the engine registers a drawdown it never suffered. The reproduced D_steps monthly log
shows this plainly:

| Month | Month P&L | Drawdown | Tier | Max lots |
|---|---|---|---|---|
| 2023-03 | **+₹116,587** | 24.8% | 0.65x | 13 |
| 2023-05 | **+₹509,869** | 31.3% | 0.35x | 7 |

Both are strongly profitable months spent in reduced exposure. This is a large part of why 16
of 34 months are flagged "reduced". A unit test pins the practical consequence: a month that
recovers an entire drawdown still cannot spend a banked lot-cap-growth streak, because its own
withholding re-opens a drawdown against the peak it just set.

**Decision**: Default to `PER_TRADE`, matching the validated run exactly. Do **not** "fix" the
artifact by default. `MONTH_CLOSE` is retained to run the comparison.

**Rationale**: The ₹49.2L figure was produced by a system behaving this way, so changing it
silently would make paper results incomparable to the backtest — the specific failure this
module exists to prevent. But the finding is significant on its own terms: the validated result
was achieved *despite* spending much of 2023-24 artificially throttled, which means the design
may be leaving return on the table rather than earning it.

**MEASURED 2026-10-13 (EXP-0020 FINDING-3) — and my framing above was wrong.** Removing the
artifact raises the ₹50k outcome from ₹49,20,067 to ₹65,36,373 (+32.9%) and cuts reduced
months from 16/34 to 9/34 — but max drawdown rises from 31.9% to **46.2%**, about 14
percentage points.

So the artifact is not "leaving return on the table". It is functioning as an *unintended
drawdown brake*, and removing it is a return-for-risk trade, not a correction. Keep
`PER_TRADE` as the default on that basis as well as on faithfulness grounds. If the artifact
is ever removed deliberately, it should be replaced by an explicit risk control rather than
simply deleted, and that is a risk-limit change under AGENTS.md §6.

**Correction to this entry's own history**: a third divergence turned up while building the
EXP-0020 harness. `lot_manager.py` had been incrementing the lot-cap growth streak on any
profitable month; exp_0017 increments it **only at the 1.00x tier**, so profitable months
during a drawdown neither increment nor reset it and nothing accrues to spend on recovery.
Fixed, with a regression test. The documented rule ("+5 every 3 consecutive profitable months
AT the 1.00x tier") reads as though a streak banks during drawdown. It does not.

**Review trigger**: Before TASK-1 paper wiring. RISK-8 (no intra-position drawdown tracking)
is separate and still open.

---

## DECISION-010 — 2026-10-13: Validated Sizing Exceeds Configured Risk Limits (OPEN — NEEDS HUMAN DECISION)

**Status**: OPEN. No decision made. This is a risk-limit question, which AGENTS.md section 6
reserves for a human, recorded here, and committed as a config change.

**Context**: The validated EXP-0017 stack and `config/risk.yaml` disagree on two numbers:

| Parameter | EXP-0017 validated design | config/risk.yaml | Ratio |
|---|---|---|---|
| Capital deployed per trade | 30% | `max_capital_deployed_pct: 25.0` | 1.2x |
| Lots per order | 10 (paper) → 20 (live), growing to 25-35 | `hard_cap_lots: 10` | up to 3.5x |

So the validated stack cannot legally run under the current risk config. The ₹49.2L projection
assumes 30% deployment and caps up to 35 lots; the config permits 25% and 10 lots.

**Options**: (a) raise the config to match the validated design, accepting the measured 44.1%
max drawdown; (b) keep the config and re-run EXP-0017 at 25%/10 lots to get honest projections
for what is actually permitted; (c) stage the limits upward across paper → shadow → live.

**Recommendation**: (b) then (c). The ₹49.2L figure is not a projection of the system as
configured, and raising limits to match a backtest — rather than raising them because
validated behaviour earned it — is the failure mode AGENTS.md section 14 warns about. Note
`hard_cap_lots` also carries a standing instruction to verify the NIFTY freeze quantity via
Upstox before trusting it.

**MEASURED 2026-10-13 (EXP-0020)** — (b) was carried out. The decision is still the human's,
but it is now an informed one, and the shape of it changed:

| Config | Net (₹50k start) | Max DD | vs validated |
|---|---|---|---|
| Validated (30%, 20→35 lots) | ₹49,20,067 | 31.9% | — |
| **Compliant as written (25%, 10 lots)** | **₹28,23,528** | **23.7%** | −42.6% |
| 25% deployment, lots uncapped | ₹49,37,019 | 32.0% | **+0.3%** |
| 30% deployment, 10-lot cap | ₹28,22,968 | 24.5% | −42.6% |
| Staged: 25%, 20-lot ceiling | ₹39,46,180 | 23.7% | −19.8% |
| Staged: 25%, 35-lot ceiling | ₹41,55,673 | 23.7% | −15.6% |

**The 25% deployment limit costs nothing** — it is marginally better than 30%. The entire
42.6% shortfall is `hard_cap_lots: 10`. So this was never a two-parameter conflict.

**Revised recommendation**: adopt 25% deployment permanently and stop treating it as a
concession. Treat `hard_cap_lots` as the single staged parameter: 10 (paper) → 20 (shadow) →
35 (live), each step earned by validated behaviour. The 35-lot ceiling returns 84% of the
validated outcome at 23.7% max drawdown versus 31.9% — better risk-adjusted than the design
it concedes from, so there is no case for ever raising deployment to 30%.

**Also**: stop quoting ₹49.2L as the expected outcome. It describes a configuration that has
never been permitted to run. Under the compliant config the three-year figure is ₹28.2L.

**Freeze quantity: RESOLVED 2026-10-13.** Upstox's published instrument master reports
`freeze_quantity` 3510 with `lot_size` 65 for all 1,888 NIFTY option contracts, so the
exchange ceiling is **54 lots per order**. Both staged ceilings are executable, and
`hard_cap_lots: 10` was never an exchange constraint — it is a self-imposed margin ~5x
tighter. Recorded in `config/risk.yaml` with a note to re-verify at each series rollover,
since the ceiling moves with lot size.

**Distribution: MEASURED 2026-10-13 (EXP-0021), and it changed the argument.** 2,000-path
month-block bootstrap, all arms on identical paths:

| Arm | p5 | median | medDD | P(ruin) |
|---|---|---|---|---|
| Validated (30%, uncapped) | ₹14.3L | ₹42.6L | 30.6% | **16.4%** |
| Compliant (25%, 10 lots) | ₹12.5L | ₹26.1L | 23.4% | **9.5%** |
| Staged (25%, 20 lots) | ₹12.0L | ₹32.9L | 26.8% | **9.5%** |
| Staged (25%, 35 lots) | ₹11.9L | ₹34.1L | 27.5% | **9.5%** |

The single-path claim that staging is *better risk-adjusted* does not survive resampling and
is withdrawn: the uncapped arm dominates on terminal wealth at every percentile and its
drawdown edge shrinks to ~3pp. **The real case for capping is ruin risk** — 16.4% → 9.5% —
and that reduction is *identical at 10, 20 and 35 lots*. Cap level does not affect P(ruin).

**Final recommendation (unchanged in substance, corrected in reasoning)**: keep 25%
deployment; stage `hard_cap_lots` 10 → 20 → 35. Staging to 35 rather than complying at 10
buys +31% median return at the same 9.5% ruin probability. But be clear what the capped-vs-
uncapped decision costs: **roughly 20% of median terminal wealth for a 42% cut in ruin
probability.** That is a judgement about ruin tolerance, not a free optimisation.

**Remaining caveats**: G1 still flatters the uncapped arm (it reaches the largest positions),
so its dominance is if anything overstated. And month blocks are drawn independently, so if
bad months cluster in reality more than independent draws imply, every tail here is
optimistic — the uncapped arm's most of all. EXP-0022 is proposed to relax that.

**Impact until resolved**: `LotManagerConfig.from_risk_config()` raises `RiskLimitConflict`
rather than clamping, so this conflict surfaces at construction instead of silently halving
exposure mid-run. Two tests pin that behaviour.

**Review trigger**: Before TASK-1 paper wiring. Blocks it.

---

## DECISION-011 — 2026-10-13: Config Environment Separation Deferred (OPEN — NEEDS HUMAN DECISION)

**Status**: OPEN. No change made.

**Context**: AGENTS.md section 6 states "Risk limits live in `configs/production/risk.yaml`"
and marks the rule NON-NEGOTIABLE. No `configs/` directory exists. There is a flat `config/`
with `instruments.yaml`, `risk.yaml`, `ml.yaml`, read by `core/config_loader.py`. CLAUDE.md
documented the five-environment layout as though it existed.

The practical consequence: **paper and live read the same `risk.yaml`.** There is no mechanism
by which a paper-trading limit change cannot alter live limits, and the separation the
constitution assumes is absent.

**Decision**: Deferred. Creating `configs/{development,research,paper,shadow,production}/`
means changing `config_loader.py`, which sits on the live path — an architecture change
requiring approval under AGENTS.md section 13. CLAUDE.md has been corrected to describe the
actual layout and flag the gap rather than imply the structure exists.

**Rationale**: Documenting a known gap accurately is safer than an unapproved migration of the
config loader. But this should not stay open long: the gate sequence reaches SHADOW, where
paper and live configs coexist and sharing one file becomes actively dangerous.

**Review trigger**: Before the PAPER → SHADOW transition at the latest.

---

## DECISION-012 — 2026-10-13: Lot Manager Activated for Paper Trading Only

**Context**: DECISION-007 built the lot manager and deliberately left it unwired, stating
that activation would be a separate explicit decision. The operator has asked to begin paper
trading, which is that decision.

**Decision**: `src/astra/risk/lot_manager.py` is now wired into
`scripts/run_paper_astra.py` — and **only** there. `scripts/run_live.py` and
`live/orchestrator.py` remain untouched. No real order path can reach it.

**Scope of what was activated**:
- P70_L40d adaptive ATR regime gate (`src/astra/alpha/regime_filter.py`, EXP-0010/0011)
- VIX bucket size tilt (`src/astra/risk/vix_sizing.py`, EXP-0015)
- Step-down 4-tier lot engine with cap growth (EXP-0017)
- Running at `config/risk.yaml` as written: 25% deployment, `hard_cap_lots: 10`

**Not activated**: the VIX×1.1 IV model (EXP-0014). Paper trading fetches real option quotes
from the broker, so the session *tests* the IV model rather than depending on it. That is a
large part of the point of paper trading.

**Rationale**: No risk limit was changed, so this needs no section 6 decision. Paper mode
places no real orders, so it is not the live execution path of section 13. The sizing engine
is exercised inside a simulator against real market data, which is exactly the validation
step the gate sequence calls for before SHADOW.

**Two deliberate deviations from the research, both fail-safe**:
1. **VIX fallback.** The research used `except: pctile = 50.0` on a VIX lookup failure — and
   50.0 is the bottom edge of the sweet spot, so that fallback sizes **up** to 1.5x. Harmless
   with a complete backtest file; the wrong direction on a live feed hiccup. An unresolvable
   VIX now returns None and sizes 1.0x. No recorded result is affected, because the research
   scripts compute their percentiles inline and do not import this module.
2. **Integer lots.** The research applied the VIX multiplier to per-lot P&L, equivalent to
   trading `lots × mult` with no rounding. Live lots are integral, so the multiplier
   truncates — at 1-2 lots a 1.5x tilt rounds away entirely. This biases toward smaller
   positions, the safe direction.

**Impact / what this session actually measures**: at ₹20,000-50,000 with 25% deployment and
~₹6,500 average premium per lot, the engine sizes **1 lot per trade**. The step-down tiers and
the VIX tilt are therefore close to inert for the first months — they only bite at larger
capital. The number worth measuring is **realised ₹/trade against the backtest's ₹307/lot**.
The lot-scaling machinery is wired and tested but will not be meaningfully exercised yet.

**Review trigger**: After 3 paper months, or before any SHADOW transition. Wiring into
`run_live.py` remains a separate decision and is NOT covered by this entry.

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
