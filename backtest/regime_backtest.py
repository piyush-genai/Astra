"""
Regime-split Backtest — runs a strategy and splits results by market regime.

Purpose:
  Shows WHEN a strategy works and when it doesn't.
  This is the training signal for StrategySelector:
    "PivotCPR earns 80% of its profits in TRENDING regimes,
     loses money in RANGING regimes — so don't run it when ranging."

Output feeds directly into ml/trainer.py as labeled training data.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from ml.regime_detector import RegimeDetector
from strategies.base import BaseStrategy, Regime

logger = logging.getLogger(__name__)


@dataclass
class RegimeMetrics:
    """Trade statistics for one regime."""
    regime: Regime
    trades: int = 0
    wins: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades > 0 else 0.0

    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.trades if self.trades > 0 else 0.0

    @property
    def has_edge(self) -> bool:
        """True if strategy has positive expected value in this regime."""
        return self.avg_pnl > 0 and self.trades >= 20


@dataclass
class RegimeBacktestResult:
    """Full regime-split backtest result."""
    per_regime_metrics: dict[Regime, RegimeMetrics] = field(default_factory=dict)
    overall_metrics: dict = field(default_factory=dict)
    best_regime: Optional[Regime] = None
    worst_regime: Optional[Regime] = None

    def summary(self) -> str:
        lines = ["Regime Backtest Results", "=" * 50]
        for regime, metrics in sorted(
            self.per_regime_metrics.items(), key=lambda x: x[1].avg_pnl, reverse=True
        ):
            edge_marker = "✅ HAS EDGE" if metrics.has_edge else "❌ NO EDGE"
            lines.append(
                f"\n{regime.value.upper()} [{edge_marker}]\n"
                f"  Trades:    {metrics.trades}\n"
                f"  Win rate:  {metrics.win_rate:.1%}\n"
                f"  Avg P&L:   ₹{metrics.avg_pnl:,.2f}\n"
                f"  Sharpe:    {metrics.sharpe:.2f}\n"
                f"  Max DD:    {metrics.max_drawdown:.1%}"
            )
        if self.best_regime:
            lines.append(f"\n✅ Best regime:  {self.best_regime.value}")
        if self.worst_regime:
            lines.append(f"❌ Worst regime: {self.worst_regime.value}")
        return "\n".join(lines)

    def get_strategy_selector_config(self) -> dict:
        """
        Return a dict mapping regime → should_trade (bool).
        Used to configure StrategySelector's preferred_regimes for this strategy.
        """
        return {
            regime.value: metrics.has_edge
            for regime, metrics in self.per_regime_metrics.items()
        }


class RegimeBacktest:
    """
    Runs a backtest and splits trade results by the market regime at entry time.

    Usage:
        rb = RegimeBacktest()
        result = rb.run(historical_5min, pivot_strategy, regime_detector)
        print(result.summary())
        # Feed into ML trainer
        config = result.get_strategy_selector_config()
    """

    def __init__(self) -> None:
        pass

    def run(
        self,
        historical_data: pd.DataFrame,
        strategy: BaseStrategy,
        regime_detector: RegimeDetector,
        initial_capital: float = 20_000,
    ) -> RegimeBacktestResult:
        """
        Run the strategy backtest and split trade P&L by regime at entry.

        Args:
            historical_data: 5-minute OHLCV DataFrame.
            strategy: Strategy to test.
            regime_detector: Used to classify each trading day's regime.
            initial_capital: Starting capital.

        Returns:
            RegimeBacktestResult with per-regime metrics.
        """
        # TODO Phase 3: implement
        # 1. Build daily regime labels from daily OHLCV
        # 2. Run src/backtest/harness.py to get trades
        # 3. Join trades with regime labels by entry_date
        # 4. Aggregate metrics per regime
        raise NotImplementedError("Phase 3: implement RegimeBacktest.run()")

    def _label_trading_days(
        self, historical_data: pd.DataFrame, regime_detector: RegimeDetector
    ) -> dict[str, Regime]:
        """Return a map of trading_date_str → Regime for each day in the dataset."""
        # TODO Phase 3: implement
        raise NotImplementedError

    def _compute_regime_metrics(
        self, trades: list[dict], capital: float
    ) -> dict[Regime, RegimeMetrics]:
        """Group trades by regime and compute stats for each group."""
        metrics: dict[Regime, RegimeMetrics] = {}
        for trade in trades:
            try:
                regime = Regime(trade.get("regime", Regime.UNKNOWN.value))
            except ValueError:
                regime = Regime.UNKNOWN
            if regime not in metrics:
                metrics[regime] = RegimeMetrics(regime=regime)
            m = metrics[regime]
            pnl = float(trade.get("pnl", 0))
            m.trades += 1
            m.total_pnl += pnl
            if pnl > 0:
                m.wins += 1
        return metrics
