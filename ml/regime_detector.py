"""
Market Regime Detector.

Classifies the current market into one of five regimes:
  TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE, CHOPPY

Two modes:
  1. Rule-based fallback (always available, no training needed)
  2. ML model (RandomForest/GradientBoosting, trained via ModelTrainer)

The rule-based fallback is the default until enough data is collected to train.
"""
from __future__ import annotations

import pickle
from pathlib import Path
from typing import Optional

import pandas as pd

from ml.features import FeatureEngineer
from strategies.base import Regime


class RegimeDetector:
    """
    Detects the current market regime from daily OHLCV data.

    Usage:
        detector = RegimeDetector()                        # rule-based mode
        detector = RegimeDetector("ml/models/regime.pkl") # ML model mode
        regime = detector.detect(daily_ohlcv)
        regime, confidence = detector.detect_with_confidence(daily_ohlcv)
    """

    # Rule-based thresholds (tuned from backtests)
    ADX_TRENDING_THRESHOLD = 25.0
    ADX_RANGING_THRESHOLD = 20.0
    VOL_RATIO_VOLATILE_THRESHOLD = 1.3
    ATR_RATIO_VOLATILE_THRESHOLD = 1.4
    TREND_STRENGTH_THRESHOLD = 2.0

    def __init__(self, model_path: Optional[str] = None) -> None:
        self._feature_engineer = FeatureEngineer()
        self._model = None
        self._use_ml = False
        if model_path and Path(model_path).exists():
            self.load(model_path)

    def detect(self, ohlcv: pd.DataFrame) -> Regime:
        """
        Classify the current market regime.

        Args:
            ohlcv: Daily OHLCV DataFrame, last row = today (or last completed day).

        Returns:
            Regime enum value.
        """
        regime, _ = self.detect_with_confidence(ohlcv)
        return regime

    def detect_with_confidence(self, ohlcv: pd.DataFrame) -> tuple[Regime, float]:
        """
        Classify the current market regime with a confidence score.

        Returns:
            (Regime, confidence) where confidence is 0.0–1.0.
            Rule-based always returns confidence=1.0 (deterministic).
            ML model returns the predicted class probability.
        """
        features = self._feature_engineer.compute_regime_features(ohlcv)

        if self._use_ml and self._model is not None:
            return self._ml_detect(features)
        return self._rule_based_detect(features)

    def train(self, X: pd.DataFrame, y: pd.Series) -> None:
        """
        Train (or retrain) the ML regime classifier.

        Args:
            X: Feature DataFrame from FeatureEngineer.build_training_dataset().
            y: Target Series of Regime labels (string values matching Regime enum).

        After training, detect() will use the ML model instead of rules.
        Call save() to persist the model.
        """
        # TODO Phase 4: implement
        # from sklearn.ensemble import RandomForestClassifier
        # self._model = RandomForestClassifier(n_estimators=100, random_state=42)
        # self._model.fit(X, y)
        # self._use_ml = True
        raise NotImplementedError("Phase 4: implement train()")

    def save(self, path: str) -> None:
        """Persist the trained ML model to disk."""
        if self._model is None:
            raise ValueError("No trained model to save.")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self._model, f)

    def load(self, path: str) -> None:
        """Load a previously trained model from disk."""
        with open(path, "rb") as f:
            self._model = pickle.load(f)
        self._use_ml = True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rule_based_detect(self, features: pd.Series) -> tuple[Regime, float]:
        """
        Deterministic regime classification from indicator thresholds.

        Priority order:
          1. VOLATILE  — ATR ratio > 1.4 OR vol ratio > 1.3
          2. TRENDING_UP / TRENDING_DOWN — ADX > 25 AND trend_strength > 2
          3. RANGING   — ADX < 20
          4. CHOPPY    — everything else (low ADX, low vol, no clear trend)
        """
        adx = features.get("adx", 0.0)
        atr_ratio = features.get("atr_ratio", 1.0)
        vol_ratio = features.get("vol_ratio", 1.0)
        trend_strength = features.get("trend_strength", 0.0)
        close_vs_sma20 = features.get("close_vs_sma20", 0.0)

        # Volatile: sudden expansion in realized vol or ATR
        if atr_ratio > self.ATR_RATIO_VOLATILE_THRESHOLD or vol_ratio > self.VOL_RATIO_VOLATILE_THRESHOLD:
            return Regime.VOLATILE, 1.0

        # Trending: strong ADX + price far from SMA
        if adx > self.ADX_TRENDING_THRESHOLD and trend_strength > self.TREND_STRENGTH_THRESHOLD:
            if close_vs_sma20 > 0:
                return Regime.TRENDING_UP, 1.0
            return Regime.TRENDING_DOWN, 1.0

        # Ranging: low ADX, price oscillating around SMA
        if adx < self.ADX_RANGING_THRESHOLD:
            return Regime.RANGING, 1.0

        return Regime.CHOPPY, 1.0

    def _ml_detect(self, features: pd.Series) -> tuple[Regime, float]:
        """Run the trained ML model and return (regime, probability)."""
        X = features.values.reshape(1, -1)
        proba = self._model.predict_proba(X)[0]
        predicted_class = self._model.classes_[proba.argmax()]
        confidence = float(proba.max())
        try:
            regime = Regime(predicted_class)
        except ValueError:
            regime = Regime.UNKNOWN
        return regime, confidence
