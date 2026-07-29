---
inclusion: always
---

# Trading Risk Rules (Non-Negotiable)

These rules apply to every strategy, every piece of engine code, and every task Kiro executes in this project. If a generated implementation would violate one of these, stop and flag it rather than implementing it — do not silently work around it.

## Position & order rules
1. **No naked option writing.** The system only buys options (long calls/puts) or uses defined-risk debit spreads. Any code path that sells/writes an option without an offsetting long leg is out of scope and should be rejected, regardless of which strategy requests it.
2. **Known max loss before every order.** Before any order is placed, the Execution Engine must be able to compute the maximum possible rupee loss for that position (premium × lot size for a long option; net debit × lot size for a spread) and compare it against the configured per-trade risk limit. If this check cannot be performed, the order must not be placed.
3. **Concurrency is a Position Manager decision, not a strategy decision.** Individual strategies never decide whether a second position can be opened alongside an existing one — they only emit signals. The Position Manager applies `max_concurrent_positions_per_instrument` and `max_total_capital_deployed_pct` from `config/risk.yaml` uniformly, regardless of which strategy(ies) generated the signals.

## Circuit breakers
4. **Daily loss circuit breaker.** Once cumulative realized + unrealized loss for the day crosses the configured threshold, the Risk Manager halts all new order placement for the remainder of the session automatically. This must be enforced in the engine, not left to strategy discipline.
5. **Manual kill switch.** A manual override must exist that immediately halts new order placement, reachable within seconds (e.g. via the Telegram bot or a CLI command), independent of whether the automated circuit breaker has tripped.

## Compliance
6. **Personal use only.** No functionality for sharing, reselling, or running this system on behalf of other accounts. This is a hard constraint tied to the operator's regulatory status, not a feature limitation to work around.
7. **Order-rate awareness.** The Execution Engine should be able to report/log its order rate; if a future strategy's design would push order frequency toward the exchange's registration threshold, flag it explicitly rather than silently allowing it.
8. **Config over constants.** Lot size, expiry weekday, and margin parameters are read from `config/instruments.yaml` at runtime. Never hardcode these as literals in strategy or engine code — they are revised periodically by the exchange.
9. **Algo-ID tagging (mandatory since 1 April 2026).** Every order this system places must carry the exchange-assigned Algo-ID obtained by registering the strategy with the broker. The Execution Engine must refuse to place an order if no valid Algo-ID is configured for the active strategy — this is not optional infrastructure, it's a legal requirement for every order.
10. **Static IP + single App ID binding.** API access is tied to exactly one whitelisted static IP and one registered App ID. The engine should fail loudly (not silently retry against a different route) if this binding breaks.
11. **Daily 2FA re-authentication.** The old always-on refresh-token session model is discontinued. The engine must handle a mandatory daily re-auth step (e.g. before market pre-open) as a normal part of its startup routine, not treat a forced daily logout as an error condition.
12. **MPP order behavior.** High-rate order submissions may be auto-converted by the exchange to Market Price Protection orders (a market order with a price-protection band). Execution logic that assumes a plain, unprotected market order fill should account for this.
13. **Current transaction cost assumptions (effective 1 April 2026).** STT is 0.05% on futures and 0.15% on options (premium + exercise). Every backtest must use current STT figures, not older/lower ones — check for further revisions periodically, since this is exactly the kind of parameter rule 8 already requires living in config, not code.

## Testing gate
9. **No strategy reaches live trading without passing, in order: unit tests on its indicator formulas → backtest against its own stated kill-criteria → a minimum live paper-trading period.** Skipping a gate is not an option Kiro should implement even if asked to "just enable live trading" for a strategy that hasn't completed the prior gates — surface this explicitly instead.
