"""
EXP-0009: Multi-year walk-forward validation of ATR>30 regime filter.

Uses the new 2023-2025 dataset (DATA-001) to answer the critical question:
  Does ATR>30 outperform unfiltered baseline across 3 years and multiple
  distinct market regimes — not just the 6-month Feb-Jul 2026 window?

Protocol:
  Monthly expanding walk-forward across all 36 months (Jan 2023 → Dec 2025).
  Each month: test ATR>30 filtered vs unfiltered baseline on that month's data.
  Report: win rate across months, consistency by market regime (ATR level).

Pass criterion: ATR>30 beats baseline in >= 65% of months (23 of 36).
"""
import sys
sys.path.insert(0, '/workshop/atlas')

import logging, pandas as pd, numpy as np
from pathlib import Path
from backtest.harness import BacktestHarness
from backtest.options_pricer import OptionsPricer
from core.config_loader import load_instruments, load_risk
from strategies.pivot_cpr_strategy import PivotCprStrategy
from core.engine.base_strategy import SignalDirection

logging.basicConfig(level=logging.WARNING)

DATA_PATH = Path("data/live_data/nifty_5min_20230101_to_20251231.csv")
if not DATA_PATH.exists():
    sys.exit(f"Missing {DATA_PATH} — run data_001_fetch_historical.py first.")

instruments_cfg = load_instruments()
risk_cfg        = load_risk()
nifty_cfg       = instruments_cfg["instruments"]["NIFTY"]

df = pd.read_csv(DATA_PATH, parse_dates=["timestamp"], index_col="timestamp")
df.index = pd.DatetimeIndex(df.index)

daily_ohlcv = df.resample("B").agg(
    open=("open","first"), high=("high","max"),
    low=("low","min"), close=("close","last"),
).dropna()

# Pre-compute ATR on full dataset (no look-ahead — only past 10 bars)
tr = pd.concat([
    df["high"] - df["low"],
    (df["high"] - df["close"].shift(1)).abs(),
    (df["low"]  - df["close"].shift(1)).abs(),
], axis=1).max(axis=1)
df["atr10"] = tr.rolling(10).mean()

pricer = OptionsPricer(
    lot_size=nifty_cfg["lot_size"], expiry_weekday=nifty_cfg["weekly_expiry_weekday"],
    strike_step=nifty_cfg["strike_step"], iv=0.14,
)
brok    = instruments_cfg.get("transaction_costs", {}).get("brokerage_per_order", 20.0)
stt_pct = instruments_cfg.get("transaction_costs", {}).get("stt_options_pct", 0.15) / 100.0
lot_sz  = nifty_cfg["lot_size"]


def run_month(month_data: pd.DataFrame, atr_thresh, initial_capital: float) -> dict:
    filtered = month_data.copy()
    if atr_thresh is not None:
        filtered = filtered[filtered["atr10"].isna() | (filtered["atr10"] > atr_thresh)]

    if len(filtered) < 30:
        return {"capital": initial_capital, "trades": 0, "net_pnl": 0.0,
                "return_pct": 0.0, "avg_pnl": 0.0, "win_rate": 0.0}

    strategy = PivotCprStrategy(config={
        "tolerance_pct": 0.18, "min_levels_for_confluence": 2,
        "momentum_enabled": True, "momentum_body_pct": 0.50,
        "momentum_accel_multiplier": 1.8, "momentum_min_criteria": 2,
    })
    strategy._daily_ohlc = daily_ohlcv

    harness = BacktestHarness(
        strategy=strategy, instruments_config=instruments_cfg,
        risk_config=risk_cfg, cooldown_minutes=0, allow_hedge=True,
        initial_capital=initial_capital,
    )
    result = harness.run(filtered[["open","high","low","close","volume"]], pricer=pricer)
    end_capital = harness._current_capital

    net_total, winners = 0.0, 0
    for t in result.trades:
        dirn = "LONG" if t.direction == SignalDirection.LONG else "SHORT"
        leg  = pricer.price_trade(dirn, t.entry_price, t.entry_time, t.exit_price, t.exit_time)
        gross = leg.pnl_rupees
        tc    = brok * 2 + leg.entry_premium * stt_pct * lot_sz + 5.0
        net_total += gross - tc
        if t.pnl_points > 0:
            winners += 1

    n = len(result.trades)
    return {
        "capital":     end_capital,
        "trades":      n,
        "net_pnl":     round(net_total, 2),
        "return_pct":  round((end_capital - initial_capital) / initial_capital * 100, 2),
        "avg_pnl":     round(net_total / n, 2) if n else 0.0,
        "win_rate":    round(100 * winners / n, 1) if n else 0.0,
    }


