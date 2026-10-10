"""
EXP-0013: India VIX as an option-quality entry filter.

Hypothesis: The price you pay for an option (the premium) is driven by
implied volatility. When India VIX is relatively HIGH, options are expensive.
After you buy them, two things can happen:
  a) market moves strongly → trade wins despite expensive entry
  b) market settles → IV crushes, trade loses even if direction was right

When India VIX is relatively LOW, options are cheap. A similar-sized move
produces a larger % gain because you started from a lower base premium.

This experiment tests whether adding a VIX percentile filter on top of
the validated P70_L40d ATR regime filter improves trade quality.

Three hypotheses tested:
  A. Trade ONLY when VIX is LOW (< 40th pctile of trailing 40 days)
     → cheap options, potential for IV expansion on entry
  B. Trade ONLY when VIX is in MEDIUM range (30th–70th pctile)
     → not too expensive, not too quiet
  C. Trade ONLY when VIX is HIGH (> 60th pctile)
     → expensive options but strong volatility confirms regime

Filter stacking: P70_L40d ATR filter FIRST, then VIX filter layered on top.
Dataset: Jan 2023 – Dec 2025 (validated dataset).
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
VIX_PATH  = Path("data/live_data/india_vix_daily_20230101_to_20251231.csv")
for p in [DATA_PATH, VIX_PATH]:
    if not p.exists(): sys.exit(f"Missing {p}")

instruments_cfg = load_instruments()
risk_cfg        = load_risk()
nifty_cfg       = instruments_cfg["instruments"]["NIFTY"]

df = pd.read_csv(DATA_PATH, parse_dates=["timestamp"], index_col="timestamp")
df.index = pd.DatetimeIndex(df.index)

vix_daily = pd.read_csv(VIX_PATH, parse_dates=["date"], index_col="date")
vix_daily.index = pd.DatetimeIndex(vix_daily.index)

daily_ohlcv = df.resample("B").agg(
    open=("open","first"), high=("high","max"),
    low=("low","min"), close=("close","last"),
).dropna()

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

# ── Build filters ──────────────────────────────────────────────────────────────
# ATR adaptive filter (P70_L40d — validated)
atr_mask = df["atr10"] > df["atr10"].rolling(3000).quantile(0.70)

# VIX rolling percentile (40-day lookback, same as ATR filter)
VIX_LOOKBACK = 40   # calendar days ≈ 28 trading days
vix_rolling_pctile = {}
for pctile in [30, 40, 60, 70]:
    # rolling quantile on daily data
    vix_rolling_pctile[pctile] = vix_daily["vix"].rolling(VIX_LOOKBACK).quantile(pctile / 100.0)

# Broadcast VIX to 5-min bars (each bar gets its day's VIX value)
def broadcast_vix_to_bars(df_bars, vix_series):
    """Map daily VIX to every 5-min bar of that day."""
    days = df_bars.index.normalize()
    # Reindex VIX to 5-min bar dates; use last available for holidays
    return vix_series.reindex(days, method="ffill").values

df["vix"]              = broadcast_vix_to_bars(df, vix_daily["vix"])
df["vix_p30"]          = broadcast_vix_to_bars(df, vix_rolling_pctile[30])
df["vix_p40"]          = broadcast_vix_to_bars(df, vix_rolling_pctile[40])
df["vix_p60"]          = broadcast_vix_to_bars(df, vix_rolling_pctile[60])
df["vix_p70"]          = broadcast_vix_to_bars(df, vix_rolling_pctile[70])

# Define VIX masks
vix_low_mask    = df["vix"] < df["vix_p40"]                              # bottom 40%
vix_medium_mask = (df["vix"] >= df["vix_p30"]) & (df["vix"] < df["vix_p70"])  # middle 40%
vix_high_mask   = df["vix"] > df["vix_p60"]                              # top 40%


def run_month(month_str: str, bar_mask) -> dict:
    ts_start = pd.Timestamp(f"{month_str}-01", tz="Asia/Kolkata")
    ts_end   = ts_start + pd.DateOffset(months=1)
    mdf      = df[(df.index >= ts_start) & (df.index < ts_end)].copy()
    if len(mdf) < 30: return {"return_pct": 0.0, "trades": 0, "avg_pnl": 0.0, "net_pnl": 0.0}

    if bar_mask is not None:
        m = bar_mask.reindex(mdf.index, fill_value=False)
        mdf = mdf[m]
    if len(mdf) < 30: return {"return_pct": 0.0, "trades": 0, "avg_pnl": 0.0, "net_pnl": 0.0}

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
    result = harness.run(mdf[["open","high","low","close","volume"]], pricer=pricer)
    end_cap = harness._current_capital
    net_total = 0.0
    for t in result.trades:
        dirn = "LONG" if t.direction == SignalDirection.LONG else "SHORT"
        leg  = pricer.price_trade(dirn, t.entry_price, t.entry_time, t.exit_price, t.exit_time)
        net_total += leg.pnl_rupees - (brok*2 + leg.entry_premium*stt_pct*lot_sz + 5.0)
    n = len(result.trades)
    return {
        "return_pct": round((end_cap - 20_000) / 20_000 * 100, 2),
        "trades": n, "net_pnl": round(net_total, 2),
        "avg_pnl": round(net_total / n, 2) if n else 0.0,
    }


from dateutil.relativedelta import relativedelta
from datetime import date

months = []
cur = date(2023, 1, 1)
while cur <= date(2025, 12, 1):
    months.append(cur.strftime("%Y-%m"))
    cur += relativedelta(months=1)

# ── Run all configs ────────────────────────────────────────────────────────────
configs = [
    ("ATR only (baseline)",         atr_mask,                       None),
    ("ATR + VIX low (<P40)",        atr_mask & vix_low_mask,        "LOW"),
    ("ATR + VIX medium (P30–P70)",  atr_mask & vix_medium_mask,     "MED"),
    ("ATR + VIX high (>P60)",       atr_mask & vix_high_mask,       "HIGH"),
]

print("=" * 75)
print("EXP-0013: INDIA VIX FILTER ON TOP OF P70_L40d ATR REGIME FILTER")
print("=" * 75)
print()

# Pre-compute baseline once to avoid repeating it 4x
print("Computing baseline results (36 months)...")
baseline_cache = {m: run_month(m, atr_mask) for m in months}
print("Done. Running VIX filter configs...")

all_results = {}
for label, mask, _ in configs:
    wins, total = 0, 0
    month_rets, month_pnls, month_trades = [], [], []
    for month_str in months:
        base_atr = baseline_cache[month_str]
        filt     = run_month(month_str, mask) if "baseline" not in label.lower() else base_atr
        beats    = filt["return_pct"] > base_atr["return_pct"]
        if beats: wins += 1
        total += 1
        month_rets.append(filt["return_pct"])
        month_pnls.append(filt["avg_pnl"])
        month_trades.append(filt["trades"])

    win_pct  = 100 * wins / total
    avg_ret  = np.mean(month_rets)
    avg_trd  = np.mean(month_trades)
    avg_pnl  = np.mean([p for p, t in zip(month_pnls, month_trades) if t > 0])
    all_results[label] = {
        "wins": wins, "total": total, "win_pct": win_pct,
        "avg_return": avg_ret, "avg_trades": avg_trd, "avg_pnl_per_trade": avg_pnl,
    }
    status = "✓" if win_pct >= 65 else " "
    print(f"  {status} {label:<35} {wins}/{total} ({win_pct:.0f}%)  "
          f"avg={avg_ret:+.1f}%/mo  trades={avg_trd:.0f}  ₹{avg_pnl:+.0f}/trade")

# ── VIX level analysis of actual ATR-filtered trades ─────────────────────────
print()
print("=" * 75)
print("VIX BUCKET ANALYSIS — avg P&L per trade within ATR-filtered universe")
print("=" * 75)

# Run full dataset, collect per-trade VIX level
filtered_bars = df[atr_mask | df["atr10"].isna()]
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
result = harness.run(filtered_bars[["open","high","low","close","volume"]], pricer=pricer)

rows = []
for t in result.trades:
    dirn = "LONG" if t.direction == SignalDirection.LONG else "SHORT"
    leg  = pricer.price_trade(dirn, t.entry_price, t.entry_time, t.exit_price, t.exit_time)
    net  = leg.pnl_rupees - (brok*2 + leg.entry_premium*stt_pct*lot_sz + 5.0)
    # Get VIX for this trade's entry bar
    entry_day = t.entry_time.normalize()
    vix_val   = vix_daily["vix"].reindex([entry_day], method="ffill").iloc[0] if entry_day in vix_daily.index or True else np.nan
    # Get VIX percentile rank at entry
    hist_vix  = vix_daily["vix"].loc[:entry_day].tail(VIX_LOOKBACK)
    vix_pctile = (hist_vix < vix_val).mean() * 100 if len(hist_vix) >= 10 else 50
    rows.append({"net_pnl": round(net, 2), "vix": round(vix_val, 2),
                 "vix_pctile": round(vix_pctile, 1), "winner": net > 0,
                 "month": t.entry_time.strftime("%Y-%m")})

td = pd.DataFrame(rows)

print(f"\n  VIX at entry distribution across {len(td)} ATR-filtered trades:")
print(f"  VIX range: {td['vix'].min():.1f} – {td['vix'].max():.1f}  |  mean: {td['vix'].mean():.1f}")
print()
bins = [(0,20,"<20 (very low)"), (20,30,"20-30 (low-med)"),
        (30,40,"30-40th pctile"), (40,50,"40-50th"), (50,60,"50-60th"),
        (60,75,"60-75th pctile"), (75,100,">75 (high)")]
print(f"  {'VIX pctile bucket':<22} {'Trades':>7} {'Win%':>6} {'Avg PnL':>10} {'Total PnL':>12}")
print("  " + "-"*60)
for lo, hi, label in bins:
    seg = td[(td["vix_pctile"] >= lo) & (td["vix_pctile"] < hi)]
    if len(seg) < 3: continue
    wr  = 100 * seg["winner"].mean()
    avg = seg["net_pnl"].mean()
    tot = seg["net_pnl"].sum()
    print(f"  {label:<22} {len(seg):>7} {wr:>5.0f}% {avg:>+10.0f} {tot:>+12,.0f}")

# ── Verdict ───────────────────────────────────────────────────────────────────
print()
print("=" * 75)
print("VERDICT")
print("=" * 75)
atr_base = all_results["ATR only (baseline)"]
print(f"\n  ATR baseline: {atr_base['wins']}/{atr_base['total']} "
      f"({atr_base['win_pct']:.0f}%), avg {atr_base['avg_return']:+.1f}%/mo, "
      f"₹{atr_base['avg_pnl_per_trade']:+.0f}/trade")
print()
for label, r in all_results.items():
    if "baseline" in label.lower(): continue
    lift = r["avg_return"] - atr_base["avg_return"]
    pnl_lift = r["avg_pnl_per_trade"] - atr_base["avg_pnl_per_trade"]
    better = r["win_pct"] > atr_base["win_pct"] or lift > 5
    print(f"  {'✓' if better else '✗'} {label:<35}")
    print(f"    Win rate: {r['win_pct']:.0f}% | Avg return: {r['avg_return']:+.1f}%/mo "
          f"(lift: {lift:+.1f}pp) | ₹{r['avg_pnl_per_trade']:+.0f}/trade ({pnl_lift:+.0f})")
    print(f"    Avg trades/month: {r['avg_trades']:.0f} "
          f"(vs {atr_base['avg_trades']:.0f} baseline)")
