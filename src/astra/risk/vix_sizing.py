"""
VIX bucket position-size tilt — validated in EXP-0015, rejected as a filter in EXP-0013.

EXP-0013 tested India VIX as a binary entry filter and rejected it: combining a VIX gate
with the ATR gate collapsed trade count from ~33/month to 6-15/month for a 22% beat rate
against a 65% bar. But it found a real signal underneath — trade quality varies sharply by
where VIX sits in its own recent range:

    VIX 50-60th percentile  →  ₹547/trade   "sweet spot"   → size UP   1.5x
    VIX 60-75th percentile  →  ₹47/trade    "danger zone"  → size DOWN 0.5x
    everything else         →  baseline                    → 1.0x

EXP-0015 confirmed the tilt: Sharpe 2.93 vs 2.87 flat, +6% P&L, and max drawdown down from
39.4% to 33.7%. So VIX modulates size, it does not gate entry. The percentile is over a
trailing 40 *trading* days, not calendar days (HANDOFF G3).

The percentile computation mirrors the research exactly, including its forward-fill.

ONE DELIBERATE DEVIATION, for money safety. The research code falls back to
`pctile = 50.0` when a VIX lookup raises — but 50.0 is the *bottom edge of the sweet
spot*, so that fallback sizes UP to 1.5x on a data failure. Harmless in a backtest with
a complete VIX file; the wrong direction entirely on a live feed hiccup. Here an
unresolvable VIX returns None and sizes at 1.0x. No recorded result is affected: the
research scripts compute their percentiles inline and do not import this module, which
exists for the live and paper paths.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

VIX_LOOKBACK_TRADING_DAYS = 40

SWEET_SPOT = (50.0, 60.0)   # percentile band → 1.5x
DANGER_ZONE = (60.0, 75.0)  # percentile band → 0.5x

# What the research used on lookup failure. Kept as a named constant so the hazard is
# documented rather than folded away — see the module docstring.
RESEARCH_FALLBACK_PERCENTILE = 50.0


def vix_percentile(
    vix_daily: pd.Series,
    as_of: pd.Timestamp,
    lookback: int = VIX_LOOKBACK_TRADING_DAYS,
) -> Optional[float]:
    """
    Percentile rank of the VIX reading for `as_of` within the trailing `lookback` sessions.

    Returns None when VIX cannot be resolved, which vix_size_mult() maps to 1.0x. See the
    module docstring for why this differs from the research's 50.0 fallback.
    """
    try:
        day = as_of.normalize()
        if vix_daily.index.tz is not None and day.tz is None:
            day = day.tz_localize(vix_daily.index.tz)
        elif vix_daily.index.tz is None and day.tz is not None:
            day = day.tz_localize(None)

        value = vix_daily.reindex([day], method="ffill").iloc[0]
        if pd.isna(value):
            return None

        history = vix_daily.loc[:day].tail(lookback)
        if history.empty:
            return None
        return float((history < value).mean() * 100.0)
    except Exception:
        return None


def vix_size_mult(percentile: Optional[float]) -> float:
    """
    Lot multiplier for a VIX percentile. EXP-0015 'Tilt' config.

    None (unresolvable VIX) → 1.0x. Never up-size on missing data.
    """
    if percentile is None:
        return 1.0
    if SWEET_SPOT[0] <= percentile < SWEET_SPOT[1]:
        return 1.5
    if DANGER_ZONE[0] <= percentile < DANGER_ZONE[1]:
        return 0.5
    return 1.0


def vix_bucket_name(percentile: Optional[float]) -> str:
    """Human-readable bucket, for logs and Telegram alerts."""
    if percentile is None:
        return "unresolved"
    if SWEET_SPOT[0] <= percentile < SWEET_SPOT[1]:
        return "sweet_spot"
    if DANGER_ZONE[0] <= percentile < DANGER_ZONE[1]:
        return "danger_zone"
    return "neutral"
