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

from core.engine.base_strategy import BaseStrategy, MarketData, Signal, SignalDirection

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
    lots: int = 1           # Number of lots traded (for position sizing)

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
    suppressed_signals: list[dict] = field(default_factory=list)  # NEW: track why signals didn't trade
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
                               for r in ("stop", "structural", "eod", "target", "reversal")},
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
        risk_config: dict,  # NEW: Pass risk config instead of individual params
        history_window: int = 100,
        cooldown_minutes: int = 0,  # DISABLED: let stop-loss be discipline, not cooldown
        allow_hedge: bool = True,   # Allow opposite-direction entries (hedge mode)
        initial_capital: Optional[float] = None,  # For position sizing (None = unlimited)
    ) -> None:
        self._strategy = strategy
        self._instruments = instruments_config
        self._risk_config = risk_config
        self._history_window = history_window
        self._cooldown_minutes = cooldown_minutes
        self._allow_hedge = allow_hedge
        self._initial_capital = initial_capital
        
        # Load risk parameters from config
        per_trade_cfg = risk_config["per_trade"]
        position_limits_cfg = risk_config["position_limits"]
        
        self._risk_per_trade_pct = per_trade_cfg["max_loss_per_trade_pct"] / 100.0
        self._max_capital_deployed_pct = per_trade_cfg["max_capital_deployed_pct"] / 100.0
        self._max_lots_per_trade = position_limits_cfg["hard_cap_lots"]
        self._current_capital = initial_capital  # Tracks capital as trades complete

    def run(self, ohlcv: pd.DataFrame, pricer=None) -> BacktestResult:
        """
        Run backtest on OHLCV data.
        
        Args:
            ohlcv: OHLCV DataFrame with DatetimeIndex
            pricer: Optional OptionsPricer for calculating position size based on premium
        """
        ohlcv = ohlcv.copy()
        ohlcv.columns = [c.lower() for c in ohlcv.columns]

        result = BacktestResult()
        
        # Reset capital to initial value at start of run
        if self._initial_capital is not None:
            self._current_capital = self._initial_capital

        # Active position state
        active_signal: Optional[Signal]     = None
        entry_price:   Optional[float]      = None
        entry_time:    Optional[pd.Timestamp] = None
        current_stop:  Optional[float]      = None
        bars_in_trade: int                  = 0
        position_lots: int                  = 0  # Lots in current position

        # Zone cooldown tracking
        last_exit_zone: Optional[tuple]     = None
        last_exit_time: Optional[pd.Timestamp] = None

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
                        lots=position_lots,
                    )
                    result.trades.append(trade)
                    
                    # Update capital if position sizing enabled
                    if self._current_capital is not None and pricer is not None:
                        direction_str = "LONG" if direction == SignalDirection.LONG else "SHORT"
                        leg = pricer.price_trade(
                            direction=direction_str,
                            entry_spot=entry_price,
                            entry_time=entry_time,
                            exit_spot=exit_price,
                            exit_time=bar_time,
                        )
                        # P&L scaled by lots
                        pnl_rupees = leg.pnl_rupees * position_lots
                        # TX costs per lot
                        tx_cost_per_lot = (
                            40.0 +  # Brokerage ₹20 × 2 legs
                            leg.entry_premium * 0.0015 * pricer.lot_size +  # STT
                            5.0  # SEBI + GST
                        )
                        total_tx_cost = tx_cost_per_lot * position_lots
                        net_pnl = pnl_rupees - total_tx_cost
                        self._current_capital += net_pnl
                    
                    logger.debug(
                        "EXIT %s %d lots | entry=%.2f exit=%.2f pnl=%.2f pts | reason=%s | %s",
                        direction, position_lots, entry_price, exit_price, trade.pnl_points, exit_reason, bar_time,
                    )
                    
                    # Record zone for cooldown tracking
                    last_exit_zone = (round(zone.price_low, 2), round(zone.price_high, 2))
                    last_exit_time = bar_time
                    
                    active_signal = None
                    entry_price   = None
                    entry_time    = None
                    current_stop  = None
                    bars_in_trade = 0
                    position_lots = 0
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
                setup = signal.metadata["setup"]
                zone  = setup.zone
                zone_key = (round(zone.price_low, 2), round(zone.price_high, 2))

                # Check if we can enter this signal
                can_enter = False
                suppress_reason = None
                
                if active_signal is None:
                    # Flat — always can enter
                    can_enter = True
                else:
                    # Position active — check hedge mode
                    if self._allow_hedge and signal.direction != active_signal.direction:
                        # Opposite direction — close existing, enter new (reversal/hedge)
                        logger.info(
                            "REVERSAL: Closing %s position to enter %s at %s",
                            active_signal.direction, signal.direction, bar_time,
                        )
                        # Close existing position at current bar's close
                        trade = Trade(
                            signal=active_signal,
                            entry_time=entry_time,
                            entry_price=entry_price,
                            exit_time=bar_time,
                            exit_price=float(bar["close"]),
                            exit_reason="reversal",
                            direction=active_signal.direction,
                            initial_stop=active_signal.metadata["setup"].initial_stop,
                            lots=position_lots,
                        )
                        result.trades.append(trade)
                        
                        # Update capital for reversal trade
                        if self._current_capital is not None and pricer is not None:
                            direction_str = "LONG" if active_signal.direction == SignalDirection.LONG else "SHORT"
                            leg = pricer.price_trade(
                                direction=direction_str,
                                entry_spot=entry_price,
                                entry_time=entry_time,
                                exit_spot=float(bar["close"]),
                                exit_time=bar_time,
                            )
                            pnl_rupees = leg.pnl_rupees * position_lots
                            tx_cost_per_lot = (
                                40.0 + 
                                leg.entry_premium * 0.0015 * pricer.lot_size +
                                5.0
                            )
                            total_tx_cost = tx_cost_per_lot * position_lots
                            net_pnl = pnl_rupees - total_tx_cost
                            self._current_capital += net_pnl
                        
                        active_signal = None
                        entry_price = None
                        entry_time = None
                        current_stop = None
                        bars_in_trade = 0
                        position_lots = 0
                        can_enter = True
                    else:
                        # Same direction or hedge disabled
                        suppress_reason = "position_active"
                
                # Check cooldown (only if cooldown enabled)
                if can_enter and self._cooldown_minutes > 0:
                    in_cooldown = (
                        last_exit_zone == zone_key 
                        and last_exit_time is not None
                        and (bar_time - last_exit_time) < pd.Timedelta(minutes=self._cooldown_minutes)
                    )
                    if in_cooldown:
                        can_enter = False
                        suppress_reason = "cooldown"
                
                if can_enter:
                    # Calculate position size
                    lots_to_trade = 1  # Default: 1 lot
                    
                    if self._current_capital is not None and self._current_capital > 0 and pricer is not None:
                        # Determine entry price for sizing calculation
                        next_i = i + 1
                        if next_i < len(ohlcv):
                            calc_entry_price = float(ohlcv.iloc[next_i]["open"])
                            calc_entry_time = ohlcv.index[next_i]
                        else:
                            calc_entry_price = float(bar["close"])
                            calc_entry_time = bar_time
                        
                        # Get option premium for sizing
                        direction_str = "LONG" if signal.direction == SignalDirection.LONG else "SHORT"
                        
                        # Price a dummy exit to get entry premium (use entry price for both)
                        dummy_leg = pricer.price_trade(
                            direction=direction_str,
                            entry_spot=calc_entry_price,
                            entry_time=calc_entry_time,
                            exit_spot=calc_entry_price,
                            exit_time=calc_entry_time,
                        )
                        entry_premium = dummy_leg.entry_premium
                        lot_size = pricer.lot_size
                        
                        if can_enter:
                            # Position sizing: min of risk-based and capital-based
                            max_loss_per_lot = entry_premium * lot_size  # Premium paid
                            
                            # Risk-based: max risk per trade (conservative: 2% of capital)
                            risk_amount = self._current_capital * self._risk_per_trade_pct
                            lots_from_risk = int(risk_amount / max_loss_per_lot) if max_loss_per_lot > 0 else 1
                            
                            # Capital-based: max % of capital deployed (don't deploy more than you have)
                            max_deployed = self._current_capital * self._max_capital_deployed_pct
                            lots_from_capital = int(max_deployed / max_loss_per_lot) if max_loss_per_lot > 0 else 1
                            
                            # Take minimum of all constraints + enforce hard cap
                            lots_to_trade = max(1, min(
                                lots_from_risk, 
                                lots_from_capital,
                                self._max_lots_per_trade  # HARD CAP: exchange/broker limits
                            ))
                            
                            logger.debug(
                                "Position sizing: capital=₹%.0f risk=%.1f%% max_deployed=%.1f%% | "
                                "premium=%.2f loss/lot=₹%.0f | lots_risk=%d lots_cap=%d cap=%d → %d lots",
                                self._current_capital, self._risk_per_trade_pct * 100, 
                                self._max_capital_deployed_pct * 100,
                                entry_premium, max_loss_per_lot, 
                                lots_from_risk, lots_from_capital, self._max_lots_per_trade, lots_to_trade,
                            )
                    elif self._current_capital is not None and self._current_capital <= 0:
                        # Capital exhausted - cannot trade
                        logger.warning("Capital exhausted (₹%.2f) - skipping trade", self._current_capital)
                        can_enter = False
                        suppress_reason = "capital_exhausted"
                    
                    if can_enter:
                        # Enter the trade
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
                        position_lots = lots_to_trade
                        logger.debug(
                            "ENTRY %s %d lots @ %.2f | stop=%.2f | %s",
                            signal.direction, lots_to_trade, entry_price, current_stop, entry_time,
                        )
                else:
                    # Suppressed
                    logger.debug(
                        "Signal %s at %s suppressed — %s",
                        signal.direction, bar_time, suppress_reason,
                    )
                    supp_record = {
                        "signal_time":   str(bar_time),
                        "direction":     signal.direction.name,
                        "zone_key":      zone_key,
                        "zone_members":  zone.members,
                        "reason":        suppress_reason,
                    }
                    if suppress_reason == "cooldown" and last_exit_time:
                        supp_record["cooldown_ends"] = str(
                            last_exit_time + pd.Timedelta(minutes=self._cooldown_minutes)
                        )
                    if suppress_reason == "position_active" and entry_time:
                        supp_record["active_since"] = str(entry_time)
                    result.suppressed_signals.append(supp_record)

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
                lots=position_lots,
            )
            result.trades.append(trade)
            
            # Update capital for final trade
            if self._current_capital is not None and pricer is not None:
                direction_str = "LONG" if active_signal.direction == SignalDirection.LONG else "SHORT"
                leg = pricer.price_trade(
                    direction=direction_str,
                    entry_spot=entry_price,
                    entry_time=entry_time,
                    exit_spot=float(last_bar["close"]),
                    exit_time=ohlcv.index[-1],
                )
                pnl_rupees = leg.pnl_rupees * position_lots
                tx_cost_per_lot = (
                    40.0 + 
                    leg.entry_premium * 0.0015 * pricer.lot_size +
                    5.0
                )
                total_tx_cost = tx_cost_per_lot * position_lots
                net_pnl = pnl_rupees - total_tx_cost
                self._current_capital += net_pnl

        result.compute_metrics()

        logger.info(
            "Backtest complete — %d bars, %d signals, %d trades executed.",
            len(ohlcv) - self._history_window,
            len(result.signals),
            len(result.trades),
        )
        return result
