"""
EXP-0001: Reproduce ATLAS baseline backtest using cached CSV data + current code.
No API calls needed — uses cached nifty_5min_20260201_to_20260731.csv.
"""
import sys
sys.path.insert(0, '/workshop/atlas')

import logging
import pandas as pd

from backtest.harness import BacktestHarness
from backtest.options_pricer import OptionsPricer
from core.config_loader import load_instruments, load_risk
from strategies.pivot_cpr_strategy import PivotCprStrategy

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

instruments_cfg = load_instruments()
risk_cfg = load_risk()
nifty_cfg = instruments_cfg["instruments"]["NIFTY"]
lot_size = nifty_cfg["lot_size"]
expiry_wd = nifty_cfg["weekly_expiry_weekday"]
strike_step = nifty_cfg["strike_step"]

print("Loading cached 5-min NIFTY data...")
df = pd.read_csv(
    '/workshop/atlas/data/live_data/nifty_5min_20260201_to_20260731.csv',
    parse_dates=['timestamp'],
    index_col='timestamp',
)
df.index = pd.DatetimeIndex(df.index)
print(f"Loaded {len(df)} bars: {df.index[0]} to {df.index[-1]}")

# Daily OHLCV for pivot calculation
daily_ohlcv = df.resample("B").agg(
    open=("open", "first"),
    high=("high", "max"),
    low=("low", "min"),
    close=("close", "last"),
).dropna(subset=["open"])
print(f"Daily bars for pivots: {len(daily_ohlcv)}")

strategy_config = {
    "tolerance_pct": 0.18,
    "min_levels_for_confluence": 2,
    "momentum_enabled": True,
    "momentum_body_pct": 0.50,
    "momentum_accel_multiplier": 1.8,
    "momentum_min_criteria": 2,
}

strategy = PivotCprStrategy(config=strategy_config)
strategy._daily_ohlc = daily_ohlcv

pricer = OptionsPricer(
    lot_size=lot_size,
    expiry_weekday=expiry_wd,
    strike_step=strike_step,
    iv=0.14,
)

months = [
    ("2026-02-01", "2026-02-28"),
    ("2026-03-01", "2026-03-31"),
    ("2026-04-01", "2026-04-30"),
    ("2026-05-01", "2026-05-31"),
    ("2026-06-01", "2026-06-30"),
    ("2026-07-01", "2026-07-31"),
]

capital = 20_000.0
month_results = []

for start_str, end_str in months:
    start = pd.Timestamp(start_str, tz="Asia/Kolkata")
    end   = pd.Timestamp(end_str, tz="Asia/Kolkata") + pd.Timedelta(days=1)
    month_data = df[(df.index >= start) & (df.index < end)]

    if month_data.empty:
        print(f"  {start_str[:7]}: No data")
        continue

    harness = BacktestHarness(
        strategy=strategy,
        instruments_config=instruments_cfg,
        risk_config=risk_cfg,
        cooldown_minutes=0,
        allow_hedge=True,
        initial_capital=capital,
    )

    result = harness.run(month_data, pricer=pricer)
    end_capital = harness._current_capital
    pnl = end_capital - capital
    ret_pct = pnl / capital * 100
    winners = sum(1 for t in result.trades if t.pnl_points > 0)
    mom = sum(1 for t in result.trades if t.signal.metadata.get("signal_type") == "momentum")

    month_results.append({
        "month": start_str[:7],
        "start": capital,
        "end": end_capital,
        "trades": len(result.trades),
        "winners": winners,
        "pnl": pnl,
        "ret_pct": ret_pct,
        "mom": mom,
        "reg": len(result.trades) - mom,
    })

    print(f"  {start_str[:7]}: {len(result.trades):4d} trades | W={winners}/{len(result.trades)-winners} | "
          f"₹{capital:>10,.0f} → ₹{end_capital:>10,.0f} ({ret_pct:+7.1f}%)")

    capital = end_capital

total_trades  = sum(r["trades"]  for r in month_results)
total_winners = sum(r["winners"] for r in month_results)

print()
print("=" * 70)
print("EXP-0001: REPRODUCED RESULT (current code, baseline config, IV=14%)")
print("=" * 70)
print(f"  Starting capital : ₹20,000")
print(f"  Ending capital   : ₹{capital:,.0f}")
print(f"  Total return     : {(capital-20000)/20000*100:+.1f}%")
print(f"  Total trades     : {total_trades}")
print(f"  Win rate         : {100*total_winners/total_trades:.1f}%")
print()
print("  USER-REPORTED   : ₹20,000 → ₹8,25,266 (+4,026%) | 1,302 trades | 25.4% WR")
print("  OLD CSV (buggy) : ₹20,000 → ₹8,56,926 (+4,185%) | 1,772 trades | 24.3% WR")
