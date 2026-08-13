# Implementation Spec: Persistent Capital + Percentage-Based Risk Management

**Hand this to Kiro as-is.** Each step references exact files/methods in the current codebase (`run_paper.py`, `risk.yaml`) so it should be unambiguous to implement.

---

## Why this is needed (context — do not skip)

Two problems exist right now, confirmed by reading the actual code:

1. **`PaperTradingEngine.__init__` hardcodes `self.capital = 20000.0`.** Nothing persists this across process runs. Every session starts fresh at ₹20,000 — profit/loss from previous days is discarded, not compounded.
2. **Three different, disagreeing sets of risk numbers exist simultaneously:**
   - `risk.yaml`'s `max_loss_per_trade: 5000` and `daily_loss_limit: 15000` are **never read by any code** — `self.risk_cfg` is stored in `__init__` and never referenced again.
   - `calculate_position_size()` independently hardcodes `2%` risk-per-trade and `10%` capital-deployed directly in Python, unrelated to the YAML.
   - `risk.yaml`'s `max_total_capital_deployed_pct: 50.0` conflicts with the code's hardcoded `10%` — different numbers, same intent.
   - The `daily_loss_limit` circuit breaker described in `risk.yaml`'s own comments ("RiskManager halts ALL new orders for the remainder of the day") **does not exist anywhere in the engine.**

The absolute rupee figures in `risk.yaml` (5000, 15000) divide out to sane percentages (2.5%, 7.5%) against `allocated_capital: 200000` — evidence they were sized for the eventual live account, not the ₹20k paper sandbox. This spec reconciles all of it into one enforced source of truth.

---

## Design principles Kiro should follow

1. **`risk.yaml` becomes the only source of truth for risk parameters.** No hardcoded percentages or rupee limits in Python.
2. **Per-trade and capital-deployment limits scale with live running capital** (`self.capital`), so they naturally grow/shrink as the account compounds or draws down. This is the mechanism the user is asking for.
3. **The daily circuit breaker is evaluated against a capital figure frozen at the start of each trading day** (`day_start_capital`), not against the continuously-moving `self.capital`. Freezing it avoids a confusing moving target where the loss limit itself shrinks as losses accrue within the same day.
4. **`allocated_capital` (₹200,000) is a separate governance ceiling**, not the paper-trading balance. It represents the maximum this system is ever allowed to deploy once live. Do not conflate it with `self.capital`. Keep paper trading on its own persisted balance, seeded from a new `starting_capital` config value — not from `allocated_capital`.
5. **One absolute (non-percentage) limit is kept deliberately: the hard lot cap.** This exists to catch a runaway math bug producing an absurd order size, and to respect the exchange's per-order freeze quantity — it is a safety rail, not a risk-sizing tool, so it should not scale with capital the same way.

---

## Step 1 — Add capital persistence across sessions

- Create a small local state file, e.g. `capital_state.json`, at project root (same directory pattern as `KILL_SWITCH.txt` / `TRADING_STATUS.txt`).
- Schema: `{"running_capital": <float>, "last_updated": "<iso timestamp>", "last_session_date": "<YYYY-MM-DD>"}`.
- On `PaperTradingEngine` startup:
  - If `capital_state.json` exists, load `running_capital` into `self.capital`.
  - If it does not exist (first run ever), initialize `self.capital` from a new `starting_capital` field in `risk.yaml` (see Step 2), and write the state file immediately.
- **Write the state file after every `exit_position()` call, not only at the end of the session.** This matches the existing `update_status()` pattern used for `TRADING_STATUS.txt` and protects against losing the day's compounding if the process crashes or the EC2 instance restarts mid-session, rather than only relying on the `finally:` block in `run()`.
- The existing `finally:` block that calls `save_results()` should also confirm the final `capital_state.json` write happened, as a safety net.

## Step 2 — Update `risk.yaml` schema

Replace the current `per_trade` / `circuit_breaker` blocks with this:

