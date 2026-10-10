"""
StrategyRegistry — loads, instantiates, and dispatches all strategies.

Rules:
- The registry catches per-strategy exceptions and logs them; one strategy
  crashing never halts the others or the engine loop.
- Strategies are never responsible for their own registration — the registry
  owns that.
"""

from __future__ import annotations

import importlib
import logging
from typing import Dict, List, Optional, Type

from core.engine.base_strategy import BaseStrategy, MarketData, Signal

logger = logging.getLogger(__name__)


class StrategyRegistry:
    """
    Manages the lifecycle of all registered strategy instances.

    Usage:
        registry = StrategyRegistry()
        registry.register(PivotCprStrategy, config={"confluence_tolerance_pct": 0.15})
        signals = registry.evaluate_all(market_data)
    """

    def __init__(self) -> None:
        # strategy_id -> strategy instance
        self._strategies: Dict[str, BaseStrategy] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, strategy_class: Type[BaseStrategy], config: dict) -> None:
        """
        Instantiate and register a strategy class.

        Raises:
            ValueError: if a strategy with the same STRATEGY_ID is already registered.
        """
        strategy = strategy_class(config=config)
        sid = strategy.strategy_id

        if sid in self._strategies:
            raise ValueError(
                f"Strategy '{sid}' is already registered. "
                "Each strategy_id must be unique."
            )

        self._strategies[sid] = strategy
        logger.info("Registered strategy: %s", sid)

    def register_by_dotpath(
        self,
        dotpath: str,
        class_name: str,
        config: dict,
    ) -> None:
        """
        Dynamic registration from a module dotpath string.

        Example:
            registry.register_by_dotpath(
                "src.strategies.pivot_cpr_strategy",
                "PivotCprStrategy",
                config={...},
            )
        """
        module = importlib.import_module(dotpath)
        cls: Type[BaseStrategy] = getattr(module, class_name)
        self.register(cls, config=config)

    def unregister(self, strategy_id: str) -> None:
        """Remove a strategy (useful in tests or for hot-reload scenarios)."""
        if strategy_id not in self._strategies:
            raise KeyError(f"Strategy '{strategy_id}' is not registered.")
        del self._strategies[strategy_id]
        logger.info("Unregistered strategy: %s", strategy_id)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def evaluate_all(self, market_data: MarketData) -> List[Signal]:
        """
        Call evaluate() on every registered strategy in registration order.

        Per-strategy exceptions are caught, logged, and do NOT propagate —
        the engine loop continues with the remaining strategies.

        Returns:
            List of Signal objects from strategies that returned a non-None result.
            Order matches registration order.
        """
        signals: List[Signal] = []

        for sid, strategy in self._strategies.items():
            try:
                signal = strategy.evaluate(market_data)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Strategy '%s' raised an unhandled exception during evaluate(); "
                    "skipping this bar for that strategy.",
                    sid,
                )
                continue

            if signal is not None:
                # Sanity: ensure the strategy correctly tagged the signal.
                if signal.strategy_id != sid:
                    logger.warning(
                        "Strategy '%s' emitted a signal with mismatched strategy_id '%s'; "
                        "correcting to '%s'.",
                        sid,
                        signal.strategy_id,
                        sid,
                    )
                    signal.strategy_id = sid
                signals.append(signal)
                logger.debug(
                    "Signal from '%s': %s %s",
                    sid,
                    signal.direction,
                    signal.instrument,
                )

        return signals

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def registered_ids(self) -> List[str]:
        return list(self._strategies.keys())

    def __len__(self) -> int:
        return len(self._strategies)

    def __contains__(self, strategy_id: str) -> bool:
        return strategy_id in self._strategies
