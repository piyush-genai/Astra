"""
Feature engineering for the Astra ML layer.

Transforms raw OHLCV data into numerical features that describe:
  1. Market regime (for RegimeDetector)
  2. Signal quality (for OpportunityRanker confidence scoring)

All features are computed from public price/volume data — no lookahead.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from strategies.base import InstrumentType, Regime, Signal, MarketData


class FeatureEngineer:
    """
    Builds feature vectors from market data for ML model consumption.

    Usage:
        fe = FeatureEngineer(atr_lookback=20, adx_period=14)
        features = fe.compute_regime_features(ohlcv_df)
        X, y = fe.build_training_dataset(backtest_results_df)
    """

    def __init__(
        self,
        atr_lookback: int = 20,
        adx_period: int = 14,
        vol_ratio_short: int = 5,
        vol_ratio_long: int = 20,
        skew_lookback: int = 20,
    ) -> None:
        self.atr_lookback = atr_lookback
        self.adx_period = adx_period
        self.vol_ratio_short = vol_ratio_short
        self.vol_ratio_long = vol_ratio_long
        self.skew_lookback = skew_lookback

    def compute_regime_features(self, ohlcv: pd.DataFrame) -> pd.Series:
        """
        Compute regime-classification features from a daily OHLCV DataFrame.

        Args:
            ohlcv: DataFrame with columns [open, high, low, close, volume],
                   daily frequency, last row = today.

        Returns:
            pd.Series with keys:
              - atr_ratio: current ATR / 20d average ATR (>1.2 = expanding volatility)
              - adx: ADX value (>25 = trending, <20 = ranging/choppy)
              - return_skew_20d: skewness of 20-day daily returns (neg = bearish tail)
              - vol_ratio: 5d realized vol / 20d realized vol (>1.2 = vol expanding)
              - trend_strength: abs(close - SMA20) / ATR (>2 = strong trend)
              - range_percentile: today's range vs. 20d range distribution (0–1)
              - close_vs_sma20: (close - SMA20) / SMA20 (sign = direction)
              - volume_ratio: today's volume / 20d avg volume
        """
        # TODO Phase 4: implement full feature computation
        close = ohlcv["close"]
        high = ohlcv["high"]
        low = ohlcv["low"]
        volume = ohlcv["volume"]

        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(self.atr_lookback).mean()
        atr_ratio = float(atr.iloc[-1] / atr.iloc[-self.atr_lookback:].mean()) if len(atr) >= self.atr_lookback else 1.0

        returns = close.pct_change().dropna()
        return_skew = float(returns.iloc[-self.skew_lookback:].skew()) if len(returns) >= self.skew_lookback else 0.0

        sma20 = close.rolling(20).mean()
        trend_strength = float(abs(close.iloc[-1] - sma20.iloc[-1]) / atr.iloc[-1]) if atr.iloc[-1] > 0 else 0.0
        close_vs_sma20 = float((close.iloc[-1] - sma20.iloc[-1]) / sma20.iloc[-1]) if sma20.iloc[-1] > 0 else 0.0

        daily_range = high - low
        range_pct = float(
            (daily_range.iloc[-1] - daily_range.iloc[-20:].min()) /
            (daily_range.iloc[-20:].max() - daily_range.iloc[-20:].min() + 1e-9)
        ) if len(daily_range) >= 20 else 0.5

        short_vol = float(returns.iloc[-self.vol_ratio_short:].std()) if len(returns) >= self.vol_ratio_short else 0.0
        long_vol = float(returns.iloc[-self.vol_ratio_long:].std()) if len(returns) >= self.vol_ratio_long else short_vol
        vol_ratio = short_vol / long_vol if long_vol > 0 else 1.0

        vol_avg = volume.rolling(20).mean()
        volume_ratio = float(volume.iloc[-1] / vol_avg.iloc[-1]) if vol_avg.iloc[-1] > 0 else 1.0

        # ADX computation (simplified)
        adx = self._compute_adx(ohlcv)

        return pd.Series({
            "atr_ratio": atr_ratio,
            "adx": adx,
            "return_skew_20d": return_skew,
            "vol_ratio": vol_ratio,
            "trend_strength": trend_strength,
            "range_percentile": range_pct,
            "close_vs_sma20": close_vs_sma20,
            "volume_ratio": volume_ratio,
        })

    def compute_signal_quality_features(
        self, signal: Signal, market_data: MarketData
    ) -> pd.Series:
        """
        Compute features that describe the quality of a specific signal.

        Args:
            signal: The Signal emitted by a strategy.
            market_data: The MarketData snapshot at signal time.

        Returns:
            pd.Series with keys:
              - zone_width_pct: zone width / price (tighter = cleaner level)
              - volume_ratio_at_breakout: breakout bar volume / 20-bar avg
              - time_of_day_score: 0–1 (avoid 9:15–9:30 and 15:00–15:30)
              - day_of_week: 0=Mon … 4=Fri
              - bars_since_last_touch: how many bars since zone was last touched
              - candle_body_ratio: body / total range at breakout bar
        """
        ohlcv = market_data.ohlcv
        bar = market_data.current_bar
        price = float(bar["close"])
        ts = market_data.timestamp

        zone_width_pct = signal.zone.width / price if price > 0 else 0.0

        avg_volume = float(ohlcv["volume"].iloc[-20:].mean()) if len(ohlcv) >= 20 else 1.0
        volume_ratio = float(bar["volume"]) / avg_volume if avg_volume > 0 else 1.0

        time_score = self._time_of_day_score(ts)

        body = abs(float(bar["close"]) - float(bar["open"]))
        total_range = float(bar["high"]) - float(bar["low"])
        body_ratio = body / total_range if total_range > 0 else 0.0

        return pd.Series({
            "zone_width_pct": zone_width_pct,
            "volume_ratio_at_breakout": volume_ratio,
            "time_of_day_score": time_score,
            "day_of_week": ts.weekday(),
            "candle_body_ratio": body_ratio,
            "signal_confidence": signal.confidence,
        })

    def build_training_dataset(
        self, backtest_results: pd.DataFrame
    ) -> tuple[pd.DataFrame, pd.Series]:
        """
        Build (X, y) training dataset from historical backtest trade records.

        Args:
            backtest_results: DataFrame with columns including:
              [entry_time, exit_time, pnl, signal_type, regime_label, ...]
              regime_label must be pre-labeled (use RegimeDetector rule-based first).

        Returns:
            X: feature DataFrame (one row per trade)
            y: target Series — Regime label for each trade's entry bar
        """
        # TODO Phase 4: implement — join trade records with regime features per bar
        raise NotImplementedError("Phase 4: implement build_training_dataset")

    def _compute_adx(self, ohlcv: pd.DataFrame, period: Optional[int] = None) -> float:
        """Compute ADX for the last bar. Returns 0.0 if insufficient data."""
        n = period or self.adx_period
        if len(ohlcv) < n * 2:
            return 0.0
        high = ohlcv["high"]
        low = ohlcv["low"]
        close = ohlcv["close"]
        plus_dm = (high.diff()).clip(lower=0)
        minus_dm = (-low.diff()).clip(lower=0)
        plus_dm = plus_dm.where(plus_dm > minus_dm, 0)
        minus_dm = minus_dm.where(minus_dm > plus_dm, 0)
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        atr_n = tr.ewm(span=n, adjust=False).mean()
        plus_di = 100 * plus_dm.ewm(span=n, adjust=False).mean() / atr_n.replace(0, np.nan)
        minus_di = 100 * minus_dm.ewm(span=n, adjust=False).mean() / atr_n.replace(0, np.nan)
        dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)).fillna(0)
        adx = dx.ewm(span=n, adjust=False).mean()
        return float(adx.iloc[-1]) if not adx.empty else 0.0

    def _time_of_day_score(self, ts: datetime) -> float:
        """Score 0–1 based on time of day. Penalises first and last 15 min."""
        minutes_since_open = (ts.hour * 60 + ts.minute) - (9 * 60 + 15)
        minutes_to_close = (15 * 60 + 30) - (ts.hour * 60 + ts.minute)
        if minutes_since_open < 15 or minutes_to_close < 15:
            return 0.2
        if minutes_since_open < 30 or minutes_to_close < 30:
            return 0.6
        return 1.0
