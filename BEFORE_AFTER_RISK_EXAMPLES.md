# Before vs After: Risk Management Examples

## Problem: Current System Has Multiple Bugs

### Bug 1: Capital Resets Every Day
**Current behavior:**
- Day 1: Start with ₹20,000 → End at ₹22,500 (+₹2,500 profit)
- Day 2: Start with ₹20,000 → Yesterday's ₹2,500 profit LOST ❌
- Day 3: Start with ₹20,000 → No compounding ❌

**After fix:**
- Day 1: Start ₹20,000 → End ₹22,500 ✅
- Day 2: Start ₹22,500 (carries forward) → End ₹24,000 ✅
- Day 3: Start ₹24,000 → Compounds automatically ✅

---

### Bug 2: Risk Config is Ignored

**Current risk.yaml says:**
```yaml
max_loss_per_trade: 5000        # ← NEVER READ BY CODE
daily_loss_limit: 15000         # ← NEVER READ BY CODE
max_total_capital_deployed_pct: 50.0  # ← CONFLICTS WITH CODE
```

**But code hardcodes different numbers:**
```python
max_risk = self.capital * 0.02        # 2% hardcoded
max_deployed = self.capital * 0.10    # 10% hardcoded (not 50%!)
hard_cap = 10                         # hardcoded
```

**After fix:** ✅ Code reads from risk.yaml, no hardcoded values

---

### Bug 3: No Circuit Breaker

**Current behavior:**
- Lose ₹15,000 in morning → Keep trading ❌
- Lose ₹30,000 total → Still no stop ❌
- Only manual kill switch available

**After fix:**
- Lose >7.5% of day-start capital → **Auto-halt all new trades** ✅
- Telegram alert sent ✅
- Must wait until next day to resume ✅

---

## Detailed Examples with Real Numbers

### Scenario 1: Normal Trading Day

| Metric | BEFORE | AFTER |
|--------|---------|--------|
| **Day 1 Start** | ₹20,000 | ₹20,000 |
| Trade 1 premium | ₹130 | ₹64.30 (real Ask) |
| Position size | 1 lot (2% of ₹20K) | 1 lot (2.5% of ₹20K) |
| Max capital deployed | 10% = ₹2,000 | 10% = ₹2,000 |
| Premium source | BLACK-SCHOLES | REAL ASK/BID |
| **Day 1 End** | ₹22,000 (+₹2,000) | ₹22,000 (+₹2,000) |
| **Day 2 Start** | ₹20,000 ❌ (resets) | ₹22,000 ✅ (carries forward) |

---

### Scenario 2: Capital Growth (Compounding Effect)

**BEFORE (No Compounding):**
```
Day 1:  ₹20,000 capital → 1 lot max → +₹2,000 profit → End ₹22,000
Day 2:  ₹20,000 capital → 1 lot max → +₹2,000 profit → End ₹22,000 ❌
Day 3:  ₹20,000 capital → 1 lot max → +₹2,000 profit → End ₹22,000 ❌
Week total: +₹6,000 total (3 days × ₹2K)
```

**AFTER (With Compounding):**
```
Day 1:  ₹20,000 capital → 1 lot max → +₹2,000 profit → End ₹22,000 ✅
Day 2:  ₹22,000 capital → 1 lot max → +₹2,200 profit → End ₹24,200 ✅
Day 3:  ₹24,200 capital → 1 lot max → +₹2,420 profit → End ₹26,620 ✅
Week total: +₹6,620 total (₹620 more from compounding)
```

**After 1 month:**
- Before: ~₹40,000 (linear)
- After: ~₹44,800 (compounded) **+₹4,800 difference!**

---

### Scenario 3: Position Sizing with Different Capital

