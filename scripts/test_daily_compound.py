#!/usr/bin/env python3
import os, sys
sys.path.insert(0, '/home/piyush/workspace/trading/atlas')
os.chdir('/home/piyush/workspace/trading/atlas')

from dotenv import load_dotenv
from src.backtest.harness import BacktestHarness
from src.backtest.options_pricer import OptionsPricer
from src.strategies.pivot_cpr_strategy import PivotCprStrategy
from src.broker.upstox_adapter import UpstoxAdapter
from src.config_loader import load_instruments
import pandas as pd
import logging

load_dotenv()
logging.basicConfig(level=logging.INFO)

instruments_cfg = load_instruments()
nifty = instruments_cfg["instruments"]["NIFTY"]

strategy = PivotCprStrategy(config={
    "tolerance_pct": 0.18,
    "min_levels_for_confluence": 2,
    "momentum_enabled": True,
    "momentum_body_pct": 0.50,
    "momentum_accel_multiplier": 1.8,
    "momentum_min_criteria": 2,
})

pricer = OptionsPricer(
    lot_size=nifty["lot_size"],
    expiry_weekday=nifty["weekly_expiry_weekday"],
    strike_step=nifty["strike_step"],
    iv=0.14,
)

adapter = UpstoxAdapter(config={
    "api_key": "", "api_secret": "", "redirect_uri": "",
    "analytics_token": os.environ["UPSTOX_ANALYTICS_TOKEN"],
    "sandbox": True,
})

# Fetch 6 months
print("Fetching 6 months...")
all_data = []
for start, end in [
    ("2026-02-01", "2026-02-28"),
    ("2026-03-01", "2026-03-31"),
    ("2026-04-01", "2026-04-30"),
    ("2026-05-01", "2026-05-31"),
    ("2026-06-01", "2026-06-30"),
    ("2026-07-01", "2026-07-31"),
]:
    print(f"  {start}")
    df = adapter.get_ohlcv("NSE_INDEX|Nifty 50", "1minute", start, end)
    if df is not None and not df.empty:
        all_data.append(df)

ohlcv_1min = pd.concat(all_data).sort_index()
ohlcv_5min = ohlcv_1min.resample("5min").agg({
    "open":"first","high":"max","low":"min","close":"last","volume":"sum"
}).dropna(subset=["open"])

print(f"\nTotal: {len(ohlcv_5min)} bars")

# Run continuous backtest (daily compounding)
harness = BacktestHarness(
    strategy=strategy,
    instruments_config=instruments_cfg,
    cooldown_minutes=0,
    allow_hedge=True,
    initial_capital=20000.0,
    risk_per_trade_pct=2.0,
    max_capital_deployed_pct=10.0,
    max_lots_per_trade=10,
)

result = harness.run(ohlcv_5min, pricer=pricer)

if not result.trades:
    print("No trades")
    sys.exit(0)

# Calculate results
ending = harness._current_capital
net_pnl = ending - 20000
ret = (net_pnl / 20000) * 100
winners = sum(1 for t in result.trades if t.pnl_points > 0)

print("\n" + "="*80)
print("DAILY COMPOUNDING (Feb-Jul 2026)")
print("="*80)
print(f"Starting: ₹20,000")
print(f"Ending:   ₹{ending:,.2f}")
print(f"P&L:      ₹{net_pnl:+,.2f} ({ret:+.1f}%)")
print(f"Trades:   {len(result.trades)} ({winners} winners, {(winners/len(result.trades))*100:.1f}% WR)")
print(f"\nVS MONTHLY: ₹856,926 (+4,185%)")
print("="*80)