```yaml
# Risk configuration — single source of truth. Enforced entirely by PaperTradingEngine
# (and, later, the live RiskManager). No risk numbers should be hardcoded in Python.

capital:
  # Capital used to seed the FIRST-EVER paper trading session. After that,
  # capital compounds automatically via capital_state.json — this value is
  # not re-applied on subsequent runs.
  starting_capital: 20000

  # Hard governance ceiling for eventual LIVE deployment. Separate from the
  # paper-trading running balance. Used only when sizing the real funded
  # account before going live — not read by the paper engine.
  allocated_capital: 200000

per_trade:
  # Max % of CURRENT running capital allowed to be at risk on a single trade.
  # Derived from your original ₹5000 / ₹200,000 target = 2.5%.
  # Review this number — it's inherited from your own prior config, not a
  # universal rule.
  max_loss_per_trade_pct: 2.5

  # Max % of CURRENT running capital allowed to be deployed across open
  # positions at once. NOTE: your old YAML said 50%, your old code enforced
  # 10% — these disagreed. Pick one deliberately; 10% is what's already been
  # running during your live paper test, so it's the safer default unless
  # you have a specific reason to raise it.
  max_capital_deployed_pct: 10.0

circuit_breaker:
  # % of DAY-START capital (frozen at session start, not continuously
  # updated) that triggers a full halt on new orders for the rest of the day.
  # Derived from your original ₹15,000 / ₹200,000 target = 7.5%.
  daily_loss_limit_pct: 7.5

concurrency:
  max_concurrent_positions_per_instrument: 1   # unchanged — count, not %

position_limits:
  # Absolute ceiling on lots per single order, independent of capital.
  # Exists to catch a sizing bug producing an absurd order, and to respect
  # the exchange's per-order freeze quantity for the current lot size.
  # VERIFY current NIFTY freeze quantity via Upstox's option contract API
  # (freeze_quantity field) before trusting this number — do not assume it.
  hard_cap_lots: 10

algo_ids:
  pivot_cpr_strategy: null   # unchanged — fill in after registering with Upstox

kill_switch_active: false     # unchanged
```

## Step 3 — Rewire `calculate_position_size()`

Replace the hardcoded `0.02`, `0.10`, and `10` with reads from `self.risk_cfg`:

```python
def calculate_position_size(self, signal, entry_premium):
    lot_size = self.instruments_cfg["instruments"]["NIFTY"]["lot_size"]
    per_trade_cfg = self.risk_cfg["per_trade"]

    max_risk = self.capital * (per_trade_cfg["max_loss_per_trade_pct"] / 100)
    max_deployed = self.capital * (per_trade_cfg["max_capital_deployed_pct"] / 100)
    hard_cap = self.risk_cfg["position_limits"]["hard_cap_lots"]

    max_loss_per_lot = entry_premium * lot_size
    lots_from_risk = int(max_risk / max_loss_per_lot) if max_loss_per_lot > 0 else 0
    lots_from_capital = int(max_deployed / max_loss_per_lot) if max_loss_per_lot > 0 else 0

    lots = max(1, min(lots_from_risk, lots_from_capital, hard_cap))
    return lots
```

Nothing else about this method's logic needs to change — it already scales correctly with `self.capital`; it just needs to read its inputs from config instead of literals.

## Step 4 — Snapshot `day_start_capital` at the start of each session

In `PaperTradingEngine.run()`, immediately after capital is loaded from `capital_state.json` (Step 1) and before the main loop starts:

```python
self.day_start_capital = self.capital
self.circuit_breaker_tripped = False
```

This is the fixed reference point for the daily circuit breaker — it does not move during the day even as `self.capital` changes with each trade.

## Step 5 — Implement the circuit breaker (this does not exist yet — build it new)

Add a method:

