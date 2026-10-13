"""
Unit tests for the VIX size tilt (EXP-0015).

The bucket boundaries are the entire content of the signal, so they are pinned exactly.
So is the fail-safe fallback: an unresolvable VIX must size at 1.0x, never 1.5x.
"""

import pandas as pd
import pytest

from src.astra.risk.vix_sizing import (
    RESEARCH_FALLBACK_PERCENTILE,
    vix_bucket_name,
    vix_percentile,
    vix_size_mult,
)


@pytest.mark.parametrize(
    "pctile, expected, bucket",
    [
        (0.0, 1.0, "neutral"),
        (49.9, 1.0, "neutral"),
        (50.0, 1.5, "sweet_spot"),    # sweet spot is inclusive at 50
        (59.9, 1.5, "sweet_spot"),
        (60.0, 0.5, "danger_zone"),   # hands over to danger at exactly 60
        (74.9, 0.5, "danger_zone"),
        (75.0, 1.0, "neutral"),       # above the danger zone, back to baseline
        (100.0, 1.0, "neutral"),
    ],
)
def test_bucket_boundaries(pctile: float, expected: float, bucket: str) -> None:
    assert vix_size_mult(pctile) == expected
    assert vix_bucket_name(pctile) == bucket


def test_unresolvable_vix_sizes_at_one_not_one_point_five() -> None:
    """
    The money-safety deviation from the research. Its fallback was `pctile = 50.0`, and
    50.0 is the bottom edge of the sweet spot — so a VIX lookup failure sized UP to 1.5x.
    Harmless with a complete backtest file, the wrong direction on a live feed hiccup.
    """
    assert vix_size_mult(RESEARCH_FALLBACK_PERCENTILE) == 1.5  # what the research did
    assert vix_size_mult(None) == 1.0                          # what this module does
    assert vix_bucket_name(None) == "unresolved"


def _vix_series(n: int = 60, tz: str | None = None) -> pd.Series:
    idx = pd.date_range("2025-01-01", periods=n, freq="D", tz=tz)
    return pd.Series(range(10, 10 + n), index=idx, dtype=float, name="vix")


def test_percentile_matches_research_formula() -> None:
    """Replicates the inline computation used by exp_0013..0017."""
    vix = _vix_series()
    as_of = vix.index[-1]

    value = vix.reindex([as_of], method="ffill").iloc[0]
    hist = vix.loc[:as_of].tail(40)
    expected = float((hist < value).mean() * 100.0)

    assert vix_percentile(vix, as_of) == pytest.approx(expected)


def test_percentile_uses_trailing_forty_sessions_not_all_history() -> None:
    """HANDOFF G3: the window is 40 trading days, not the full series."""
    vix = _vix_series()  # strictly increasing → latest value is the max
    # In a 40-row trailing window the final value exceeds the other 39.
    assert vix_percentile(vix, vix.index[-1]) == pytest.approx(97.5)


def test_percentile_forward_fills_to_the_previous_session() -> None:
    """A holiday or weekend must resolve to the last available reading, not fail."""
    vix = _vix_series(n=45)
    gap_day = vix.index[-1] + pd.Timedelta(3, unit="D")
    assert vix_percentile(vix, gap_day) is not None


def test_empty_series_returns_none() -> None:
    assert vix_percentile(pd.Series(dtype=float, name="vix"), pd.Timestamp("2025-06-01")) is None


def test_all_nan_series_returns_none() -> None:
    idx = pd.date_range("2025-01-01", periods=5, freq="D")
    vix = pd.Series([float("nan")] * 5, index=idx, name="vix")
    assert vix_percentile(vix, idx[-1]) is None


def test_timezone_mismatch_does_not_raise() -> None:
    """The live feed is tz-aware IST; a naive bar timestamp must not blow up the lookup."""
    vix = _vix_series(n=45, tz="Asia/Kolkata")
    result = vix_percentile(vix, pd.Timestamp("2025-02-10"))
    assert result is not None and 0.0 <= result <= 100.0
