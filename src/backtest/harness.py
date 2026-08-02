"""
Backtest harness.

Runs a strategy against historical OHLCV data, enforces one-trade-at-a-time
position discipline (mirroring what PositionManager does in live trading),
applies trailing-stop and structural-invalidation exits, and reports results.

Options P&L overlay (task 10) will be layered on top once signal quality
is confirmed via this index-point P&L approximation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from src.engine.base_strategy import BaseStrategy, MarketData, Signal, SignalDirection

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """A completed trade with entry, exit and P&L in index points."""
    signal: Signal
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp
    exit_price: float
    exit_reason: str        # "stop", "structural", "eod", "target"
    direction: SignalDirection
    initial_stop: float

    @property
    def pnl_points(self) -> float:
        if self.direction == SignalDirection.LONG:
            return self.exit_price - self.entry_price
        else:
            return self.entry_price - self.exit_price


@dataclass
class BacktestResult:
    signals: list[Signal] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    equity_curve: Optional[pd.Series] = None
    metrics: dict = field(default_factory=dict)

    def compute_metrics(self) -> None:
        if not self.trades:
            self.metrics = {"total_trades": 0}
            return

        pnls = [t.pnl_points for t in self.trades]
        winners = [p for p in pnls if p > 0]
        losers  = [p for p in pnls if p <= 0]

        gross_profit = sum(winners) if winners else 0.0
        gross_loss   = abs(sum(losers)) if losers else 0.0

        cumulative = pd.Series(pnls).cumsum()
        running_max = cumulative.cummax()
        drawdown = cumulative - running_max
        max_dd = drawdown.min()

        self.metrics = {
            "total_trades":   len(self.trades),
            "winners":        len(winners),
            "losers":         len(losers),
            "win_rate_pct":   round(100 * len(winners) / len(self.trades), 1),
            "total_pnl_pts":  round(sum(pnls), 2),
            "avg_win_pts":    round(sum(winners) / len(winners), 2) if winners else 0,
            "avg_loss_pts":   round(sum(losers) / len(losers), 2) if losers else 0,
            "profit_factor":  round(gross_profit / gross_loss, 2) if gross_loss else float("inf"),
            "max_drawdown_pts": round(max_dd, 2),
            "exit_reasons":   {r: sum(1 for t in self.trades if t.exit_reason == r)
                               for r in ("stop", "structural", "eod", "target")},
        }
        self.equity_curve = cumulative


class BacktestHarness:
    """
    Iterates over historical 5-min bars, calls strategy.evaluate() on each,
    and simulates trade execution with:
      - One active position at a time (mirrors PositionManager concurrency rules)
      - Trailing stop: ratchet to low/high of bar 2 bars back, after 2 post-entry bars
      - Structural invalidation: close back through broken zone → exit
      - End-of-day close: any open position exits at the last bar's close

    All P&L is in index points (not rupees/options premium).
    Options P&L overlay is task 10.
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        instruments_config: dict,
        history_window: int = 100,
    ) -> None:
        self._strategy = strategy
        self._instruments = instruments_config
        self._history_window = history_window

    def run(self, ohlcv: pd.DataFrame) -> BacktestResult:
        ohlcv = ohlcv.copy()
        ohlcv.columns = [c.lower() for c in ohlcv.columns]

        result = BacktestResult()

        # Active position state
        active_signal: Optional[Signal]     = None
        entry_price:   Optional[float]      = None
        entry_time:    Optional[pd.Timestamp] = None
        current_stop:  Optional[float]      = None
        bars_in_trade: int                  = 0

        for i in range(self._history_window, len(ohlcv)):
            bar      = ohlcv.iloc[i]
            bar_time = bar.name
            history  = ohlcv.iloc[max(0, i - self._history_window): i + 1]

            # ── Manage active position ────────────────────────────────────────
            if active_signal is not None:
                setup     = active_signal.metadata["setup"]
                direction = active_signal.direction
                bars_in_trade += 1

                # Trailing stop: after 2 post-entry bars, ratchet to 2-bars-back extreme.
                if bars_in_trade >= 2 and i >= 2:
                    bar_2back = ohlcv.iloc[i - 2]
                    if direction == SignalDirection.LONG:
                        new_stop = bar_2back["low"]
                        if new_stop > current_stop:
                            current_stop = new_stop
                    else:
                        new_stop = bar_2back["high"]
                        if new_stop < current_stop:
                            current_stop = new_stop

                # Check stop hit (intrabar — uses low/high of current bar).
                stop_hit = (
                    bar["low"]  <= current_stop if direction == SignalDirection.LONG
                    else bar["high"] >= current_stop
                )

                # Check structural invalidation: close back through broken zone.
                zone = setup.zone
                structural_exit = (
                    bar["close"] < zone.price_low  if direction == SignalDirection.LONG
                    else bar["close"] > zone.price_high
                )

                # End-of-day: last bar of the session (15:25 or 15:29).
                is_eod = bar_time.time() >= pd.Timestamp("15:25").time()

                exit_price  = None
                exit_reason = None

                if stop_hit:
                    exit_price  = current_stop
                    exit_reason = "stop"
                elif structural_exit:
                    exit_price  = bar["close"]
                    exit_reason = "structural"
                elif is_eod:
                    exit_price  = bar["close"]
                    exit_reason = "eod"

                if exit_price is not None:
                    trade = Trade(
                        signal=active_signal,
                        entry_time=entry_time,
                        entry_price=entry_price,
                        exit_time=bar_time,
                        exit_price=exit_price,
                        exit_reason=exit_reason,
                        direction=direction,
                        initial_stop=setup.initial_stop,
                    )
                    result.trades.append(trade)
                    logger.debug(
                        "EXIT %s | entry=%.2f exit=%.2f pnl=%.2f pts | reason=%s | %s",
                        direction, entry_price, exit_price, trade.pnl_points, exit_reason, bar_time,
                    )
                    active_signal = None
                    entry_price   = None
                    entry_time    = None
                    current_stop  = None
                    bars_in_trade = 0
                    continue  # Don't evaluate for new entry on same bar as exit

            # ── Evaluate strategy for new signal ─────────────────────────────
            market_data = MarketData(
                instrument="NIFTY",
                bar_time=bar_time,
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
                logger.exception("Strategy raised during bar %s; skipping.", bar_time)
                continue

            if signal is not None:
                result.signals.append(signal)

                # One trade at a time — only enter if flat.
                if active_signal is None:
                    setup = signal.metadata["setup"]
                    # Entry price = next bar's open (approximate with current close + 1 tick).
                    # We'll use next bar's open on the following iteration for accuracy,
                    # but for simplicity use this bar's close as the entry approximation.
                    next_i = i + 1
                    if next_i < len(ohlcv):
                        entry_price   = float(ohlcv.iloc[next_i]["open"])
                        entry_time    = ohlcv.index[next_i]
                    else:
                        entry_price   = float(bar["close"])
                        entry_time    = bar_time

                    active_signal = signal
                    current_stop  = setup.initial_stop
                    bars_in_trade = 0
                    logger.debug(
                        "ENTRY %s @ %.2f | stop=%.2f | %s",
                        signal.direction, entry_price, current_stop, entry_time,
                    )
                else:
                    logger.debug(
                        "Signal %s at %s suppressed — position already active.",
                        signal.direction, bar_time,
                    )

        # ── Close any open position at end of data ────────────────────────────
        if active_signal is not None:
            last_bar = ohlcv.iloc[-1]
            setup    = active_signal.metadata["setup"]
            trade = Trade(
                signal=active_signal,
                entry_time=entry_time,
                entry_price=entry_price,
                exit_time=ohlcv.index[-1],
                exit_price=float(last_bar["close"]),
                exit_reason="eod",
                direction=active_signal.direction,
                initial_stop=setup.initial_stop,
            )
            result.trades.append(trade)

        result.compute_metrics()

        logger.info(
            "Backtest complete — %d bars, %d signals, %d trades executed.",
            len(ohlcv) - self._history_window,
            len(result.signals),
            len(result.trades),
        )
        return result
