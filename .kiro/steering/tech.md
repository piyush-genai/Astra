---
inclusion: always
---

# Technology Stack

## Language & core libraries
- **Python 3.11+** for all engine, strategy, and execution code.
- **pandas** for all OHLC/indicator data handling. Indicator formulas (pivots, CPR) are implemented directly with pandas/numpy arithmetic — do not pull in a black-box TA library for these, since the exact formulas are already specified in the `pivot-cpr-strategy` spec and must match precisely.
- **backtrader** or **vectorbt** for backtesting the signal layer. Pick one per-project and stay consistent; do not mix both in the same backtest harness.
- **pytest** for all unit and integration tests.

## Broker integration
- Broker API access goes through a **Broker Adapter interface** (see `trading-engine-core` design.md) — never call a broker SDK directly from strategy or engine core code. This keeps the door open to support more than one broker later without touching strategy logic.
- Primary adapter target: Upstox (data + order-placement APIs are free of subscription cost, unlike Zerodha's ₹500/month Kite Connect data plan). Other adapters (Zerodha Kite Connect, Angel One SmartAPI, Fyers, Dhan) may be added later behind the same interface.
- All option-chain lookups (strike/expiry selection) go through the adapter, not hardcoded contract logic.

## Infrastructure
- Runs on a cloud VM (AWS Lightsail/EC2 or GCP) with a static IP, required for broker API whitelisting under SEBI's retail algo framework.
- **SQLite** for local development and early testing; **PostgreSQL** once the system is running live, for trade logs, position history, and strategy performance tracking.
- **Telegram bot** (or equivalent) for operator alerts and as a manual kill-switch trigger channel.

## Configuration, not hardcoding
The following MUST live in a config file (e.g. `config/instruments.yaml`), never as hardcoded constants in code, because they change periodically via NSE circulars:
- Lot size per instrument (e.g. Nifty 50 = 65 as of Jan 2026 — subject to revision)
- Weekly/monthly expiry weekday per instrument (e.g. Nifty weekly = Tuesday as of Sept 2025 — subject to revision)
- Risk parameters: max % risk per trade, daily loss circuit-breaker threshold, max concurrent positions per instrument

## Testing philosophy
- Every strategy module ships with unit tests that verify its indicator formulas against known/hand-computed values before any backtest is trusted.
- The engine core (Position Manager, Risk Manager) ships with tests that specifically exercise concurrent-signal and circuit-breaker scenarios, since these are the highest-risk-of-bugs paths.
