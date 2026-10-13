"""
EXP-0007: ATR regime filter + near-expiry position sizing.

Baseline: ATR>30 filter (EXP-0006 validated, OOS avg +88%/month).
Hypothesis: trades where days_to_expiry==1 AND session==AFTERNOON have
            dramatically higher expected value (avg ₹2,803 vs ₹77 overall).
            Sizing up on these trades should improve overall returns.

Method: Run full 6-month backtest with ATR>30 filter. For each trade,
        compute days_to_expiry and session at entry time. Apply lot
        multiplier (1x, 1.5x, 2x, 3x) to near-expiry AFTERNOON trades.
        Compare risk-adjusted returns across multipliers.

Walk-forward note: building on already-validated ATR>30 base. The sizing
layer is an incremental adjustment; a separate OOS validation (EXP-0008)
will be needed before production.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

pricer = OptionsPricer(
    lot_size=nifty_cfg["lot_size"], expiry_weekday=nifty_cfg["weekly_expiry_weekday"],
    strike_step=nifty_cfg["strike_step"], iv=0.14,
)

brok    = instruments_cfg.get("transaction_costs", {}).get("brokerage_per_order", 20.0)
stt_pct = instruments_cfg.get("transaction_costs", {}).get("stt_options_pct", 0.15) / 100.0
lot_sz  = nifty_cfg["lot_size"]

SESSION_BOUNDS = {
    "MORNING_OPEN": (9 * 60 + 15, 9 * 60 + 55),
    "MID_MORNING":  (9 * 60 + 55, 12 * 60),
    "AFTERNOON":    (12 * 60, 14 * 60 + 30),
    "CLOSING":      (14 * 60 + 30, 15 * 60 + 30),
}

def session_for(ts):
    mins = ts.hour * 60 + ts.minute
    for name, (lo, hi) in SESSION_BOUNDS.items():
        if lo <= mins < hi:
            return name
    return "OTHER"

def days_to_next_expiry(ts):
    d = ts.date()
    exp = next_expiry(d, 1)
    return (exp.toordinal() - d.toordinal())


# ── Run ATR>30 filtered backtest once across full 6 months ────────────────────
print("Running ATR>30 filtered backtest (full 6-month)...")
strategy = PivotCprStrategy(config={
    "tolerance_pct": 0.18, "min_levels_for_confluence": 2,
    "momentum_enabled": True, "momentum_body_pct": 0.50,
    "momentum_accel_multiplier": 1.8, "momentum_min_criteria": 2,
})
strategy._daily_ohlc = daily_ohlcv

filtered = df[df['atr10'].isna() | (df['atr10'] > 30)]
harness = BacktestHarness(
    strategy=strategy, instruments_config=instruments_cfg,
    risk_config=risk_cfg, cooldown_minutes=0, allow_hedge=True,
    initial_capital=20_000.0,
)
result = harness.run(filtered[['open','high','low','close','volume']], pricer=pricer)
print(f"  Total trades: {len(result.trades)}")

# ── Enrich each trade with session, DTE, net P&L ─────────────────────────────
trade_rows = []
for t in result.trades:
    dirn = "LONG" if t.direction == SignalDirection.LONG else "SHORT"
    leg  = pricer.price_trade(dirn, t.entry_price, t.entry_time, t.exit_price, t.exit_time)
    gross_1lot = leg.pnl_rupees                               # per lot P&L (1 lot)
    tc_1lot    = brok * 2 + leg.entry_premium * stt_pct * lot_sz + 5.0
    net_1lot   = gross_1lot - tc_1lot

    dte  = days_to_next_expiry(t.entry_time)
    sess = session_for(t.entry_time)
    is_near_expiry_pm = (dte == 1 and sess == "AFTERNOON")

    trade_rows.append({
        "entry_time": t.entry_time,
        "direction": dirn,
        "lots_base": t.lots,
        "dte": dte,
        "session": sess,
        "near_expiry_pm": is_near_expiry_pm,
        "entry_premium": round(leg.entry_premium, 2),
        "exit_premium":  round(leg.exit_premium, 2),
        "net_pnl_1lot": round(net_1lot, 2),
        "winner": t.pnl_points > 0,
        "month": t.entry_time.strftime("%Y-%m"),
    })

td = pd.DataFrame(trade_rows)
print(f"  Near-expiry AFTERNOON trades: {td['near_expiry_pm'].sum()} "
      f"({100*td['near_expiry_pm'].mean():.1f}% of all trades)")
print()

# ── Segment analysis ──────────────────────────────────────────────────────────
print("=" * 70)
print("TRADE SEGMENTATION (ATR>30 filtered universe)")
print("=" * 70)

for seg_label, mask in [
    ("Near-expiry AFTERNOON (DTE=1, AFTERNOON)", td['near_expiry_pm']),
    ("Other trades",                              ~td['near_expiry_pm']),
    ("ALL trades",                                pd.Series([True]*len(td), index=td.index)),
]:
    seg = td[mask]
    if len(seg) == 0:
        continue
    wr  = 100 * seg['winner'].mean()
    avg = seg['net_pnl_1lot'].mean()
    tot = seg['net_pnl_1lot'].sum()
    print(f"\n  {seg_label}")
    print(f"    Count      : {len(seg)}")
    print(f"    Win rate   : {wr:.1f}%")
    print(f"    Avg P&L    : ₹{avg:+,.0f}/trade")
    print(f"    Total P&L  : ₹{tot:+,.0f}")
    print(f"    Avg premium: ₹{seg['entry_premium'].mean():.1f}")

# DTE breakdown
print(f"\n  DTE breakdown (ATR>30 filtered):")
for dte_val in sorted(td['dte'].unique()):
    s = td[td['dte'] == dte_val]
    print(f"    DTE={dte_val}: {len(s):3d} trades | "
          f"avg ₹{s['net_pnl_1lot'].mean():+6.0f}/trade | "
          f"WR={100*s['winner'].mean():.0f}% | "
          f"AFTERNOON: {s[s['session']=='AFTERNOON']['near_expiry_pm'].sum()}")

# ── Position sizing simulation ────────────────────────────────────────────────
print()
print("=" * 70)
print("POSITION SIZING SIMULATION")
print("=" * 70)
print("  Boost applies to: DTE=1, AFTERNOON trades only")
print("  All other trades: 1 lot (unchanged)")
print()

BOOST_FACTORS = [1.0, 1.5, 2.0, 3.0, 4.0]
sizing_results = []

for boost in BOOST_FACTORS:
    lots = td.apply(lambda r: boost if r['near_expiry_pm'] else 1.0, axis=1)
    pnl  = (td['net_pnl_1lot'] * lots).values
    capital = 20_000.0
    monthly_caps = {}
    for _, row in td.assign(lots_applied=lots).iterrows():
        capital += row['net_pnl_1lot'] * row['lots_applied']
        monthly_caps[row['month']] = capital

    total_pnl  = pnl.sum()
    final_cap  = 20_000.0 + total_pnl
    ret_pct    = (final_cap - 20_000.0) / 20_000.0 * 100
    n_near     = td['near_expiry_pm'].sum()
    near_pnl   = (td[td['near_expiry_pm']]['net_pnl_1lot'] * boost).sum()
    other_pnl  = td[~td['near_expiry_pm']]['net_pnl_1lot'].sum()

    # Drawdown estimate: max loss on a single near-expiry trade * boost
    max_loss_near = td[td['near_expiry_pm']]['net_pnl_1lot'].min()
    worst_loss    = max_loss_near * boost

    print(f"  Boost {boost:.1f}x")
    print(f"    Final capital : ₹{final_cap:>10,.0f}  ({ret_pct:+.1f}%)")
    print(f"    Near-expiry contribution: ₹{near_pnl:+,.0f} over {n_near} trades")
    print(f"    Other trades  : ₹{other_pnl:+,.0f}")
    print(f"    Worst single loss (near-expiry at {boost}x): ₹{worst_loss:,.0f}")
    print()

    sizing_results.append({
        "boost": boost, "final_capital": final_cap,
        "return_pct": ret_pct, "near_pnl": near_pnl,
        "worst_loss": worst_loss,
    })

# ── Month-by-month breakdown for 2x boost ─────────────────────────────────────
print("=" * 70)
print("MONTHLY BREAKDOWN — Baseline ATR>30 vs 2x Near-Expiry Boost")
print("=" * 70)
print(f"  {'Month':<10} {'No boost':>12} {'2x boost':>12} {'Lift':>10} {'Near-exp trades':>18}")

for month in sorted(td['month'].unique()):
    seg = td[td['month'] == month]
    cap_no   = seg['net_pnl_1lot'].sum()
    boost_2x = seg.apply(lambda r: r['net_pnl_1lot'] * (2.0 if r['near_expiry_pm'] else 1.0), axis=1).sum()
    n_near   = seg['near_expiry_pm'].sum()
    lift     = boost_2x - cap_no
    print(f"  {month:<10} {cap_no:>+12,.0f} {boost_2x:>+12,.0f} {lift:>+10,.0f} {n_near:>18}")

# ── Summary verdict ───────────────────────────────────────────────────────────
print()
print("=" * 70)
print("VERDICT")
print("=" * 70)
sr = pd.DataFrame(sizing_results)
baseline = sr[sr['boost'] == 1.0].iloc[0]
best     = sr.sort_values('return_pct', ascending=False).iloc[0]
print(f"\n  Baseline (1x): ₹{baseline['final_capital']:,.0f} ({baseline['return_pct']:+.1f}%)")
print(f"  Best boost   : {best['boost']:.1f}x → ₹{best['final_capital']:,.0f} ({best['return_pct']:+.1f}%)")
print(f"  Near-expiry trades: {td['near_expiry_pm'].sum()} out of {len(td)} ({100*td['near_expiry_pm'].mean():.1f}%)")
print()
two_x = sr[sr['boost'] == 2.0].iloc[0]
print(f"  Recommended: 2x boost")
print(f"    Return: {two_x['return_pct']:+.1f}% vs {baseline['return_pct']:+.1f}% baseline")
print(f"    Worst near-expiry loss at 2x: ₹{two_x['worst_loss']:,.0f}")
print()
print("  CAVEAT: This is in-sample. Near-expiry AFTERNOON trades are rare")
print("  (~3-5/month) — small-sample. EXP walk-forward required before")
print("  applying variable sizing in production.")