```python
def check_circuit_breaker(self):
    """Halt new entries if today's realized loss breaches the daily limit."""
    daily_limit_pct = self.risk_cfg["circuit_breaker"]["daily_loss_limit_pct"]
    daily_limit_rupees = self.day_start_capital * (daily_limit_pct / 100)
    today_pnl = self.capital - self.day_start_capital  # realized only

    if today_pnl <= -daily_limit_rupees and not self.circuit_breaker_tripped:
        self.circuit_breaker_tripped = True
        logger.warning(
            "🛑 CIRCUIT BREAKER TRIPPED: today's loss ₹%.2f exceeds limit ₹%.2f (%.1f%% of day-start capital ₹%.2f)",
            -today_pnl, daily_limit_rupees, daily_limit_pct, self.day_start_capital
        )
        self.update_status(f"CIRCUIT BREAKER TRIPPED — halted for the day. Loss: ₹{-today_pnl:.2f}")
        send_telegram_alert(
            f"🛑 <b>CIRCUIT BREAKER TRIPPED</b>\n"
            f"Today's loss: ₹{-today_pnl:.2f}\n"
            f"Limit: ₹{daily_limit_rupees:.2f} ({daily_limit_pct}%)\n"
            f"No new positions will open for the rest of today."
        )
```

**Call this in two places:**
- Right after `exit_position()` completes (so a trip is detected the moment it happens).
- In the main loop, before evaluating a new signal — gate entry on `not self.circuit_breaker_tripped`, the same way `active_position` is currently checked:
  ```python
  if not self.active_position and not self.circuit_breaker_tripped:
      # ... existing signal evaluation block
  ```

**Known limitation to flag, not silently paper over:** this checks *realized* P&L only (closed trades), not unrealized loss on an open position. If you want the breaker to also account for a large open loss before it's closed, that requires fetching a live quote for the open position on every loop iteration to mark it to market — a real feature, not a trivial addition. Decide explicitly whether you want that now or later; don't assume it's covered.

## Step 6 — Verify the hard lot cap against real exchange limits

Before trusting `hard_cap_lots: 10`, pull the current NIFTY option contract's `freeze_quantity` from Upstox's option contract API response and confirm 10 lots × current `lot_size` (65) = 650 units doesn't approach or exceed it. Don't assume a number from memory or an old blog post — check it live, since freeze quantities get revised alongside lot size changes.

## Step 7 — Close the gap in `run_live.py`

`risk.yaml`'s own comment says the engine "will refuse to place orders" if `algo_ids.pivot_cpr_strategy` is null — but `run_live.py`'s `GATE_STATUS` dict only checks three unrelated flags and never reads this field. Add a fourth, explicit gate:

```python
def check_algo_id_registered(risk_cfg, strategy_name):
    return bool(risk_cfg.get("algo_ids", {}).get(strategy_name))
```

Fold this into the existing `failed = [...]` gate check in `main()`, alongside the three existing named gates, so the script's actual behavior matches what `risk.yaml` already promises in writing.

## Step 8 — Prove it actually works before trusting the "paper_trading_completed" gate

Don't just deploy this and assume it's correct. Write a small standalone test (separate script or pytest) that:
1. Instantiates `PaperTradingEngine` with a small `day_start_capital`.
2. Feeds it a sequence of synthetic losing trades via direct calls to `exit_position()` with negative P&L, until the cumulative loss should exceed `daily_loss_limit_pct`.
3. Asserts `self.circuit_breaker_tripped` becomes `True`.
4. Asserts a subsequent `enter_position()` call is actually blocked (or that the main-loop gating condition would block it).

Only once this test passes should "paper_trading_completed" be considered to mean what it claims — that the safety rails, not just the signal logic, have been exercised and proven.

---

## Summary checklist for Kiro

- [ ] `capital_state.json` persistence added; capital compounds across sessions
- [ ] `risk.yaml` rewritten to the schema above — percentages for scaling limits, absolute for the lot cap only
- [ ] `calculate_position_size()` reads from `risk_cfg`, no hardcoded 0.02/0.10/10
- [ ] `day_start_capital` snapshot taken once per session, before the loop
- [ ] `check_circuit_breaker()` implemented and called after every exit + before every new entry
- [ ] Hard lot cap cross-checked against live Upstox `freeze_quantity`
- [ ] `run_live.py` gate updated to check `algo_ids` registration
- [ ] Standalone test proves the circuit breaker actually trips and blocks entries
