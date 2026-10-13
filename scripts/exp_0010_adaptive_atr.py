"""
EXP-0010: Adaptive ATR percentile filter.

Problem from EXP-0009: fixed ATR>30 threshold is calibrated on an extreme
2026 outlier regime. In normal markets (2023-2025), ATR rarely hits 30.

Solution: replace the fixed threshold with a RELATIVE one.
  Entry allowed only when: current_atr > PCTILE-th percentile of the
  trailing LOOKBACK bars of ATR.

This means "trade only when volatility is elevated vs recent history" —
the threshold adapts automatically to whatever market regime we're in.

Tests: percentile thresholds [60, 65, 70, 75, 80] × lookback [20, 40, 60 days].
Pass criterion: best config beats baseline in >= 65% of the 36 months.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    sys.exit("Missing DATA-001 file — run data_001_fetch_historical.py first.")

instruments_cfg = load_instruments()
risk_cfg        = load_risk()
nifty_cfg       = instruments_cfg["instruments"]["NIFTY"]

df = pd.read_csv(DATA_PATH, parse_dates=["timestamp"], index_col="timestamp")
df.index = pd.DatetimeIndex(df.index)

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


def build_adaptive_filter(df_full: pd.DataFrame, pctile: int, lookback_bars: int) -> pd.Series:
    """
    For each bar, compute the PCTILE-th percentile of ATR over the past
    LOOKBACK_BARS bars, then return a boolean mask: True if current ATR
    exceeds that percentile (bar is in a 'high volatility' regime).
    No look-ahead: rolling window uses only past bars.
    """
    rolling_pctile = df_full["atr10"].rolling(lookback_bars).quantile(pctile / 100.0)
    return df_full["atr10"] > rolling_pctile


def run_month(month_data: pd.DataFrame, mask: pd.Series | None, initial: float) -> dict:
    filtered = month_data.copy()
    if mask is not None:
        m = mask.reindex(filtered.index, fill_value=False)
        filtered = filtered[m | filtered["atr10"].isna()]

    if len(filtered) < 30:
        return {"return_pct": 0.0, "trades": 0, "net_pnl": 0.0, "avg_pnl": 0.0}

    strategy = PivotCprStrategy(config={
        "tolerance_pct": 0.18, "min_levels_for_confluence": 2,
        "momentum_enabled": True, "momentum_body_pct": 0.50,
        "momentum_accel_multiplier": 1.8, "momentum_min_criteria": 2,
    })
    strategy._daily_ohlc = daily_ohlcv

    harness = BacktestHarness(
        strategy=strategy, instruments_config=instruments_cfg,
        risk_config=risk_cfg, cooldown_minutes=0, allow_hedge=True,
        initial_capital=initial,
    )
    result = harness.run(filtered[["open","high","low","close","volume"]], pricer=pricer)
    end_cap = harness._current_capital
    net_total = 0.0
    for t in result.trades:
        dirn = "LONG" if t.direction == SignalDirection.LONG else "SHORT"
        leg  = pricer.price_trade(dirn, t.entry_price, t.entry_time, t.exit_price, t.exit_time)
        net_total += leg.pnl_rupees - (brok * 2 + leg.entry_premium * stt_pct * lot_sz + 5.0)

    n = len(result.trades)
    return {
        "return_pct": round((end_cap - initial) / initial * 100, 2),
        "trades": n,
        "net_pnl": round(net_total, 2),
        "avg_pnl": round(net_total / n, 2) if n else 0.0,
    }


# ── Build months list ──────────────────────────────────────────────────────────
from dateutil.relativedelta import relativedelta
from datetime import date

months = []
cur = date(2023, 1, 1)
while cur <= date(2025, 12, 1):
    months.append(cur.strftime("%Y-%m"))
    cur += relativedelta(months=1)

INITIAL = 20_000.0
CONFIGS = [
    # (pctile, lookback_trading_bars)
    # lookback in bars: 1 trading day ≈ 75 bars; 20 days ≈ 1500 bars
    (65, 1500),   # 65th pctile, 20-day lookback
    (70, 1500),   # 70th pctile, 20-day lookback
    (75, 1500),   # 75th pctile, 20-day lookback
    (70, 3000),   # 70th pctile, 40-day lookback
    (75, 3000),   # 75th pctile, 40-day lookback
    (70, 4500),   # 70th pctile, 60-day lookback
]

# Pre-compute baseline month results (run once)
print("Computing baselines...")
baseline_results = {}
for month_str in months:
    ts_start = pd.Timestamp(f"{month_str}-01", tz="Asia/Kolkata")
    ts_end   = ts_start + pd.DateOffset(months=1)
    mdf = df[(df.index >= ts_start) & (df.index < ts_end)]
    if len(mdf) >= 100:
        baseline_results[month_str] = run_month(mdf, None, INITIAL)

print(f"  Baseline ready for {len(baseline_results)} months.")
print()

# ── Test each config ───────────────────────────────────────────────────────────
config_summaries = []

for pctile, lookback in CONFIGS:
    label = f"P{pctile}_L{lookback//75}d"

    # Build the adaptive mask for the FULL dataset (no look-ahead)
    mask = build_adaptive_filter(df, pctile, lookback)

    wins, tested = 0, 0
    month_pnls, month_trades = [], []

    for month_str in months:
        if month_str not in baseline_results:
            continue
        ts_start = pd.Timestamp(f"{month_str}-01", tz="Asia/Kolkata")
        ts_end   = ts_start + pd.DateOffset(months=1)
        mdf  = df[(df.index >= ts_start) & (df.index < ts_end)]
        base = baseline_results[month_str]
        filt = run_month(mdf, mask, INITIAL)

        beats = filt["return_pct"] > base["return_pct"]
        if beats:
            wins += 1
        tested += 1
        month_pnls.append(filt["return_pct"])
        month_trades.append(filt["trades"])

    win_pct = 100 * wins / tested
    avg_ret = np.mean(month_pnls)
    avg_trd = np.mean(month_trades)

    config_summaries.append({
        "config": label, "pctile": pctile, "lookback_bars": lookback,
        "wins": wins, "tested": tested, "win_pct": win_pct,
        "avg_return_pct": round(avg_ret, 1), "avg_trades": round(avg_trd, 1),
        "passed": win_pct >= 65,
    })

    status = "✓ PASS" if win_pct >= 65 else "✗ fail"
    print(f"  {label:<14} {wins}/{tested} ({win_pct:.0f}%)  "
          f"avg={avg_ret:+.1f}%/mo  avg_trades={avg_trd:.0f}  {status}")

# ── Detailed monthly breakdown for best config ─────────────────────────────────
best = max(config_summaries, key=lambda x: x["win_pct"])
print()
print("=" * 75)
print(f"BEST CONFIG: {best['config']}  ({best['wins']}/{best['tested']} = {best['win_pct']:.0f}%)")
print("=" * 75)

pctile, lookback = best["pctile"], best["lookback_bars"]
mask = build_adaptive_filter(df, pctile, lookback)

print(f"\n  {'Month':<10} {'ATR_avg':>8} {'Baseline':>10} {'Adaptive':>10} "
      f"{'Beats?':>7} {'Trades':>7} {'Avg PnL':>9}")
print("-" * 75)

for month_str in months:
    if month_str not in baseline_results:
        continue
    ts_start = pd.Timestamp(f"{month_str}-01", tz="Asia/Kolkata")
    ts_end   = ts_start + pd.DateOffset(months=1)
    mdf  = df[(df.index >= ts_start) & (df.index < ts_end)]
    avg_atr = mdf["atr10"].mean()
    base = baseline_results[month_str]
    filt = run_month(mdf, mask, INITIAL)
    beats = filt["return_pct"] > base["return_pct"]
    print(f"  {month_str:<10} {avg_atr:>7.1f}  {base['return_pct']:>+9.1f}% "
          f"{filt['return_pct']:>+9.1f}% {'✓' if beats else '✗':>7}  "
          f"{filt['trades']:>6}  {filt['avg_pnl']:>+8.0f}")

# ── Final verdict ──────────────────────────────────────────────────────────────
print()
print("=" * 75)
print("VERDICT")
print("=" * 75)
print(f"\n  Baseline avg return : {np.mean([r['return_pct'] for r in baseline_results.values()]):+.1f}%/month")
print(f"\n  Config results:")
for s in sorted(config_summaries, key=lambda x: -x["win_pct"]):
    st = "✓ PASSED" if s["passed"] else "✗ failed"
    print(f"    {s['config']:<14} {s['wins']}/{s['tested']} ({s['win_pct']:.0f}%)  "
          f"avg {s['avg_return_pct']:+.1f}%/mo  {st}")
