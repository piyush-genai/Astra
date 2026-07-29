---
inclusion: always
---

# Product Overview

## What this is
A personal, semi-automated trading system for Indian NSE index options (Nifty 50), operated by a single retail user under SEBI's retail algo-trading framework. The system runs one or more independent **strategies** (technical-signal generators) against live/historical index data, and executes the resulting trades via option contracts on a SEBI-registered broker's API.

## Why it exists
This system is one disciplined allocation sleeve within a broader personal wealth plan — it is explicitly NOT the mechanism expected to deliver the bulk of that plan's return target. Its job is to execute a small number of well-tested, defined-risk strategies mechanically and consistently, and to prove or disprove each strategy's edge through rigorous backtesting and paper-trading before any capital is committed.

## Non-negotiable product principles
- **Defined risk only.** The system buys options or uses debit spreads. It never writes (sells) naked options as a strategy mechanism — undefined risk is out of scope by design, not an oversight.
- **Multiple strategies, one engine.** The user will add strategies over time. The core engine must never need to change when a new strategy is added — new strategies are plug-ins against a stable interface.
- **Compliance is a feature, not an afterthought.** Static IP whitelisting, personal-account-only use, and staying under the exchange's retail algo order-rate threshold are hard requirements, not nice-to-haves.
- **Nothing goes live without passing gates.** Every strategy must clear: (1) backtest against defined kill-criteria, (2) walk-forward/out-of-sample validation, (3) live paper-trading for a minimum period, before it can place real orders.
- **Minimal capital, hard limits.** The operator defines a fixed, small capital allocation for this system, separate from other funds. Risk-per-trade and daily-loss circuit breakers are enforced by the engine, not left to strategy authors' discretion.

## Target user
A single operator (also the developer) — not a multi-tenant product, not sold or shared with others. No user-management, billing, or multi-account concerns apply.

## Current scope
One strategy is implemented today (pivot + CPR confluence on Nifty, 15-minute timeframe). The architecture must support adding further strategies without touching the engine core — see the `trading-engine-core` and `pivot-cpr-strategy` specs.
