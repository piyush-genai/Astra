"""
BrokerAdapter interface — the ONLY way engine code talks to a broker.

Strategies never import from this module.
Only src/engine/execution_engine.py is allowed to import from src/broker/.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"  # Reserved for spread-leg closes; naked sells are never initiated.


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class ProductType(str, Enum):
    INTRADAY = "I"
    DELIVERY = "D"


@dataclass
class OrderRequest:
    """Everything needed to submit a single-leg order."""
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int          # in units (not lots); execution_engine multiplies by lot_size
    algo_id: str           # mandatory since 1 April 2026 (Rule 9)
    price: Optional[float] = None       # required for LIMIT orders
    product_type: ProductType = ProductType.INTRADAY
    # Note: MPP (Market Price Protection) may apply at high order rates —
    # callers must not assume a plain unprotected market fill (Rule 12).


@dataclass
class OptionContract:
    """A resolved option contract returned by get_option_contract()."""
    symbol: str            # broker-specific symbol string
    instrument: str        # e.g. "NIFTY"
    strike: float
    option_type: str       # "CE" or "PE"
    expiry: str            # ISO date string, e.g. "2026-08-05"
    lot_size: int


class BrokerAdapter(abc.ABC):
    """
    Abstract interface for all broker integrations.

    Implementations: UpstoxAdapter, KiteAdapter, etc.
    Add a new broker by subclassing this — no engine code changes needed.
    """

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def authenticate(self) -> None:
        """
        Perform (or refresh) authentication.

        Daily 2FA re-auth is a required part of startup (Rule 11).
        Implementations must treat the daily forced-logout as a normal
        startup step, not an error condition.
        """
        ...

    @abc.abstractmethod
    def is_authenticated(self) -> bool:
        """Return True if the current session is valid and ready to trade."""
        ...

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def get_ltp(self, symbol: str) -> Optional[float]:
        """Return the last traded price for a symbol, or None on failure."""
        ...

    @abc.abstractmethod
    def get_option_chain(self, instrument: str, expiry: Optional[str] = None) -> list:
        """
        Return the option chain for instrument.
        Expiry defaults to the nearest weekly/monthly expiry per instruments.yaml.
        """
        ...

    @abc.abstractmethod
    def get_option_contract(
        self,
        instrument: str,
        option_type: str,   # "CE" or "PE"
        target_strike: Optional[float] = None,
    ) -> Optional[OptionContract]:
        """
        Resolve the best matching option contract.

        If target_strike is None, the adapter selects ATM or nearest OTM
        using the current underlying price and instruments.yaml config.
        Returns None if no liquid contract is found.
        """
        ...

    @abc.abstractmethod
    def get_ohlcv(
        self,
        symbol: str,
        interval: str,           # e.g. "15minute", "day"
        from_date: str,          # ISO date
        to_date: str,
    ) -> "pd.DataFrame":         # noqa: F821  — avoid circular import
        """Return OHLCV data as a pandas DataFrame with a DatetimeIndex."""
        ...

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def place_order(self, order: OrderRequest) -> str:
        """
        Submit an order.

        Returns the broker-assigned order_id on success.
        Raises on failure — callers should let exceptions propagate so
        the engine can log and skip, not silently swallow errors.
        """
        ...

    @abc.abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True if successfully cancelled."""
        ...

    @abc.abstractmethod
    def get_positions(self) -> list:
        """Return current open positions from the broker's perspective."""
        ...
