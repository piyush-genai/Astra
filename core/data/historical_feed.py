"""
Historical data feed — wraps BrokerAdapter for backtesting and offline use.

This module provides a thin interface for fetching and caching historical
OHLCV data. Strategy-agnostic; used by the backtest harness and by the
live feed's warmup phase.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from core.broker.base_adapter import BrokerAdapter

logger = logging.getLogger(__name__)


class HistoricalFeed:
    """Fetches OHLCV data via the broker adapter, with optional in-memory cache."""

    def __init__(self, adapter: BrokerAdapter) -> None:
        self._adapter = adapter
        # Simple in-memory cache: (symbol, interval, from, to) -> DataFrame
        self._cache: dict[tuple, pd.DataFrame] = {}

    def get_ohlcv(
        self,
        symbol: str,
        interval: str,
        from_date: str,
        to_date: str,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data for symbol between from_date and to_date.

        Args:
            symbol:    Broker-specific symbol string.
            interval:  e.g. "15minute", "day".
            from_date: ISO date string "YYYY-MM-DD".
            to_date:   ISO date string "YYYY-MM-DD".
            use_cache: If True, return cached result if available.

        Returns:
            pandas DataFrame with DatetimeIndex, columns: open high low close volume.
        """
        key = (symbol, interval, from_date, to_date)
        if use_cache and key in self._cache:
            logger.debug("Cache hit for %s %s %s→%s", symbol, interval, from_date, to_date)
            return self._cache[key]

        logger.info("Fetching OHLCV: %s %s %s→%s", symbol, interval, from_date, to_date)
        df = self._adapter.get_ohlcv(
            symbol=symbol,
            interval=interval,
            from_date=from_date,
            to_date=to_date,
        )

        if use_cache:
            self._cache[key] = df

        return df

    def clear_cache(self) -> None:
        self._cache.clear()
