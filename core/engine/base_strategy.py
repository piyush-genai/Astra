"""
Base interface for all strategies.

Rules:
- Every strategy subclasses BaseStrategy and implements evaluate().
- Strategies NEVER place orders, call the broker, or manage positions directly.
- Strategies NEVER import from core.broker or core.engine.execution_engine.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pandas as pd


class SignalDirection(str, Enum):
    LONG = "LONG"   # buy a call (or call debit spread)
    SHORT = "SHORT"  # buy a put (or put debit spread)


class OptionType(str, Enum):
    CALL = "CE"
    PUT = "PE"


@dataclass
class Signal:
    """
    Emitted by a strategy's evaluate() call.

    The engine (ExecutionEngine + PositionManager) decides whether and how
    to act on this — the strategy has no say in that decision.
    """

    strategy_id: str
    instrument: str           # e.g. "NIFTY"
    direction: SignalDirection

    # Optional guidance on contract selection. If None, ExecutionEngine
    # applies its own ATM/near-OTM selection logic from instruments.yaml.
    target_strike: Optional[float] = None
    target_option_type: Optional[OptionType] = None

    # The bar timestamp that produced this signal (UTC-aware recommended).
    bar_time: Optional[pd.Timestamp] = None

    # Arbitrary key-value context for logging / debugging.
    # Strategies may populate this; the engine never relies on it for logic.
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.target_option_type is None:
            # Infer from direction when not explicitly set.
            self.target_option_type = (
                OptionType.CALL if self.direction == SignalDirection.LONG else OptionType.PUT
            )


@dataclass
class MarketData:
    """
    Snapshot of data passed to strategy.evaluate() for one bar.

    The engine populates this from live or historical feeds before
    dispatching to each strategy.
    """

    instrument: str
    bar_time: pd.Timestamp

    # OHLC for the current bar (15m or whatever the strategy's timeframe is).
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    # Full historical OHLC frame for indicator computation (strategy-specific length).
    # Strategies should treat this as read-only.
    history: Optional[pd.DataFrame] = None

    # Pre-computed indicator context — the engine may pass pre-computed values
    # to avoid redundant computation across multiple strategies.
    # Keyed by indicator name, value is whatever the indicator returns.
    indicators: dict = field(default_factory=dict)


class BaseStrategy(abc.ABC):
    """
    Abstract base for all strategy plug-ins.

    Subclass this, implement evaluate(), and register the class via
    StrategyRegistry. That's the entire contract.
    """

    # Override in each concrete strategy. Used as the registry key
    # and as the strategy_id on emitted Signals.
    STRATEGY_ID: str = ""

    def __init__(self, config: dict) -> None:
        """
        Args:
            config: strategy-specific section from config (e.g. from a
                    per-strategy YAML block). Risk limits are NOT passed
                    here — those live in risk.yaml and are enforced by the engine.
        """
        if not self.STRATEGY_ID:
            raise ValueError(
                f"{self.__class__.__name__} must define a non-empty STRATEGY_ID class attribute."
            )
        self._config = config

    @abc.abstractmethod
    def evaluate(self, market_data: MarketData) -> Optional[Signal]:
        """
        Analyse market_data and return a Signal if a trade condition is met,
        or None if no action should be taken this bar.

        This method must be side-effect-free with respect to orders and positions.
        It may update internal state (e.g. carry state across bars), but it must
        never call the broker or touch PositionManager.
        """
        ...

    @property
    def strategy_id(self) -> str:
        return self.STRATEGY_ID
