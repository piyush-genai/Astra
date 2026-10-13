"""
Unit tests for the P70_L40d adaptive ATR regime filter (EXP-0010/0011).

The decisive test is test_mask_matches_research_code_on_real_data: it recomputes the
filter the way scripts/exp_0010_adaptive_atr.py does, inline, on the real 2023-2025
dataset, and requires bar-for-bar agreement across all 55,513 bars. That is the only
check that proves the live filter will gate trades identically to the validated backtest.
It skips when the dataset is absent, since the CSV is gitignored.
"""

from pathlib import Path

import pandas as pd
import pytest

from src.astra.alpha.regime_filter import BARS_PER_SESSION_5MIN, AdaptiveAtrFilter

DATA_PATH = Path("data/live_data/nifty_5min_20230101_to_20251231.csv")


def _synthetic(n: int, base: float = 25_000.0, span: float = 50.0) -> pd.DataFrame:
    """Deterministic saw-tooth bars — enough structure for a non-degenerate ATR."""
    idx = pd.date_range("2024-01-01 09:15", periods=n, freq="5min")
    close = [base + (i % 20) * span / 20 for i in range(n)]
    return pd.DataFrame(
        {
            "open": close,
            "high": [c + span for c in close],
            "low": [c - span for c in close],
            "close": close,
            "volume": [0] * n,
        },
        index=idx,
    )


def test_defaults_are_the_validated_config() -> None:
    f = AdaptiveAtrFilter()
    assert f.percentile == 70.0
    assert f.lookback_bars == 3000
    assert f.atr_period == 10
    assert f.min_warmup_bars == 3000


def test_bars_per_session_constant() -> None:
    """375-minute session / 5 = 75 bars. 3000 bars is therefore ~40 trading days."""
    assert BARS_PER_SESSION_5MIN == 75
    assert AdaptiveAtrFilter().lookback_bars / BARS_PER_SESSION_5MIN == 40


def test_true_range_formula() -> None:
    f = AdaptiveAtrFilter()
    bars = _synthetic(5)
    tr = f.true_range(bars)
    prev_close = bars["close"].shift(1)
    expected = pd.concat(
        [bars["high"] - bars["low"],
         (bars["high"] - prev_close).abs(),
         (bars["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    pd.testing.assert_series_equal(tr, expected)


def test_closed_before_warmup_completes() -> None:
    """
    No threshold exists until 3,000 bars have accumulated, so the filter refuses to
    trade. This is the research's `atr10 > NaN` → False, and it is the correct live
    behaviour: without a threshold the filter has no opinion, so it must not permit
    trading rather than permit everything.
    """
    f = AdaptiveAtrFilter()
    bars = _synthetic(500)
    assert not f.is_open(bars)
    state = f.describe(bars)
    assert state["open"] is False
    assert state["warmed_up"] is False
    assert "warming up" in str(state["reason"])
    assert "2500 short" in str(state["reason"])


def test_first_bars_pass_by_the_nan_convention() -> None:
    """
    The research selection is `atr_mask | atr10.isna()`, so bars whose own ATR is still
    undefined (the first atr_period-1) are included. Pinned to preserve equivalence even
    though it is counter-intuitive.
    """
    f = AdaptiveAtrFilter(lookback_bars=20, atr_period=10)
    bars = _synthetic(40)
    mask = f.mask(bars)
    assert mask.iloc[:9].all()  # ATR undefined → pass


def test_opens_when_atr_exceeds_its_own_percentile() -> None:
    """A volatility burst after a calm stretch must open the gate."""
    calm = _synthetic(120, span=5.0)
    burst = _synthetic(10, span=500.0)
    burst.index = pd.date_range(calm.index[-1] + pd.Timedelta(5, unit="m"),
                                periods=10, freq="5min")
    bars = pd.concat([calm, burst])

    f = AdaptiveAtrFilter(lookback_bars=100, atr_period=10)
    assert f.is_open(bars)
    assert f.describe(bars)["open"] is True


def test_closed_in_a_flat_regime() -> None:
    """Uniform volatility cannot exceed its own 70th percentile."""
    f = AdaptiveAtrFilter(lookback_bars=100, atr_period=10)
    bars = _synthetic(300, span=20.0)
    # A perfectly constant ATR sits at its own percentile, not above it.
    assert not f.is_open(bars)


def test_empty_frame_is_closed_not_an_error() -> None:
    f = AdaptiveAtrFilter()
    assert f.is_open(pd.DataFrame()) is False
    assert f.describe(pd.DataFrame())["open"] is False


@pytest.mark.skipif(not DATA_PATH.exists(), reason="2023-2025 dataset absent (gitignored)")
def test_mask_matches_research_code_on_real_data() -> None:
    """
    Bar-for-bar equivalence with the inline computation in exp_0010_adaptive_atr.py and
    exp_0017_drawdown_management.py, over the full 55,513-bar dataset. If this passes,
    the live gate selects exactly the bars the validated backtest traded.
    """
    df = pd.read_csv(DATA_PATH, parse_dates=["timestamp"], index_col="timestamp")
    df.index = pd.DatetimeIndex(df.index)

    # --- the research code, verbatim ---
    tr = pd.concat(
        [df["high"] - df["low"],
         (df["high"] - df["close"].shift(1)).abs(),
         (df["low"] - df["close"].shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    research_atr = tr.rolling(10).mean()
    research_mask = (research_atr > research_atr.rolling(3000).quantile(0.70)) | research_atr.isna()
    # --- end research code ---

    module_mask = AdaptiveAtrFilter().mask(df)

    assert len(module_mask) == len(research_mask) == len(df)
    assert int(module_mask.sum()) == int(research_mask.sum()), "selected bar count differs"
    pd.testing.assert_series_equal(
        module_mask.rename(None), research_mask.rename(None), check_names=False
    )
