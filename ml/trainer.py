"""
Model Trainer — builds and validates the Astra ML models.

Responsibilities:
  1. Train the RegimeDetector from labeled backtest data.
  2. Walk-forward validate a strategy (train on N months, test on M months).
  3. Schedule weekly retraining as live data accumulates.
  4. Evaluate model quality with proper classification metrics.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from ml.features import FeatureEngineer
from ml.regime_detector import RegimeDetector
from strategies.base import BaseStrategy


class ModelTrainer:
    """
    Trains and validates Astra's ML models.

    Usage:
        trainer = ModelTrainer(FeatureEngineer())
        detector = trainer.train_regime_detector(daily_ohlcv)
        result = trainer.walk_forward_validate(ohlcv, strategy, train_months=3, test_months=1)
    """

    def __init__(self, feature_engineer: FeatureEngineer) -> None:
        self._fe = feature_engineer

    def train_regime_detector(
        self,
        historical_ohlcv: pd.DataFrame,
        min_samples: int = 500,
    ) -> RegimeDetector:
        """
        Train a RegimeDetector from historical OHLCV data.

        Process:
          1. Use rule-based detector to label each day with a regime.
          2. Compute features for each day.
          3. Train ML classifier on (features, regime_labels).
          4. Return trained RegimeDetector in ML mode.

        Args:
            historical_ohlcv: Daily OHLCV, at least 2 years recommended.
            min_samples: Refuse to train if fewer samples available.

        Returns:
            Trained RegimeDetector. Call detector.save() to persist.
        """
        # TODO Phase 4: implement
        # 1. Label each day via rule-based detector
        # 2. Build feature matrix with self._fe.compute_regime_features per day
        # 3. Split 80/20 train/test
        # 4. Train RandomForest, evaluate, return
        raise NotImplementedError("Phase 4: implement train_regime_detector()")

    def walk_forward_validate(
        self,
        ohlcv: pd.DataFrame,
        strategy: BaseStrategy,
        train_months: int = 3,
        test_months: int = 1,
        initial_capital: float = 20_000,
    ) -> dict[str, Any]:
        """
        Walk-forward validation of a strategy.

        Splits the historical data into rolling windows:
          - Train period: train_months (used to fit/configure the strategy)
          - Test period: test_months (out-of-sample evaluation)

        Returns a dict with per-fold metrics and aggregate stats:
          {
            "folds": [
              {
                "train_period": ("2026-02-01", "2026-04-30"),
                "test_period": ("2026-05-01", "2026-05-31"),
                "test_return": 0.22,
                "test_win_rate": 0.26,
                "test_sharpe": 1.4,
                "test_max_drawdown": -0.08,
              },
              ...
            ],
            "aggregate_return": 0.18,
            "aggregate_sharpe": 1.2,
            "aggregate_max_drawdown": -0.12,
            "is_robust": True,   # True if all folds are profitable
          }
        """
        # TODO Phase 3: implement
        raise NotImplementedError("Phase 3: implement walk_forward_validate()")

    def schedule_weekly_retrain(
        self,
        model_path: str = "ml/models/regime.pkl",
        data_source: str = "live",
    ) -> None:
        """
        Set up a weekly retraining job.

        In production: called by live/orchestrator.py every Sunday at 18:00.
        Loads accumulated live trade data, retrains the regime detector,
        and saves the updated model.

        Args:
            model_path: Where to save the updated model.
            data_source: "live" (from state_manager) or path to CSV.
        """
        # TODO Phase 4: implement
        raise NotImplementedError("Phase 4: implement schedule_weekly_retrain()")

    def evaluate_model(
        self, model: Any, X_test: pd.DataFrame, y_test: pd.Series
    ) -> dict[str, Any]:
        """
        Evaluate a trained classifier with classification metrics.

        Returns:
            {
              "accuracy": 0.72,
              "per_class": {
                "trending_up":   {"precision": 0.8,  "recall": 0.75, "f1": 0.77},
                "trending_down": {"precision": 0.75, "recall": 0.70, "f1": 0.72},
                "ranging":       {"precision": 0.65, "recall": 0.68, "f1": 0.66},
                ...
              }
            }
        """
        # TODO Phase 4: implement with sklearn.metrics.classification_report
        raise NotImplementedError("Phase 4: implement evaluate_model()")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _label_regimes_rule_based(self, ohlcv: pd.DataFrame) -> pd.Series:
        """
        Apply the rule-based RegimeDetector across each row of historical data
        to generate training labels.

        Returns a pd.Series of Regime string values indexed by date.
        """
        detector = RegimeDetector()  # rule-based mode (no model path)
        labels = {}
        for i in range(40, len(ohlcv)):
            window = ohlcv.iloc[:i]
            regime = detector.detect(window)
            labels[ohlcv.index[i]] = regime.value
        return pd.Series(labels)

    def _compute_metrics(
        self, trades: list[dict], initial_capital: float
    ) -> dict[str, float]:
        """Compute return, Sharpe, max drawdown from a trade list."""
        if not trades:
            return {"return": 0.0, "win_rate": 0.0, "sharpe": 0.0, "max_drawdown": 0.0}
        pnls = [t["pnl"] for t in trades]
        wins = sum(1 for p in pnls if p > 0)
        equity = pd.Series(pnls).cumsum() + initial_capital
        returns = equity.pct_change().dropna()
        sharpe = float(returns.mean() / returns.std() * (252 ** 0.5)) if returns.std() > 0 else 0.0
        drawdown = float(((equity - equity.cummax()) / equity.cummax()).min())
        return {
            "return": float((equity.iloc[-1] - initial_capital) / initial_capital),
            "win_rate": wins / len(pnls),
            "sharpe": sharpe,
            "max_drawdown": drawdown,
        }
