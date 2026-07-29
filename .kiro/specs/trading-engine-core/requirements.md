# Requirements: Trading Engine Core

## Overview
The engine core is the strategy-agnostic infrastructure that every strategy plugs into: it registers strategies, tracks positions, enforces risk limits, and executes orders. It must be built and tested before any strategy (including `pivot-cpr-strategy`) can go beyond backtesting its own signal logic in isolation.

## User Story 1 — Strategy registration
As the system operator, I want to register any number of independent strategy modules with the engine, so that I can add new strategies later without modifying core engine code.

**Acceptance Criteria**
- WHEN a strategy module implementing the `BaseStrategy` interface is added to `src/strategies/` and listed in the strategy registry config THEN the engine SHALL invoke its `evaluate()` method on every new market data bar without any changes to `src/engine/` code
- WHEN a strategy's `evaluate()` method raises an exception THEN the engine SHALL log the error and continue processing other registered strategies, rather than halting the entire system
- WHEN no strategies are registered THEN the engine SHALL run without error and take no trading action

## User Story 2 — Concurrent signals & position management
As the system operator, I want the engine to handle multiple simultaneous signals — from the same strategy firing again, or from different strategies — against shared capital, so that positions are never opened in an uncontrolled way.

**Acceptance Criteria**
- WHEN a strategy emits a signal for an instrument that already has an open position THEN the Position Manager SHALL check the configured `max_concurrent_positions_per_instrument` value before allowing a new, separately-tracked position to open
- WHEN two different strategies emit signals for the same instrument at the same time THEN the Position Manager SHALL evaluate each signal independently against position and capital limits, in a defined order (e.g. registration order), not process them as a single combined decision
- WHEN the configured `max_total_capital_deployed_pct` would be exceeded by a new position THEN the engine SHALL reject the new order and log the reason
- WHEN a position's exit condition is met (stop, target, or strategy-issued close signal) THEN the Position Manager SHALL close that specific position without affecting other concurrently open positions on the same or other instruments

## User Story 3 — Risk enforcement
As the system operator, I want hard, automatic risk limits enforced centrally, so that no individual strategy's bug or bad signal can exceed my risk tolerance.

**Acceptance Criteria**
- WHEN a new order would result in a known maximum loss exceeding the configured per-trade risk limit THEN the Execution Engine SHALL reject the order before submission
- WHEN cumulative daily realized + unrealized loss crosses the configured circuit-breaker threshold THEN the Risk Manager SHALL halt all new order placement for the remainder of the trading session
- WHEN the manual kill switch is triggered THEN the system SHALL stop placing new orders within a defined maximum latency (e.g. under 10 seconds) and SHALL notify the operator
- WHEN any risk check cannot be evaluated (e.g. missing option chain data needed to compute max loss) THEN the engine SHALL treat this as a rejection, not a pass-through

## User Story 4 — Order execution & contract selection
As the system operator, I want a signal (expressed in index points/direction) translated into a specific, defined-risk option order, so that strategies never need to know about option mechanics themselves.

**Acceptance Criteria**
- WHEN a strategy emits a valid signal THEN the Execution Engine SHALL select a specific option contract (strike, expiry) per the rules in `config/instruments.yaml`, without the strategy specifying contract details itself
- WHEN contract selection would require writing/selling a naked option THEN the Execution Engine SHALL refuse and log the refusal, per the non-negotiable rule in `.kiro/steering/trading-risk-rules.md`
- WHEN an order is placed THEN the Execution Engine SHALL record the instrument, strategy_id, entry time, contract details, and computed max loss for later position management and reporting

## Out of scope for this spec
- The specific pivot/CPR signal logic (covered in `.kiro/specs/pivot-cpr-strategy/`)
- Any specific broker's SDK details beyond the adapter interface shape
- UI/dashboard — this spec covers engine logic only
