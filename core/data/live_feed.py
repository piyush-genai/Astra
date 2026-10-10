"""
Live data feed — stub for real-time OHLCV bar delivery.

Will be implemented once the broker adapter is functional.
Uses WebSocket streaming (Upstox V2 market data feed) or
polling as a fallback.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from core.broker.base_adapter import BrokerAdapter

logger = logging.getLogger(__name__)

# Callback type: called with each new completed bar's MarketData.
BarCallback = Callable[["MarketData"], None]  # type: ignore[name-defined]


class LiveFeed:
    """
    Delivers real-time OHLCV bars to registered callbacks.

    Stub implementation — the WebSocket streaming logic will be added
    once broker credentials and sandbox access are confirmed.
    """

    def __init__(self, adapter: BrokerAdapter, interval: str = "15minute") -> None:
        self._adapter = adapter
        self._interval = interval
        self._callbacks: list[BarCallback] = []
        self._running = False

    def subscribe(self, callback: BarCallback) -> None:
        """Register a callback to be called on each new completed bar."""
        self._callbacks.append(callback)

    def start(self) -> None:
        """Begin streaming. Raises NotImplementedError until implemented."""
        raise NotImplementedError(
            "LiveFeed.start() is not yet implemented. "
            "Implement WebSocket streaming via Upstox market data API."
        )

    def stop(self) -> None:
        self._running = False
        logger.info("LiveFeed stopped.")
