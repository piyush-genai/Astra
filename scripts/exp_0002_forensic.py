"""
EXP-0002: March 2026 forensic analysis.
Runs the corrected backtest and captures detailed per-trade data for analysis.
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
lot_size = nifty_cfg["lot_size"]
expiry_wd = nifty_cfg["weekly_expiry_weekday"]
strike_step = nifty_cfg["strike_step"]

df = pd.read_csv(
    'data/live_data/nifty_5min_20260201_to_20260731.csv',
    parse_dates=['timestamp'], index_col='timestamp',
)
df.index = pd.DatetimeIndex(df.index)
daily_ohlcv = df.resample("B").agg(
    open=("open","first"), high=("high","max"),
    low=("low","min"), close=("close","last"),
).dropna()

strategy = PivotCprStrategy(config={
    "tolerance_pct": 0.18, "min_levels_for_confluence": 2,
    "momentum_enabled": True, "momentum_body_pct": 0.50,
    "momentum_accel_multiplier": 1.8, "momentum_min_criteria": 2,
})
strategy._daily_ohlc = daily_ohlcv

pricer = OptionsPricer(lot_size=lot_size, expiry_weekday=expiry_wd,
                        strike_step=strike_step, iv=0.14)

months = [
    ("2026-02-01", "2026-02-28"),
    ("2026-03-01", "2026-03-31"),
    ("2026-04-01", "2026-04-30"),
    ("2026-05-01", "2026-05-31"),
    ("2026-06-01", "2026-06-30"),
    ("2026-07-01", "2026-07-31"),
]

all_trade_records = []
capital = 20_000.0
tx_costs = instruments_cfg.get("transaction_costs", {})
brokerage = tx_costs.get("brokerage_per_order", 20.0)
stt_pct   = tx_costs.get("stt_options_pct", 0.15) / 100.0

for start_str, end_str in months:
    start = pd.Timestamp(start_str, tz="Asia/Kolkata")
    end   = pd.Timestamp(end_str, tz="Asia/Kolkata") + pd.Timedelta(1, unit="D")
    month_data = df[(df.index >= start) & (df.index < end)]
    if month_data.empty:
        continue

    harness = BacktestHarness(
        strategy=strategy, instruments_config=instruments_cfg,
        risk_config=risk_cfg, cooldown_minutes=0, allow_hedge=True,
        initial_capital=capital,
    )
    result = harness.run(month_data, pricer=pricer)

    for t in result.trades:
        direction = "LONG" if t.direction == SignalDirection.LONG else "SHORT"
        signal_type = t.signal.metadata.get("signal_type", "regular")
        setup = t.signal.metadata["setup"]
        zone = setup.zone

        leg = pricer.price_trade(
            direction=direction,
            entry_spot=t.entry_price, entry_time=t.entry_time,
            exit_spot=t.exit_price,  exit_time=t.exit_time,
        )
        gross_pnl = leg.pnl_rupees * t.lots
        tx_cost = (brokerage*2 + leg.entry_premium*stt_pct*lot_size + 5.0) * t.lots
        net_pnl = gross_pnl - tx_cost

        # Weekly context: which expiry week?
        entry_date = t.entry_time.date()
        from backtest.options_pricer import next_expiry
        expiry = next_expiry(entry_date, expiry_wd)
        days_to_expiry = (expiry - entry_date).days

        # Daily ATR context
        day_data = month_data[month_data.index.date == entry_date]
        if not day_data.empty:
            day_range = float(day_data['high'].max() - day_data['low'].min())
        else:
            day_range = 0

        hold_min = (t.exit_time - t.entry_time).total_seconds() / 60
        hour = t.entry_time.hour

        all_trade_records.append({
            "month": start_str[:7],
            "entry_date": str(entry_date),
            "entry_time": str(t.entry_time),
            "direction": direction,
            "signal_type": signal_type,
            "exit_reason": t.exit_reason,
            "lots": t.lots,
            "entry_spot": round(t.entry_price, 2),
            "exit_spot": round(t.exit_price, 2),
            "entry_premium": round(leg.entry_premium, 2),
            "exit_premium": round(leg.exit_premium, 2),
            "hold_minutes": round(hold_min, 1),
            "net_pnl": round(net_pnl, 2),
            "pnl_points": round(t.pnl_points, 2),
            "days_to_expiry": days_to_expiry,
            "day_range": round(day_range, 1),
            "session": (
                "MORNING_OPEN" if 9 <= hour < 10 else
                "MID_MORNING" if 10 <= hour < 13 else
                "AFTERNOON" if 13 <= hour < 15 else "CLOSING"
            ),
            "zone_type": (
                "CONFLUENCE" if zone.is_confluence else
                "DAILY_CPR"  if zone.is_daily_cpr_only else
                "STRONG_SINGLE" if zone.is_strong_single_level else "OTHER"
            ),
            "zone_width": round(zone.price_high - zone.price_low, 2),
            "start_capital": round(capital, 2),
        })

    capital = harness._current_capital

trades = pd.DataFrame(all_trade_records)
trades.to_csv("data/backtest_results/exp_0002_corrected_trades.csv", index=False)
print(f"Saved {len(trades)} trade records")

# ─── ANALYSIS ────────────────────────────────────────────────────────────────

print("\n" + "="*70)
print("EXP-0002: MARCH 2026 FORENSIC ANALYSIS")
print("="*70)

march  = trades[trades['month'] == '2026-03']
others = trades[trades['month'] != '2026-03']

print(f"\n{'':40} {'March':>10} {'Others avg':>12}")
print("-"*65)
print(f"{'Trades':40} {len(march):>10} {len(others)/5:>12.1f}")
print(f"{'Win rate (net pnl > 0)':40} {100*len(march[march.net_pnl>0])/len(march):>9.1f}% {100*len(others[others.net_pnl>0])/len(others):>11.1f}%")
print(f"{'Avg net P&L per trade (₹)':40} {march.net_pnl.mean():>10.0f} {others.net_pnl.mean():>12.0f}")
print(f"{'Avg lots per trade':40} {march.lots.mean():>10.1f} {others.lots.mean():>12.1f}")
print(f"{'Avg entry premium (₹)':40} {march.entry_premium.mean():>10.1f} {others.entry_premium.mean():>12.1f}")
print(f"{'Avg hold time (minutes)':40} {march.hold_minutes.mean():>10.1f} {others.hold_minutes.mean():>12.1f}")
print(f"{'Avg day range (pts)':40} {march.day_range.mean():>10.0f} {others.day_range.mean():>12.0f}")

print("\n── Direction split ──")
for col, d in [('March', march), ('Others', others)]:
    longs  = d[d.direction=='LONG']
    shorts = d[d.direction=='SHORT']
    print(f"  {col}: LONG {len(longs)} trades ₹{longs.net_pnl.sum():+,.0f} | "
          f"SHORT {len(shorts)} trades ₹{shorts.net_pnl.sum():+,.0f}")

print("\n── Session breakdown (March) ──")
for sess, grp in march.groupby('session'):
    print(f"  {sess:<18} {len(grp):3d} trades | P&L ₹{grp.net_pnl.sum():+,.0f} | "
          f"avg ₹{grp.net_pnl.mean():+,.0f}/trade | WR {100*len(grp[grp.net_pnl>0])/len(grp):.0f}%")

print("\n── Days-to-expiry breakdown (March) ──")
march['expiry_bucket'] = march.days_to_expiry.apply(
    lambda d: "expiry_day(0)" if d==0 else
              "1_day_out" if d==1 else
              "2_3_days"  if d<=3 else "4+_days"
)
for bkt, grp in march.groupby('expiry_bucket'):
    print(f"  {bkt:<20} {len(grp):3d} trades | P&L ₹{grp.net_pnl.sum():+,.0f} | "
          f"avg prem ₹{grp.entry_premium.mean():.1f}")

print("\n── Weekly breakdown (March) ──")
march_dates = pd.to_datetime(march['entry_date'])
march['iso_week'] = march_dates.dt.isocalendar().week.values
for wk, grp in march.groupby('iso_week'):
    # Rough date range
    first = grp.entry_date.min()[5:]  # MM-DD
    last  = grp.entry_date.max()[5:]
    print(f"  Week {wk} ({first}→{last}): {len(grp):3d} trades | P&L ₹{grp.net_pnl.sum():+,.0f} | "
          f"WR {100*len(grp[grp.net_pnl>0])/len(grp):.0f}%")

print("\n── Day-range buckets (when profitable vs not) ──")
print("  (Does high daily range = better P&L?)")
all_m = trades.copy()
all_m['range_bucket'] = pd.cut(all_m.day_range, bins=[0,200,300,400,600,2000],
                                labels=['<200','200-300','300-400','400-600','>600'])
rb = all_m.groupby('range_bucket').agg(
    trades=('net_pnl','count'),
    total_pnl=('net_pnl','sum'),
    avg_pnl=('net_pnl','mean'),
    win_rate=('net_pnl', lambda x: 100*(x>0).mean()),
).round(0)
print(rb.to_string())

print("\n── Zone type breakdown (March) ──")
for zt, grp in march.groupby('zone_type'):
    print(f"  {zt:<20} {len(grp):3d} trades | P&L ₹{grp.net_pnl.sum():+,.0f} | "
          f"WR {100*len(grp[grp.net_pnl>0])/len(grp):.0f}%")

print("\n── Top 10 March trades ──")
top10 = march.nlargest(10, 'net_pnl')[
    ['entry_date','direction','lots','entry_premium','exit_premium',
     'net_pnl','hold_minutes','session','days_to_expiry','zone_type']]
print(top10.to_string(index=False))

print(f"\n── Bottom 10 March trades ──")
bot10 = march.nsmallest(10, 'net_pnl')[
    ['entry_date','direction','lots','entry_premium','exit_premium',
     'net_pnl','hold_minutes','days_to_expiry']]
print(bot10.to_string(index=False))
