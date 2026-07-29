"""
Backtest harness — stub.

Runs a strategy against historical OHLCV data and collects signals,
then layers an approximate options P&L on top.

Will be fleshed out in tasks 8–10 of the pivot-cpr-strategy spec,
after Stage 2 evaluate() is unblocked (task 7).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from src.engine.base_strategy import BaseStrategy, MarketData, Signal

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    signals: list[Signal] = field(default_factory=list)
    # Populated after options P&L overlay is implemented (task 10).
    equity_curve: Optional[pd.Series] = None
    metrics: dict = field(default_factory=dict)


class BacktestHarness:
    """
    Iterates over historical bars, calls strategy.evaluate() on each,
    and records signals.

    Transaction costs are applied using values from instruments.yaml
    (never hardcoded) — see task 8 in the spec.
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        instruments_config: dict,
        history_window: int = 100,  # bars of history passed to each evaluate() call
    ) -> None:
        self._strategy = strategy
        self._instruments = instruments_config
        self._history_window = history_window

    def run(self, ohlcv: pd.DataFrame) -> BacktestResult:
        """
        Run the backtest over the full OHLCV frame.

        Args:
            ohlcv: DataFrame with DatetimeIndex and columns open/high/low/close/volume.

        Returns:
            BacktestResult with signals list.
        """
        result = BacktestResult()
        ohlcv = ohlcv.copy()
        ohlcv.columns = [c.lower() for c in ohlcv.columns]

        for i in range(self._history_window, len(ohlcv)):
            bar = ohlcv.iloc[i]
            history = ohlcv.iloc[max(0, i - self._history_window): i + 1]

            market_data = MarketData(
                instrument="NIFTY",  # TODO: make configurable
                bar_time=bar.name,
                open=float(bar["open"]),
                high=float(bar["high"]),
                low=float(bar["low"]),
                close=float(bar["close"]),
                volume=float(bar.get("volume", 0)),
                history=history,
            )

            try:
                signal = self._strategy.evaluate(market_data)
            except Exception:
                logger.exception("Strategy raised during bar %s; skipping.", bar.name)
                continue

            if signal is not None:
                result.signals.append(signal)
                logger.debug("Signal: %s @ %s", signal.direction, bar.name)

        logger.info(
            "Backtest complete — %d bars processed, %d signals generated.",
            len(ohlcv) - self._history_window,
            len(result.signals),
        )
        return result