# ── Generate all months ────────────────────────────────────────────────────────
from dateutil.relativedelta import relativedelta
from datetime import date

months = []
cur = date(2023, 1, 1)
while cur <= date(2025, 12, 1):
    months.append(cur.strftime("%Y-%m"))
    cur += relativedelta(months=1)

print("=" * 80)
print("EXP-0009: MULTI-YEAR ATR FILTER VALIDATION  (Jan 2023 → Dec 2025)")
print("=" * 80)
print(f"  {'Month':<10} {'ATR_avg':>8} {'Baseline':>10} {'ATR>30':>10} {'Beats?':>7} "
      f"{'B_trades':>9} {'F_trades':>9} {'F_avg_pnl':>10}")
print("-" * 80)

results = []
INITIAL  = 20_000.0

for month_str in months:
    ts_start = pd.Timestamp(f"{month_str}-01", tz="Asia/Kolkata")
    ts_end   = ts_start + pd.DateOffset(months=1)
    month_df = df[(df.index >= ts_start) & (df.index < ts_end)]

    if len(month_df) < 100:
        continue

    avg_atr = month_df["atr10"].mean()
    base  = run_month(month_df, None,  INITIAL)
    filt  = run_month(month_df, 30,    INITIAL)
    beats = filt["return_pct"] > base["return_pct"]

    # ATR regime label
    if avg_atr > 30:
        regime = "HIGH"
    elif avg_atr > 20:
        regime = "MED"
    else:
        regime = "LOW"

    print(f"  {month_str:<10} {avg_atr:>7.1f}  {base['return_pct']:>+9.1f}% "
          f"{filt['return_pct']:>+9.1f}% {'✓' if beats else '✗':>7}  "
          f"{base['trades']:>8} {filt['trades']:>9} {filt['avg_pnl']:>+10.0f}")

    results.append({
        "month": month_str, "avg_atr": round(avg_atr, 1), "regime": regime,
        "base_return": base["return_pct"], "filt_return": filt["return_pct"],
        "base_trades": base["trades"], "filt_trades": filt["trades"],
        "filt_avg_pnl": filt["avg_pnl"], "beats": beats,
    })

# ── Aggregate verdict ─────────────────────────────────────────────────────────
print()
print("=" * 80)
print("VERDICT")
print("=" * 80)

rd = pd.DataFrame(results)
wins = rd["beats"].sum()
total = len(rd)
pct   = 100 * wins / total

print(f"\n  ATR>30 beats baseline: {wins}/{total} months ({pct:.0f}%)")
print(f"  Pass threshold: 65% ({int(total*0.65)} months)")
print(f"  Result: {'✓ PASSED' if pct >= 65 else '✗ FAILED'}")
print()

# By regime
for regime in ["HIGH", "MED", "LOW"]:
    seg = rd[rd["regime"] == regime]
    if len(seg) == 0: continue
    seg_wins = seg["beats"].sum()
    seg_pct  = 100 * seg_wins / len(seg)
    avg_b    = seg["base_return"].mean()
    avg_f    = seg["filt_return"].mean()
    print(f"  Regime {regime} (avg ATR {'> 30' if regime=='HIGH' else '20-30' if regime=='MED' else '< 20'}): "
          f"{seg_wins}/{len(seg)} months ({seg_pct:.0f}%)  "
          f"avg baseline={avg_b:+.1f}%  avg filtered={avg_f:+.1f}%")

print()
print(f"  Overall avg baseline return : {rd['base_return'].mean():+.1f}%/month")
print(f"  Overall avg ATR>30 return   : {rd['filt_return'].mean():+.1f}%/month")
print(f"  Avg trades per month (baseline)  : {rd['base_trades'].mean():.0f}")
print(f"  Avg trades per month (ATR>30)    : {rd['filt_trades'].mean():.0f}")
print(f"  Avg P&L per trade (ATR>30)       : ₹{rd['filt_avg_pnl'].mean():+.0f}")

# Worst months for filtered strategy
print(f"\n  Worst 5 months (ATR>30 filtered):")
worst = rd.nsmallest(5, "filt_return")[["month","avg_atr","regime","base_return","filt_return","filt_trades"]]
print(worst.to_string(index=False))

print(f"\n  Best 5 months (ATR>30 filtered):")
best = rd.nlargest(5, "filt_return")[["month","avg_atr","regime","base_return","filt_return","filt_trades"]]
print(best.to_string(index=False))
