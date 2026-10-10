"""
Strategy Comparison — runs multiple strategies on the same data and ranks them.

Use this to:
  1. Compare a new strategy against PivotCPR before promoting it to live.
  2. Find correlations between strategies (low correlation = good diversification).
  3. Pick the best strategy per market regime.

Generates a markdown report for commit history / documentation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


@dataclass
class StrategyStats:
    """Performance stats for one strategy in the comparison."""
    name: str
    total_return: float = 0.0
    annualised_return: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    avg_pnl_per_trade: float = 0.0
    total_trades: int = 0
    calmar: float = 0.0   # annualised_return / abs(max_drawdown)

    def __post_init__(self) -> None:
        if self.max_drawdown != 0:
            self.calmar = self.annualised_return / abs(self.max_drawdown)


@dataclass
class ComparisonResult:
    """Head-to-head comparison of multiple strategies."""
    per_strategy: dict[str, StrategyStats] = field(default_factory=dict)
    winner_by_return: Optional[str] = None
    winner_by_sharpe: Optional[str] = None
    winner_by_max_drawdown: Optional[str] = None   # smallest drawdown
    winner_by_calmar: Optional[str] = None
    correlation_matrix: Optional[pd.DataFrame] = None   # pnl time-series correlation

    def ranking_table(self) -> pd.DataFrame:
        """Return a DataFrame ranking all strategies across all metrics."""
        rows = []
        for name, stats in self.per_strategy.items():
            rows.append({
                "Strategy": name,
                "Return": f"{stats.total_return:+.1%}",
                "Sharpe": f"{stats.sharpe:.2f}",
                "Max Drawdown": f"{stats.max_drawdown:.1%}",
                "Calmar": f"{stats.calmar:.2f}",
                "Win Rate": f"{stats.win_rate:.1%}",
                "Trades": stats.total_trades,
            })
        df = pd.DataFrame(rows)
        return df.sort_values("Sharpe", ascending=False).reset_index(drop=True)


class StrategyComparison:
    """
    Runs multiple strategies on the same historical data and compares performance.

    Usage:
        comparison = StrategyComparison()
        result = comparison.compare([pivot_cpr, momentum_v2], historical_data)
        print(comparison.generate_report(result))
    """

    def compare(
        self,
        strategies: list[BaseStrategy],
        historical_data: pd.DataFrame,
        capital: float = 20_000,
    ) -> ComparisonResult:
        """
        Run each strategy on the same historical data and collect metrics.

        Args:
            strategies: List of strategies to compare.
            historical_data: 5-minute OHLCV. All strategies see identical data.
            capital: Starting capital per strategy (independent runs).

        Returns:
            ComparisonResult with per-strategy metrics and correlation matrix.
        """
        # TODO Phase 3: implement
        # For each strategy:
        #   1. Run src/backtest/harness.py
        #   2. Compute StrategyStats
        # Compute correlation matrix from daily P&L time series
        raise NotImplementedError("Phase 3: implement StrategyComparison.compare()")

    def generate_report(self, result: ComparisonResult) -> str:
        """
        Generate a markdown-formatted report from ComparisonResult.

        Suitable for saving to disk or posting in a PR description.
        """
        lines = [
            "# Strategy Comparison Report",
            "",
            "## Rankings",
            "",
            result.ranking_table().to_markdown(index=False),
            "",
            "## Winners",
            f"- **Best Return**: {result.winner_by_return}",
            f"- **Best Sharpe**: {result.winner_by_sharpe}",
            f"- **Smallest Drawdown**: {result.winner_by_max_drawdown}",
            f"- **Best Calmar**: {result.winner_by_calmar}",
            "",
        ]
        if result.correlation_matrix is not None:
            lines += [
                "## P&L Correlation Matrix",
                "",
                "> Values near 0 = good diversification; values near 1 = strategies overlap",
                "",
                result.correlation_matrix.round(2).to_markdown(),
                "",
            ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_stats(
        self, trades: list[dict], capital: float, strategy_name: str
    ) -> StrategyStats:
        """Convert a list of trade dicts into a StrategyStats object."""
        if not trades:
            return StrategyStats(name=strategy_name)
        pnls = [float(t["pnl"]) for t in trades]
        wins = sum(1 for p in pnls if p > 0)
        equity = pd.Series(pnls).cumsum() + capital
        daily_ret = equity.pct_change().dropna()
        total_return = float((equity.iloc[-1] - capital) / capital)
        sharpe = float(daily_ret.mean() / daily_ret.std() * (252 ** 0.5)) if daily_ret.std() > 0 else 0.0
        max_dd = float(((equity - equity.cummax()) / equity.cummax()).min())
        # Annualise: assume 250 trading days, proportional
        trading_days = max(1, len(set(t.get("entry_date", "") for t in trades)))
        annualised = (1 + total_return) ** (250 / trading_days) - 1
        return StrategyStats(
            name=strategy_name,
            total_return=total_return,
            annualised_return=annualised,
            sharpe=sharpe,
            max_drawdown=max_dd,
            win_rate=wins / len(pnls),
            avg_pnl_per_trade=float(np.mean(pnls)),
            total_trades=len(pnls),
        )

    def _compute_correlation(
        self, pnl_series_map: dict[str, pd.Series]
    ) -> pd.DataFrame:
        """Compute pairwise correlation of daily P&L series."""
        df = pd.DataFrame(pnl_series_map).fillna(0)
        return df.corr()
