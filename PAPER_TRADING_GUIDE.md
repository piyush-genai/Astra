# 📝 Paper Trading Guide

## What is Paper Trading?

Paper trading runs your strategy with **real-time market data** but with **simulated orders** (no real money). This validates that:

1. ✅ Strategy works in live market conditions
2. ✅ Data fetching is reliable during market hours
3. ✅ Signal generation happens fast enough
4. ✅ Position sizing logic works correctly
5. ✅ You can handle the emotional aspect of trading

---

## Prerequisites

Before starting paper trading, ensure:

- [x] Unit tests passing (44 tests ✅)
- [x] Backtest completed (₹20K → ₹825K ✅)
- [x] Strategy documented in `CURRENT_STRATEGY.md` ✅
- [ ] **Paper trading for 2-4 weeks** ← YOU ARE HERE
- [ ] Move to live trading with small capital

---

## How to Run Paper Trading

### Step 1: Activate Virtual Environment

```bash
cd /home/piyush/workspace/trading/atlas
source venv/bin/activate
```

### Step 2: Start Paper Trading Session

**Full trading day (9:15 AM - 3:30 PM):**
```bash
python scripts/run_paper.py
```

**Custom duration (e.g., 2 hours):**
```bash
python scripts/run_paper.py --duration 120
```

**With custom implied volatility:**
```bash
python scripts/run_paper.py --iv 16.0
```

### Step 3: Monitor the Session

The script will:
- Fetch 1-min bars from Upstox every 30 seconds
- Resample to 5-min bars
- Check for signals
- Manage open positions with trailing stops
- Log all activity to console
- Save trades to CSV when done

**Sample Output:**
```
2026-08-05 09:20:15 INFO: Paper Trading Engine initialized with ₹20000.00 capital
2026-08-05 09:20:30 INFO: Processing bar: 2026-08-05 09:20:00+05:30 | Close=24950.25
2026-08-05 09:25:45 INFO: 📈 PAPER ENTRY: LONG 1 lots @ ₹24955.30 | Premium=₹145.50 | Stop=₹24920.00 | Capital=₹20000.00
2026-08-05 09:40:10 INFO: 📉 PAPER EXIT: LONG | P&L=₹-485.25 (-5.1%) | Reason=stop | Hold=14.4min | Capital=₹19514.75
```

### Step 4: Stop Paper Trading

- Press **Ctrl+C** to stop gracefully
- Script will close any open position
- Results auto-saved to `paper_trades_YYYYMMDD_HHMMSS.csv`

---

## What Gets Logged

### Console Logs:
- Real-time bar processing (price, time)
- Entry signals with lots, premium, stop level
- Exit signals with P&L, exit reason, hold time
- Position management (trailing stop updates)
- Cooldown suppressions

### CSV Output (`paper_trades_*.csv`):
| Column | Description |
|--------|-------------|
| `exit_time` | When trade exited |
| `signal_type` | "momentum" or "regular" |
| `direction` | "LONG" or "SHORT" |
| `entry_price` | Nifty spot price at entry |
| `exit_price` | Nifty spot price at exit |
| `entry_premium` | Option premium paid |
| `exit_premium` | Option premium received |
| `lots` | Number of lots traded |
| `gross_pnl` | P&L before costs (₹) |
| `tx_cost` | Transaction costs (₹) |
| `net_pnl` | Net P&L after costs (₹) |
| `exit_reason` | "stop", "structural", "eod" |
| `hold_minutes` | How long position held |
| `capital_after` | Capital after this trade |

---

## Daily Routine

### Before Market Open (9:00 AM):
1. Start paper trading script
2. Verify Analytics Token is valid
3. Check internet connection
4. Have notepad ready for observations

### During Market Hours:
1. **Don't interfere** - let the script run
2. Observe how signals are generated
3. Note any unusual behavior
4. Watch how stops are managed

### After Market Close:
1. Review the CSV output
2. Compare to backtest expectations:
   - Win rate should be ~25%
   - Avg trades/day should be ~10
   - P&L pattern similar to backtest
3. Note any concerns for next day

---

## Success Criteria

Paper trading is successful if, after 2-4 weeks:

### Quantitative Checks:
- ✅ **Win rate**: 20-30% (similar to backtest 25.4%)
- ✅ **Trade frequency**: 8-12 trades/day (backtest: 9.9)
- ✅ **Signal types**: ~95% momentum, ~5% regular
- ✅ **No crashes** - script runs full day without errors
- ✅ **P&L reasonable** - Not making/losing wildly different from backtest

### Qualitative Checks:
- ✅ **You're comfortable** watching real-time losses
- ✅ **No urge to intervene** when strategy takes losses
- ✅ **Trust the system** - you don't want to "improve" it mid-session
- ✅ **Data reliability** - Upstox API performs well during market hours

---

## Common Issues & Solutions

### Issue 1: "Analytics Token expired"
**Solution**: Regenerate token on Upstox developer portal, update `.env` file

### Issue 2: "Insufficient history"
**Solution**: Wait 5-10 minutes after market open for enough bars to accumulate

### Issue 3: "No trades executed"
**Solution**: 
- Check if market is volatile enough (strategy needs breakouts)
- Verify strategy config matches `CURRENT_STRATEGY.md`
- Some days naturally have fewer signals

### Issue 4: Script stops unexpectedly
**Solution**:
- Check internet connection
- Verify Upstox API is working (check their status page)
- Look at error logs in terminal

### Issue 5: Too many trades (>15/day)
**Solution**:
- Check if cooldown is working (should be 15 min)
- Verify position limits (1 position max)
- May indicate high volatility day (normal)

---

## Paper Trading Checklist

Use this checklist for each day of paper trading:

### Daily Log Template:

```
Date: _____________________
Market Open: Nifty at _______
Market Close: Nifty at _______

Trades Executed: _____
Winners / Losers: _____ / _____
Net P&L: ₹_______
Ending Capital: ₹_______

Signal Types:
- Momentum: _____
- Regular: _____

Issues Observed:
- [ ] None
- [ ] Data delays
- [ ] Unexpected exits
- [ ] Signal generation issues
- [ ] Other: __________________

Notes:
_________________________________
_________________________________
_________________________________

Ready for Next Day: ☐ Yes ☐ No
```

---

## After 2-4 Weeks

### If Paper Trading is Successful:
1. Update `run_live.py` gate status:
   ```python
   GATE_STATUS = {
       "pivot_cpr": {
           "unit_tests_passed": True,
           "backtest_passed": True,
           "paper_trading_completed": True,  # ← Update this
       }
   }
   ```

2. Move to **Live Trading**:
   - Start with ₹20-50K (same as backtest)
   - Set up daily loss circuit breaker
   - Configure manual kill switch (Telegram)
   - Register Algo-ID with broker

### If Paper Trading Shows Issues:
- Document what went wrong
- Fix the issues
- Restart paper trading for another 2-4 weeks
- **Do NOT skip this gate**

---

## Next Steps

Once paper trading passes all checks:

1. [ ] Set up Telegram bot for alerts
2. [ ] Implement daily loss circuit breaker
3. [ ] Configure Algo-ID with Upstox
4. [ ] Test manual kill switch
5. [ ] Start live trading with small capital

---

**Remember**: Paper trading is the final safety check before risking real money. Take it seriously. It's better to find issues now than lose capital later.

**Questions?** Review `CURRENT_STRATEGY.md` for strategy details or check steering files in `.kiro/steering/`
