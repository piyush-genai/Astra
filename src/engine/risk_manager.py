"""
RiskManager — pre-trade max-loss check, daily circuit breaker, kill switch.

Rules enforced here (values read from risk.yaml, never hardcoded):
- max_loss_per_trade: reject any order whose max loss exceeds this.
- daily_loss_limit: halt all new orders once cumulative loss (realized +
  unrealized) crosses this threshold for the session.
- kill_switch_active: immediate halt regardless of circuit-breaker state.

This module has NO knowledge of individual strategies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    max_loss_per_trade: float       # INR; per-position cap
    daily_loss_limit: float         # INR; session cumulative cap
    kill_switch_active: bool = False  # set True via CLI or Telegram


class RiskManager:
    """
    All checks return (allowed: bool, reason: str).
    Callers must check allowed before proceeding with an order.
    """

    def __init__(self, config: RiskConfig) -> None:
        self._config = config
        self._session_realized_loss: float = 0.0  # accumulated closed-position losses
        self._circuit_breaker_tripped: bool = False

    # ------------------------------------------------------------------
    # Pre-trade checks (called by ExecutionEngine before every order)
    # ------------------------------------------------------------------

    def check_pre_trade(
        self,
        max_loss_for_trade: float,
        current_unrealized_loss: float,
    ) -> tuple[bool, str]:
        """
        Run all pre-trade risk checks in order.

        Args:
            max_loss_for_trade: maximum possible rupee loss for this specific
                                order (premium × lot_size for a long option;
                                net_debit × lot_size for a spread).
            current_unrealized_loss: total unrealized loss across all open
                                     positions RIGHT NOW (negative = loss).
        Returns:
            (True, "") if the order is allowed.
            (False, reason) if any check fails.
        """
        # Kill switch takes priority over everything.
        if self._config.kill_switch_active:
            return False, "Kill switch is active — no new orders permitted."

        # Circuit breaker.
        if self._circuit_breaker_tripped:
            return False, (
                "Daily loss circuit breaker has tripped — "
                "no new orders for the remainder of this session."
            )

        # Per-trade max-loss check (Rule 2 in trading-risk-rules.md).
        if max_loss_for_trade > self._config.max_loss_per_trade:
            reason = (
                f"Max loss for this trade (₹{max_loss_for_trade:,.2f}) exceeds "
                f"per-trade limit (₹{self._config.max_loss_per_trade:,.2f})."
            )
            logger.info("Pre-trade check failed — %s", reason)
            return False, reason

        # Check whether circuit breaker WOULD trip if we include current
        # unrealized losses. This prevents opening a new position when the
        # account is already at the daily limit in unrealized terms.
        total_loss = self._session_realized_loss + abs(min(current_unrealized_loss, 0))
        if total_loss >= self._config.daily_loss_limit:
            self._trip_circuit_breaker(total_loss)
            return False, (
                f"Daily loss limit reached (₹{total_loss:,.2f} ≥ "
                f"₹{self._config.daily_loss_limit:,.2f}) — circuit breaker tripped."
            )

        return True, ""

    # ------------------------------------------------------------------
    # Session P&L tracking (called by ExecutionEngine on position close)
    # ------------------------------------------------------------------

    def record_realized_loss(self, pnl: float) -> None:
        """
        Record a closed position's P&L.
        Only losses (negative pnl) count toward the circuit breaker.
        """
        if pnl < 0:
            self._session_realized_loss += abs(pnl)
            logger.debug(
                "Realized loss recorded: ₹%.2f | session total: ₹%.2f",
                abs(pnl),
                self._session_realized_loss,
            )
            if self._session_realized_loss >= self._config.daily_loss_limit:
                self._trip_circuit_breaker(self._session_realized_loss)

    def update_unrealized_check(self, total_unrealized_pnl: float) -> None:
        """
        Called each bar with the aggregate unrealized P&L.
        Trips the circuit breaker proactively if combined loss exceeds the limit.
        """
        total_loss = self._session_realized_loss + abs(min(total_unrealized_pnl, 0))
        if total_loss >= self._config.daily_loss_limit and not self._circuit_breaker_tripped:
            self._trip_circuit_breaker(total_loss)

    # ------------------------------------------------------------------
    # Kill switch
    # ------------------------------------------------------------------

    def activate_kill_switch(self) -> None:
        """Immediately halt new orders. Callable from CLI or Telegram bot."""
        self._config.kill_switch_active = True
        logger.warning("KILL SWITCH ACTIVATED — all new order placement halted.")

    def deactivate_kill_switch(self) -> None:
        """Re-enable order placement (operator action required)."""
        self._config.kill_switch_active = False
        logger.warning("Kill switch deactivated by operator.")

    # ------------------------------------------------------------------
    # Session reset (call at start of each trading day)
    # ------------------------------------------------------------------

    def reset_session(self) -> None:
        """Reset daily accumulators. Must be called at the start of each session."""
        self._session_realized_loss = 0.0
        self._circuit_breaker_tripped = False
        logger.info("RiskManager session reset.")

    # ------------------------------------------------------------------
    # State inspection
    # ------------------------------------------------------------------

    @property
    def circuit_breaker_tripped(self) -> bool:
        return self._circuit_breaker_tripped

    @property
    def kill_switch_active(self) -> bool:
        return self._config.kill_switch_active

    @property
    def session_realized_loss(self) -> float:
        return self._session_realized_loss

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _trip_circuit_breaker(self, total_loss: float) -> None:
        if not self._circuit_breaker_tripped:
            self._circuit_breaker_tripped = True
            logger.warning(
                "CIRCUIT BREAKER TRIPPED — cumulative session loss ₹%.2f ≥ limit ₹%.2f. "
                "No new orders will be placed for the remainder of this session.",
                total_loss,
                self._config.daily_loss_limit,
            )
