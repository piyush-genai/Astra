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
        
        # Momentum breakout settings (NEW)
        momentum_enabled (bool):     Enable momentum breakout signals.
                                     Default True.
        momentum_volume_multiplier (float): Volume must exceed this multiple
                                     of 20-bar average. Default 2.0.
        momentum_body_pct (float):   Candle body must be this % of total range.
                                     Default 0.75 (75%).
        momentum_accel_multiplier (float): Current range must exceed previous
                                     range by this multiple. Default 1.5.
        momentum_min_criteria (int): Minimum criteria that must be met (of 3).
                                     Default 2.
    """

    STRATEGY_ID = "pivot_cpr_strategy"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._tolerance_pct: float = float(config.get("tolerance_pct", 0.18))
        self._min_levels: int = int(config.get("min_levels_for_confluence", 2))

        # Momentum breakout config
        self._momentum_enabled: bool = config.get("momentum_enabled", True)
        self._momentum_vol_mult: float = float(config.get("momentum_volume_multiplier", 2.0))
        self._momentum_body_pct: float = float(config.get("momentum_body_pct", 0.75))
        self._momentum_accel_mult: float = float(config.get("momentum_accel_multiplier", 1.5))
        self._momentum_min_criteria: int = int(config.get("momentum_min_criteria", 2))
        self._momentum_checked: bool = False  # Track if we've logged at least once

        # Rolling state across bars.
        self._pending: Optional[_Pending] = None
        self._pivot_table: Optional[pd.DataFrame] = None
        self._pivot_table_date: Optional[pd.Timestamp] = None

        logger.info(
            "PivotCprStrategy initialised | tolerance=%.3f%% | min_levels=%d | momentum=%s (vol×%.1f, body≥%.0f%%, accel×%.1f)",
            self._tolerance_pct, self._min_levels, 
            "enabled" if self._momentum_enabled else "disabled",
            self._momentum_vol_mult, self._momentum_body_pct * 100, self._momentum_accel_mult,
        )

    # ------------------------------------------------------------------
    # BaseStrategy contract
    # ------------------------------------------------------------------

    def evaluate(self, market_data: MarketData) -> Optional[Signal]:
        """
        Evaluate one 5-minute bar.

        Returns a Signal on the bar where the setup is confirmed
        (i.e. the confirmation candle, N+1 — the engine enters at N+2's open).
        
        OR returns an immediate momentum breakout signal if criteria are met.
        
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
            # Check if strategy has daily_ohlc injected (for live trading)
            daily_ohlc = getattr(self, '_daily_ohlc', None)
            self._pivot_table = self._build_pivots(history, today, daily_ohlc=daily_ohlc)
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
        # Accept 3 zone types:
        # 1. True confluence (2+ different timeframes)
        # 2. Daily/CPR-only (heavily watched in Indian markets)
        # 3. Strong single weekly/monthly levels (major institutional S/R)
        tradeable_zones = [
            z for z in zones 
            if z.is_confluence or z.is_daily_cpr_only or z.is_strong_single_level
        ]

        # ── Check for MOMENTUM BREAKOUT (priority check - immediate entry) ────
        if self._momentum_enabled:
            # Log once to confirm we're trying
            if not hasattr(self, '_momentum_attempt_logged'):
                logger.info("Attempting momentum breakout checks (enabled)")
                self._momentum_attempt_logged = True
                
            if len(history) < 21:  # Need 20 for avg + 1 current
                if not hasattr(self, '_momentum_hist_warning_shown'):
                    logger.warning(
                        "Momentum breakout disabled - insufficient history (%d bars, need 21+)",
                        len(history)
                    )
                    self._momentum_hist_warning_shown = True
            else:
                momentum_signal = self._check_momentum_breakout(
                    market_data, tradeable_zones, history
                )
                if momentum_signal is not None:
                    # Clear any pending regular breakout - momentum takes priority
                    self._pending = None
                    return momentum_signal

        # ── State machine: no pending → look for breakout ─────────────────────
        if self._pending is None:
            # Get the previous bar's close from history to detect a crossing.
            if history is not None and len(history) >= 2:
                prev_close = float(history.iloc[-2]["close"]) if "close" in history.columns else None
            else:
                prev_close = None

            for z in tradeable_zones:
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
            metadata={
                "setup": setup,
                "signal_type": "regular",
            },
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_momentum_breakout(
        self,
        market_data: MarketData,
        zones: list[Zone],
        history: pd.DataFrame,
    ) -> Optional[Signal]:
        """
        Check if current bar qualifies as a high-impact momentum breakout.
        
        VOLUME-FREE IMPLEMENTATION (volume data not available from broker):
        Criteria:
        1. Range explosion: current range > accel_multiplier × average of last 10 bars
        2. Strong body: candle body > body_pct of total range
        3. Multi-level penetration: breaks through zone + moves deep beyond it
        
        If enough criteria met + breaks a zone → immediate entry signal.
        
        This captures violent moves like July 8th crash without volume.
        """
        bar = history.iloc[-1]
        
        # Log first successful check to confirm momentum logic is running
        if not self._momentum_checked:
            logger.info(
                "✓ Momentum breakout checker active (VOLUME-FREE mode) | Looking for: range≥%.1fx avg, body≥%.0f%%",
                self._momentum_accel_mult, self._momentum_body_pct * 100,
            )
            self._momentum_checked = True
        
        # Calculate metrics
        body_size = abs(bar["close"] - bar["open"])
        total_range = bar["high"] - bar["low"]
        
        if total_range == 0:  # Avoid division by zero
            return None
        
        # Criterion 1: Range explosion (replaces volume spike)
        # Compare current candle range to average of last 10 candles
        recent_ranges = []
        for i in range(-11, -1):  # Last 10 bars (exclude current)
            if abs(i) <= len(history):
                bar_hist = history.iloc[i]
                recent_ranges.append(bar_hist["high"] - bar_hist["low"])
        
        if not recent_ranges:
            return None
        
        avg_range = sum(recent_ranges) / len(recent_ranges)
        range_explosion = total_range > (self._momentum_accel_mult * avg_range) if avg_range > 0 else False
        
        # Criterion 2: Strong body (not a doji/wick)
        strong_body = (body_size / total_range) > self._momentum_body_pct
        
        # Criterion 3: Deep penetration (NEW - replaces acceleration check)
        # If price moves MORE than 1.5× zone width beyond the zone, it's a strong breakout
        deep_penetration = False
        
        # Count how many criteria met
        criteria = [range_explosion, strong_body]  # Start with 2 base criteria
        score = sum(criteria)
        
        # Log momentum checks for analysis (even when criteria not fully met)
        if score >= 1 or range_explosion:  # Log if any momentum detected
            logger.debug(
                "Momentum check @ %s | range=%.2f (avg=%.2f, mult=%.2fx) | body=%.1f%% | score=%d/%d",
                market_data.bar_time,
                total_range, avg_range, total_range / avg_range if avg_range > 0 else 0,
                100 * (body_size / total_range),
                score, 2,  # Out of 2 base criteria
            )
        
        # Relaxed threshold: need only 1 strong criterion + zone break
        # (since we don't have volume, we're more aggressive)
        if score < 1:
            return None  # Not enough momentum
        
        # Check if this bar broke through any zone
        for zone in zones:
            broke_up = bar["close"] > zone.price_high
            broke_down = bar["close"] < zone.price_low
            
            if not (broke_up or broke_down):
                continue
            
            # Check for deep penetration (3rd criterion)
            zone_width = zone.price_high - zone.price_low
            if broke_up:
                penetration_depth = bar["close"] - zone.price_high
                deep_penetration = penetration_depth > (1.5 * zone_width) if zone_width > 0 else False
            else:
                penetration_depth = zone.price_low - bar["close"]
                deep_penetration = penetration_depth > (1.5 * zone_width) if zone_width > 0 else False
            
            # Add deep penetration to score
            if deep_penetration:
                score += 1
            
            # MOMENTUM BREAKOUT CONFIRMED (need 2+ of 3 criteria)
            if score >= 2:
                direction = SignalDirection.LONG if broke_up else SignalDirection.SHORT
                
                # Tighter stop for momentum trades - 50% retracement of breakout candle
                if direction == SignalDirection.LONG:
                    initial_stop = bar["low"] + 0.5 * (bar["close"] - bar["low"])
                else:
                    initial_stop = bar["high"] - 0.5 * (bar["high"] - bar["close"])
                
                target = zone_above(zones, zone.price_high) if broke_up else zone_below(zones, zone.price_low)
                
                setup = TradeSetup(
                    direction=direction,
                    breakout_time=market_data.bar_time,
                    confirm_time=market_data.bar_time,  # Immediate, no confirmation needed
                    entry_time=market_data.bar_time,
                    entry_price=market_data.close,
                    zone=zone,
                    initial_stop=initial_stop,
                    target_zone=target,
                )
                
                logger.info(
                    "⚡ MOMENTUM BREAKOUT | %s | zone=[%.2f-%.2f] | range_explo=%s body=%s deep_pen=%s | score=%d/3",
                    direction,
                    zone.price_low, zone.price_high,
                    "✓" if range_explosion else "✗",
                    "✓" if strong_body else "✗",
                    "✓" if deep_penetration else "✗",
                    score,
                )
                
                return Signal(
                    strategy_id=self.STRATEGY_ID,
                    instrument=market_data.instrument,
                    direction=direction,
                    bar_time=market_data.bar_time,
                    metadata={
                        "setup": setup,
                        "signal_type": "momentum",
                        "range_explosion": range_explosion,
                        "strong_body": strong_body,
                        "deep_penetration": deep_penetration,
                        "momentum_score": score,
                    },
                )
        
        return None  # Momentum criteria met but no zone broken OR insufficient score

    def _build_pivots(
        self,
        history: pd.DataFrame,
        today: pd.Timestamp,
        daily_ohlc: Optional[pd.DataFrame] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Build the daily pivot table.

        Args:
            history: 5-min bars (fallback if daily_ohlc not provided)
            today: Current trading day
            daily_ohlc: Optional pre-fetched daily OHLC data (PREFERRED)
        
        If daily_ohlc is provided, use it directly. Otherwise, resample from
        intraday history (requires many bars).
        
        Returns None if there isn't enough data.
        """
        if daily_ohlc is not None:
            # Use pre-fetched daily data (preferred path for live trading)
            daily = daily_ohlc.copy()
            daily.columns = [c.lower() for c in daily.columns]
            
            # Ensure today is included
            if today not in daily.index:
                # Get today's partial bar from intraday history
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
        
        # Fallback: resample from 5-min bars (needs many bars)
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
