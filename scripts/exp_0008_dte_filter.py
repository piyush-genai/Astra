"""
EXP-0008: DTE bucket filtering and sizing within ATR>30 universe.

From EXP-0007 FINDING-4: within ATR>30 filtered universe:
  DTE=0: avg +487 (35% WR)
  DTE=1: avg +1076 (40% WR)  ← strongest
  DTE=4: avg +301 (32% WR)
  DTE=5: avg +161 (26% WR)   ← weakest
  DTE=6: avg +463 (43% WR)   ← strong WR

Tests:
  A. Baseline:        ATR>30, all DTE buckets
  B. Drop DTE=5:      ATR>30, exclude DTE=5 (weakest)
  C. DTE=1 sizing 2x: ATR>30, all DTE, but DTE=1 gets 2x lots
  D. B+C combined:    ATR>30, no DTE=5, DTE=1 gets 2x lots
"""
import sys
sys.path.insert(0, '/workshop/atlas')

import logging, pandas as pd, numpy as np
from backtest.harness import BacktestHarness
from backtest.options_pricer import OptionsPricer, next_expiry
from core.config_loader import load_instruments, load_risk
from strategies.pivot_cpr_strategy import PivotCprStrategy
from core.engine.base_strategy import SignalDirection

logging.basicConfig(level=logging.WARNING)

instruments_cfg = load_instruments()
risk_cfg        = load_risk()
nifty_cfg       = instruments_cfg["instruments"]["NIFTY"]

df = pd.read_csv(
    'data/live_data/nifty_5min_20260201_to_20260731.csv',
    parse_dates=['timestamp'], index_col='timestamp',
)
df.index = pd.DatetimeIndex(df.index)
daily_ohlcv = df.resample("B").agg(
    open=("open","first"), high=("high","max"),
    low=("low","min"), close=("close","last"),
).dropna()

tr = pd.concat([
    df['high'] - df['low'],
    (df['high'] - df['close'].shift(1)).abs(),
    (df['low']  - df['close'].shift(1)).abs(),
], axis=1).max(axis=1)
df['atr10'] = tr.rolling(10).mean()

def dte_for(ts):
    d = ts.date()
    return next_expiry(d, 1).toordinal() - d.toordinal()

pricer = OptionsPricer(
    lot_size=nifty_cfg["lot_size"], expiry_weekday=nifty_cfg["weekly_expiry_weekday"],
    strike_step=nifty_cfg["strike_step"], iv=0.14,
)
brok    = instruments_cfg.get("transaction_costs", {}).get("brokerage_per_order", 20.0)
stt_pct = instruments_cfg.get("transaction_costs", {}).get("stt_options_pct", 0.15) / 100.0
lot_sz  = nifty_cfg["lot_size"]

# Pre-filter to ATR>30 universe
atr30 = df[df['atr10'].isna() | (df['atr10'] > 30)].copy()
atr30['dte'] = [dte_for(ts) for ts in atr30.index]

# Run backtest once, collect all trades with DTE
strategy = PivotCprStrategy(config={
    "tolerance_pct": 0.18, "min_levels_for_confluence": 2,
    "momentum_enabled": True, "momentum_body_pct": 0.50,
    "momentum_accel_multiplier": 1.8, "momentum_min_criteria": 2,
})
strategy._daily_ohlc = daily_ohlcv

harness = BacktestHarness(
    strategy=strategy, instruments_config=instruments_cfg,
    risk_config=risk_cfg, cooldown_minutes=0, allow_hedge=True,
    initial_capital=20_000.0,
)
result = harness.run(atr30[['open','high','low','close','volume']], pricer=pricer)

trade_rows = []
for t in result.trades:
    dirn = "LONG" if t.direction == SignalDirection.LONG else "SHORT"
    leg  = pricer.price_trade(dirn, t.entry_price, t.entry_time, t.exit_price, t.exit_time)
    gross = leg.pnl_rupees
    tc    = brok * 2 + leg.entry_premium * stt_pct * lot_sz + 5.0
    net   = gross - tc
    dte   = dte_for(t.entry_time)
    trade_rows.append({
        "month": t.entry_time.strftime("%Y-%m"),
        "dte": dte, "winner": t.pnl_points > 0,
        "net_pnl_1lot": round(net, 2),
    })

td = pd.DataFrame(trade_rows)

