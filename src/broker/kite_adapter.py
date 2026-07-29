"""
KiteAdapter — optional secondary adapter for Zerodha Kite Connect.

Note: Kite Connect data API costs ₹500/month. Upstox is the primary
adapter; this is here for future optionality behind the same interface.

All method bodies are stubs until the adapter is needed.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from src.broker.base_adapter import (
    BrokerAdapter,
    OptionContract,
    OrderRequest,
)

logger = logging.getLogger(__name__)


class KiteAdapter(BrokerAdapter):
    """Zerodha Kite Connect V3 adapter stub."""

    def __init__(self, config: dict) -> None:
        self._api_key: str = config["api_key"]
        self._api_secret: str = config["api_secret"]
        self._access_token: Optional[str] = config.get("access_token")
        logger.info("KiteAdapter initialised (stub — not yet implemented).")

    def authenticate(self) -> None:
        raise NotImplementedError("KiteAdapter.authenticate() not yet implemented.")

    def is_authenticated(self) -> bool:
        return bool(self._access_token)

    def get_ltp(self, symbol: str) -> Optional[float]:
        raise NotImplementedError

    def get_option_chain(self, instrument: str, expiry: Optional[str] = None) -> list:
        raise NotImplementedError

    def get_option_contract(
        self,
        instrument: str,
        option_type: str,
        target_strike: Optional[float] = None,
    ) -> Optional[OptionContract]:
        raise NotImplementedError

    def get_ohlcv(
        self,
        symbol: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> pd.DataFrame:
        raise NotImplementedError

    def place_order(self, order: OrderRequest) -> str:
        raise NotImplementedError

    def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError

    def get_positions(self) -> list:
        raise NotImplementedError
