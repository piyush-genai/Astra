#!/usr/bin/env python3
"""
Paper Trading Mode - Run strategy with simulated orders.

Connects to live market data but does NOT place actual orders.
Logs all trades to CSV for review and validation before going live.

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

import pandas as pd
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backtest.options_pricer import OptionsPricer
from src.broker.upstox_adapter import UpstoxAdapter
from src.config_loader import load_instruments, load_risk
from src.engine.base_strategy import MarketData, Signal, SignalDirection
from src.strategies.pivot_cpr_strategy import PivotCprStrategy

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Telegram bot for real-time trade alerts
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_alert(message: str):
    """Send a message to Telegram (trade alerts)."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return  # Silently skip if Telegram not configured
    
    try:
        import requests
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
        }
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.warning("Failed to send Telegram alert: %s", e)



class PaperTradingEngine:
    """Simulated trading engine - logs trades but doesn't place orders."""
    
    def __init__(self, strategy, adapter, pricer, instruments_cfg, risk_cfg):
        self.strategy = strategy
        self.adapter = adapter
        self.pricer = pricer
        self.instruments_cfg = instruments_cfg
        self.risk_cfg = risk_cfg
        
        # Paper trading state
        self.capital = 20000.0  # Starting capital
        self.active_position = None
        self.entry_time = None
        self.entry_price = None
        self.entry_premium = None
        self.lots = 0
        self.current_stop = None
        self.bars_in_trade = 0
        
        # Tracking
        self.trades = []
        self.signals_suppressed = []
        
        # Cooldown tracking
        self.last_exit_zone = None
        self.last_exit_time = None
        self.cooldown_minutes = 15
        
        logger.info("Paper Trading Engine initialized with ₹%.2f capital", self.capital)
    
    def calculate_position_size(self, signal, entry_premium):
        """Calculate how many lots to trade based on capital and risk limits."""
        lot_size = self.instruments_cfg["instruments"]["NIFTY"]["lot_size"]
        
        # Rule 1: Risk-based (max 2% risk)
        max_risk = self.capital * 0.02
        max_loss_per_lot = entry_premium * lot_size
        lots_from_risk = int(max_risk / max_loss_per_lot) if max_loss_per_lot > 0 else 0
        
        # Rule 2: Capital-based (max 10% deployed)
        max_deployed = self.capital * 0.10
        lots_from_capital = int(max_deployed / max_loss_per_lot) if max_loss_per_lot > 0 else 0
        
        # Rule 3: Hard cap
        hard_cap = 10
        
        # Take minimum, but at least 1 if we're trading
        lots = max(1, min(lots_from_risk, lots_from_capital, hard_cap))
        
        logger.debug(
            "Position sizing: capital=₹%.0f, premium=₹%.2f, risk_lots=%d, cap_lots=%d → %d lots",
            self.capital, entry_premium, lots_from_risk, lots_from_capital, lots
        )
        
        return lots
    
    def check_cooldown(self, signal):
        """Check if this zone is in cooldown period."""
        setup = signal.metadata["setup"]
        zone = setup.zone
        zone_key = (round(zone.price_low, 2), round(zone.price_high, 2))
        
        if (self.last_exit_zone == zone_key and 
            self.last_exit_time is not None and
            (datetime.now() - self.last_exit_time) < timedelta(minutes=self.cooldown_minutes)):
            return True
        return False
    
    def enter_position(self, signal, bar_time, entry_price):
        """Enter a paper position."""
        setup = signal.metadata["setup"]
        direction = signal.direction
        
        # Calculate entry premium for position sizing
        direction_str = "LONG" if direction == SignalDirection.LONG else "SHORT"
        dummy_leg = self.pricer.price_trade(
            direction=direction_str,
            entry_spot=entry_price,
            entry_time=bar_time,
            exit_spot=entry_price,
            exit_time=bar_time,
        )
        entry_premium = dummy_leg.entry_premium
        
        # Calculate position size
        lots = self.calculate_position_size(signal, entry_premium)
        
        if lots == 0:
            logger.warning("⚠️ Insufficient capital - skipping trade (premium=₹%.2f)", entry_premium)
            return
        
        # Enter position
        self.active_position = signal
        self.entry_time = bar_time
        self.entry_price = entry_price
        self.entry_premium = entry_premium
        self.lots = lots
        self.current_stop = setup.initial_stop
        self.bars_in_trade = 0
        
        # Determine option contract details
        from src.backtest.options_pricer import atm_strike, next_expiry
        strike = atm_strike(entry_price, self.pricer.strike_step)
        option_type = "CALL" if direction == SignalDirection.LONG else "PUT"
        expiry_date = next_expiry(bar_time.date(), self.pricer.expiry_weekday)
        contract_symbol = f"NIFTY {expiry_date.strftime('%d%b%y').upper()} {strike:.0f} {option_type}"
        
        logger.info(
            "📈 PAPER ENTRY: %s %d lots @ ₹%.2f | Premium=₹%.2f | Stop=₹%.2f | Capital=₹%.2f | Contract=%s",
            direction, lots, entry_price, entry_premium, self.current_stop, self.capital, contract_symbol
        )
        
        # Send Telegram alert
        alert_msg = (
            f"📈 <b>ENTRY</b>\n"
            f"Contract: <b>{contract_symbol}</b>\n"
            f"Direction: {direction.name}\n"
            f"Lots: {lots}\n"
            f"Spot: ₹{entry_price:.2f}\n"
            f"Premium: ₹{entry_premium:.2f}\n"
            f"Stop: ₹{self.current_stop:.2f}\n"
            f"Capital: ₹{self.capital:.2f}\n"
            f"Time: {bar_time.strftime('%H:%M')}"
        )
        send_telegram_alert(alert_msg)
    
    def exit_position(self, bar_time, exit_price, exit_reason):
        """Exit paper position and calculate P&L."""
        if not self.active_position:
            return
        
        direction = self.active_position.direction
        direction_str = "LONG" if direction == SignalDirection.LONG else "SHORT"
        setup = self.active_position.metadata["setup"]
        zone = setup.zone
        
        # Calculate P&L
        leg = self.pricer.price_trade(
            direction=direction_str,
            entry_spot=self.entry_price,
            entry_time=self.entry_time,
            exit_spot=exit_price,
            exit_time=bar_time,
        )
        
        gross_pnl = leg.pnl_rupees * self.lots
        
        # Transaction costs
        lot_size = self.pricer.lot_size
        tx_cost = (40.0 + self.entry_premium * 0.0015 * lot_size + 5.0) * self.lots
        net_pnl = gross_pnl - tx_cost
        
        # Update capital
        self.capital += net_pnl
        
        # Get contract details for logging
        from src.backtest.options_pricer import atm_strike, next_expiry
        strike = atm_strike(self.entry_price, self.pricer.strike_step)
        option_type = "CALL" if direction == SignalDirection.LONG else "PUT"
        expiry_date = next_expiry(self.entry_time.date(), self.pricer.expiry_weekday)
        contract_symbol = f"NIFTY {expiry_date.strftime('%d%b%y').upper()} {strike:.0f} {option_type}"
        
        # Record trade
        hold_minutes = (bar_time - self.entry_time).total_seconds() / 60
        trade = {
            "exit_time": str(bar_time),
            "signal_type": self.active_position.metadata.get("signal_type", "regular"),
            "direction": direction.name,
            "entry_price": self.entry_price,
            "exit_price": exit_price,
            "entry_premium": self.entry_premium,
            "exit_premium": leg.exit_premium,
            "lots": self.lots,
            "gross_pnl": gross_pnl,
            "tx_cost": tx_cost,
            "net_pnl": net_pnl,
            "exit_reason": exit_reason,
            "hold_minutes": hold_minutes,
            "capital_after": self.capital,
            "contract": contract_symbol,
        }
        self.trades.append(trade)
        
        logger.info(
            "📉 PAPER EXIT: %s | %s | P&L=₹%.2f (%.1f%%) | Reason=%s | Hold=%.1fmin | Capital=₹%.2f",
            contract_symbol, direction, net_pnl, (net_pnl / (self.entry_premium * lot_size * self.lots)) * 100,
            exit_reason, hold_minutes, self.capital
        )
        
        # Send Telegram alert
        pnl_emoji = "✅" if net_pnl > 0 else "❌"
        pnl_pct = (net_pnl / (self.entry_premium * lot_size * self.lots)) * 100
        alert_msg = (
            f"{pnl_emoji} <b>EXIT</b>\n"
            f"Contract: <b>{contract_symbol}</b>\n"
            f"Direction: {direction.name}\n"
            f"P&L: ₹{net_pnl:.2f} ({pnl_pct:+.1f}%)\n"
            f"Entry: ₹{self.entry_premium:.2f} → Exit: ₹{leg.exit_premium:.2f}\n"
            f"Reason: {exit_reason}\n"
            f"Hold: {hold_minutes:.1f} min\n"
            f"Capital: ₹{self.capital:.2f}\n"
            f"Time: {bar_time.strftime('%H:%M')}"
        )
        send_telegram_alert(alert_msg)
        
        # Set cooldown
        self.last_exit_zone = (round(zone.price_low, 2), round(zone.price_high, 2))
        self.last_exit_time = datetime.now()
        
        # Clear position
        self.active_position = None
        self.entry_time = None
        self.entry_price = None
        self.entry_premium = None
        self.lots = 0
        self.current_stop = None
        self.bars_in_trade = 0
    
    def manage_position(self, bar, history):
        """Check stops and manage active position."""
        if not self.active_position:
            return
        
        direction = self.active_position.direction
        setup = self.active_position.metadata["setup"]
        zone = setup.zone
        self.bars_in_trade += 1
        
        # Trailing stop (after 2 bars)
        if self.bars_in_trade >= 2 and len(history) >= 2:
            bar_2back = history.iloc[-3]  # Current is -1, so 2 back is -3
            if direction == SignalDirection.LONG:
                new_stop = bar_2back["low"]
                if new_stop > self.current_stop:
                    self.current_stop = new_stop
            else:
                new_stop = bar_2back["high"]
                if new_stop < self.current_stop:
                    self.current_stop = new_stop
        
        # Check stop hit
        stop_hit = (
            bar["low"] <= self.current_stop if direction == SignalDirection.LONG
            else bar["high"] >= self.current_stop
        )
        
        # Check structural invalidation
        structural_exit = (
            bar["close"] < zone.price_low if direction == SignalDirection.LONG
            else bar["close"] > zone.price_high
        )
        
        # Check EOD
        is_eod = bar.name.time() >= pd.Timestamp("15:25").time()
        
        if stop_hit:
            self.exit_position(bar.name, self.current_stop, "stop")
        elif structural_exit:
            self.exit_position(bar.name, bar["close"], "structural")
        elif is_eod:
            self.exit_position(bar.name, bar["close"], "eod")
    
    def check_kill_switch(self):
        """Check if kill switch has been activated."""
        kill_switch_file = Path(__file__).parent.parent / "KILL_SWITCH.txt"
        return kill_switch_file.exists()
    
    def update_status(self, message):
        """Update status file for Telegram bot."""
        status_file = Path(__file__).parent.parent / "TRADING_STATUS.txt"
        with open(status_file, "w") as f:
            f.write(f"{datetime.now()}: {message}\n")
    
    def run(self, duration_minutes=390):
        """Run paper trading for specified duration (default = full trading day)."""
        logger.info("🚀 Starting paper trading session...")
        self.update_status("Paper trading started")
        
        start_time = datetime.now()
        end_time = start_time + timedelta(minutes=duration_minutes)
        
        # Pre-fetch historical DAILY data for pivot calculation
        logger.info("📊 Fetching historical daily data for pivot calculation...")
        lookback_days = 90  # 90 days ensures we have weekly/monthly pivots
        from_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")
        
        daily_ohlcv = self.adapter.get_ohlcv(
            symbol="NSE_INDEX|Nifty 50",
            interval="day",
            from_date=from_date,
            to_date=today,
        )
        
        if daily_ohlcv is None or daily_ohlcv.empty:
            logger.error("Failed to fetch historical daily data - cannot calculate pivots!")
            return
        
        logger.info("✓ Fetched %d days of historical data for pivot calculation", len(daily_ohlcv))
        
        # Initialize history buffer - only need 2 bars minimum now!
        history_window = 2  # Minimum for strategy to work
        history = pd.DataFrame()
        historical_data_for_pivots = daily_ohlcv  # Store for pivot calculation
        
        try:
            while datetime.now() < end_time:
                # Check kill switch
                if self.check_kill_switch():
                    logger.warning("🛑 KILL SWITCH ACTIVATED - Stopping trading!")
                    self.update_status("STOPPED by kill switch")
                    break
                # Fetch latest 1-min bar
                today = datetime.now().strftime("%Y-%m-%d")
                ohlcv_1min = self.adapter.get_ohlcv(
                    symbol="NSE_INDEX|Nifty 50",
                    interval="1minute",
                    from_date=today,
                    to_date=today,
                )
                
                if ohlcv_1min is None or ohlcv_1min.empty:
                    time.sleep(60)  # Wait 1 minute before retry
                    continue
                
                # Resample to 5-min
                ohlcv_5min = ohlcv_1min.resample("5min").agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }).dropna(subset=["open"])
                
                if len(ohlcv_5min) < history_window:
                    logger.debug("Insufficient history (%d bars), waiting...", len(ohlcv_5min))
                    time.sleep(60)
                    continue
                
                # Get latest bar
                current_bar = ohlcv_5min.iloc[-1]
                bar_time = current_bar.name
                
                # Skip if we've already processed this bar
                if not history.empty and bar_time <= history.index[-1]:
                    time.sleep(30)  # Wait 30 seconds
                    continue
                
                # Update history
                history = ohlcv_5min.iloc[-history_window:]
                
                # Update today's running daily bar for pivot calculation
                today_date = bar_time.normalize()
                today_bars = ohlcv_5min[ohlcv_5min.index.normalize() == today_date]
                today_daily = pd.DataFrame([{
                    "open": today_bars.iloc[0]["open"],
                    "high": today_bars["high"].max(),
                    "low": today_bars["low"].min(),
                    "close": current_bar["close"],
                }], index=[today_date])
                
                # Combine: historical daily + today's running bar
                pivot_data = pd.concat([historical_data_for_pivots, today_daily])
                pivot_data = pivot_data[~pivot_data.index.duplicated(keep='last')]
                
                # Inject daily data into strategy for pivot calculation
                self.strategy._daily_ohlc = pivot_data
                
                logger.info("Processing bar: %s | Close=%.2f", bar_time, current_bar["close"])
                self.update_status(f"Processing bar {bar_time} | Close={current_bar['close']:.2f} | Capital=₹{self.capital:.2f}")
                
                # Manage existing position (uses 5-min history for trailing stops)
                self.manage_position(current_bar, history)
                
                # Evaluate for new signal (if no active position)
                if not self.active_position:
                    market_data = MarketData(
                        instrument="NIFTY",
                        bar_time=bar_time,
                        open=float(current_bar["open"]),
                        high=float(current_bar["high"]),
                        low=float(current_bar["low"]),
                        close=float(current_bar["close"]),
                        volume=float(current_bar.get("volume", 0)),
                        history=history,  # 5-min bars for signals and momentum
                    )
                    
                    try:
                        signal = self.strategy.evaluate(market_data)
                        
                        if signal:
                            # Check cooldown
                            if self.check_cooldown(signal):
                                logger.debug("Signal suppressed - zone in cooldown")
                                self.signals_suppressed.append({
                                    "time": str(bar_time),
                                    "direction": signal.direction.name,
                                    "reason": "cooldown",
                                })
                            else:
                                # Enter on next bar's open (simulated)
                                entry_price = float(current_bar["close"])  # Approximate
                                self.enter_position(signal, bar_time, entry_price)
                    
                    except Exception as e:
                        logger.exception("Strategy evaluation failed: %s", e)
                
                # Wait before next check
                time.sleep(30)  # Check every 30 seconds
        
        except KeyboardInterrupt:
            logger.info("Paper trading stopped by user")
        
        finally:
            # Close any open position
            if self.active_position:
                last_bar = history.iloc[-1]
                self.exit_position(last_bar.name, last_bar["close"], "eod")
            
            # Save results
            self.save_results()
    
    def save_results(self):
        """Save paper trading results to CSV."""
        if not self.trades:
            logger.warning("No trades executed during paper trading session")
            return
        
        # Save trades
        df = pd.DataFrame(self.trades)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"paper_trades_{timestamp}.csv"
        df.to_csv(output_path, index=False)
        
        # Summary
        winners = df[df["net_pnl"] > 0]
        losers = df[df["net_pnl"] <= 0]
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("PAPER TRADING SESSION SUMMARY")
        logger.info("=" * 80)
        logger.info("Starting Capital: ₹20,000.00")
        logger.info("Ending Capital:   ₹%.2f", self.capital)
        logger.info("Net P&L:          ₹%.2f (%.2f%%)", 
                   self.capital - 20000, ((self.capital - 20000) / 20000) * 100)
        logger.info("")
        logger.info("Total Trades:     %d", len(df))
        logger.info("Winners:          %d (%.1f%%)", len(winners), 
                   100 * len(winners) / len(df) if len(df) > 0 else 0)
        logger.info("Losers:           %d (%.1f%%)", len(losers),
                   100 * len(losers) / len(df) if len(df) > 0 else 0)
        logger.info("")
        logger.info("Avg Winner:       ₹%.2f", winners["net_pnl"].mean() if len(winners) > 0 else 0)
        logger.info("Avg Loser:        ₹%.2f", losers["net_pnl"].mean() if len(losers) > 0 else 0)
        logger.info("")
        logger.info("Signals Suppressed: %d", len(self.signals_suppressed))
        logger.info("")
        logger.info("Results saved to: %s", output_path)
        logger.info("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Paper trading mode")
    parser.add_argument("--strategy", default="pivot_cpr", help="Strategy to run")
    parser.add_argument("--duration", type=int, default=390, help="Duration in minutes (default: 390 = full day)")
    parser.add_argument("--iv", type=float, default=14.0, help="Implied volatility %")
    args = parser.parse_args()
    
    # Load config
    instruments_cfg = load_instruments()
    risk_cfg = load_risk()
    
    nifty_cfg = instruments_cfg["instruments"]["NIFTY"]
    
    # Create components
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
    
    # Run paper trading
    engine = PaperTradingEngine(strategy, adapter, pricer, instruments_cfg, risk_cfg)
    engine.run(duration_minutes=args.duration)


if __name__ == "__main__":
    main()
