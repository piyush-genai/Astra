"""
PivotCprStrategy — Pivot + CPR Confluence Breakout on Nifty.

Signal logic (fully specified — task 6 resolved):
- Timeframe: 5-minute bars
- Entry trigger:
    Candle N  closes beyond a CONFLUENCE zone (2+ pivot levels)
    Candle N+1 also closes beyond that same zone  (confirmation)
    Entry at open of candle N+2
- Direction:
    Close above zone → LONG (buy Call)
    Close below zone → SHORT (buy Put)
- Initial stop:
    LONG:  min(zone.price_low, candle_N.low)
    SHORT: max(zone.price_high, candle_N.high)
- Trailing stop (after 2 post-entry candles have closed):
    Ratchet stop to low (long) / high (short) of candle 2 bars back.
    Never loosens. Checked intrabar — if violated inside a candle,
    exit immediately without waiting for close.
- Structural invalidation:
    If any candle CLOSES back on the wrong side of the broken zone,
    exit immediately regardless of stop level.
- Target:
    Next confluence zone in the direction of trade. Informational only —
    NOT an auto-exit. Scaling decisions are the execution layer's concern.

See src/data/indicators.py for zone detection and pivot formulas.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from src.data.indicators import (
    Zone,
    build_pivot_table,
    find_zones,
    zone_above,
    zone_below,
)
from src.engine.base_strategy import BaseStrategy, MarketData, Signal, SignalDirection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal signal state (pending confirmation across bars)
# ---------------------------------------------------------------------------

@dataclass
class _Pending:
    """A breakout that has fired but not yet been confirmed."""
    direction: SignalDirection
    breakout_bar: pd.Timestamp
    zone: Zone
    breakout_candle_low: float   # for initial stop calculation
    breakout_candle_high: float


@dataclass
class TradeSetup:
    """
    Fully confirmed setup ready for the execution layer.
    Returned inside Signal.metadata so ExecutionEngine can use it.
    """
    direction: SignalDirection
    breakout_time: pd.Timestamp
    confirm_time: pd.Timestamp
    entry_time: pd.Timestamp
    entry_price: float          # open of candle N+2 (approximate at signal time)
    zone: Zone
    initial_stop: float
    target_zone: Optional[Zone]


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------

class PivotCprStrategy(BaseStrategy):
    """
    Nifty 5-minute Pivot + CPR Confluence Breakout strategy.

    Config keys:
        tolerance_pct (float):       zone grouping tolerance in %.
                                     Default 0.18. Calibrate via backtest.
        min_levels_for_confluence (int): min levels to call a zone confluent.
                                     Default 2.
    """

    STRATEGY_ID = "pivot_cpr_strategy"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._tolerance_pct: float = float(config.get("tolerance_pct", 0.18))
        self._min_levels: int = int(config.get("min_levels_for_confluence", 2))

        # Rolling state across bars.
        self._pending: Optional[_Pending] = None
        self._pivot_table: Optional[pd.DataFrame] = None
        self._pivot_table_date: Optional[pd.Timestamp] = None

        logger.info(
            "PivotCprStrategy initialised | tolerance=%.3f%% | min_levels=%d",
            self._tolerance_pct, self._min_levels,
        )

    # ------------------------------------------------------------------
    # BaseStrategy contract
    # ------------------------------------------------------------------

    def evaluate(self, market_data: MarketData) -> Optional[Signal]:
        """
        Evaluate one 5-minute bar.

        Returns a Signal on the bar where the setup is confirmed
        (i.e. the confirmation candle, N+1 — the engine enters at N+2's open).
        Returns None otherwise.
        """
        history = market_data.history
        if history is None or len(history) < 2:
            return None

        bar_time = market_data.bar_time
        close    = market_data.close

        # ── Rebuild pivot table once per day ─────────────────────────────────
        today = bar_time.normalize()
        if self._pivot_table is None or today != self._pivot_table_date:
            self._pivot_table = self._build_pivots(history, today)
            self._pivot_table_date = today
            self._pending = None   # reset pending on day change

        if self._pivot_table is None:
            return None

        # ── Get today's zones ─────────────────────────────────────────────────
        if today not in self._pivot_table.index:
            return None

        zones = find_zones(
            self._pivot_table.loc[today],
            tolerance_pct=self._tolerance_pct,
        )
        confluence_zones = [z for z in zones if z.is_confluence]

        # ── State machine: no pending → look for breakout ─────────────────────
        if self._pending is None:
            # Get the previous bar's close from history to detect a crossing.
            if history is not None and len(history) >= 2:
                prev_close = float(history.iloc[-2]["close"]) if "close" in history.columns else None
            else:
                prev_close = None

            for z in confluence_zones:
                # A breakout requires price to have CROSSED the zone boundary,
                # not merely to be on one side of it (prevents false triggers
                # when price starts the day already far from the zone).
                broke_up   = (close > z.price_high and
                              prev_close is not None and prev_close <= z.price_high)
                broke_down = (close < z.price_low and
                              prev_close is not None and prev_close >= z.price_low)

                if broke_up:
                    self._pending = _Pending(
                        direction=SignalDirection.LONG,
                        breakout_bar=bar_time,
                        zone=z,
                        breakout_candle_low=market_data.low,
                        breakout_candle_high=market_data.high,
                    )
                    logger.debug(
                        "Breakout UP through zone [%.2f-%.2f] at %s",
                        z.price_low, z.price_high, bar_time,
                    )
                    break

                if broke_down:
                    self._pending = _Pending(
                        direction=SignalDirection.SHORT,
                        breakout_bar=bar_time,
                        zone=z,
                        breakout_candle_low=market_data.low,
                        breakout_candle_high=market_data.high,
                    )
                    logger.debug(
                        "Breakout DOWN through zone [%.2f-%.2f] at %s",
                        z.price_low, z.price_high, bar_time,
                    )
                    break

            return None  # breakout bar itself never emits a signal

        # ── Pending → check confirmation ──────────────────────────────────────
        p = self._pending
        confirmed = (
            close > p.zone.price_high if p.direction == SignalDirection.LONG
            else close < p.zone.price_low
        )

        if not confirmed:
            # Closed back inside or on wrong side — setup cancelled.
            logger.debug(
                "Breakout at %s cancelled — confirmation failed at %s",
                p.breakout_bar, bar_time,
            )
            self._pending = None
            return None

        # ── Confirmed — build the setup and emit a Signal ─────────────────────
        if p.direction == SignalDirection.LONG:
            initial_stop = min(p.zone.price_low, p.breakout_candle_low)
            target = zone_above(zones, p.zone.price_high)
        else:
            initial_stop = max(p.zone.price_high, p.breakout_candle_high)
            target = zone_below(zones, p.zone.price_low)

        setup = TradeSetup(
            direction=p.direction,
            breakout_time=p.breakout_bar,
            confirm_time=bar_time,
            entry_time=bar_time,   # engine enters at next bar's open
            entry_price=market_data.close,
            zone=p.zone,
            initial_stop=initial_stop,
            target_zone=target,
        )

        logger.info(
            "Signal confirmed | %s | zone=[%.2f-%.2f] | stop=%.2f | target=%s",
            p.direction,
            p.zone.price_low, p.zone.price_high,
            initial_stop,
            f"[{target.price_low:.2f}-{target.price_high:.2f}]" if target else "none",
        )

        self._pending = None

        return Signal(
            strategy_id=self.STRATEGY_ID,
            instrument=market_data.instrument,
            direction=p.direction,
            bar_time=bar_time,
            metadata={"setup": setup},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_pivots(
        self,
        history: pd.DataFrame,
        today: pd.Timestamp,
    ) -> Optional[pd.DataFrame]:
        """
        Build the daily pivot table from intraday history.

        history is 5-min bars; resample to daily OHLC first.
        Returns None if there isn't enough daily history.
        """
        history = history.copy()
        history.columns = [c.lower() for c in history.columns]

        daily = history.resample("D").agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
        ).dropna(subset=["open"])

        # Need at least 2 daily rows (yesterday + today stub) to have
        # a valid prior-day row after .shift(1).
        if len(daily) < 2:
            logger.debug("Insufficient daily history to build pivot table.")
            return None

        # Ensure today is included so pivot_table.loc[today] works.
        if today not in daily.index:
            # Add a placeholder row for today using the latest intraday bar.
            today_bars = history[history.index.normalize() == today]
            if not today_bars.empty:
                daily.loc[today] = {
                    "open":  today_bars["open"].iloc[0],
                    "high":  today_bars["high"].max(),
                    "low":   today_bars["low"].min(),
                    "close": today_bars["close"].iloc[-1],
                }
                daily = daily.sort_index()

        return build_pivot_table(daily)
