"""
Walk-Forward Validator — out-of-sample strategy validation.

Why this matters:
  The Atlas backtest (₹20K → ₹8.25L) was in-sample. We trained and tested
  on the same 6 months. Walk-forward splits the data into rolling windows:
  train on N months, test on the next M months you never trained on.

  If the strategy is real, it profits in every out-of-sample window.
  If it only worked because it was overfit, the OOS windows will be flat or negative.

Run this BEFORE going live. is_robust=True is the gate condition.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import pandas as pd

from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


@dataclass
class FoldResult:
    """Metrics for one walk-forward fold (out-of-sample period)."""
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    test_return: float          # e.g. 0.22 = +22%
    test_win_rate: float        # e.g. 0.26
    test_sharpe: float          # annualised Sharpe ratio
    test_max_drawdown: float    # e.g. -0.08 = −8% peak-to-trough
    test_trades: int
    is_profitable: bool = False

    def __post_init__(self) -> None:
        self.is_profitable = self.test_return > 0


@dataclass
class WalkForwardResult:
    """Aggregated results across all walk-forward folds."""
    folds: list[FoldResult] = field(default_factory=list)
    aggregate_return: float = 0.0
    aggregate_sharpe: float = 0.0
    aggregate_max_drawdown: float = 0.0
    is_robust: bool = False     # True only if EVERY fold is profitable

    def summary(self) -> str:
        lines = [
            f"Walk-Forward Validation: {len(self.folds)} folds",
            f"  Aggregate return:    {self.aggregate_return:+.1%}",
            f"  Aggregate Sharpe:    {self.aggregate_sharpe:.2f}",
            f"  Max drawdown:        {self.aggregate_max_drawdown:.1%}",
            f"  Robust (all profitable): {'✅ YES' if self.is_robust else '❌ NO'}",
            "",
        ]
        for i, fold in enumerate(self.folds):
            profitable_marker = "✅" if fold.is_profitable else "❌"
            lines.append(
                f"  Fold {i+1}: {fold.test_start} → {fold.test_end} | "
                f"Return: {fold.test_return:+.1%} | "
                f"Win: {fold.test_win_rate:.1%} | "
                f"Sharpe: {fold.test_sharpe:.2f} {profitable_marker}"
            )
        return "\n".join(lines)


class WalkForwardValidator:
    """
    Runs rolling walk-forward validation on a strategy.

    Usage:
        validator = WalkForwardValidator(strategy, train_months=3, test_months=1)
        result = validator.run(daily_ohlcv, initial_capital=20_000)
        print(result.summary())
        if not result.is_robust:
            raise ValueError("Strategy failed walk-forward — do NOT go live")
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        train_months: int = 3,
        test_months: int = 1,
    ) -> None:
        self._strategy = strategy
        self._train_months = train_months
        self._test_months = test_months

    def run(
        self,
        historical_data: pd.DataFrame,
        initial_capital: float = 20_000,
    ) -> WalkForwardResult:
        """
        Run the full walk-forward validation.

        Args:
            historical_data: 5-minute OHLCV DataFrame with datetime index.
                             Minimum: (train_months + 2 × test_months) of data.
            initial_capital: Starting capital for each test fold.

        Returns:
            WalkForwardResult with per-fold and aggregate metrics.
        """
        # TODO Phase 3: implement
        # 1. Generate fold date ranges
        # 2. For each fold: run backtest on test period with strategy
        # 3. Aggregate metrics
        raise NotImplementedError("Phase 3: implement WalkForwardValidator.run()")

    def plot_equity_curves(
        self, result: WalkForwardResult, save_path: Optional[str] = None
    ) -> None:
        """
        Plot per-fold equity curves on a single chart.

        Each fold is a different colour; OOS periods are shaded.
        Requires matplotlib.
        """
        # TODO Phase 3: implement
        raise NotImplementedError("Phase 3: implement plot_equity_curves()")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_folds(self, index: pd.DatetimeIndex) -> list[tuple[slice, slice]]:
        """
        Generate (train_slice, test_slice) pairs for each rolling window.

        Advances by test_months each iteration until no full test window remains.
        """
        # TODO Phase 3: implement
        raise NotImplementedError

    def _run_backtest_on_window(
        self, data_window: pd.DataFrame, capital: float
    ) -> list[dict]:
        """Run the strategy on a specific data window, return list of trade dicts."""
        # TODO Phase 3: reuse src/backtest/harness.py logic
        raise NotImplementedError

    def _compute_fold_metrics(
        self,
        trades: list[dict],
        capital: float,
        train_start: date,
        train_end: date,
        test_start: date,
        test_end: date,
    ) -> FoldResult:
        """Convert a list of trades into a FoldResult."""
        if not trades:
            return FoldResult(
                train_start=train_start, train_end=train_end,
                test_start=test_start, test_end=test_end,
                test_return=0.0, test_win_rate=0.0,
                test_sharpe=0.0, test_max_drawdown=0.0,
                test_trades=0,
            )
        pnls = [t["pnl"] for t in trades]
        wins = sum(1 for p in pnls if p > 0)
        equity = pd.Series(pnls).cumsum() + capital
        ret = float((equity.iloc[-1] - capital) / capital)
        daily_ret = equity.pct_change().dropna()
        sharpe = float(daily_ret.mean() / daily_ret.std() * (252 ** 0.5)) if daily_ret.std() > 0 else 0.0
        max_dd = float(((equity - equity.cummax()) / equity.cummax()).min())
        return FoldResult(
            train_start=train_start, train_end=train_end,
            test_start=test_start, test_end=test_end,
            test_return=ret,
            test_win_rate=wins / len(pnls),
            test_sharpe=sharpe,
            test_max_drawdown=max_dd,
            test_trades=len(trades),
        )
