"""
Shared indicator formula library.

Rules:
- All formulas implemented directly with pandas/numpy arithmetic.
- No black-box TA libraries (e.g. ta-lib, pandas-ta) for these formulas.
- The exact pivot and CPR formulas are the authoritative source of truth;
  unit tests in tests/strategies/test_indicators.py verify against
  hand-computed sample values from the spec.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PivotSet:
    """
    Standard floor-pivot levels computed from a single prior period's H/L/C.

    P  = (H + L + C) / 3
    R1 = 2P - L
    S1 = 2P - H
    R2 = P + (H - L)
    S2 = P - (H - L)
    R3 = H + 2(P - L)
    S3 = L - 2(H - P)
    """
    period: str        # e.g. "daily", "weekly", "monthly"
    P: float
    R1: float
    S1: float
    R2: float
    S2: float
    R3: float
    S3: float


@dataclass
class CPR:
    """
    Central Pivot Range: three levels derived from the prior period's H/L/C.

    BC  = (H + L + C) / 3 - (H + L) / 2     ... bottom of CPR
    TC  = (H + L + C) / 3 - BC + (H+L+C)/3  ... top of CPR
    PP  = (H + L + C) / 3                    ... pivot (= BC's reference)

    Simplified standard formulas:
        PP  = (H + L + C) / 3
        BC  = (H + L) / 2
        TC  = PP - BC + PP  = 2*PP - BC
    """
    period: str
    PP: float     # central pivot = (H+L+C)/3
    BC: float     # bottom of CPR = (H+L)/2
    TC: float     # top of CPR   = 2*PP - BC


# ---------------------------------------------------------------------------
# Core formula functions
# ---------------------------------------------------------------------------

def compute_pivot_set(high: float, low: float, close: float, period: str = "daily") -> PivotSet:
    """
    Compute standard floor-pivot levels from prior-period H/L/C.

    Args:
        high, low, close: Prior period's High, Low, Close.
        period: Label only ("daily", "weekly", "monthly").

    Returns:
        PivotSet with P, R1-R3, S1-S3.
    """
    P = (high + low + close) / 3.0
    R1 = 2 * P - low
    S1 = 2 * P - high
    R2 = P + (high - low)
    S2 = P - (high - low)
    R3 = high + 2 * (P - low)
    S3 = low - 2 * (high - P)
    return PivotSet(period=period, P=P, R1=R1, S1=S1, R2=R2, S2=S2, R3=R3, S3=S3)


def compute_cpr(high: float, low: float, close: float, period: str = "daily") -> CPR:
    """
    Compute the Central Pivot Range from prior-period H/L/C.

    Args:
        high, low, close: Prior period's High, Low, Close.
        period: Label only.

    Returns:
        CPR with PP, BC (bottom), TC (top).
    """
    PP = (high + low + close) / 3.0
    BC = (high + low) / 2.0
    TC = 2 * PP - BC
    # Ensure TC >= BC (they can coincide if H==C or L==C on a doji-like candle)
    if TC < BC:
        TC, BC = BC, TC
    return CPR(period=period, PP=PP, BC=BC, TC=TC)


# ---------------------------------------------------------------------------
# Resampling helpers
# ---------------------------------------------------------------------------

def resample_to_daily(df: pd.DataFrame) -> pd.DataFrame:
    """
    Resample an intraday OHLCV DataFrame to daily OHLCV.

    Args:
        df: DataFrame with DatetimeIndex (timezone-aware recommended),
            columns: open, high, low, close, volume (case-insensitive).

    Returns:
        Daily OHLCV DataFrame.
    """
    df = _normalize_columns(df)
    daily = df.resample("D").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna(subset=["open"])
    return daily


def resample_to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Resample intraday OHLCV to weekly (week ending Friday)."""
    df = _normalize_columns(df)
    weekly = df.resample("W-FRI").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna(subset=["open"])
    return weekly


def resample_to_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """Resample intraday OHLCV to monthly (month-end)."""
    df = _normalize_columns(df)
    monthly = df.resample("ME").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna(subset=["open"])
    return monthly


def get_prior_period_hlc(
    resampled_df: pd.DataFrame,
    as_of: pd.Timestamp,
) -> tuple[float, float, float] | None:
    """
    Return (high, low, close) for the period immediately preceding as_of.

    Args:
        resampled_df: daily/weekly/monthly OHLCV DataFrame.
        as_of: the current bar's timestamp; we want the period before this.

    Returns:
        (high, low, close) tuple, or None if insufficient history.
    """
    prior = resampled_df[resampled_df.index < as_of]
    if prior.empty:
        return None
    row = prior.iloc[-1]
    return float(row["high"]), float(row["low"]), float(row["close"])


# ---------------------------------------------------------------------------
# Confluence detection helpers
# ---------------------------------------------------------------------------

def group_levels_into_zones(
    levels: list[float],
    tolerance_pct: float,
) -> list[list[float]]:
    """
    Group a flat list of price levels into confluence zones.

    Two levels are considered confluent if they are within `tolerance_pct`
    percent of each other (relative to their average).

    Args:
        levels: unsorted list of price levels.
        tolerance_pct: e.g. 0.15 means ±0.15% = 0.0015 in fractional terms.

    Returns:
        List of groups (each group is a list of confluent levels).
        Groups are sorted by ascending average price.
    """
    if not levels:
        return []

    sorted_levels = sorted(levels)
    tolerance = tolerance_pct / 100.0

    groups: list[list[float]] = []
    current_group = [sorted_levels[0]]

    for lvl in sorted_levels[1:]:
        ref = np.mean(current_group)
        if abs(lvl - ref) / ref <= tolerance:
            current_group.append(lvl)
        else:
            groups.append(current_group)
            current_group = [lvl]

    groups.append(current_group)
    return groups


def zone_midpoint(group: list[float]) -> float:
    """Return the average (midpoint) price of a confluence zone."""
    return float(np.mean(group))


def zone_width_pct(group: list[float]) -> float:
    """Return the width of a confluence zone as % of its midpoint."""
    if len(group) < 2:
        return 0.0
    mid = zone_midpoint(group)
    return (max(group) - min(group)) / mid * 100.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase column names so callers don't need to worry about casing."""
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    return df
