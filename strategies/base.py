"""
Base interfaces for all Astra trading strategies.

Every strategy is a stateless plugin that implements BaseStrategy.
It receives MarketData, returns an optional Signal — nothing more.
Strategies never place orders, manage positions, or check risk limits directly.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

import pandas as pd


class InstrumentType(Enum):
    INDEX = "index"
    INDEX_OPTION = "index_option"
    EQUITY = "equity"
    EQUITY_OPTION = "equity_option"


class Direction(Enum):
    BUY = "BUY"   # go long / buy call
    SELL = "SELL"  # go short / buy put


class Regime(Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    VOLATILE = "volatile"
    CHOPPY = "choppy"
    UNKNOWN = "unknown"


@dataclass
class MarketData:
    """Snapshot of market state passed to a strategy's evaluate() on every bar."""
    symbol: str
    timeframe: str                    # e.g. "5min", "15min", "1day"
    ohlcv: pd.DataFrame               # columns: open, high, low, close, volume; index: datetime
    current_bar: pd.Series            # the latest bar (last row of ohlcv)
    timestamp: datetime               # bar close time
    instrument_type: InstrumentType
    daily_ohlc: Optional[pd.DataFrame] = None   # prior-day OHLC for pivot computation
    regime: Regime = Regime.UNKNOWN             # current market regime (set by Astra layer)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Zone:
    """A price zone (support/resistance band) that the strategy detected."""
    low: float
    high: float
    zone_type: str = ""   # e.g. "pivot", "CPR", "resistance", "support"

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2

    @property
    def width(self) -> float:
        return self.high - self.low


@dataclass
class Signal:
    """
    A trading signal emitted by a strategy.
    The ExecutionEngine consumes this and decides whether to act.
    """
    direction: Direction
    signal_type: str                  # e.g. "regular_breakout", "momentum_breakout"
    confidence: float                 # 0.0–1.0; used by OpportunityRanker
    zone: Zone
    stop_loss: float                  # price level where the trade is invalidated
    symbol: str = ""
    timestamp: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyMetadata:
    """Describes a strategy's identity and operating constraints."""
    name: str
    version: str
    description: str
    supported_instruments: list[InstrumentType]
    preferred_regimes: list[Regime]   # regimes where this strategy has edge
    min_capital: float = 20_000.0
    expected_win_rate: float = 0.25   # from backtest; used as prior by StrategySelector
    expected_rr: float = 3.0          # risk:reward ratio from backtest


@dataclass
class TradeOutcome:
    """Feedback passed back to the strategy after a trade closes."""
    signal: Signal
    entry_price: float
    exit_price: float
    pnl: float
    exit_reason: str       # "stop_loss", "trailing_stop", "structural_invalidation", "eod", "reversal"
    regime_at_entry: Regime
    hold_bars: int


class BaseStrategy(abc.ABC):
    """
    Abstract base class for all Astra strategies.

    Contract:
    - evaluate() is the only public method that produces signals.
    - Strategies are stateless between calls except for internal cooldown/tracking.
    - Strategies never import from core.broker or core.engine.execution_engine.
    """

    @property
    @abc.abstractmethod
    def metadata(self) -> StrategyMetadata:
        """Return static metadata about this strategy."""
        ...

    @abc.abstractmethod
    def evaluate(self, market_data: MarketData) -> Optional[Signal]:
        """
        Analyse one bar of market data and return a Signal, or None.

        Called on every bar close during paper and live trading.
        Must be fast (< 50ms); do not call external APIs here.
        """
        ...

    def on_trade_result(self, outcome: TradeOutcome) -> None:
        """
        Optional feedback hook called after each trade closes.

        Strategies can use this to update internal state (e.g. zone cooldowns,
        regime-specific win-rate tracking). Default implementation is a no-op.
        """

    def is_applicable(self, instrument_type: InstrumentType, regime: Regime) -> bool:
        """
        Return True if this strategy should be considered for the given instrument
        type and market regime. The StrategySelector calls this before evaluate().

        Default: True if instrument_type is in supported_instruments.
        Override to add regime-aware logic.
        """
        return instrument_type in self.metadata.supported_instruments

    def reset_daily_state(self) -> None:
        """
        Called at market open each day to reset any intra-day state
        (cooldowns, signal counters, etc.). Default is a no-op.
        """
