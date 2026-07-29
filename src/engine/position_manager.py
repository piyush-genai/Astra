"""
PositionManager — tracks open positions and enforces concurrency limits.

Rules enforced here (from risk.yaml, never hardcoded):
- max_concurrent_positions_per_instrument
- max_total_capital_deployed_pct of allocated_capital

Individual strategies NEVER call this directly.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from src.engine.base_strategy import Signal, SignalDirection

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Represents one open position."""

    position_id: str
    instrument: str
    strategy_id: str
    direction: SignalDirection
    entry_time: datetime

    # Contract details filled in by ExecutionEngine after order placement.
    contract_symbol: Optional[str] = None
    lot_size: int = 0
    premium_paid: float = 0.0      # per unit (not × lot size)
    num_lots: int = 1

    # Running mark-to-market unrealized P&L (updated by the engine on each bar).
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0

    @property
    def capital_deployed(self) -> float:
        """Total capital at risk for this position (premium × lots × lot_size)."""
        return self.premium_paid * self.num_lots * self.lot_size

    @property
    def max_loss(self) -> float:
        """Maximum possible loss — same as capital deployed for a long option."""
        return self.capital_deployed


@dataclass
class ConcurrencyConfig:
    max_concurrent_positions_per_instrument: int
    max_total_capital_deployed_pct: float   # e.g. 50.0 means 50 %
    allocated_capital: float                 # total capital for pct check


class PositionManager:
    """
    Owns the positions table and decides whether a new position is allowed.

    The engine calls can_open() before every order; it never asks the
    strategy whether a second position is acceptable.
    """

    def __init__(self, config: ConcurrencyConfig) -> None:
        self._config = config
        # position_id -> Position
        self._positions: Dict[str, Position] = {}

    # ------------------------------------------------------------------
    # Concurrency / capital checks
    # ------------------------------------------------------------------

    def can_open(self, signal: Signal, estimated_capital: float) -> tuple[bool, str]:
        """
        Returns (True, "") if a new position is allowed, or
        (False, reason_string) if it is not.

        Args:
            signal: the signal being considered.
            estimated_capital: the capital that would be deployed
                               (premium × lot_size × num_lots).
        """
        open_on_instrument = self._open_positions_for(signal.instrument)

        # Rule 1: per-instrument concurrency cap.
        if len(open_on_instrument) >= self._config.max_concurrent_positions_per_instrument:
            reason = (
                f"max_concurrent_positions_per_instrument "
                f"({self._config.max_concurrent_positions_per_instrument}) "
                f"already reached for {signal.instrument}"
            )
            logger.info("Position rejected — %s", reason)
            return False, reason

        # Rule 2: total capital deployed cap.
        current_deployed = sum(p.capital_deployed for p in self._positions.values())
        new_deployed = current_deployed + estimated_capital
        max_allowed = (
            self._config.max_total_capital_deployed_pct / 100.0
        ) * self._config.allocated_capital

        if new_deployed > max_allowed:
            reason = (
                f"Opening this position would deploy ₹{new_deployed:,.2f} total "
                f"(limit: ₹{max_allowed:,.2f} = "
                f"{self._config.max_total_capital_deployed_pct}% of allocated capital)"
            )
            logger.info("Position rejected — %s", reason)
            return False, reason

        return True, ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open_position(
        self,
        signal: Signal,
        entry_time: datetime,
        contract_symbol: str,
        lot_size: int,
        premium_paid: float,
        num_lots: int = 1,
    ) -> Position:
        """Record a newly placed order as an open position."""
        position_id = str(uuid.uuid4())
        position = Position(
            position_id=position_id,
            instrument=signal.instrument,
            strategy_id=signal.strategy_id,
            direction=signal.direction,
            entry_time=entry_time,
            contract_symbol=contract_symbol,
            lot_size=lot_size,
            premium_paid=premium_paid,
            num_lots=num_lots,
        )
        self._positions[position_id] = position
        logger.info(
            "Position opened — id=%s instrument=%s strategy=%s contract=%s",
            position_id,
            signal.instrument,
            signal.strategy_id,
            contract_symbol,
        )
        return position

    def close_position(self, position_id: str, exit_pnl: float) -> Position:
        """Mark a position as closed; move it out of the open table."""
        if position_id not in self._positions:
            raise KeyError(f"Position '{position_id}' not found.")

        position = self._positions.pop(position_id)
        position.realized_pnl = exit_pnl
        position.unrealized_pnl = 0.0
        logger.info(
            "Position closed — id=%s realized_pnl=%.2f",
            position_id,
            exit_pnl,
        )
        return position

    def update_unrealized_pnl(self, position_id: str, pnl: float) -> None:
        """Update mark-to-market P&L for a position."""
        if position_id not in self._positions:
            raise KeyError(f"Position '{position_id}' not found.")
        self._positions[position_id].unrealized_pnl = pnl

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def open_positions(self) -> List[Position]:
        return list(self._positions.values())

    def _open_positions_for(self, instrument: str) -> List[Position]:
        return [p for p in self._positions.values() if p.instrument == instrument]

    @property
    def total_unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self._positions.values())

    @property
    def total_capital_deployed(self) -> float:
        return sum(p.capital_deployed for p in self._positions.values())

    def __len__(self) -> int:
        return len(self._positions)
