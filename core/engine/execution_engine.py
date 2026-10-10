"""
ExecutionEngine — the ONLY module allowed to import from core.broker.

Responsibilities:
- Receive signals from StrategyRegistry.
- Select the appropriate option contract (via BrokerAdapter).
- Compute max loss; reject orders that violate risk rules.
- Reject any naked-short code path (Rule 1 in trading-risk-rules.md).
- Check Algo-ID is configured before placing (Rule 9 — legal requirement).
- Route orders through BrokerAdapter.
- Record positions via PositionManager.
- Report realized P&L to RiskManager on close.

This module does NOT contain strategy logic, indicator formulas, or risk
parameter values — those live in risk.yaml and are injected via config dicts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from core.broker.base_adapter import BrokerAdapter, OrderRequest, OrderSide, OrderType
from core.engine.base_strategy import OptionType, Signal, SignalDirection
from core.engine.position_manager import Position, PositionManager
from core.engine.risk_manager import RiskManager

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """
    Translates validated signals into option orders via the BrokerAdapter.

    All decisions about WHETHER to open a position are delegated to
    PositionManager (concurrency) and RiskManager (risk). This class
    handles the HOW.
    """

    def __init__(
        self,
        broker: BrokerAdapter,
        position_manager: PositionManager,
        risk_manager: RiskManager,
        instruments_config: dict,  # parsed config/instruments.yaml
        risk_config: dict,         # parsed config/risk.yaml
        dry_run: bool = True,      # True = log orders, never send to broker
    ) -> None:
        self._broker = broker
        self._pm = position_manager
        self._rm = risk_manager
        self._instruments = instruments_config
        self._risk_config = risk_config
        self._dry_run = dry_run

        if dry_run:
            logger.warning(
                "ExecutionEngine is in DRY-RUN mode — orders will be logged but NOT sent."
            )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def process_signal(self, signal: Signal) -> Optional[Position]:
        """
        Attempt to execute a signal.

        Returns the Position if an order was successfully placed, None otherwise.
        """
        strategy_id = signal.strategy_id
        instrument = signal.instrument

        # ── 1. Algo-ID check (mandatory since 1 April 2026) ─────────────────
        algo_id = self._get_algo_id(strategy_id)
        if not algo_id:
            logger.error(
                "No Algo-ID configured for strategy '%s'. "
                "Order placement refused — this is a legal requirement.",
                strategy_id,
            )
            return None

        # ── 2. Reject any naked-short path ──────────────────────────────────
        # Signals only express LONG or SHORT directional intent; the engine
        # always buys the corresponding option. Selling/writing is never done.
        option_type: OptionType = (
            OptionType.CALL if signal.direction == SignalDirection.LONG else OptionType.PUT
        )

        # ── 3. Contract selection ────────────────────────────────────────────
        instrument_cfg = self._instruments.get("instruments", {}).get(instrument)
        if instrument_cfg is None:
            logger.error("Instrument '%s' not found in instruments.yaml.", instrument)
            return None

        lot_size: int = instrument_cfg["lot_size"]

        # Ask the adapter for the nearest liquid contract.
        contract = self._broker.get_option_contract(
            instrument=instrument,
            option_type=option_type.value,
            target_strike=signal.target_strike,
        )
        if contract is None:
            logger.error("Could not resolve option contract for signal: %s", signal)
            return None

        # Fetch indicative premium from the adapter.
        premium = self._broker.get_ltp(contract.symbol)
        if premium is None or premium <= 0:
            logger.error("Invalid LTP for contract '%s'.", contract.symbol)
            return None

        # ── 4. Max-loss computation (Rule 2) ─────────────────────────────────
        # For a long option: max loss = premium_paid × lot_size (total premium at risk).
        max_loss = premium * lot_size
        logger.debug(
            "Max loss for %s %s %s: ₹%.2f (premium=%.2f × lot=%d)",
            instrument,
            option_type.value,
            contract.symbol,
            max_loss,
            premium,
            lot_size,
        )

        # ── 5. Concurrency check ─────────────────────────────────────────────
        allowed, reason = self._pm.can_open(signal, estimated_capital=max_loss)
        if not allowed:
            logger.info("Signal rejected by PositionManager — %s", reason)
            return None

        # ── 6. Risk checks ────────────────────────────────────────────────────
        unrealized_pnl = self._pm.total_unrealized_pnl
        allowed, reason = self._rm.check_pre_trade(
            max_loss_for_trade=max_loss,
            current_unrealized_loss=unrealized_pnl,
        )
        if not allowed:
            logger.info("Signal rejected by RiskManager — %s", reason)
            return None

        # ── 7. Place order ────────────────────────────────────────────────────
        order_request = OrderRequest(
            symbol=contract.symbol,
            side=OrderSide.BUY,           # we only BUY options (long only)
            order_type=OrderType.MARKET,
            quantity=lot_size,
            algo_id=algo_id,
        )

        if self._dry_run:
            logger.info(
                "[DRY RUN] Would place order: %s | premium≈%.2f | max_loss=₹%.2f",
                order_request,
                premium,
                max_loss,
            )
            order_id = "DRY_RUN"
        else:
            order_id = self._broker.place_order(order_request)
            logger.info("Order placed — order_id=%s symbol=%s", order_id, contract.symbol)

        # ── 8. Record position ────────────────────────────────────────────────
        position = self._pm.open_position(
            signal=signal,
            entry_time=datetime.now(timezone.utc),
            contract_symbol=contract.symbol,
            lot_size=lot_size,
            premium_paid=premium,
            num_lots=1,
        )
        return position

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_algo_id(self, strategy_id: str) -> Optional[str]:
        """Return the Algo-ID for a strategy, or None if not configured."""
        algo_ids: dict = self._risk_config.get("algo_ids", {})
        algo_id = algo_ids.get(strategy_id)
        # Treat None, empty string, and the literal "null" as unconfigured.
        if not algo_id or str(algo_id).lower() in ("null", "none", ""):
            return None
        return str(algo_id)
