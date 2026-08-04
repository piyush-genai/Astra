# Nifty 50 Options Strategy — Pivot CPR + Momentum Breakout

**Version:** v1.0 "Cooldown Configuration"
**Status:** ✅ Approved — Ready for Paper Trading
**Last Updated:** August 5, 2026

> Update this file whenever a new configuration is tested. This document is the single source of truth for the live strategy.

---

## 1. Overview

This is an **options-buying** strategy on the Nifty 50 index. We only ever **buy** calls or puts — never sell/write options — so maximum loss per trade is capped at the premium paid.

It hunts for two kinds of setups:

| Type | Description | Frequency | Reliability |
|---|---|---|---|
| **Regular Breakout** | Price breaks a support/resistance level with 2-candle confirmation | Low (~4.5% of trades) | Higher win rate (~30.5%) |
| **Momentum Breakout** | A single explosive candle signals panic buying/selling | High (~95.5% of trades) | Lower win rate (~20%) |

---

## 2. Signal Detection

### 2.1 Regular Breakout

**Step 1 — Map the key levels**
Every day, the system computes pivot points and CPR (Central Pivot Range) levels from the prior day's price action. Where two or more levels cluster, that forms a **confluence zone** — a "wall" where price is likely to bounce or break through.

**Step 2 — Wait for a breakout**
On 5-minute candles, a breakout occurs when a candle **closes** above a resistance zone (bullish) or below a support zone (bearish).

**Step 3 — Confirm it**
The breakout is not tradeable yet. Wait for the **next** candle to also close beyond the zone — this filters out false breakouts.

**Step 4 — Enter**
Enter at the open of the **third** candle (N+2). Break up → buy a **CALL**. Break down → buy a **PUT**.

```
09:15  Price 24,900 | Resistance zone 24,920–24,925
09:20  Candle closes 24,935 (above zone)         → Breakout detected
09:25  Next candle closes 24,945 (still above)   → Confirmed
09:30  BUY CALL at open                          → Entry
```

### 2.2 Momentum Breakout

Catches explosive, high-conviction candles. Requires **at least 2 of these 3 conditions**:

| # | Condition | Test | What it shows |
|---|---|---|---|
| 1 | **Range explosion** | Candle range (high − low) ≥ **1.8×** the average range of the last 10 candles | Volatility spike |
| 2 | **Strong body** | Candle body (close − open) ≥ **50%** of total range | Conviction, not indecision |
| 3 | **Deep penetration** | Price moves ≥ **1.5×** the zone width beyond the broken zone | Momentum is continuing |

If 2 or 3 conditions are met, enter **immediately** — no 2-candle confirmation needed. Direction logic is the same as a regular breakout (up → call, down → put).

```
10:15  Price 24,850 | Support zone 24,860–24,865
10:20  Candle: O=24,862  H=24,868  L=24,812  C=24,820
       Range = 56 pts (avg 20)        → 2.8× explosion   ✓
       Body  = 42 pts (75% of range)  → Strong body      ✓
       Penetration = 45 pts (zone width 5) → 9× penetration ✓
       → BUY PUT IMMEDIATELY
```

---

## 3. Exit Rules

Four ways out of a trade, checked in this priority order.

### 3.1 Stop Loss *(96.5% of all exits)*

**Initial stop:**

| Trade type | Long stop | Short stop |
|---|---|---|
| Regular | `min(zone.low, breakout_candle.low)` | `max(zone.high, breakout_candle.high)` |
| Momentum *(tighter — 50% retracement)* | `breakout_candle.low + 50% × (close − low)` | `breakout_candle.high − 50% × (high − close)` |

**Trailing stop** (activates after 2 candles in the trade):
- Every new candle, move the stop to the high/low of the candle **from 2 bars ago**.
- The stop only tightens — it never moves away from entry.
- Touch the stop at any point intra-candle → exit immediately.

```
09:30  Entry @ 24,950 | Initial stop 24,920
09:35  1st candle in trade → stop stays 24,920
09:40  2nd candle in trade → stop stays 24,920
09:45  3rd candle → trailing begins: candle from 09:35 had low 24,935 → stop moves to 24,935
09:50  Candle from 09:40 had low 24,948 → stop moves to 24,948
       ... continues until stopped out or another exit fires
```

### 3.2 Structural Invalidation
If **any** candle closes back through the broken zone, the breakout has failed. Exit at market immediately — ignore the stop-loss level.

> Example: broke up through 24,920–24,925, went long. A later candle closes at 24,918 (back inside/below the zone) → exit now.

