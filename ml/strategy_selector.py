"""
Strategy Selector — the Astra decision layer.

Given a market regime and instrument type, selects the best strategy to deploy.
Tracks per-regime performance so it can learn which strategy works when.

Key design rule: the selector NEVER modifies strategy parameters.
It only decides which strategy to run (or not run at all).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from strategies.base import BaseStrategy, InstrumentType, Regime


@dataclass
class RegimePerformance:
    """Running performance stats for one strategy in one regime."""
    strategy_name: str
    regime: Regime
    total_trades: int = 0
    winning_trades: int = 0
    total_pnl: float = 0.0
    # Exponentially weighted running mean (recent trades count more)
    ewa_pnl: float = 0.0
    decay_factor: float = 0.95  # weight given to past observations

    @property
    def win_rate(self) -> float:
        return self.winning_trades / self.total_trades if self.total_trades > 0 else 0.0

    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.total_trades if self.total_trades > 0 else 0.0

    @property
    def has_enough_data(self) -> bool:
        return self.total_trades >= 50  # min samples before trusting this stat


class StrategySelector:
    """
    Selects which strategy (or strategies) to deploy given current market conditions.

    On startup, uses strategy metadata (preferred_regimes, expected_win_rate) as priors.
    After enough live/paper trades accumulate per regime, switches to observed performance.

    Usage:
        selector = StrategySelector(strategies=[pivot_cpr, momentum])
        best = selector.select(Regime.TRENDING_UP, InstrumentType.INDEX_OPTION)
        allocations = selector.select_with_allocation(Regime.RANGING, capital=100_000)
    """

    def __init__(
        self,
        strategies: list[BaseStrategy],
        min_regime_samples: int = 50,
        performance_decay_factor: float = 0.95,
    ) -> None:
        self._strategies = strategies
        self._min_regime_samples = min_regime_samples
        self._decay = performance_decay_factor
        # _performance_matrix[regime][strategy_name] = RegimePerformance
        self._performance_matrix: dict[Regime, dict[str, RegimePerformance]] = defaultdict(dict)
        self._initialize_priors()

    def select(
        self, regime: Regime, instrument_type: InstrumentType
    ) -> Optional[BaseStrategy]:
        """
        Select the single best strategy for the given regime and instrument type.

        Returns None if no applicable strategy passes minimum confidence threshold,
        which halts trading for that instrument rather than forcing a bad trade.
        """
        candidates = [
            s for s in self._strategies if s.is_applicable(instrument_type, regime)
        ]
        if not candidates:
            return None

        # Score each candidate
        scored = [(s, self._score(s, regime)) for s in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        best_strategy, best_score = scored[0]

        # If best score is negative expected value, trade nothing
        if best_score <= 0:
            return None
        return best_strategy

    def select_with_allocation(
        self, regime: Regime, available_capital: float
    ) -> list[tuple[BaseStrategy, float]]:
        """
        Select multiple strategies and their capital fractions for a given regime.

        Returns a list of (strategy, capital_fraction) pairs, ordered best-first.
        Fractions sum to at most 1.0. Returns empty list if no strategy has edge.

        Used when running multiple instruments simultaneously.
        """
        # TODO Phase 4: implement Kelly-based allocation across strategies
        # For now: single strategy gets all capital
        all_instrument_types = list(InstrumentType)
        for instrument_type in all_instrument_types:
            strategy = self.select(regime, instrument_type)
            if strategy:
                return [(strategy, 1.0)]
        return []

    def update_performance(
        self, strategy_name: str, regime: Regime, outcome: dict
    ) -> None:
        """
        Record a completed trade outcome to update per-regime performance.

        Args:
            strategy_name: Strategy that generated the signal.
            regime: Market regime at trade entry.
            outcome: Dict with keys: pnl (float), win (bool).
        """
        if strategy_name not in self._performance_matrix[regime]:
            self._performance_matrix[regime][strategy_name] = RegimePerformance(
                strategy_name=strategy_name,
                regime=regime,
                decay_factor=self._decay,
            )
        perf = self._performance_matrix[regime][strategy_name]
        pnl = float(outcome.get("pnl", 0.0))
        won = bool(outcome.get("win", pnl > 0))
        perf.total_trades += 1
        perf.total_pnl += pnl
        if won:
            perf.winning_trades += 1
        # Exponentially weighted average PnL
        perf.ewa_pnl = self._decay * perf.ewa_pnl + (1 - self._decay) * pnl

    def get_performance_report(self) -> dict:
        """Return a human-readable summary of per-regime performance."""
        report = {}
        for regime, strategies in self._performance_matrix.items():
            report[regime.value] = {
                name: {
                    "trades": p.total_trades,
                    "win_rate": round(p.win_rate, 3),
                    "avg_pnl": round(p.avg_pnl, 2),
                    "ewa_pnl": round(p.ewa_pnl, 2),
                    "data_sufficient": p.has_enough_data,
                }
                for name, p in strategies.items()
            }
        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _initialize_priors(self) -> None:
        """Seed the performance matrix with strategy metadata as priors."""
        for strategy in self._strategies:
            meta = strategy.metadata
            for regime in meta.preferred_regimes:
                self._performance_matrix[regime][meta.name] = RegimePerformance(
                    strategy_name=meta.name,
                    regime=regime,
                    # Seed with backtest win rate so selector has a prior before live data
                    total_trades=self._min_regime_samples,
                    winning_trades=int(meta.expected_win_rate * self._min_regime_samples),
                    total_pnl=meta.expected_win_rate * meta.expected_rr * self._min_regime_samples,
                )

    def _score(self, strategy: BaseStrategy, regime: Regime) -> float:
        """
        Score a strategy for a given regime.

        Uses observed performance if enough data exists, otherwise falls back
        to strategy metadata priors.
        Returns expected PnL per trade (positive = edge exists).
        """
        perf = self._performance_matrix.get(regime, {}).get(strategy.metadata.name)
        if perf and perf.has_enough_data:
            return perf.ewa_pnl
        # Prior from metadata: E[PnL] = win_rate * RR - (1 - win_rate)
        meta = strategy.metadata
        return meta.expected_win_rate * meta.expected_rr - (1 - meta.expected_win_rate)
