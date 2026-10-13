"""
P70_L40d adaptive ATR regime filter — the validated primary regime filter (EXP-0010/0011).

Trade only when current volatility is high relative to recent history: 10-bar ATR above
the 70th percentile of its own trailing 3,000-bar distribution. "Relative" is the whole
point — EXP-0009 showed a fixed ATR>30 threshold fails across regimes (56% beat rate
against a 65% bar) because 30 was only meaningful in 2023 conditions.

This implementation is deliberately a line-by-line match of the research code in
scripts/exp_0010_adaptive_atr.py and exp_0017_drawdown_management.py:

    tr    = max(high-low, |high - prev_close|, |low - prev_close|)
    atr10 = tr.rolling(10).mean()
    mask  = atr10 > atr10.rolling(3000).quantile(0.70)

with the research's NaN convention preserved: a bar passes when its own ATR is still NaN
(the first 9 bars), and fails when the rolling threshold is NaN (the first ~3,000 bars,
since `x > NaN` is False). The second case matters live — it means the filter refuses to
trade until it has 3,000 bars of warmup, roughly 40 trading days at 75 bars/day. That is
the correct behaviour, not a bug to work around: without the warmup there is no threshold
and the filter has no opinion.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# NSE cash session is 09:15-15:30 = 375 minutes = 75 five-minute bars.
BARS_PER_SESSION_5MIN = 75


@dataclass(frozen=True)
class AdaptiveAtrFilter:
    """
    Validated configuration is the default: P70_L40d.

    `lookback_bars=3000` is the rolling window for the percentile, which is ~40 trading
    days of 5-minute bars — hence the "L40d" in the name. It is expressed in bars rather
    than days because that is how the research computed it.
    """

    percentile: float = 70.0
    lookback_bars: int = 3000
    atr_period: int = 10

    @property
    def min_warmup_bars(self) -> int:
        """Bars required before the filter can express any opinion."""
        return self.lookback_bars

    def true_range(self, bars: pd.DataFrame) -> pd.Series:
        prev_close = bars["close"].shift(1)
        return pd.concat(
            [
                bars["high"] - bars["low"],
                (bars["high"] - prev_close).abs(),
                (bars["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

    def atr(self, bars: pd.DataFrame) -> pd.Series:
        return self.true_range(bars).rolling(self.atr_period).mean()

    def threshold(self, bars: pd.DataFrame) -> pd.Series:
        """Rolling percentile of ATR. NaN until `lookback_bars` have accumulated."""
        return self.atr(bars).rolling(self.lookback_bars).quantile(self.percentile / 100.0)

    def mask(self, bars: pd.DataFrame) -> pd.Series:
        """
        Per-bar pass/fail, matching the research's `atr_mask | atr10.isna()` selection.

        Returns a boolean Series aligned to `bars`.
        """
        atr = self.atr(bars)
        return (atr > self.threshold(bars)) | atr.isna()

    def is_open(self, bars: pd.DataFrame) -> bool:
        """Whether the most recent bar passes the filter."""
        if bars.empty:
            return False
        return bool(self.mask(bars).iloc[-1])

    def describe(self, bars: pd.DataFrame) -> dict[str, object]:
        """Current filter state, for logging and alerting."""
        if bars.empty:
            return {"open": False, "reason": "no bars"}

        atr = self.atr(bars)
        thr = self.threshold(bars)
        atr_now, thr_now = atr.iloc[-1], thr.iloc[-1]
        warm = len(bars) >= self.min_warmup_bars

        if pd.isna(thr_now):
            reason = (
                f"warming up — {len(bars)}/{self.min_warmup_bars} bars "
                f"({self.min_warmup_bars - len(bars)} short, no threshold yet)"
            )
        elif pd.isna(atr_now):
            reason = "ATR not yet defined — bar passes by the research NaN convention"
        else:
            verb = "above" if atr_now > thr_now else "below"
            reason = f"ATR {atr_now:.2f} {verb} P{self.percentile:.0f} threshold {thr_now:.2f}"

        return {
            "open": self.is_open(bars),
            "bars": len(bars),
            "warmed_up": warm,
            "atr": None if pd.isna(atr_now) else round(float(atr_now), 2),
            "threshold": None if pd.isna(thr_now) else round(float(thr_now), 2),
            "reason": reason,
        }
