#!/usr/bin/env python3
"""
Paper Trading Mode — runs the strategy against live data with simulated fills.

Architecture
-----------
  PaperTradingEngine
  ├── RiskManager    — circuit breaker, per-trade limits, kill switch
  ├── PositionManager — in-memory concurrency + capital-deployment tracking
  ├── StateManager   — SQLite persistence (capital, trades, open positions)
  └── UpstoxAdapter  — market data + option quotes (dry_run; no real orders)

Usage:
    python scripts/run_paper.py --strategy pivot_cpr
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest.options_pricer import OptionsPricer, atm_strike, next_expiry
from core.broker.upstox_adapter import UpstoxAdapter
from core.config_loader import load_instruments, load_risk
from core.engine.base_strategy import MarketData, Signal, SignalDirection
from core.engine.position_manager import ConcurrencyConfig, Position, PositionManager
from core.engine.risk_manager import RiskConfig, RiskManager
from live.state_manager import StateManager
from strategies.pivot_cpr_strategy import PivotCprStrategy

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram_alert(message: str) -> None:
    """Send a message to Telegram. Silently skips if credentials not set."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception as e:
        logger.warning("Telegram alert failed: %s", e)


class PaperTradingEngine:
    """
    Simulated trading engine.

    Delegates risk decisions to RiskManager, position lifecycle to
    PositionManager, and durable state to StateManager (SQLite). No real
    orders are ever placed — all order paths are paper-only.
    """

    def __init__(
        self,
        strategy,
        adapter: UpstoxAdapter,
        pricer: OptionsPricer,
        instruments_cfg: dict,
        risk_cfg: dict,
        state_manager: StateManager,
        strategy_id: str = "pivot_cpr",
    ) -> None:
        self.strategy = strategy
        self.adapter = adapter
        self.pricer = pricer
        self.instruments_cfg = instruments_cfg
        self.risk_cfg = risk_cfg
        self._sm = state_manager
        self._strategy_id = strategy_id

        # Load persisted capital; initialise on first run.
        capital = self._sm.get_capital()
        if capital == 0.0:
            capital = risk_cfg.get("capital", {}).get("starting_capital", 20_000.0)
            self._sm.update_capital(capital, "initial_deposit")
            logger.info("First run — initialising capital at ₹%.2f", capital)
        else:
            logger.info("Loaded persisted capital: ₹%.2f", capital)

        # Derive absolute INR limits from day-start capital + config percentages.
        # Limits are locked to day-start capital (not compounded mid-session).
        per_trade = risk_cfg["per_trade"]
        cb = risk_cfg["circuit_breaker"]
        self._rm = RiskManager(RiskConfig(
            max_loss_per_trade=capital * (per_trade["max_loss_per_trade_pct"] / 100),
            daily_loss_limit=capital * (cb["daily_loss_limit_pct"] / 100),
        ))
        self._pm = PositionManager(ConcurrencyConfig(
            max_concurrent_positions_per_instrument=1,
            max_total_capital_deployed_pct=per_trade["max_capital_deployed_pct"],
            allocated_capital=capital,
        ))

        # Active position tracking. _active is the PositionManager Position;
        # _entry_details holds quote + contract info needed at exit time.
        self._active: Optional[Position] = None
        self._entry_details: dict = {}
        self._current_stop: Optional[float] = None
        self._bars_in_trade: int = 0

        # Cooldown: avoid re-entering the same zone within cooldown_minutes.
        self._last_exit_zone: Optional[tuple] = None
        self._last_exit_time: Optional[datetime] = None
        self._cooldown_minutes: int = 15

        self._day_start_capital: float = capital

    # ------------------------------------------------------------------
    # Capital access (always reads from StateManager, not a cached local)
    # ------------------------------------------------------------------

    @property
    def capital(self) -> float:
        return self._sm.get_capital()

    # ------------------------------------------------------------------
    # Kill switch + status file
    # ------------------------------------------------------------------

    def _sync_kill_switch(self) -> None:
        """Activate RiskManager kill switch if the sentinel file is present."""
        if (project_root / "KILL_SWITCH.txt").exists():
            if not self._rm.kill_switch_active:
                self._rm.activate_kill_switch()
                logger.warning("🛑 KILL SWITCH FILE detected — halting new entries.")

    def _update_status(self, message: str) -> None:
        with open(project_root / "TRADING_STATUS.txt", "w") as f:
            f.write(f"{datetime.now()}: {message}\n")

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

    def _calc_lots(self, entry_premium: float) -> int:
        """Return how many lots to trade given current capital and risk config."""
        capital = self.capital
        lot_size = self.instruments_cfg["instruments"]["NIFTY"]["lot_size"]
        per_trade = self.risk_cfg["per_trade"]
        hard_cap = self.risk_cfg["position_limits"]["hard_cap_lots"]
        cost_per_lot = entry_premium * lot_size

        if cost_per_lot <= 0:
            return 0

        lots = max(1, min(
            int(capital * (per_trade["max_loss_per_trade_pct"] / 100) / cost_per_lot),
            int(capital * (per_trade["max_capital_deployed_pct"] / 100) / cost_per_lot),
            hard_cap,
        ))
        logger.debug("Position sizing: ₹%.0f capital, ₹%.2f premium → %d lots", capital, entry_premium, lots)
        return lots

    # ------------------------------------------------------------------
    # Cooldown
    # ------------------------------------------------------------------

    def _in_cooldown(self, signal: Signal) -> bool:
        setup = signal.metadata.get("setup")
        if not setup:
            return False
        zone = setup.zone
        zone_key = (round(zone.price_low, 2), round(zone.price_high, 2))
        return (
            self._last_exit_zone == zone_key
            and self._last_exit_time is not None
            and (datetime.now() - self._last_exit_time) < timedelta(minutes=self._cooldown_minutes)
        )

    # ------------------------------------------------------------------
    # Entry
    # ------------------------------------------------------------------

    def _enter(self, signal: Signal, bar_time: datetime, entry_price: float) -> None:
        setup = signal.metadata["setup"]
        direction = signal.direction
        lot_size = self.instruments_cfg["instruments"]["NIFTY"]["lot_size"]

        strike = atm_strike(entry_price, self.pricer.strike_step)
        option_type = "CE" if direction == SignalDirection.LONG else "PE"
        expiry_date = next_expiry(bar_time.date(), self.pricer.expiry_weekday)
        contract_symbol = f"NIFTY {expiry_date.strftime('%d%b%y').upper()} {strike:.0f} {option_type}"

        quote = self.adapter.get_option_quote(
            instrument="NIFTY", strike=strike,
            option_type=option_type, expiry_date=expiry_date.isoformat(),
        )

        if quote and quote["ask"] > 0:
            entry_premium, premium_source = quote["ask"], "REAL ASK"
            logger.info("Option quote: LTP=₹%.2f Bid=₹%.2f Ask=₹%.2f", quote["ltp"], quote["bid"], quote["ask"])
        elif quote and quote["ltp"] > 0:
            entry_premium, premium_source = quote["ltp"], "REAL LTP"
            logger.warning("Bid/Ask unavailable — using LTP for entry")
        else:
            logger.warning("Live quote unavailable — using Black-Scholes fallback")
            direction_str = "LONG" if direction == SignalDirection.LONG else "SHORT"
            leg = self.pricer.price_trade(
                direction=direction_str, entry_spot=entry_price, entry_time=bar_time,
                exit_spot=entry_price, exit_time=bar_time,
            )
            entry_premium, premium_source = leg.entry_premium, "BLACK-SCHOLES"

        # Gate 1: position concurrency check.
        max_loss_for_1_lot = entry_premium * lot_size
        allowed, reason = self._pm.can_open(signal, estimated_capital=max_loss_for_1_lot)
        if not allowed:
            logger.info("Entry blocked by PositionManager — %s", reason)
            return

        # Gate 2: risk limits (per-trade + circuit breaker + kill switch).
        allowed, reason = self._rm.check_pre_trade(
            max_loss_for_trade=max_loss_for_1_lot,
            current_unrealized_loss=self._pm.total_unrealized_pnl,
        )
        if not allowed:
            logger.info("Entry blocked by RiskManager — %s", reason)
            return

        lots = self._calc_lots(entry_premium)
        if lots == 0:
            logger.warning("Insufficient capital — skipping (premium=₹%.2f)", entry_premium)
            return

        # Register with PositionManager (in-memory) and StateManager (SQLite).
        self._active = self._pm.open_position(
            signal=signal,
            entry_time=bar_time,
            contract_symbol=contract_symbol,
            lot_size=lot_size,
            premium_paid=entry_premium,
            num_lots=lots,
        )
        self._sm.open_position({
            "id": self._active.position_id,
            "symbol": contract_symbol,
            "direction": direction.name,
            "entry_price": entry_premium,
            "lots": lots,
            "stop_loss": setup.initial_stop,
            "entry_time": bar_time.isoformat(),
            "strategy_name": self._strategy_id,
            "regime": "live",
        })

        # Keep quote/contract details for exit P&L calculation.
        self._entry_details = {
            "signal": signal,
            "strike": strike,
            "option_type": option_type,
            "expiry": expiry_date,
            "premium": entry_premium,
            "source": premium_source,
            "entry_spot": entry_price,
            "entry_time": bar_time,
        }
        self._current_stop = setup.initial_stop
        self._bars_in_trade = 0

        logger.info(
            "📈 PAPER ENTRY: %s %d lots @ spot ₹%.2f | premium=₹%.2f (%s) | stop=₹%.2f | contract=%s",
            direction.name, lots, entry_price, entry_premium, premium_source,
            self._current_stop, contract_symbol,
        )
        send_telegram_alert(
            f"📈 <b>ENTRY</b>\nContract: <b>{contract_symbol}</b>\n"
            f"Direction: {direction.name}\nLots: {lots}\n"
            f"Spot: ₹{entry_price:.2f}\nPremium: ₹{entry_premium:.2f} ({premium_source})\n"
            f"Stop: ₹{self._current_stop:.2f}\nCapital: ₹{self.capital:.2f}\n"
            f"Time: {bar_time.strftime('%H:%M')}"
        )

    # ------------------------------------------------------------------
    # Exit
    # ------------------------------------------------------------------

    def _exit(self, bar_time: datetime, exit_price: float, exit_reason: str) -> None:
        if self._active is None:
            return

        direction = self._active.direction
        lot_size = self._active.lot_size
        lots = self._active.num_lots
        det = self._entry_details
        position_id = self._active.position_id

        quote = self.adapter.get_option_quote(
            instrument="NIFTY", strike=det["strike"],
            option_type=det["option_type"], expiry_date=det["expiry"].isoformat(),
        )

        if quote and quote["bid"] > 0:
            exit_premium, exit_source = quote["bid"], "REAL BID"
            logger.info("Exit quote: LTP=₹%.2f Bid=₹%.2f Ask=₹%.2f", quote["ltp"], quote["bid"], quote["ask"])
        elif quote and quote["ltp"] > 0:
            exit_premium, exit_source = quote["ltp"], "REAL LTP"
            logger.warning("Bid/Ask unavailable — using LTP for exit")
        else:
            logger.warning("Live exit quote unavailable — using Black-Scholes fallback")
            direction_str = "LONG" if direction == SignalDirection.LONG else "SHORT"
            leg = self.pricer.price_trade(
                direction=direction_str,
                entry_spot=det["entry_spot"], entry_time=det["entry_time"],
                exit_spot=exit_price, exit_time=bar_time,
            )
            exit_premium, exit_source = leg.exit_premium, "BLACK-SCHOLES"

        premium_change = (
            det["premium"] - exit_premium if direction == SignalDirection.SHORT
            else exit_premium - det["premium"]
        )
        gross_pnl = premium_change * lot_size * lots
        tx_cost = (40.0 + det["premium"] * 0.0015 * lot_size + 5.0) * lots
        net_pnl = gross_pnl - tx_cost
        hold_min = (bar_time - det["entry_time"]).total_seconds() / 60

        contract_symbol = self._active.contract_symbol

        # Delegate to core components.
        self._pm.close_position(position_id, net_pnl)

        # Detect if circuit breaker trips on this loss.
        was_tripped = self._rm.circuit_breaker_tripped
        self._rm.record_realized_loss(net_pnl)
        if not was_tripped and self._rm.circuit_breaker_tripped:
            msg = (
                f"🛑 <b>CIRCUIT BREAKER TRIPPED</b>\n"
                f"Cumulative session loss exceeded daily limit.\n"
                f"No new positions for the rest of today."
            )
            self._update_status("CIRCUIT BREAKER TRIPPED — halted for the day.")
            send_telegram_alert(msg)

        # Persist to SQLite atomically.
        new_capital = self.capital + net_pnl
        self._sm.update_capital(new_capital, f"trade:{exit_reason}")
        self._sm.close_position(position_id)
        self._sm.record_trade({
            "id": position_id,
            "symbol": contract_symbol,
            "direction": direction.name,
            "signal_type": "paper",
            "strategy_name": self._strategy_id,
            "regime": "live",
            "entry_time": det["entry_time"].isoformat(),
            "exit_time": bar_time.isoformat(),
            "entry_price": det["premium"],
            "exit_price": exit_premium,
            "lots": lots,
            "lot_size": lot_size,
            "pnl": net_pnl,
            "exit_reason": exit_reason,
            "metadata": {
                "entry_source": det["source"],
                "exit_source": exit_source,
                "gross_pnl": gross_pnl,
                "tx_cost": tx_cost,
                "hold_minutes": hold_min,
            },
        })

        logger.info(
            "📉 PAPER EXIT: %s | %s | P&L=₹%.2f | hold=%.1fmin | capital=₹%.2f | reason=%s",
            contract_symbol, direction.name, net_pnl, hold_min, new_capital, exit_reason,
        )
        pnl_emoji = "✅" if net_pnl > 0 else "❌"
        cost_basis = det["premium"] * lot_size * lots
        send_telegram_alert(
            f"{pnl_emoji} <b>EXIT</b>\nContract: <b>{contract_symbol}</b>\n"
            f"Direction: {direction.name}\n"
            f"P&L: ₹{net_pnl:.2f} ({(net_pnl / cost_basis * 100):+.1f}%)\n"
            f"Entry: ₹{det['premium']:.2f} ({det['source']})\n"
            f"Exit: ₹{exit_premium:.2f} ({exit_source})\n"
            f"Reason: {exit_reason}\nHold: {hold_min:.1f} min\n"
            f"Capital: ₹{new_capital:.2f}\nTime: {bar_time.strftime('%H:%M')}"
        )

        # Record cooldown so we skip the same zone for cooldown_minutes.
        signal = det.get("signal")
        if signal:
            setup = signal.metadata.get("setup")
            if setup:
                zone = setup.zone
                self._last_exit_zone = (round(zone.price_low, 2), round(zone.price_high, 2))
                self._last_exit_time = datetime.now()

        # Clear active position state.
        self._active = None
        self._entry_details = {}
        self._current_stop = None
        self._bars_in_trade = 0

    # ------------------------------------------------------------------
    # Trailing stop management
    # ------------------------------------------------------------------

    def _manage(self, bar: pd.Series, history: pd.DataFrame) -> None:
        """Check and update trailing stops; trigger exits when hit."""
        if self._active is None:
            return

        direction = self._active.direction
        setup = self._entry_details["signal"].metadata["setup"]
        zone = setup.zone
        self._bars_in_trade += 1

        # Trailing stop: after 2 bars, trail to the 2-bar-back candle's low/high.
        if self._bars_in_trade >= 2 and len(history) >= 2:
            bar_2back = history.iloc[-3]
            if direction == SignalDirection.LONG:
                new_stop = bar_2back["low"]
                if new_stop > self._current_stop:
                    self._current_stop = new_stop
            else:
                new_stop = bar_2back["high"]
                if new_stop < self._current_stop:
                    self._current_stop = new_stop

        # Update mark-to-market unrealized P&L for RiskManager proactive check.
        # (Premium-based approximation; real MTM would need a live option quote.)
        self._rm.update_unrealized_check(self._pm.total_unrealized_pnl)

        stop_hit = (
            bar["low"] <= self._current_stop if direction == SignalDirection.LONG
            else bar["high"] >= self._current_stop
        )
        structural_exit = (
            bar["close"] < zone.price_low if direction == SignalDirection.LONG
            else bar["close"] > zone.price_high
        )
        is_eod = bar.name.time() >= pd.Timestamp("15:25").time()

        if stop_hit:
            self._exit(bar.name, self._current_stop, "stop")
        elif structural_exit:
            self._exit(bar.name, bar["close"], "structural")
        elif is_eod:
            self._exit(bar.name, bar["close"], "eod")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self, duration_minutes: int = 390) -> None:
        """Run paper trading for specified duration (default = full trading day)."""
        logger.info("🚀 Starting paper trading session...")
        self._rm.reset_session()
        self._day_start_capital = self.capital
        self._update_status("Paper trading started")

        daily_loss_limit = self._rm._config.daily_loss_limit
        logger.info(
            "📊 Day-start capital: ₹%.2f | circuit breaker limit: ₹%.2f",
            self._day_start_capital, daily_loss_limit,
        )

        start_time = datetime.now()
        end_time = start_time + timedelta(minutes=duration_minutes)

        # Pre-fetch daily data for pivot calculation.
        logger.info("Fetching historical daily data for pivot calculation...")
        from_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")
        daily_ohlcv = self.adapter.get_ohlcv(
            symbol="NSE_INDEX|Nifty 50", interval="day",
            from_date=from_date, to_date=today,
        )
        if daily_ohlcv is None or daily_ohlcv.empty:
            logger.error("Failed to fetch historical daily data — cannot calculate pivots!")
            return
        logger.info("✓ Fetched %d days of historical data", len(daily_ohlcv))

        history_window = 2
        history = pd.DataFrame()
        historical_data_for_pivots = daily_ohlcv

        try:
            while datetime.now() < end_time:
                self._sync_kill_switch()
                if self._rm.kill_switch_active:
                    logger.warning("🛑 Kill switch active — stopping paper trading.")
                    self._update_status("STOPPED by kill switch")
                    break

                today = datetime.now().strftime("%Y-%m-%d")
                ohlcv_1min = self.adapter.get_ohlcv(
                    symbol="NSE_INDEX|Nifty 50", interval="1minute",
                    from_date=today, to_date=today,
                )
                if ohlcv_1min is None or ohlcv_1min.empty:
                    time.sleep(60)
                    continue

                ohlcv_5min = ohlcv_1min.resample("5min").agg({
                    "open": "first", "high": "max",
                    "low": "min", "close": "last", "volume": "sum",
                }).dropna(subset=["open"])

                if len(ohlcv_5min) < history_window:
                    logger.debug("Insufficient bars (%d), waiting...", len(ohlcv_5min))
                    time.sleep(60)
                    continue

                current_bar = ohlcv_5min.iloc[-1]
                bar_time = current_bar.name

                if not history.empty and bar_time <= history.index[-1]:
                    time.sleep(30)
                    continue

                history = ohlcv_5min.iloc[-history_window:]

                # Build today's running daily bar and append to historical daily data.
                today_date = bar_time.normalize()
                today_bars = ohlcv_5min[ohlcv_5min.index.normalize() == today_date]
                today_daily = pd.DataFrame([{
                    "open": today_bars.iloc[0]["open"],
                    "high": today_bars["high"].max(),
                    "low": today_bars["low"].min(),
                    "close": current_bar["close"],
                }], index=[today_date])
                pivot_data = pd.concat([historical_data_for_pivots, today_daily])
                pivot_data = pivot_data[~pivot_data.index.duplicated(keep="last")]

                # Inject daily data into strategy for pivot calculation.
                # TODO(arch): replace with a public set_daily_ohlc() method on the strategy.
                self.strategy._daily_ohlc = pivot_data

                logger.info("Bar: %s | close=%.2f | capital=₹%.2f", bar_time, current_bar["close"], self.capital)
                self._update_status(
                    f"Bar {bar_time} | Close={current_bar['close']:.2f} | Capital=₹{self.capital:.2f}"
                )

                self._manage(current_bar, history)

                if self._active is None and not self._rm.circuit_breaker_tripped:
                    market_data = MarketData(
                        instrument="NIFTY",
                        bar_time=bar_time,
                        open=float(current_bar["open"]),
                        high=float(current_bar["high"]),
                        low=float(current_bar["low"]),
                        close=float(current_bar["close"]),
                        volume=float(current_bar.get("volume", 0)),
                        history=history,
                    )
                    try:
                        signal = self.strategy.evaluate(market_data)
                        if signal:
                            if self._in_cooldown(signal):
                                logger.debug("Signal suppressed — zone in cooldown")
                            else:
                                self._enter(signal, bar_time, float(current_bar["close"]))
                    except Exception:
                        logger.exception("Strategy evaluation error")

                time.sleep(30)

        except KeyboardInterrupt:
            logger.info("Paper trading stopped by user")

        finally:
            if self._active is not None:
                last_bar = history.iloc[-1]
                self._exit(last_bar.name, last_bar["close"], "eod")
            self._print_summary()

    # ------------------------------------------------------------------
    # Session summary
    # ------------------------------------------------------------------

    def _print_summary(self) -> None:
        """Print session summary from StateManager data."""
        end_capital = self.capital
        net_pnl = end_capital - self._day_start_capital
        daily_pnl = self._sm.get_daily_pnl()

        logger.info("")
        logger.info("=" * 70)
        logger.info("PAPER TRADING SESSION SUMMARY")
        logger.info("=" * 70)
        logger.info("Starting Capital: ₹%.2f", self._day_start_capital)
        logger.info("Ending Capital:   ₹%.2f", end_capital)
        logger.info(
            "Net P&L:          ₹%.2f (%.2f%%)",
            net_pnl,
            (net_pnl / self._day_start_capital * 100) if self._day_start_capital else 0,
        )
        logger.info("Today's P&L:      ₹%.2f", daily_pnl)
        logger.info("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper trading mode")
    parser.add_argument("--strategy", default="pivot_cpr", help="Strategy to run")
    parser.add_argument("--duration", type=int, default=390, help="Duration in minutes")
    parser.add_argument("--iv", type=float, default=14.0, help="Implied volatility %%")
    parser.add_argument("--db", default="paper_state.db", help="SQLite state file path")
    args = parser.parse_args()

    instruments_cfg = load_instruments()
    risk_cfg = load_risk()
    nifty_cfg = instruments_cfg["instruments"]["NIFTY"]

    strategy = PivotCprStrategy(config={
        "tolerance_pct": 0.18,
        "min_levels_for_confluence": 2,
        "momentum_enabled": True,
        "momentum_body_pct": 0.50,
        "momentum_accel_multiplier": 1.8,
        "momentum_min_criteria": 2,
    })

    pricer = OptionsPricer(
        lot_size=nifty_cfg["lot_size"],
        expiry_weekday=nifty_cfg["weekly_expiry_weekday"],
        strike_step=nifty_cfg["strike_step"],
        iv=args.iv / 100.0,
    )

    adapter = UpstoxAdapter(config={
        "api_key": os.environ.get("UPSTOX_SANDBOX_API_KEY", ""),
        "api_secret": os.environ.get("UPSTOX_SANDBOX_API_SECRET", ""),
        "redirect_uri": os.environ.get("UPSTOX_SANDBOX_REDIRECT_URI", ""),
        "analytics_token": os.environ["UPSTOX_ANALYTICS_TOKEN"],
        "sandbox": True,
    })

    state_manager = StateManager(args.db)

    engine = PaperTradingEngine(
        strategy=strategy,
        adapter=adapter,
        pricer=pricer,
        instruments_cfg=instruments_cfg,
        risk_cfg=risk_cfg,
        state_manager=state_manager,
        strategy_id=args.strategy,
    )
    engine.run(duration_minutes=args.duration)


if __name__ == "__main__":
    main()
