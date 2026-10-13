"""
EXP-0003: Range filter — trade only on days with prior-day range > 300 pts.
No look-ahead: uses PRIOR day's range as proxy (available at session open).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import pandas as pd
import numpy as np

from backtest.harness import BacktestHarness
from backtest.options_pricer import OptionsPricer
from core.config_loader import load_instruments, load_risk
from strategies.pivot_cpr_strategy import PivotCprStrategy
from core.engine.base_strategy import SignalDirection

logging.basicConfig(level=logging.WARNING)

instruments_cfg = load_instruments()
risk_cfg = load_risk()
nifty_cfg = instruments_cfg["instruments"]["NIFTY"]

df = pd.read_csv(
    'data/live_data/nifty_5min_20260201_to_20260731.csv',
    parse_dates=['timestamp'], index_col='timestamp',
)
df.index = pd.DatetimeIndex(df.index)
daily_ohlcv = df.resample("B").agg(
    open=("open","first"), high=("high","max"),
    low=("low","min"), close=("close","last"),
).dropna()

# Compute PRIOR-DAY range for each trading day (no look-ahead)
daily_ohlcv['range'] = daily_ohlcv['high'] - daily_ohlcv['low']
daily_ohlcv['prev_range'] = daily_ohlcv['range'].shift(1)  # yesterday's range

# For each 5-min bar, compute prior-day range
df['date'] = df.index.normalize()
prev_ranges = {}
for dt in daily_ohlcv.index:
    prev = daily_ohlcv['prev_range'].loc[dt]
    prev_ranges[dt] = prev

def get_prev_range(ts):
    day = ts.normalize()
    return prev_ranges.get(day, np.nan)

df['prev_day_range'] = [get_prev_range(ts) for ts in df.index]

RANGE_THRESHOLD = 300  # pts

months = [
    ("2026-02-01", "2026-02-28"),
    ("2026-03-01", "2026-03-31"),
    ("2026-04-01", "2026-04-30"),
    ("2026-05-01", "2026-05-31"),
    ("2026-06-01", "2026-06-30"),
    ("2026-07-01", "2026-07-31"),
]

pricer = OptionsPricer(lot_size=nifty_cfg["lot_size"], expiry_weekday=nifty_cfg["weekly_expiry_weekday"],
                        strike_step=nifty_cfg["strike_step"], iv=0.14)

results = {}
for label, threshold in [("BASELINE (no filter)", None), (f"RANGE_FILTER (>{RANGE_THRESHOLD}pts)", RANGE_THRESHOLD)]:
    strategy = PivotCprStrategy(config={
        "tolerance_pct": 0.18, "min_levels_for_confluence": 2,
        "momentum_enabled": True, "momentum_body_pct": 0.50,
        "momentum_accel_multiplier": 1.8, "momentum_min_criteria": 2,
    })
    strategy._daily_ohlc = daily_ohlcv

    capital = 20_000.0
    monthly_summary = []
    all_trades = []

    for start_str, end_str in months:
        start = pd.Timestamp(start_str, tz="Asia/Kolkata")
        end   = pd.Timestamp(end_str, tz="Asia/Kolkata") + pd.Timedelta(1, unit="D")
        month_data = df[(df.index >= start) & (df.index < end)].copy()

        if threshold is not None:
            # Filter: only include bars on days where PRIOR DAY range > threshold
            month_data = month_data[
                month_data['prev_day_range'].isna() |  # keep first day (no prior)
                (month_data['prev_day_range'] > threshold)
            ]

        if month_data.empty or len(month_data) < 100:
            monthly_summary.append({"month": start_str[:7], "start": capital, "end": capital, "trades": 0, "winners": 0})
            continue

        harness = BacktestHarness(
            strategy=strategy, instruments_config=instruments_cfg,
            risk_config=risk_cfg, cooldown_minutes=0, allow_hedge=True,
            initial_capital=capital,
        )
        result = harness.run(month_data[['open','high','low','close','volume']], pricer=pricer)
        end_capital = harness._current_capital
        winners = sum(1 for t in result.trades if t.pnl_points > 0)

        # Net P&L with options pricing
        tx_costs = instruments_cfg.get("transaction_costs", {})
        brokerage = tx_costs.get("brokerage_per_order", 20.0)
        stt_pct   = tx_costs.get("stt_options_pct", 0.15) / 100.0
        net_total = 0
        for t in result.trades:
            direction = "LONG" if t.direction == SignalDirection.LONG else "SHORT"
            leg = pricer.price_trade(direction=direction,
                                      entry_spot=t.entry_price, entry_time=t.entry_time,
                                      exit_spot=t.exit_price, exit_time=t.exit_time)
            gross = leg.pnl_rupees * t.lots
            tc = (brokerage*2 + leg.entry_premium*stt_pct*nifty_cfg["lot_size"] + 5.0) * t.lots
            net_total += gross - tc
            all_trades.append({
                "month": start_str[:7], "direction": direction, "lots": t.lots,
                "net_pnl": round(gross - tc, 2), "exit_reason": t.exit_reason,
            })

        monthly_summary.append({
            "month": start_str[:7], "start": capital, "end": end_capital,
            "trades": len(result.trades), "winners": winners,
        })
        capital = end_capital

    results[label] = {"summary": monthly_summary, "trades": all_trades, "final_capital": capital}

# ─── COMPARISON ──────────────────────────────────────────────────────────────
print("\n" + "="*80)
print("EXP-0003: RANGE FILTER COMPARISON")
print("="*80)

for label, r in results.items():
    sm = r["summary"]
    all_t = r["trades"]
    total_trades = sum(s["trades"] for s in sm)
    total_winners = sum(s["winners"] for s in sm)
    wr = 100 * total_winners / total_trades if total_trades else 0
    final = r["final_capital"]
    ret = (final - 20000) / 20000 * 100
    avg_pnl = sum(t["net_pnl"] for t in all_t) / len(all_t) if all_t else 0

    print(f"\n{'─'*60}")
    print(f"  {label}")
    print(f"{'─'*60}")
    print(f"  Final capital : ₹{final:,.0f} ({ret:+.1f}%)")
    print(f"  Total trades  : {total_trades}")
    print(f"  Win rate      : {wr:.1f}%")
    print(f"  Avg P&L/trade : ₹{avg_pnl:.0f}")
    print(f"  Monthly:")
    for s in sm:
        ret_m = (s['end'] - s['start']) / s['start'] * 100 if s['start'] else 0
        print(f"    {s['month']}: {s['trades']:3d} trades | ₹{s['start']:>9,.0f} → ₹{s['end']:>9,.0f} ({ret_m:+6.1f}%)")

# Days filtered out
print(f"\n── Days filtered out by range > {RANGE_THRESHOLD}pts ──")
for start_str, end_str in months:
    start = pd.Timestamp(start_str, tz="Asia/Kolkata")
    end   = pd.Timestamp(end_str, tz="Asia/Kolkata") + pd.Timedelta(1, unit="D")
    month_data = df[(df.index >= start) & (df.index < end)]
    trading_days = month_data.index.normalize().nunique()
    filtered_days = month_data[
        month_data['prev_day_range'].notna() &
        (month_data['prev_day_range'] <= RANGE_THRESHOLD)
    ].index.normalize().nunique()
    print(f"  {start_str[:7]}: {trading_days} total days, {filtered_days} filtered out ({100*filtered_days/trading_days:.0f}%)")