| Capital | BEFORE | AFTER |
|---------|---------|--------|
| **₹20,000** | | |
| Max risk (2% / 2.5%) | ₹400 (hardcoded 2%) | ₹500 (from risk.yaml) |
| Premium = ₹130 | 1 lot | 1 lot |
| **₹50,000** (after wins) | | |
| Max risk | ₹1,000 (still 2%) | ₹1,250 (still 2.5%) |
| Premium = ₹130 | 1 lot ❌ (doesn't scale) | **2 lots** ✅ (scales up!) |
| **₹10,000** (after losses) | | |
| Max risk | ₹200 | ₹250 |
| Premium = ₹130 | 0 lots ❌ (insufficient) | 0 lots (correctly blocks) |

**Key difference:** After fix, position size **automatically scales** with capital growth/drawdown.

---

### Scenario 4: Circuit Breaker in Action

**BEFORE (No Protection):**
```
9:30 AM:  Trade 1 → -₹5,000 loss  (capital: ₹15,000)
10:00 AM: Trade 2 → -₹4,000 loss  (capital: ₹11,000)
11:00 AM: Trade 3 → -₹3,000 loss  (capital: ₹8,000)
12:00 PM: Trade 4 → -₹2,000 loss  (capital: ₹6,000)
Result: Lost ₹14,000 (70% of capital) - NO AUTO-STOP ❌
```

**AFTER (Circuit Breaker at 7.5%):**
```
Day start: ₹20,000
Loss limit: 7.5% × ₹20,000 = ₹1,500

9:30 AM:  Trade 1 → -₹800 loss   (capital: ₹19,200, loss: ₹800)
10:00 AM: Trade 2 → -₹750 loss   (capital: ₹18,450, loss: ₹1,550)
🛑 CIRCUIT BREAKER TRIPPED! Daily loss ₹1,550 > ₹1,500 limit
11:00 AM: Signal fires → BLOCKED (no new entry allowed)
12:00 PM: Signal fires → BLOCKED
3:30 PM:  Market close → Down only ₹1,550 (7.75%) ✅

Telegram: "🛑 CIRCUIT BREAKER TRIPPED - No new positions for rest of day"
```

**Protection:** Limits max daily loss to ~7.5% instead of unlimited.

---

### Scenario 5: Risk Configuration Comparison

| Setting | BEFORE (risk.yaml) | BEFORE (actual code) | AFTER (unified) |
|---------|---------------------|----------------------|-----------------|
| **Risk per trade** | ₹5,000 (ignored) | 2% hardcoded | 2.5% from config |
| **Max deployed** | 50% (ignored) | 10% hardcoded | 10% from config |
| **Daily loss limit** | ₹15,000 (ignored) | None (no breaker) | 7.5% from config |
| **Hard cap lots** | None | 10 hardcoded | 10 from config |
| **Source of truth** | ❌ Multiple sources | ❌ Hardcoded | ✅ Single config |

---

## Real Trade Example Comparison

### BEFORE: Aug 13, 2024 Trade
```
Entry:
- Spot: ₹24,369
- Premium: ₹126.57 (BLACK-SCHOLES estimate)
- Lots: 1 (₹126.57 × 65 = ₹8,227 deployed = 41% of capital) ❌ Violates 10% limit!
- Capital: ₹20,000

Exit:
- Premium: ₹127.77 (BLACK-SCHOLES estimate)
- P&L: -₹78.14
- Capital: ₹19,921.86 (NOT SAVED - resets tomorrow) ❌
```

### AFTER: With All Fixes
```
Entry:
- Spot: ₹24,369
- Premium: ₹64.30 (REAL ASK from Upstox)
- Lots: 1 (₹64.30 × 65 = ₹4,179 deployed = 20.9% of ₹20K)
- Max risk check: ₹4,179 < 10% limit ✅
- Capital: ₹20,000
- Day-start capital: ₹20,000 (snapshot)

Exit:
- Premium: ₹63.85 (REAL BID from Upstox)
- P&L: -₹29.25 (actual bid-ask spread included)
- Capital: ₹19,970.75
- Saved to capital_state.json ✅
- Circuit breaker check: -₹29.25 < -₹1,500? No, keep trading ✅

Tomorrow:
- Capital loads as ₹19,970.75 (carries forward) ✅
- Position sizing scales to new capital ✅
```

---

## Summary: Key Improvements

| Feature | BEFORE | AFTER |
|---------|---------|--------|
| **Capital persistence** | ❌ Resets daily | ✅ Saves after every trade |
| **Compounding** | ❌ No growth | ✅ Automatic |
| **Position scaling** | ❌ Fixed 1 lot | ✅ Scales with capital |
| **Circuit breaker** | ❌ None | ✅ Auto-halts at 7.5% loss |
| **Config honored** | ❌ Ignored | ✅ Single source of truth |
| **Real premiums** | ❌ Fake (Black-Scholes) | ✅ Real (Upstox API) |
| **Bid-ask spread** | ❌ Not modeled | ✅ Included |
| **Risk management** | ❌ Hardcoded | ✅ Configurable |

---

## Expected Long-Term Impact

**Scenario: 60% Win Rate, ₹2K Avg Win, ₹1K Avg Loss**

**Without compounding (BEFORE):**
- Month 1: ₹20,000 → ₹30,000 (+50%)
- Month 2: ₹20,000 → ₹30,000 (+50%)
- Month 3: ₹20,000 → ₹30,000 (+50%)
- **Total: ₹30,000 final**

**With compounding (AFTER):**
- Month 1: ₹20,000 → ₹30,000 (+50%)
- Month 2: ₹30,000 → ₹45,000 (+50%)
- Month 3: ₹45,000 → ₹67,500 (+50%)
- **Total: ₹67,500 final (+125% more!)**

This is the power of compounding - the same win rate produces exponentially better results.

---

**Ready to implement?** This will make paper trading genuinely realistic and prepare you for live trading.
