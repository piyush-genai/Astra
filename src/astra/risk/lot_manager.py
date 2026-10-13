"""
Compounding lot sizing with step-down drawdown tiers (TASK-5 / EXP-0017 winner "D_steps").

This module implements the validated compounding engine: how many lots to trade given
current capital, how the lot-cap grows with sustained profitability, and how exposure
steps down as drawdown from the high-water mark deepens.

NOT WIRED INTO ANY EXECUTION PATH. Nothing imports this yet. AGENTS.md section 13
requires human approval before a change to position sizing reaches a path that can place
orders, so activation is deliberately left as a separate, explicit step. See
docs/decisions/DECISION_LOG.md DECISION-008.

─── The formula discrepancy this module resolves ───────────────────────────────────

CLAUDE.md, HANDOFF.md and ASTRA_STATUS.md all write the sizing rule with the drawdown
multiplier applied to the *capital* term, in one of two orderings:

    HANDOFF/ASTRA_STATUS:  lots = min(floor(net_capital × 0.30 / premium × dd_mult), cap)
    CLAUDE.md:             lots = min(floor(net_capital × 0.30 / premium) × dd_mult, cap)

Neither can reproduce EXP-0017's own recorded recovery narrative. That record states
"Oct-Dec 2023 ... 7 lots at 0.35x tier (step-down: 0.35x × 20 = 7 lots max)" and
"Jul 2024: ... recovered to 1.00x → 20 lots restored". With a cap of 20, both written
forms yield 20 whenever the capital term exceeds the cap — they can never yield 7,
because the min() clamps to the unscaled cap. The figure 7 is reachable only if the
multiplier scales the cap itself:

    effective_cap = floor(max_lots_cap × dd_mult)      # 0.35 × 20 = 7  ✓
    lots          = min(capital_lots, effective_cap)

This also reconciles the 0.12x tier ("2-8 lots": floor(20 × 0.12) = 2 at the original
cap, rising as the cap grows) and April 2025 at 25 lots. So the implementation that
produced the validated results applied the multiplier to the cap, and all three written
formulas are wrong.

`DrawdownApplication.CAP_SCALED` is therefore the default. `CAPITAL_SCALED` implements
the documented-but-unverified form, kept so the two can be compared directly once the
2023-2025 data is restored and EXP-0017 can actually be re-run. Until then, treat
CAP_SCALED as "consistent with the recorded results" rather than "proven correct" —
no execution of the original experiment was available to confirm either form.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence


class RiskLimitConflict(ValueError):
    """
    Raised when a requested sizing configuration exceeds the limits in config/risk.yaml.

    Deliberately fatal rather than clamping. Silently reducing exposure to fit the config
    would make a paper run diverge from the backtest it is meant to validate, with nothing
    in the logs to explain the gap.
    """


class DrawdownApplication(str, Enum):
    CAP_SCALED = "cap_scaled"          # multiplier scales max_lots_cap (matches EXP-0017 results)
    CAPITAL_SCALED = "capital_scaled"  # multiplier scales the capital term (matches the written docs)


class HwmMarking(str, Enum):
    """
    When the high-water mark is re-marked.

    PER_TRADE is the default because it is what `exp_0017_drawdown_management.py` — the
    script that produced the validated ₹49.2L result — actually does: it re-marks the peak
    inside the trade loop (`if net_cap > hwm: hwm = net_cap`), as well as at month close.
    EXP-0016 re-marked only at month close; EXP-0017 changed this, and EXP-0017 is the run
    the production recommendation rests on.

    This carries a real artifact, verified in the reproduced EXP-0017 monthly log. The HWM
    is marked on capital that has not yet had that month's tax withheld; at month close 30%
    of the month's profit moves to the tax reserve, net capital drops below the peak, and
    the engine registers a drawdown it never actually suffered. In the validated run,
    2023-03 posts +₹116,587 and sits at 0.65x; 2023-05 posts +₹509,869 and sits at 0.35x.
    Strongly profitable months demote the engine for purely accounting reasons, which is
    why 16 of 34 months are in reduced mode.

    So the ₹49.2L result was achieved *despite* spending much of 2023-24 artificially
    throttled. Correcting it may well improve the outcome — but that is a new experiment,
    not a silent default change, because the projections on record assume this behaviour.
    MONTH_CLOSE is retained to run that comparison. See DECISION-009.
    """

    PER_TRADE = "per_trade"
    MONTH_CLOSE = "month_close"


# Step-down 4-tier table from EXP-0017 config D_steps, as (drawdown_below, lot_multiplier).
# Evaluated in order; the final entry must be unbounded.
STEP_DOWN_TIERS: tuple[tuple[float, float], ...] = (
    (0.15, 1.00),   # normal operation — full lots
    (0.25, 0.65),   # caution
    (0.40, 0.35),   # defense
    (math.inf, 0.12),  # crisis minimum
)


@dataclass(frozen=True)
class LotManagerConfig:
    """Sizing policy. Frozen — a live change to these numbers is a governance event."""

    risk_per_trade_pct: float = 30.0
    initial_max_lots: int = 10          # 10 for paper, 20 for live per CLAUDE.md
    lot_step: int = 5                   # cap grows by this much...
    consec_months_for_step: int = 3     # ...every this many consecutive profitable months
    tax_rate_pct: float = 30.0
    premium_floor_per_lot: float = 500.0
    hard_cap_lots: int | None = None    # absolute ceiling from risk.yaml; None = unenforced
    max_capital_deployed_pct: float | None = None  # ceiling from risk.yaml
    tiers: tuple[tuple[float, float], ...] = STEP_DOWN_TIERS
    dd_application: DrawdownApplication = DrawdownApplication.CAP_SCALED
    hwm_marking: HwmMarking = HwmMarking.PER_TRADE

    def __post_init__(self) -> None:
        if self.tiers[-1][0] != math.inf:
            raise ValueError("final drawdown tier must be unbounded (math.inf)")
        if not 0 < self.risk_per_trade_pct <= 100:
            raise ValueError(f"risk_per_trade_pct out of range: {self.risk_per_trade_pct}")
        if self.initial_max_lots < 1:
            raise ValueError(f"initial_max_lots must be >= 1, got {self.initial_max_lots}")

        # Fail loud when the validated design asks for more than the config permits. Both
        # of these currently conflict for the EXP-0017 stack (30% vs 25%, 20 lots vs 10).
        if (
            self.max_capital_deployed_pct is not None
            and self.risk_per_trade_pct > self.max_capital_deployed_pct
        ):
            raise RiskLimitConflict(
                f"risk_per_trade_pct={self.risk_per_trade_pct} exceeds "
                f"max_capital_deployed_pct={self.max_capital_deployed_pct} from config/risk.yaml. "
                "Reconciling these is a risk-limit decision (AGENTS.md section 6): it requires a "
                "human decision, a DECISION_LOG.md entry, and a committed config change."
            )
        if self.hard_cap_lots is not None and self.initial_max_lots > self.hard_cap_lots:
            raise RiskLimitConflict(
                f"initial_max_lots={self.initial_max_lots} exceeds "
                f"hard_cap_lots={self.hard_cap_lots} from config/risk.yaml. "
                "See AGENTS.md section 6."
            )

    @classmethod
    def from_risk_config(
        cls, risk_cfg: dict[str, Any], **overrides: Any
    ) -> "LotManagerConfig":
        """
        Build a config whose ceilings come from config/risk.yaml.

        Raises RiskLimitConflict if the requested sizing exceeds those ceilings, so a
        mismatch between the validated design and the configured limits surfaces at
        construction time rather than at order time.
        """
        per_trade = risk_cfg.get("per_trade", {})
        limits = risk_cfg.get("position_limits", {})
        return cls(
            hard_cap_lots=limits.get("hard_cap_lots"),
            max_capital_deployed_pct=per_trade.get("max_capital_deployed_pct"),
            **overrides,
        )


@dataclass
class LotManager:
    """
    Tracks capital, tax reserve, high-water mark and lot cap across a compounding run.

    Usage per trading month:
        for each trade:   mgr.lots_for(premium_per_lot)  →  mgr.record_trade_pnl(pnl)
        at month end:     mgr.close_month()
    """

    config: LotManagerConfig = field(default_factory=LotManagerConfig)
    gross_capital: float = 20_000.0
    tax_reserve: float = 0.0

    _hwm: float = field(init=False)
    _max_lots_cap: int = field(init=False)
    _consecutive_profitable_months: int = field(init=False, default=0)
    _month_pnl: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        self._hwm = self.net_capital
        self._max_lots_cap = self.config.initial_max_lots

    # ── state ────────────────────────────────────────────────────────────────────────

    @property
    def net_capital(self) -> float:
        """Capital available for sizing. The tax reserve is withheld and never sized on."""
        return self.gross_capital - self.tax_reserve

    @property
    def high_water_mark(self) -> float:
        return self._hwm

    @property
    def max_lots_cap(self) -> int:
        return self._max_lots_cap

    @property
    def consecutive_profitable_months(self) -> int:
        return self._consecutive_profitable_months

    @property
    def drawdown(self) -> float:
        """Fractional drawdown of net capital from its high-water mark, floored at 0."""
        if self._hwm <= 0:
            return 0.0
        return max(0.0, (self._hwm - self.net_capital) / self._hwm)

    @property
    def dd_multiplier(self) -> float:
        dd = self.drawdown
        for upper_bound, multiplier in self.config.tiers:
            if dd < upper_bound:
                return multiplier
        return self.config.tiers[-1][1]  # unreachable: final tier is unbounded

    @property
    def at_full_tier(self) -> bool:
        """True when operating at the 1.00x tier. Gates lot-cap growth."""
        return self.dd_multiplier >= 1.0

    @property
    def effective_lot_cap(self) -> int:
        """The lot cap actually in force, after the drawdown tier is applied."""
        if self.config.dd_application is DrawdownApplication.CAP_SCALED:
            cap = math.floor(self._max_lots_cap * self.dd_multiplier)
        else:
            cap = self._max_lots_cap
        return max(1, cap)

    # ── sizing ───────────────────────────────────────────────────────────────────────

    def mark_hwm(self) -> None:
        """
        Re-mark the high-water mark against current net capital.

        Called automatically by lots_for() under PER_TRADE marking, and by close_month()
        in every mode. Exposed publicly because the *timing* of this call changes results:
        see the comment in lots_for().
        """
        self._hwm = max(self._hwm, self.net_capital)

    def lots_for(self, premium_per_lot: float) -> int:
        """
        Lot count for one trade at the given premium.

        Never returns 0: if a trade is taken at all it is taken at a minimum of 1 lot.
        Deciding *whether* to trade belongs to the Decision Plane, not here.
        """
        if premium_per_lot <= 0:
            raise ValueError(f"premium_per_lot must be positive, got {premium_per_lot}")

        # Mark the HWM immediately BEFORE sizing, which is what exp_0017's trade loop does
        # (`if net_cap > hwm: hwm = net_cap` precedes the dd computation). The ordering is
        # load-bearing, not incidental: marking after the trade's P&L instead captures the
        # last trade of each month as a peak that month-end withholding then undercuts,
        # deepening every drawdown tier by a notch. Verified against EXP-0017 — the wrong
        # ordering shifts 2023-03 from 0.65x to 0.35x and costs ~0.7% over three years.
        if self.config.hwm_marking is HwmMarking.PER_TRADE:
            self.mark_hwm()

        # Floor the premium so a deep-OTM quote cannot inflate the lot count (HANDOFF G2).
        premium = max(premium_per_lot, self.config.premium_floor_per_lot)
        budget = self.net_capital * (self.config.risk_per_trade_pct / 100.0)

        if self.config.dd_application is DrawdownApplication.CAPITAL_SCALED:
            budget *= self.dd_multiplier

        capital_lots = math.floor(budget / premium)
        return max(1, min(capital_lots, self.effective_lot_cap))

    # ── bookkeeping ──────────────────────────────────────────────────────────────────

    def record_trade_pnl(self, pnl: float) -> None:
        """
        Apply one closed trade's P&L.

        Drawdown responds immediately, since net capital moves with every trade. The HWM
        is deliberately NOT re-marked here — lots_for() marks it before sizing instead,
        for the ordering reason documented there. Note RISK-8: drawdown *within* an open
        position is still invisible, so a fast adverse move can breach a tier boundary
        without the lot count reacting until the position closes.
        """
        self.gross_capital += pnl
        self._month_pnl += pnl
        # Capital floor mirrors the EXP-0016/0017 simulations, which clamped at ₹500 to
        # keep a wiped account from producing nonsense lot counts.
        self.gross_capital = max(self.gross_capital, 500.0)

    def close_month(self) -> dict[str, Any]:
        """
        Settle the month: withhold tax, update the profitable-month streak, grow the cap.

        The cap grows only while at the 1.00x tier, so a streak accumulated during a
        drawdown recovery cannot enlarge exposure while the strategy is still impaired.
        Returns a summary row suitable for a monthly log.
        """
        month_pnl = self._month_pnl
        tax_withheld = 0.0

        if month_pnl > 0:
            tax_withheld = month_pnl * (self.config.tax_rate_pct / 100.0)
            self.tax_reserve += tax_withheld

        # Re-mark the HWM on post-withholding net capital, matching the order in
        # exp_0016_compounded_equity.py: the peak is updated first, then the tier is
        # evaluated against it. Doing this before the growth gate matters — otherwise a
        # month that sets a new high is still judged against the stale peak.
        self._hwm = max(self._hwm, self.net_capital)

        # Streak semantics follow exp_0017 exactly: a profitable month counts ONLY while at
        # the 1.00x tier. A profitable month taken at a reduced tier neither increments nor
        # resets it — so no streak accrues during a drawdown recovery and there is nothing
        # "banked" to spend on the way out. A losing month always resets.
        if month_pnl > 0 and self.at_full_tier:
            self._consecutive_profitable_months += 1
        elif month_pnl <= 0:
            self._consecutive_profitable_months = 0

        grew = False
        if self._consecutive_profitable_months >= self.config.consec_months_for_step:
            proposed = self._max_lots_cap + self.config.lot_step
            if self.config.hard_cap_lots is not None:
                proposed = min(proposed, self.config.hard_cap_lots)
            grew = proposed > self._max_lots_cap
            self._max_lots_cap = proposed
            # Reset the streak only when it is actually spent, so a cap sitting at the
            # hard ceiling does not silently burn qualifying months.
            if grew:
                self._consecutive_profitable_months = 0

        self._month_pnl = 0.0

        return {
            "month_pnl": round(month_pnl, 2),
            "tax_withheld": round(tax_withheld, 2),
            "gross_capital": round(self.gross_capital, 2),
            "net_capital": round(self.net_capital, 2),
            "tax_reserve": round(self.tax_reserve, 2),
            "drawdown_pct": round(self.drawdown * 100, 2),
            "dd_multiplier": self.dd_multiplier,
            "max_lots_cap": self._max_lots_cap,
            "effective_lot_cap": self.effective_lot_cap,
            "consecutive_profitable_months": self._consecutive_profitable_months,
            "cap_grew": grew,
        }


def dd_multiplier_for(
    drawdown: float, tiers: Sequence[tuple[float, float]] = STEP_DOWN_TIERS
) -> float:
    """Standalone tier lookup, for callers that hold no LotManager state."""
    if drawdown < 0:
        raise ValueError(f"drawdown must be non-negative, got {drawdown}")
    for upper_bound, multiplier in tiers:
        if drawdown < upper_bound:
            return multiplier
    return tiers[-1][1]
