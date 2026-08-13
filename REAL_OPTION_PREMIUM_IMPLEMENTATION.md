# Real Option Premium Implementation

## What Changed

### 1. New Method in Upstox Adapter
**File**: `src/broker/upstox_adapter.py`

Added `get_option_ltp()` method that:
- Constructs instrument key from (instrument, strike, option_type, expiry)
- Format: `NSE_FO|NIFTY13AUG2624350PE`
- Fetches real-time LTP from Upstox market-quote API

### 2. Updated Paper Trading Script
**File**: `scripts/run_paper.py`

**Entry Logic**:
1. Calculate ATM strike from spot price
2. **Call `adapter.get_option_ltp()` to fetch REAL premium**
3. Fallback to Black-Scholes if API fails
4. Use real premium for position sizing
5. Telegram shows "(REAL)" tag when real premium used

**Exit Logic**:
1. **Fetch REAL exit premium** from same contract
2. Calculate P&L from actual premium difference
3. No more estimation - actual market movement

### 3. Instrument Key Format
```python
# Format: NSE_FO|<SYMBOL><DD><MMM><YY><STRIKE><CE/PE>
# Example: NSE_FO|NIFTY13AUG2624350PE

# Built from:
instrument = "NIFTY"
strike = 24350
option_type = "PE"  
expiry = datetime(2026, 8, 13)

# Result: NSE_FO|NIFTY13AUG2624350PE
```

## Current Status

⚠️ **Analytics Token Issue Discovered**

The Upstox Analytics Token is returning 401 Unauthorized for market-quote endpoints. This could be:

1. **Token expired** - Analytics tokens have 1-year validity
2. **Endpoint access** - Token may not have market-quote permissions
3. **API version mismatch** - v2 vs v3 endpoint confusion

## Next Steps to Complete

### Option A: Fix Analytics Token (Recommended)
1. Check if Analytics Token in `.env` is still valid
2. Regenerate token from Upstox dashboard if expired
3. Verify token has market-quote access permissions

### Option B: Use OAuth Token Instead
1. The OAuth access token (for order placement) also has market data access
2. Would need daily authentication but guarantees access
3. More reliable for live trading anyway

### Option C: Hybrid Approach (Best for Production)
1. Try Analytics Token first (no daily auth needed)
2. Fallback to OAuth token if Analytics fails
3. Final fallback to Black-Scholes for backtesting compatibility

## Testing the Fix

Once token issue is resolved, run:

```bash
source venv/bin/activate
python scripts/test_real_option_ltp.py
```

Expected output:
```
✅ Found: NIFTY 13AUG26 24350 PE @ ₹126.50
```

## Benefits Once Working

### Before (Black-Scholes):
- Premium: **CALCULATED** at fixed IV=14%
- Reality: Could be 40-60% off on volatile days
- Position sizing: Based on fake premium
- P&L: Misleading

### After (Real LTP):
- Premium: **ACTUAL MARKET PRICE**
- Position sizing: Based on what you'd really pay
- P&L: Exact profit/loss as if you traded
- Paper trading = Real trading preview

## Code Changes Summary

**Modified Files:**
1. `src/broker/upstox_adapter.py` - Added `get_option_ltp()` method
2. `scripts/run_paper.py` - Entry/exit now fetch real premiums
3. `scripts/test_real_option_ltp.py` - New test script

**Backward Compatible:**
- Backtests still use Black-Scholes (no API calls)
- Paper trading falls back to Black-Scholes if API fails
- No changes needed to strategy or engine code

## Deployment Status

✅ Code committed and ready
⚠️ Needs Analytics Token verification
🔄 Once token fixed, ready for tomorrow's paper trading

---

**Next Action Required**: Check and update `UPSTOX_ANALYTICS_TOKEN` in `.env` file