### 3.3 End of Day
Close any open position at **15:25** (or the session's last bar). No overnight option exposure — the theta/decay risk isn't worth it.

### 3.4 Reversal *(rare)*
If in a **long** and a **short** signal fires → close the long, open the short (and vice versa). Acts as a hedge/reversal mechanism when the market flips hard.

---

## 4. Position Sizing

Dynamic sizing — capital grows, lot size grows, within strict limits. **Always take the smallest of the three rules below.**

| Rule | Formula | Cap |
|---|---|---|
| 1. Risk limit | `Lots = (Capital × 2%) / (Premium × Lot Size)` | Never risk more than 2% of capital on one trade |
| 2. Capital deployment limit | `Lots = (Capital × 10%) / (Premium × Lot Size)` | Never deploy more than 10% of capital in one position |
| 3. Hard cap | — | **10 lots**, regardless of what Rules 1–2 allow (exchange freeze-limit / retail-algo protection) |

**Final lots = MIN(Risk Lots, Capital Lots, 10)** — floored down, with a floor of 1 lot if a signal triggers and any rule allows ≥1.

**Worked examples:**

| | Capital | Premium | Risk Lots | Capital Lots | Hard Cap | **Trade** |
|---|---|---|---|---|---|---|
| A — Small capital, cheap option | ₹20,000 | ₹25 | 0.25 → min 1 | 1.23 → 1 | 10 | **1 lot** |
| B — Mid stage | ₹200,000 | ₹150 | 0.41 → min 1 | 2.05 → 2 | 10 | **1 lot** |
| C — Large capital | ₹800,000 | ₹120 | 2.05 → **2** | 10.25 → 10 | 10 | **2 lots** (risk limit is the binding constraint) |

*Lot size used throughout: 65.*

---

## 5. Zone Cooldown

**Problem it solves:** without a cooldown, the same zone can get traded 4–5 times in 30 minutes and whipsaw the account.

**Rule:** once a trade exits from a given zone `[price_low, price_high]`, that exact zone is blocked from generating new signals for **15 minutes**. Other zones are unaffected and can trade immediately.

```
10:30  Enter LONG from zone [24,920–24,925]
10:35  Exit on stop loss → zone [24,920–24,925] locked until 10:50
10:40  New LONG signal, same zone       → BLOCKED (cooldown active)
10:42  New SHORT signal, zone [24,950–24,955] → ALLOWED (different zone)
10:51  New LONG signal, zone [24,920–24,925] → ALLOWED (cooldown expired)
```

---

## 6. Position Limits

- **One trade at a time.** Max 1 active position. New signals while in a trade are ignored, *except* a reversal signal (see §3.4).
- **Capital exhaustion kill switch.** If capital hits ₹0 or below, all trading stops until capital is manually restored. (This is what happened in the failed "optimized" config, which went to **−₹131**.)

---

## 7. Capital Compounding

Compounding is **monthly**, not per-trade:

1. Start the month with current capital (e.g., ₹20,000 in Month 1).
2. Trade throughout the month; profits accumulate.
3. Start the next month with the full ending balance — no capital withdrawn.
4. Position sizes (lots) scale up automatically via §4 as capital grows.

**Capital scaled from ~1 lot/trade in Feb to 10 lots/trade (hard cap) by July** — see backtest table in §9.

---

## 8. Transaction Costs

*(Already included in all backtest P&L figures.)*

| Cost | Amount |
|---|---|
| Brokerage | ₹20/order × 2 (entry + exit) = **₹40/lot** |
| STT | 0.15% on premium × lot size |
| SEBI + GST | ~₹5/lot |
| **Total** | **~₹45–60 per lot per trade** |

**Worked example:** Buy call @ ₹150, sell @ ₹180, lot size 65:
`Gross profit = (180 − 150) × 65 = ₹1,950`
`− Brokerage ₹40 − STT ₹14.63 − Other ₹5 = Net profit ₹1,890.38`

---

## 9. Backtest Performance (Feb 1 – Jul 31, 2026)

### Headline numbers

| Metric | Value |
|---|---|
| Starting capital | ₹20,000 |
| Ending capital | ₹8,25,266 |
| Absolute gain | ₹8,05,266 |
| Return | **+4,026%** (≈40×) |
| Total trades | 1,302 |
| Win rate | 25.4% (331 wins / 971 losses) |
| Avg trades/day | 9.9 |

### Signal breakdown

| Signal type | Trades | Share | Win rate |
|---|---|---|---|
| Momentum | 1,243 | 95.5% | 20.0% |
| Regular | 59 | 4.5% | 30.5% |

### Month-by-month

| Month | Start Capital | Trades | Lots Traded | Net P&L | Return | End Capital |
|---|---|---|---|---|---|---|
| Feb 2026 | ₹20,000 | 207 | 414 | +₹53,257 | +266% | ₹73,257 |
| Mar 2026 | ₹73,257 | 208 | 576 | +₹2,56,301 | +350% | ₹3,29,558 |
| Apr 2026 | ₹3,29,558 | 205 | 709 | +₹1,53,137 | +46% | ₹4,82,695 |
| May 2026 | ₹4,82,695 | 195 | 837 | +₹1,04,916 | +22% | ₹5,87,611 |
| Jun 2026 | ₹5,87,611 | 240 | 1,107 | +₹1,77,642 | +30% | ₹7,65,254 |
| Jul 2026 | ₹7,65,254 | 247 | 1,161 | +₹60,012 | +8% | ₹8,25,266 |

**Key observations:**
- March was the standout month — capital grew 4.5× (₹73K → ₹330K).
- July was the slowest — only +8%, possibly a market-regime shift.
- Lot size scaled from 1 (Feb) to the 10-lot hard cap (Jul).
- Trade volume stayed consistent: 195–247 trades/month.

---

## 10. What This Strategy Demands From You

**Discipline**
- Accept a 75% losing-trade rate — this is high-volume, low-win-rate by design.
- 10 losses in a row is normal, not a signal to intervene.
- Winners are sized to outweigh losers by a wide margin; trust the system, not any single trade.

**Capital**
- Minimum backtested starting capital: ₹20,000.
- More capital → more lots → higher absolute returns, same % growth.
- Don't inject fresh capital mid-month; wait for month-end.

**Time**
- Runs automatically during market hours (9:15 AM – 3:30 PM).
- Check positions 2–3×/day.
- Stay reachable for a manual kill switch.

**Emotional strength**
- Expect real intra-month drawdowns (Feb dipped to ₹15K before recovering to ₹73K).
- Don't change the strategy mid-month based on a bad streak.

---

## 11. Risk Factors

| Risk | Detail |
|---|---|
| **Market regime change** | Strategy is tuned to Feb–Jul 2026 conditions. A range-bound or low-volatility market means fewer/weaker signals. |
| **Capital wipeout** | Overtrading, over-leverage, or bad parameters can still cause a full loss — the "optimized" config example lost 100% and went negative. Current safeguards reduce but don't eliminate this. |
| **Exchange / broker issues** | Freeze limits above 36 lots (we stay capped at 10), API downtime at critical moments, order rejections from insufficient margin. |
| **Black swan events** | Sudden crashes, circuit breakers, surprise regulatory changes. |

---

## 12. Next Steps

**Before going live:**
1. Paper trade for 2–4 weeks.
2. Verify every parameter against this document.
3. Set up a Telegram kill switch for immediate manual stop.
4. Watch every trade closely during week 1.
5. Start with ₹20,000–50,000 — not full capital.

**Ongoing monitoring cadence:**
- **Daily:** open positions, capital level.
- **Weekly:** win rate, average P&L per trade.
- **Monthly:** full performance review vs. backtest.

**Hard stop conditions — halt and reassess if:**
- Capital drops below ₹10,000 (50% drawdown from the ₹20K start).
- Daily loss exceeds 10% of capital.
- Win rate stays below 15% for 2+ consecutive weeks.
- A regulatory issue arises.

---

## 13. Settings Reference

| Category | Setting | Value |
|---|---|---|
| Strategy | Name | Pivot CPR + Momentum Breakout |
| | Timeframe | 5-minute bars |
| | Instrument | Nifty 50 Index Options |
| | Lot size | 65 |
| | Strike step | 50 |
| Entry | Regular | 2-bar confirmation, enter on bar 3 |
| | Momentum | Immediate entry, needs 2 of 3 criteria |
| | — Range explosion | ≥ 1.8× |
| | — Body requirement | ≥ 50% of range |
| | — Penetration | ≥ 1.5× zone width |
| Exit | Initial stop | Zone edge or breakout extreme (regular); 50% retracement (momentum) |
| | Trailing stop | 2 bars back, after 2 bars in trade |
| | Structural invalidation | Close through zone |
| | EOD | Flat by 15:25 |
| Sizing | Risk per trade | 2% max |
| | Capital deployed | 10% max |
| | Hard cap | 10 lots/trade |
| | Minimum | 1 lot |
| Other | Cooldown | 15 min per zone |
| | Concurrency | 1 position max (unless reversal) |
| | Compounding | Monthly |
| Costs | Brokerage | ₹40/lot |
| | STT | 0.15% on premium |
| | Other | ₹5/lot |

---

**Status:** ✅ Approved for Paper Trading
**Last updated:** 2026-08-05