def simulate(df_trades, exclude_dte=None, boost_dte=None, boost_factor=2.0):
    rows = df_trades.copy()
    if exclude_dte is not None:
        rows = rows[~rows['dte'].isin(exclude_dte)]
    lots = rows['dte'].apply(
        lambda d: boost_factor if (boost_dte is not None and d in boost_dte) else 1.0
    )
    pnl     = (rows['net_pnl_1lot'] * lots).sum()
    trades  = len(rows)
    winners = (rows['winner']).sum()
    avg     = (rows['net_pnl_1lot'] * lots).mean()
    return {
        "final_capital": round(20_000 + pnl, 0),
        "return_pct":    round(pnl / 20_000 * 100, 1),
        "trades":        trades,
        "win_rate":      round(100 * winners / trades, 1) if trades else 0,
        "avg_pnl":       round(avg, 0),
        "total_pnl":     round(pnl, 0),
    }


configs = [
    ("A: Baseline (ATR>30, all DTE)",           dict()),
    ("B: Drop DTE=5",                            dict(exclude_dte=[5])),
    ("C: DTE=1 sizing 2x",                       dict(boost_dte=[1], boost_factor=2.0)),
    ("D: Drop DTE=5 + DTE=1 2x",                dict(exclude_dte=[5], boost_dte=[1], boost_factor=2.0)),
    ("E: Drop DTE=5 + DTE=1 2x + DTE=6 1.5x",  dict(exclude_dte=[5], boost_dte=[1, 6], boost_factor=2.0)),
]

print("=" * 75)
print("EXP-0008: DTE FILTER + SIZING WITHIN ATR>30 UNIVERSE")
print("=" * 75)
print()

results = {}
for label, kwargs in configs:
    r = simulate(td, **kwargs)
    results[label] = r
    print(f"  {label}")
    print(f"    ₹{r['final_capital']:>9,.0f}  ({r['return_pct']:+.1f}%)  "
          f"{r['trades']:3d} trades  WR={r['win_rate']:.1f}%  avg=₹{r['avg_pnl']:+,.0f}")
    print()

# Monthly breakdown for best configs
print("=" * 75)
print("MONTHLY BREAKDOWN (A vs D)")
print("=" * 75)
print(f"  {'Month':<10} {'A: baseline':>13} {'D: no-DTE5+1x2':>16} {'Lift':>8} {'DTE=5 trades':>14}")

for month in sorted(td['month'].unique()):
    seg    = td[td['month'] == month]
    a      = simulate(seg)
    d      = simulate(seg, exclude_dte=[5], boost_dte=[1], boost_factor=2.0)
    dte5_n = (seg['dte'] == 5).sum()
    lift   = d['total_pnl'] - a['total_pnl']
    print(f"  {month:<10} {a['total_pnl']:>+13,} {d['total_pnl']:>+16,} {lift:>+8,} {dte5_n:>14}")

# DTE=5 month distribution
print(f"\n  DTE=5 trade details:")
dte5 = td[td['dte'] == 5]
print(f"    Total: {len(dte5)} trades | avg ₹{dte5['net_pnl_1lot'].mean():+.0f} | "
      f"WR={100*dte5['winner'].mean():.0f}% | total ₹{dte5['net_pnl_1lot'].sum():+,.0f}")
for month in sorted(dte5['month'].unique()):
    seg = dte5[dte5['month'] == month]
    print(f"    {month}: {len(seg)} trades | avg ₹{seg['net_pnl_1lot'].mean():+.0f} | "
          f"WR={100*seg['winner'].mean():.0f}%")

# Verdict
print()
print("=" * 75)
print("VERDICT")
print("=" * 75)
base  = results["A: Baseline (ATR>30, all DTE)"]
best  = max(results.items(), key=lambda x: x[1]['return_pct'])
print(f"\n  Baseline: ₹{base['final_capital']:,.0f} ({base['return_pct']:+.1f}%)")
print(f"  Best cfg: {best[0]}")
print(f"            ₹{best[1]['final_capital']:,.0f} ({best[1]['return_pct']:+.1f}%)")

d_res = results["D: Drop DTE=5 + DTE=1 2x"]
print(f"\n  Config D (recommended): {d_res['return_pct']:+.1f}% vs {base['return_pct']:+.1f}% baseline")
print(f"    +{d_res['return_pct'] - base['return_pct']:.1f}pp improvement")
print(f"    Trades: {d_res['trades']} (dropped {base['trades'] - d_res['trades']} DTE=5 trades)")
print()
print("  CAVEAT: In-sample result — all findings from 6 months of data.")
print("  DTE=5 filter and DTE=1 sizing both need walk-forward validation.")
