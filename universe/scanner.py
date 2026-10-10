"""
Universe Scanner — scans all instruments for trading signals every bar.

On each 5-minute bar close:
  1. Receives a map of symbol → MarketData (fetched by live/orchestrator.py)
  2. For each instrument, asks StrategySelector which strategy to run
  3. Calls strategy.evaluate(market_data)
  4. Collects all signals into ScanResults for OpportunityRanker
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from ml.regime_detector import RegimeDetector
from ml.strategy_selector import StrategySelector
from strategies.base import BaseStrategy, InstrumentType, MarketData, Regime, Signal
from universe.instruments import Instrument

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """A signal that passed the scanner's applicability check."""
    instrument: Instrument
    signal: Signal
    strategy_used: BaseStrategy
    regime: Regime
    priority_score: float = 0.0   # set by OpportunityRanker
    metadata: dict = field(default_factory=dict)


class UniverseScanner:
    """
    Scans all instruments for signals on every bar.

    Usage:
        scanner = UniverseScanner(broker, strategy_selector, regime_detector, risk_manager)
        results = scanner.scan(market_data_map)
        filtered = scanner.filter_by_capital(results, available_capital=50_000)
    """

    def __init__(
        self,
        broker_adapter,              # core.broker.base_adapter.BrokerAdapter
        strategy_selector: StrategySelector,
        regime_detector: RegimeDetector,
        risk_manager,                # core.engine.risk_manager.RiskManager
    ) -> None:
        self._broker = broker_adapter
        self._selector = strategy_selector
        self._regime_detector = regime_detector
        self._risk = risk_manager

    def scan(self, market_data_map: dict[str, MarketData]) -> list[ScanResult]:
        """
        Scan all instruments and return every valid signal found.

        Args:
            market_data_map: symbol → MarketData for all instruments with fresh data.

        Returns:
            List of ScanResults, unranked. Pass to OpportunityRanker.rank().
        """
        if not self._risk.is_trading_allowed():
            logger.warning("Risk manager has halted trading — skipping scan.")
            return []

        results: list[ScanResult] = []
        for symbol, market_data in market_data_map.items():
            result = self._scan_instrument_safe(market_data)
            if result:
                results.append(result)
        return results

    def filter_by_capital(
        self, results: list[ScanResult], available_capital: float
    ) -> list[ScanResult]:
        """
        Remove signals that would require more capital than available.

        Estimates minimum capital needed as: 1 lot × ATM premium × lot_size × 1.1 buffer.
        """
        # TODO Phase 2: implement premium estimation via broker LTP
        # For now return all results (capital check happens in ExecutionEngine)
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _scan_instrument_safe(self, market_data: MarketData) -> Optional[ScanResult]:
        """Wraps _scan_instrument with exception isolation so one bad instrument never halts the scan."""
        try:
            return self._scan_instrument(market_data)
        except Exception:
            logger.exception("Error scanning %s — skipping", market_data.symbol)
            return None

    def _scan_instrument(self, market_data: MarketData) -> Optional[ScanResult]:
        """
        Run regime detection + strategy selection + signal evaluation for one instrument.

        Returns ScanResult if a signal was generated, else None.
        """
        instrument_type = market_data.instrument_type

        # Detect regime from daily OHLCV if available
        regime = Regime.UNKNOWN
        if market_data.daily_ohlc is not None and len(market_data.daily_ohlc) >= 40:
            regime = self._regime_detector.detect(market_data.daily_ohlc)
        market_data.regime = regime

        # Select best strategy for this instrument + regime
        strategy = self._selector.select(regime, instrument_type)
        if strategy is None:
            logger.debug("No applicable strategy for %s in regime %s", market_data.symbol, regime.value)
            return None

        # Ask the strategy to evaluate this bar
        signal = strategy.evaluate(market_data)
        if signal is None:
            return None

        signal.symbol = market_data.symbol
        signal.timestamp = market_data.timestamp

        instrument = self._make_instrument_stub(market_data)
        return ScanResult(
            instrument=instrument,
            signal=signal,
            strategy_used=strategy,
            regime=regime,
        )

    def _make_instrument_stub(self, market_data: MarketData) -> Instrument:
        """Create a minimal Instrument from MarketData for the ScanResult."""
        from universe.instruments import Exchange, Instrument
        return Instrument(
            symbol=market_data.symbol,
            name=market_data.symbol,
            instrument_type=market_data.instrument_type,
            exchange=Exchange.NFO,
            lot_size=0,
            tick_size=0.05,
        )
