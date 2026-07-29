"""
PivotCprStrategy — Pivot + CPR Confluence on Nifty 15m.

Implements the BaseStrategy interface. Evaluates each 15m bar for
confluence of daily, weekly, and monthly pivot/CPR levels.

Stage 1 (tasks 1–5 of pivot-cpr-strategy spec):
  Indicator computation + zone detection + monthly bias — logged, no Signal emitted.

Stage 2 (task 7 — BLOCKED until task 6 operator input):
  Full Signal emission after the exact entry trigger and session filter are specified.

See .kiro/specs/pivot-cpr-strategy/requirements.md for the full spec.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from src.data.indicators import (
    CPR,
    PivotSet,
    compute_cpr,
    compute_pivot_set,
    get_prior_period_hlc,
    group_levels_into_zones,
    resample_to_daily,
    resample_to_monthly,
    resample_to_weekly,
    zone_midpoint,
)
from src.engine.base_strategy import BaseStrategy, MarketData, Signal, SignalDirection

logger = logging.getLogger(__name__)


class PivotCprStrategy(BaseStrategy):
    """
    Nifty 50 / 15-minute Pivot + CPR confluence strategy.

    Config keys:
        confluence_tolerance_pct (float): tolerance for grouping levels into zones.
            Default 0.15. Marked TBD/calibratable in the spec — do not treat as final.
        min_levels_for_confluence (int): minimum number of levels in a zone
            to consider it a valid confluence zone. Default 2.
    """

    STRATEGY_ID = "pivot_cpr_strategy"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        # Read from config — never hardcoded.
        self._tolerance_pct: float = float(config.get("confluence_tolerance_pct", 0.15))
        self._min_levels: int = int(config.get("min_levels_for_confluence", 2))

        logger.info(
            "PivotCprStrategy initialised | tolerance=%.3f%% | min_levels=%d",
            self._tolerance_pct,
            self._min_levels,
        )

    # ------------------------------------------------------------------
    # BaseStrategy contract
    # ------------------------------------------------------------------

    def evaluate(self, market_data: MarketData) -> Optional[Signal]:
        """
        Stage 1: compute indicators, detect zones, log. No Signal emitted yet.
        Stage 2 is BLOCKED — see task 6 in the spec.
        """
        history = market_data.history
        if history is None or len(history) < 2:
            logger.debug("PivotCprStrategy: insufficient history at %s", market_data.bar_time)
            return None

        bar_time: pd.Timestamp = market_data.bar_time

        # ── Resample to daily / weekly / monthly ──────────────────────────
        daily_df = resample_to_daily(history)
        weekly_df = resample_to_weekly(history)
        monthly_df = resample_to_monthly(history)

        # ── Prior-period H/L/C ────────────────────────────────────────────
        d_hlc = get_prior_period_hlc(daily_df, as_of=bar_time)
        w_hlc = get_prior_period_hlc(weekly_df, as_of=bar_time)
        m_hlc = get_prior_period_hlc(monthly_df, as_of=bar_time)

        if d_hlc is None or w_hlc is None or m_hlc is None:
            logger.debug(
                "PivotCprStrategy: missing prior-period data at %s "
                "(d=%s w=%s m=%s)",
                bar_time,
                d_hlc is not None,
                w_hlc is not None,
                m_hlc is not None,
            )
            return None

        # ── Compute pivot sets and CPRs ───────────────────────────────────
        daily_pivots = compute_pivot_set(*d_hlc, period="daily")
        weekly_pivots = compute_pivot_set(*w_hlc, period="weekly")
        monthly_pivots = compute_pivot_set(*m_hlc, period="monthly")

        daily_cpr = compute_cpr(*d_hlc, period="daily")
        weekly_cpr = compute_cpr(*w_hlc, period="weekly")
        monthly_cpr = compute_cpr(*m_hlc, period="monthly")

        # ── Monthly bias ──────────────────────────────────────────────────
        # Monthly PP acts as a bias reference only — excluded from zone grouping.
        monthly_bias = _compute_monthly_bias(market_data.close, monthly_pivots.P)

        # ── Collect levels for confluence (exclude monthly PP from grouping) ──
        levels_for_confluence = _collect_levels(
            daily_pivots, weekly_pivots, daily_cpr, weekly_cpr
        )

        # ── Group into confluence zones ───────────────────────────────────
        zones = group_levels_into_zones(levels_for_confluence, self._tolerance_pct)
        strong_zones = [z for z in zones if len(z) >= self._min_levels]

        logger.debug(
            "PivotCprStrategy [%s] | close=%.2f | bias=%s | "
            "%d confluence zones (%d strong) | "
            "daily_PP=%.2f | daily_CPR=[%.2f-%.2f]",
            bar_time,
            market_data.close,
            monthly_bias,
            len(zones),
            len(strong_zones),
            daily_pivots.P,
            daily_cpr.BC,
            daily_cpr.TC,
        )

        # ── Stage 2 — BLOCKED ─────────────────────────────────────────────
        # Entry trigger and session filter not yet specified by operator.
        # See .kiro/specs/pivot-cpr-strategy/tasks.md task 6.
        # Do NOT implement signal emission here until task 6 is resolved.

        return None  # Stage 1 only — no signals yet.

    # ------------------------------------------------------------------
    # Debug / introspection (used by Stage 2 and backtest harness)
    # ------------------------------------------------------------------

    def compute_state(self, market_data: MarketData) -> dict:
        """
        Return the full indicator state for a bar without emitting a Signal.
        Used by the backtest harness and for debugging.
        """
        # Re-run the same logic as evaluate() but return structured output.
        history = market_data.history
        if history is None or len(history) < 2:
            return {}

        bar_time = market_data.bar_time
        daily_df = resample_to_daily(history)
        weekly_df = resample_to_weekly(history)
        monthly_df = resample_to_monthly(history)

        d_hlc = get_prior_period_hlc(daily_df, as_of=bar_time)
        w_hlc = get_prior_period_hlc(weekly_df, as_of=bar_time)
        m_hlc = get_prior_period_hlc(monthly_df, as_of=bar_time)

        if not all([d_hlc, w_hlc, m_hlc]):
            return {}

        daily_pivots = compute_pivot_set(*d_hlc, period="daily")
        weekly_pivots = compute_pivot_set(*w_hlc, period="weekly")
        monthly_pivots = compute_pivot_set(*m_hlc, period="monthly")
        daily_cpr = compute_cpr(*d_hlc, period="daily")
        weekly_cpr = compute_cpr(*w_hlc, period="weekly")
        monthly_cpr = compute_cpr(*m_hlc, period="monthly")

        monthly_bias = _compute_monthly_bias(market_data.close, monthly_pivots.P)
        levels = _collect_levels(daily_pivots, weekly_pivots, daily_cpr, weekly_cpr)
        zones = group_levels_into_zones(levels, self._tolerance_pct)
        strong_zones = [z for z in zones if len(z) >= self._min_levels]

        return {
            "bar_time": bar_time,
            "close": market_data.close,
            "monthly_bias": monthly_bias,
            "monthly_PP": monthly_pivots.P,
            "daily_pivots": daily_pivots,
            "weekly_pivots": weekly_pivots,
            "daily_cpr": daily_cpr,
            "weekly_cpr": weekly_cpr,
            "monthly_cpr": monthly_cpr,
            "all_zones": zones,
            "strong_zones": strong_zones,
            "strong_zone_midpoints": [zone_midpoint(z) for z in strong_zones],
        }


# ---------------------------------------------------------------------------
# Module-level helpers (pure functions)
# ---------------------------------------------------------------------------

def _compute_monthly_bias(current_price: float, monthly_pp: float) -> str:
    """
    Monthly bias based on price relative to monthly pivot.

    Returns "BULLISH" if price > monthly PP, "BEARISH" if below, "NEUTRAL" if equal.
    Monthly PP is used as a bias reference only — it is excluded from
    confluence-zone grouping (see spec design.md).
    """
    if current_price > monthly_pp:
        return "BULLISH"
    elif current_price < monthly_pp:
        return "BEARISH"
    return "NEUTRAL"


def _collect_levels(
    daily_pivots: PivotSet,
    weekly_pivots: PivotSet,
    daily_cpr: CPR,
    weekly_cpr: CPR,
) -> list[float]:
    """
    Flatten pivot and CPR levels into a single list for confluence grouping.

    Monthly PP is intentionally excluded — it is used for bias only.
    Monthly R/S levels and BC/TC are also excluded to keep the zone set
    focused on the most actively-watched intraday levels.
    Adjust this set based on backtesting results.
    """
    return [
        # Daily pivots
        daily_pivots.P,
        daily_pivots.R1, daily_pivots.R2, daily_pivots.R3,
        daily_pivots.S1, daily_pivots.S2, daily_pivots.S3,
        # Daily CPR
        daily_cpr.BC, daily_cpr.TC,
        # Weekly pivots
        weekly_pivots.P,
        weekly_pivots.R1, weekly_pivots.R2,
        weekly_pivots.S1, weekly_pivots.S2,
        # Weekly CPR
        weekly_cpr.BC, weekly_cpr.TC,
    ]
