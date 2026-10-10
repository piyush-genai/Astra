"""
System Monitor — operational health and Telegram alerts.

Sends:
  - Trade alerts (entry/exit with P&L)
  - Daily summary (trades, capital, win rate)
  - Heartbeat every 5 min (confirms system is alive)
  - Anomaly alerts (unexpected losses, API failures, circuit breaker trips)
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional

import requests

from live.state_manager import StateManager

logger = logging.getLogger(__name__)


class SystemMonitor:
    """
    Sends Telegram notifications and monitors system health.

    Usage:
        monitor = SystemMonitor(token, chat_id, state_manager)
        monitor.send_trade_alert(trade)
        monitor.start_heartbeat(interval_seconds=300)
    """

    TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(
        self,
        telegram_token: str,
        chat_id: str,
        state_manager: StateManager,
    ) -> None:
        self._token = telegram_token
        self._chat_id = chat_id
        self._state = state_manager
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._running = False

    def send_trade_alert(self, trade: dict) -> None:
        """Send a Telegram message for a trade entry or exit."""
        direction = trade.get("direction", "")
        symbol = trade.get("symbol", "")
        lots = trade.get("lots", 0)
        signal_type = trade.get("signal_type", "")

        if trade.get("exit_price"):
            pnl = trade.get("pnl", 0)
            emoji = "✅" if pnl >= 0 else "❌"
            msg = (
                f"{emoji} <b>EXIT</b> | {symbol}\n"
                f"Direction: {direction} | Lots: {lots}\n"
                f"Entry: ₹{trade.get('entry_price', 0):,.2f} → Exit: ₹{trade.get('exit_price', 0):,.2f}\n"
                f"P&L: ₹{pnl:,.2f} | Reason: {trade.get('exit_reason', '')}\n"
                f"Capital: ₹{self._state.get_capital():,.0f}"
            )
        else:
            msg = (
                f"🎯 <b>ENTRY</b> | {symbol}\n"
                f"Direction: {direction} | Lots: {lots} | Type: {signal_type}\n"
                f"Entry: ₹{trade.get('entry_price', 0):,.2f}\n"
                f"Stop: ₹{trade.get('stop_loss', 0):,.2f}"
            )
        self._send(msg)

    def send_daily_summary(self) -> None:
        """Send end-of-day summary with capital and performance stats."""
        capital = self._state.get_capital()
        daily_pnl = self._state.get_daily_pnl()
        emoji = "📈" if daily_pnl >= 0 else "📉"
        msg = (
            f"{emoji} <b>Daily Summary</b> — {datetime.today().strftime('%d %b %Y')}\n\n"
            f"Capital: ₹{capital:,.0f}\n"
            f"Daily P&L: ₹{daily_pnl:,.2f}\n"
        )
        self._send(msg)

    def send_health_check(self) -> None:
        """Send a status message with current system state."""
        health = self.check_system_health()
        capital = self._state.get_capital()
        positions = self._state.get_open_positions()
        status_lines = [
            f"{'✅' if v else '❌'} {k.replace('_', ' ').title()}"
            for k, v in health.items()
        ]
        msg = (
            f"💓 <b>Health Check</b> — {datetime.now().strftime('%H:%M')}\n\n"
            + "\n".join(status_lines)
            + f"\n\nCapital: ₹{capital:,.0f} | Open positions: {len(positions)}"
        )
        self._send(msg)

    def check_system_health(self) -> dict[str, bool]:
        """
        Run health checks and return status dict.

        Returns:
            {
              "api_connected": True/False,
              "data_fresh": True/False,    # last bar < 10 min ago
              "capital_ok": True/False,    # capital > minimum threshold
              "within_risk_limits": True/False,
            }
        """
        capital = self._state.get_capital()
        return {
            "api_connected": True,        # TODO Phase 1: ping broker API
            "data_fresh": True,           # TODO Phase 2: check last bar timestamp
            "capital_ok": capital > 5_000,
            "within_risk_limits": True,   # TODO Phase 1: check risk_manager state
        }

    def alert_on_anomaly(self, anomaly: str) -> None:
        """Send an immediate high-priority Telegram alert."""
        msg = f"🚨 <b>ANOMALY DETECTED</b>\n\n{anomaly}\n\nCheck the system immediately."
        logger.error("Anomaly: %s", anomaly)
        self._send(msg)

    def start_heartbeat(self, interval_seconds: int = 300) -> None:
        """Send a heartbeat message every interval_seconds in a background thread."""
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._running = True
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(interval_seconds,),
            daemon=True,
            name="astra-heartbeat",
        )
        self._heartbeat_thread.start()
        logger.info("Heartbeat started (interval=%ds)", interval_seconds)

    def stop_heartbeat(self) -> None:
        """Stop the heartbeat thread."""
        self._running = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _heartbeat_loop(self, interval: int) -> None:
        while self._running:
            try:
                self.send_health_check()
            except Exception:
                logger.exception("Heartbeat failed")
            time.sleep(interval)

    def _send(self, text: str) -> None:
        """Post a message to Telegram. Logs but never raises on failure."""
        url = self.TELEGRAM_API.format(token=self._token)
        try:
            resp = requests.post(
                url,
                json={"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"},
                timeout=5,
            )
            if not resp.ok:
                logger.warning("Telegram send failed: %s", resp.text)
        except Exception:
            logger.exception("Telegram send error (message: %s)", text[:80])
