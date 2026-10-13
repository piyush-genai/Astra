"""
EXP-0015: VIX bucket-based position sizing.

EXP-0013 found that VIX percentile at trade entry is a quality signal
but a BAD binary filter (cutting 60-75th pctile trades hurts because it
removes too many trades). The hypothesis here: instead of filtering,
MODULATE position size by VIX quality bucket.

Findings from EXP-0013 driving this design:
  - VIX 60-75th pctile:  ₹47/trade  (danger zone  — least alpha)
  - VIX 50-60th pctile:  ₹547/trade (sweet spot   — most alpha)
  - VIX <20th pctile:    ₹325/trade (cheap options — solid)
  - VIX >75th pctile:    ₹355/trade (high VIX      — still works)

The key insight: we cannot eliminate the danger zone without losing too many
trades, but we CAN reduce our exposure to it while increasing exposure to
the sweet spot. This is standard position sizing by signal quality.

Configs tested (post-hoc multiplier on trade P&L):
  A: Flat 1x (baseline, same as P70_L40d with VIX×1.1 IV)
  B: Defensive — danger zone 0.5x, else 1x
  C: Tilt — sweet spot 1.5x + danger zone 0.5x, else 1x
  D: Gradient — full VIX-quality grade (5 buckets)
  E: Aggressive — sweet spot 2x + danger zone 0.25x, else 1x

All trades use VIX×1.1 dynamic IV (validated EXP-0014).
VIX percentile = rolling 40-day lookback (same as ATR regime filter).
No look-ahead bias: percentile computed from past data only.

Method: post-hoc simulation — run strategy once, scale each trade's P&L
by the sizing multiplier for that trade's VIX bucket. This is equivalent
to trading variable lots. Appropriate for research; paper trading would
use the same logic in real time.
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
atr_mask    = df["atr10"] > df["atr10"].rolling(3000).quantile(0.70)

brok    = instruments_cfg.get("transaction_costs", {}).get("brokerage_per_order", 20.0)
stt_pct = instruments_cfg.get("transaction_costs", {}).get("stt_options_pct", 0.15) / 100.0
lot_sz  = nifty_cfg["lot_size"]

VIX_LOOKBACK = 40  # trading days rolling window for percentile

# ── VIX×1.1 IV function (validated EXP-0014) ─────────────────────────────────
def vix_iv_fn(ts: pd.Timestamp) -> float:
    day = ts.normalize()
    try:
        val = vix_daily["vix"].reindex([day], method="ffill").iloc[0]
        return (val / 100.0) * 1.1 if not pd.isna(val) else 0.14
    except Exception:
        return 0.14


# ── Step 1: collect all P70_L40d trades with VIX metadata ─────────────────────
print("Collecting P70_L40d trades (VIX×1.1 IV, 2023-2025)...")

pricer = OptionsPricer(
    lot_size=nifty_cfg["lot_size"], expiry_weekday=nifty_cfg["weekly_expiry_weekday"],
    strike_step=nifty_cfg["strike_step"], iv=0.14, iv_fn=vix_iv_fn,
)
filtered = df[atr_mask | df["atr10"].isna()]
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
result = harness.run(filtered[["open","high","low","close","volume"]], pricer=pricer)

rows = []
for t in result.trades:
    dirn = "LONG" if t.direction == SignalDirection.LONG else "SHORT"
    leg  = pricer.price_trade(dirn, t.entry_price, t.entry_time, t.exit_price, t.exit_time)
    net  = leg.pnl_rupees - (brok*2 + leg.entry_premium*stt_pct*lot_sz + 5.0)

    entry_day = t.entry_time.normalize()
    try:
        vix_val = vix_daily["vix"].reindex([entry_day], method="ffill").iloc[0]
    except Exception:
        vix_val = 13.5  # fallback to mean

    # Rolling VIX percentile (look-back only — no future data)
    hist_vix   = vix_daily["vix"].loc[:entry_day].tail(VIX_LOOKBACK)
    vix_pctile = float((hist_vix < vix_val).mean() * 100) if len(hist_vix) >= 5 else 50.0

    rows.append({
        "net_pnl":    round(net, 2),
        "winner":     net > 0,
        "month":      t.entry_time.strftime("%Y-%m"),
        "vix":        round(vix_val, 2),
        "vix_pctile": round(vix_pctile, 1),
    })

td = pd.DataFrame(rows)
print(f"  {len(td)} trades collected. VIX pctile range: "
      f"{td['vix_pctile'].min():.0f}–{td['vix_pctile'].max():.0f}  "
      f"mean: {td['vix_pctile'].mean():.0f}")
print()


# ── Step 2: define sizing configs ─────────────────────────────────────────────
def sizing_multiplier(vix_pctile: float, config: str) -> float:
    p = vix_pctile
    if config == "A_flat":
        return 1.0
    elif config == "B_defensive":
        # Only protect against danger zone — no upsizing
        return 0.5 if 60 <= p < 75 else 1.0
    elif config == "C_tilt":
        # Tilt toward sweet spot, away from danger zone
        if 50 <= p < 60:  return 1.5   # sweet spot
        if 60 <= p < 75:  return 0.5   # danger zone
        return 1.0
    elif config == "D_gradient":
        # Full quality gradient — 5 buckets
        if p < 20:        return 1.2   # very cheap options — slightly more
        if 20 <= p < 40:  return 1.0
        if 40 <= p < 50:  return 1.1
        if 50 <= p < 60:  return 1.5   # sweet spot
        if 60 <= p < 75:  return 0.5   # danger zone
        return 1.1                     # >75th: high VIX still works
    elif config == "E_aggressive":
        # Maximum tilt — double sweet spot, quarter danger zone
        if 50 <= p < 60:  return 2.0
        if 60 <= p < 75:  return 0.25
        return 1.0
    raise ValueError(f"Unknown config: {config}")


CONFIGS = [
    ("A_flat",        "Flat 1x (baseline)"),
    ("B_defensive",   "Defensive: danger zone 0.5x"),
    ("C_tilt",        "Tilt: sweet 1.5x + danger 0.5x"),
    ("D_gradient",    "Gradient: 5-bucket quality scale"),
    ("E_aggressive",  "Aggressive: sweet 2x + danger 0.25x"),
]

INITIAL_CAPITAL = 20_000.0
MONTHS          = sorted(td["month"].unique())


def simulate_sizing(td: pd.DataFrame, config_key: str) -> dict:
    pnls_scaled = td.apply(
        lambda r: r["net_pnl"] * sizing_multiplier(r["vix_pctile"], config_key), axis=1
    )
    td2 = td.assign(scaled_pnl=pnls_scaled)

    total     = pnls_scaled.sum()
    avg_pnl   = pnls_scaled.mean()
    win_rate  = (pnls_scaled > 0).mean() * 100
    avg_win   = pnls_scaled[pnls_scaled > 0].mean() if (pnls_scaled > 0).any() else 0
    avg_loss  = pnls_scaled[pnls_scaled < 0].mean() if (pnls_scaled < 0).any() else 0

    n    = len(pnls_scaled)
    sharpe = (avg_pnl * n/3 - INITIAL_CAPITAL * 0.07) / (pnls_scaled.std() * np.sqrt(n/3)) \
             if pnls_scaled.std() > 0 else 0

    pf = (pnls_scaled[pnls_scaled > 0].sum() / abs(pnls_scaled[pnls_scaled < 0].sum())
          if (pnls_scaled < 0).any() else 999)

    monthly = td2.groupby("month")["scaled_pnl"].sum()
    months_pos = int((monthly > 0).sum())

    # Equity curve & max drawdown
    equity = np.zeros(n + 1)
    equity[0] = INITIAL_CAPITAL
    for i, p in enumerate(pnls_scaled.values):
        equity[i+1] = max(equity[i] + p, 1)
    peak   = np.maximum.accumulate(equity)
    dd     = (peak - equity) / peak
    max_dd = dd.max() * 100

    return {
        "total": round(total, 0), "avg_pnl": round(avg_pnl, 1),
        "win_rate": round(win_rate, 1), "sharpe": round(sharpe, 2),
        "pf": round(pf, 3), "months_pos": months_pos,
        "max_dd": round(max_dd, 1),
        "avg_win": round(avg_win, 1), "avg_loss": round(avg_loss, 1),
        "monthly": monthly,
        "avg_size": round(td.apply(
            lambda r: sizing_multiplier(r["vix_pctile"], config_key), axis=1
        ).mean(), 3),
    }


# ── Step 3: run all configs ───────────────────────────────────────────────────
print("=" * 76)
print("EXP-0015: VIX BUCKET POSITION SIZING")
print("=" * 76)
print()

all_res = {key: simulate_sizing(td, key) for key, _ in CONFIGS}

# Summary table
print(f"  {'Config':<35} {'Total ₹':>10} {'Avg/tr':>7} {'Win%':>5} {'Sharpe':>7} {'PF':>6} {'Mo+':>4} {'MaxDD':>7} {'AvgSz':>7}")
print("  " + "-" * 76)
base = all_res["A_flat"]
for key, label in CONFIGS:
    r = all_res[key]
    lift = (r["total"] - base["total"]) / abs(base["total"]) * 100
    lift_str = f"  ({lift:+.0f}%)" if key != "A_flat" else ""
    print(f"  {label:<35} {r['total']:>+10,.0f} {r['avg_pnl']:>+7.0f} "
          f"{r['win_rate']:>5.1f}% {r['sharpe']:>7.2f} {r['pf']:>6.3f} "
          f"{r['months_pos']:>3}/{len(MONTHS)} {r['max_dd']:>6.1f}%  {r['avg_size']:>5.3f}x{lift_str}")

# ── Step 4: monthly P&L comparison for best config ───────────────────────────
# Identify best config by Sharpe
best_key = max((k for k, _ in CONFIGS if k != "A_flat"), key=lambda k: all_res[k]["sharpe"])
best_label = dict(CONFIGS)[best_key]

print()
print("=" * 76)
print(f"MONTHLY BREAKDOWN: FLAT vs {best_label.upper()}")
print("=" * 76)
print()
print(f"  {'Month':<10} {'Flat ₹':>10} {'Best ₹':>10} {'Δ ₹':>9}  {'Trades':>6}  {'Buckets (D=danger, S=sweet, R=rest)'}")
print("  " + "-" * 76)
for m in MONTHS:
    f_pnl   = all_res["A_flat"]["monthly"].get(m, 0.0)
    b_pnl   = all_res[best_key]["monthly"].get(m, 0.0)
    delta   = b_pnl - f_pnl
    mdf     = td[td["month"] == m]
    n_tot   = len(mdf)
    n_d     = int(((mdf["vix_pctile"] >= 60) & (mdf["vix_pctile"] < 75)).sum())
    n_s     = int(((mdf["vix_pctile"] >= 50) & (mdf["vix_pctile"] < 60)).sum())
    n_r     = n_tot - n_d - n_s
    tag     = "↑" if delta > 500 else ("↓" if delta < -500 else "≈")
    print(f"  {m:<10} {f_pnl:>+10,.0f} {b_pnl:>+10,.0f} {delta:>+9,.0f}  {tag} "
          f"  {n_tot:>3}tr  D:{n_d} S:{n_s} R:{n_r}")

# ── Step 5: sizing breakdown by VIX bucket ────────────────────────────────────
print()
print("=" * 76)
print(f"TRADE QUALITY BY VIX BUCKET — raw (1x) vs best sizing config ({best_label})")
print("=" * 76)
print()
buckets = [
    (0,  20,  "VIX <20th pctile",    None),
    (20, 40,  "VIX 20-40th",         None),
    (40, 50,  "VIX 40-50th",         None),
    (50, 60,  "VIX 50-60th ★SWEET★", None),
    (60, 75,  "VIX 60-75th ⚠DANGER", None),
    (75, 100, "VIX >75th",           None),
]
best_mult = lambda p: sizing_multiplier(p, best_key)
print(f"  {'Bucket':<26} {'Trd':>5} {'1x Avg':>9} {'Sized Avg':>10} {'Size':>6} {'Win%':>6}")
print("  " + "-" * 65)
for lo, hi, label, _ in buckets:
    seg  = td[(td["vix_pctile"] >= lo) & (td["vix_pctile"] < hi)]
    if len(seg) < 5: continue
    mult = best_mult((lo + hi) / 2)
    raw  = seg["net_pnl"].mean()
    siz  = raw * mult
    wr   = 100 * seg["winner"].mean()
    print(f"  {label:<26} {len(seg):>5} {raw:>+9.0f} {siz:>+10.0f} "
          f"{mult:>5.2f}x {wr:>5.0f}%")

# ── Step 6: Kelly-inspired sizing analysis ────────────────────────────────────
print()
print("=" * 76)
print("KELLY OPTIMAL SIZING BY VIX BUCKET")
print("  (Kelly fraction = (p×b - q) / b where b = avg_win/avg_loss)")
print("=" * 76)
print()
print(f"  {'Bucket':<26} {'p(win)':>8} {'W/L ratio':>10} {'Kelly f':>10} {'Rec size':>10}")
print("  " + "-"*65)
for lo, hi, label, _ in buckets:
    seg  = td[(td["vix_pctile"] >= lo) & (td["vix_pctile"] < hi)]
    if len(seg) < 10: continue
    p_win = seg["winner"].mean()
    p_lose = 1 - p_win
    wins  = seg.loc[seg["winner"], "net_pnl"]
    loses = seg.loc[~seg["winner"], "net_pnl"]
    if len(wins) == 0 or len(loses) == 0: continue
    b = wins.mean() / abs(loses.mean())
    kelly = (p_win * b - p_lose) / b
    kelly = max(0.0, min(kelly, 2.0))  # clamp to [0, 2]
    rec   = f"{kelly:.2f}x"
    print(f"  {label:<26} {p_win:>8.1%} {b:>10.2f} {kelly:>10.3f} {rec:>10}")

# ── Conclusion ────────────────────────────────────────────────────────────────
print()
print("=" * 76)
print("VERDICT")
print("=" * 76)
print()
for key, label in CONFIGS:
    r   = all_res[key]
    ref = all_res["A_flat"]
    if key == "A_flat":
        print(f"  BASELINE → {label:<35} total ₹{r['total']:>+9,.0f}  Sharpe {r['sharpe']:.2f}  max DD {r['max_dd']:.1f}%")
        continue
    total_lift  = (r["total"] - ref["total"]) / abs(ref["total"]) * 100
    sharpe_lift = r["sharpe"] - ref["sharpe"]
    better = r["sharpe"] > ref["sharpe"] and r["total"] >= ref["total"] * 0.90
    tick = "✓ PASS" if better else "✗ FAIL"
    print(f"  {tick} {label:<35} total lift {total_lift:+.1f}%  Sharpe {r['sharpe']:.2f} ({sharpe_lift:+.2f})  max DD {r['max_dd']:.1f}%")
