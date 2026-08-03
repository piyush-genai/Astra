"""
Shared indicator formula library.

Implements:
- Classic floor-trader pivot points (Daily / Weekly / Monthly)
- Central Pivot Range (Daily)
- build_pivot_table(): no-look-ahead pivot table from daily OHLC
- Confluence zone detection

Formulas match CM_Pivots_Filtered (Filtered OFF, D/W/M enabled) and
CD_PivotR exactly as configured in the TradingView chart settings.

Rules:
- All formulas implemented directly with pandas/numpy arithmetic.
- No black-box TA libraries.
- Unit tests in tests/strategies/test_indicators.py verify against
  hand-computed values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Core pivot formulas
# ---------------------------------------------------------------------------

def classic_pivot(high: float, low: float, close: float) -> dict:
    """
    Standard floor-trader pivot points.
    P, R1, S1, R2, S2 — confirmed formula (Filtered toggle OFF).
    """
    p = (high + low + close) / 3.0
    return {
        "P":  p,
        "R1": 2 * p - low,
        "S1": 2 * p - high,
        "R2": p + (high - low),
        "S2": p - (high - low),
    }


def cpr(high: float, low: float, close: float) -> dict:
    """Central Pivot Range — matches CD_PivotR (Daily only)."""
    p  = (high + low + close) / 3.0
    bc = (high + low) / 2.0
    tc = 2 * p - bc
    if tc < bc:
        tc, bc = bc, tc
    return {"P": p, "BC": bc, "TC": tc, "width": abs(tc - bc)}


def _pivot_frame(ohlc: pd.DataFrame, formula) -> pd.DataFrame:
    """
    Apply a pivot formula row-wise to a frame with columns
    [high, low, close], returning one output column per level.
    NaN rows (from .shift()) are passed through as NaN rows.
    """
    records = []
    for r in ohlc.itertuples():
        if pd.isna(r.high):
            records.append({k: float("nan") for k in formula(0, 0, 0)})
        else:
            records.append(formula(r.high, r.low, r.close))
    return pd.DataFrame(records, index=ohlc.index)


# ---------------------------------------------------------------------------
# No-look-ahead pivot table builder
# ---------------------------------------------------------------------------

def build_pivot_table(daily_ohlc: pd.DataFrame) -> pd.DataFrame:
    """
    Build a daily pivot table with no look-ahead bias.

    Args:
        daily_ohlc: DataFrame indexed by trading date (DatetimeIndex),
                    columns [open, high, low, close] — one row per Nifty
                    session, real trading days only (holidays simply absent).

    Returns:
        One row per trading day with every level "live" that day:
        daily_P/R1/R2/S1/S2, weekly_*, monthly_*, cpr_P/BC/TC/width.

    Implementation notes:
    - Daily:   .shift(1) on the raw frame → yesterday's close drives today's levels.
    - Weekly:  group by W-FRI period, .shift(1) on the period frame, reindex back
               to daily. Every trading day in week W gets week W-1's levels.
    - Monthly: same pattern with month-end periods.
    - Grouping uses to_period() so holidays inside a week/month don't create
      phantom partial periods.
    """
    df = daily_ohlc[["high", "low", "close"]].copy()
    df.columns = [c.lower() for c in df.columns]

    # ── Daily ────────────────────────────────────────────────────────────────
    daily     = _pivot_frame(df.shift(1), classic_pivot).add_prefix("daily_")
    daily_cpr = _pivot_frame(df.shift(1), cpr).add_prefix("cpr_")

    # ── Weekly ───────────────────────────────────────────────────────────────
    # Strip timezone before to_period() to avoid the "will drop timezone" warning;
    # we restore the original index when reindexing back.
    tz_naive_index = df.index.tz_localize(None) if df.index.tz is None else df.index.tz_convert(None)
    week_key    = tz_naive_index.to_period("W-FRI")
    weekly_ohlc = df.groupby(week_key).agg(
        high=("high", "max"), low=("low", "min"), close=("close", "last")
    )
    weekly_prev = weekly_ohlc.shift(1)
    weekly_piv  = _pivot_frame(weekly_prev, classic_pivot).add_prefix("weekly_")
    weekly      = weekly_piv.reindex(week_key).set_axis(df.index)

    # ── Monthly ──────────────────────────────────────────────────────────────
    month_key    = tz_naive_index.to_period("M")
    monthly_ohlc = df.groupby(month_key).agg(
        high=("high", "max"), low=("low", "min"), close=("close", "last")
    )
    monthly_prev = monthly_ohlc.shift(1)
    monthly_piv  = _pivot_frame(monthly_prev, classic_pivot).add_prefix("monthly_")
    monthly      = monthly_piv.reindex(month_key).set_axis(df.index)

    return pd.concat([daily, weekly, monthly, daily_cpr], axis=1)


# ---------------------------------------------------------------------------
# Confluence zone detection
# ---------------------------------------------------------------------------

# Every level column produced by build_pivot_table() that counts as
# "a line on the chart" for confluence purposes.
LEVEL_COLUMNS = [
    "daily_R2",  "daily_R1",  "daily_P",  "daily_S1",  "daily_S2",
    "weekly_R2", "weekly_R1", "weekly_P", "weekly_S1", "weekly_S2",
    "monthly_R2","monthly_R1","monthly_P","monthly_S1","monthly_S2",
    "cpr_TC", "cpr_P", "cpr_BC",
]


# ---------------------------------------------------------------------------
# Zone grouping and confluence detection
# ---------------------------------------------------------------------------

def _level_group(level_name: str) -> str:
    """
    Return which independent lookback basis a level comes from.
    
    Daily and CPR levels derive from the SAME prior day's OHLC — one piece 
    of evidence, not two — so they share a group. This prevents the bug where
    daily_P and cpr_P (which are mathematically identical: (H+L+C)/3 from the
    same day's OHLC) get counted as two independent confirmations.
    """
    if level_name.startswith("daily_") or level_name.startswith("cpr_"):
        return "daily"
    if level_name.startswith("weekly_"):
        return "weekly"
    if level_name.startswith("monthly_"):
        return "monthly"
    return level_name


@dataclass
class Zone:
    price_low:  float
    price_high: float
    members:    list = field(default_factory=list)  # pivot level names in this zone
    anchor:     float = 0.0   # first (lowest) member price — used for tolerance check

    @property
    def center(self) -> float:
        return (self.price_low + self.price_high) / 2

    @property
    def is_confluence(self) -> bool:
        """
        True only when 2+ DIFFERENT independent timeframes contribute.
        
        A zone with ['daily_P', 'cpr_P', 'cpr_BC'] has only ONE independent
        source (all from yesterday's OHLC) → NOT confluence.
        
        A zone with ['daily_R1', 'weekly_R1'] has TWO independent sources
        (different lookback windows) → IS confluence.
        """
        return len({_level_group(m) for m in self.members}) >= 2
    
    @property
    def is_daily_cpr_only(self) -> bool:
        """
        True when zone is formed ONLY from daily/CPR levels (single-timeframe).
        These are still tradeable — CPR is heavily watched in Indian markets.
        """
        groups = {_level_group(m) for m in self.members}
        return groups == {"daily"} and len(self.members) >= 2


def find_zones(
    day_levels: pd.Series,
    tolerance_pct: float = 0.18,   # expressed as %, e.g. 0.18 = 0.18%
) -> list[Zone]:
    """
    Cluster all pivot levels active on a given day into confluence zones.

    Args:
        day_levels:    One row from build_pivot_table() output.
        tolerance_pct: Levels within this % of the zone anchor are grouped
                       together. 0.18% (~32 pts on Nifty at 18000) is the
                       starting value — calibrate against backtest results.

    Returns:
        List of Zone objects sorted low-to-high.

    Note: new members are compared against the zone's ANCHOR (its first/
    lowest member), not against the running edge — prevents tolerance
    chaining stretching a zone wider than intended.
    """
    tolerance = tolerance_pct / 100.0

    values = sorted(
        (day_levels[col], col)
        for col in LEVEL_COLUMNS
        if col in day_levels.index and pd.notna(day_levels[col])
    )

    zones: list[Zone] = []
    for price, name in values:
        if zones and price <= zones[-1].anchor * (1 + tolerance):
            zones[-1].price_high = max(zones[-1].price_high, price)
            zones[-1].members.append(name)
        else:
            zones.append(Zone(
                price_low=price,
                price_high=price,
                members=[name],
                anchor=price,
            ))
    return zones


def zone_above(zones: list[Zone], price: float) -> Optional[Zone]:
    """Return the nearest zone whose low is above price."""
    above = [z for z in zones if z.price_low > price]
    return min(above, key=lambda z: z.price_low) if above else None


def zone_below(zones: list[Zone], price: float) -> Optional[Zone]:
    """Return the nearest zone whose high is below price."""
    below = [z for z in zones if z.price_high < price]
    return max(below, key=lambda z: z.price_high) if below else None
