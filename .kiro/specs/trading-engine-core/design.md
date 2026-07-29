# Design: Trading Engine Core

## Architecture overview

```
                 ┌─────────────────┐
  Market Data →  │ Strategy Registry │  (holds N BaseStrategy instances)
  (Data Feed)    └────────┬─────────┘
                          │  Signal (or None) per strategy, per bar
                          ▼
                 ┌─────────────────┐
                 │  Position Manager │  (tracks open positions, enforces
                 └────────┬─────────┘   concurrency + capital limits)
                          │  approved intent to open/close
                          ▼
                 ┌─────────────────┐
                 │   Risk Manager    │  (per-trade max-loss check,
                 └────────┬─────────┘   circuit breaker, kill switch)
                          │  approved order
                          ▼
                 ┌─────────────────┐
                 │ Execution Engine  │  (contract selection, order
                 └────────┬─────────┘   placement via Broker Adapter)
                          ▼
                 ┌─────────────────┐
                 │  Broker Adapter   │  (Upstox, etc.)
                 └─────────────────┘
```

Every signal flows through this same pipeline regardless of which strategy produced it. No component upstream of the Broker Adapter is allowed to talk to the broker directly.

## Core interfaces

### `BaseStrategy` (src/engine/base_strategy.py)
```python
class Signal:
    strategy_id: str
    instrument: str
    direction: Literal["LONG", "SHORT"]
    stop_points: float      # in underlying index points
    target_points: float    # in underlying index points
    metadata: dict           # strategy-specific context for logging/debugging

class BaseStrategy(ABC):
    @abstractmethod
    def evaluate(self, market_data: MarketData) -> Optional[Signal]:
        """Called once per new bar. Returns a Signal or None. Must not
        place orders, check positions, or touch the broker."""
```

### `PositionManager`
Maintains a table of open positions keyed by `(instrument, strategy_id, entry_time)` — deliberately NOT keyed by instrument alone, so multiple concurrent positions on the same instrument (from the same or different strategies) are tracked as distinct entries. Before approving a new position, checks:
- `count(open positions for instrument) < max_concurrent_positions_per_instrument` (from `config/risk.yaml`)
- `sum(capital deployed across all open positions) + new position capital <= max_total_capital_deployed_pct * total_capital`

### `RiskManager`
Stateless per-check, but tracks running daily P&L. Two responsibilities:
- **Pre-trade check:** given a candidate order's computed max loss, reject if it exceeds `max_risk_per_trade_pct * total_capital`.
- **Circuit breaker:** on every position close and periodically, recompute cumulative daily P&L; if it crosses the configured negative threshold, set a global `trading_halted` flag that the Execution Engine checks before every new order.
- **Kill switch:** a separate, always-checked flag settable via CLI command or Telegram bot message, independent of the automatic circuit breaker.

### `ExecutionEngine`
The only component allowed to import from `src/broker/`. Responsibilities:
- Given an approved Signal, query the Broker Adapter's option chain for the instrument
- Select strike (ATM or configured offset) and expiry (current week, per `config/instruments.yaml`) per configured rules
- Compute max loss (premium × lot size, or net debit × lot size for a spread) and pass it to the Risk Manager's pre-trade check
- If approved, place the order via the Broker Adapter and record the resulting position with the Position Manager
- Refuses any contract selection path that would require writing an uncovered short option leg

### `BrokerAdapter` (interface)
```python
class BrokerAdapter(ABC):
    @abstractmethod
    def get_option_chain(self, instrument: str, expiry: date) -> OptionChain: ...
    @abstractmethod
    def place_order(self, order: OrderRequest) -> OrderResult: ...
    @abstractmethod
    def get_positions(self) -> list[Position]: ...
```
Concrete implementation: `UpstoxAdapter` (primary target — free data + order APIs, versus Zerodha's paid Kite Connect data plan). A `KiteAdapter` or other future adapters (Angel One, Fyers, Dhan) can be added later implementing the same interface without touching engine or strategy code.

## Handling the "two strategies fire on the same instrument" case
Signals are processed strategy-by-strategy in registration order within a single bar's evaluation cycle — not batched or merged. Each signal independently goes through Position Manager → Risk Manager → Execution Engine. This means:
- If Strategy A's signal is approved and opens a position, and Strategy B's signal (same instrument, same bar) is then evaluated, it sees Strategy A's position already counted against `max_concurrent_positions_per_instrument` — so the *order* strategies are registered in has a real effect and should be a deliberate config choice, not incidental.
- This ordering behavior must be covered by a specific integration test (see tasks.md) so it's a documented decision, not an emergent surprise.

## Data model (positions table, minimum fields)
`instrument, strategy_id, entry_time, direction, contract_symbol, strike, expiry, lots, entry_premium, stop_points, target_points, max_loss_rupees, status (open/closed), exit_time, exit_reason, realized_pnl`
