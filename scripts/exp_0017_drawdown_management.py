"""
EXP-0017: Drawdown-adaptive lot sizing.

EXP-0016 found that a cliff-edge drawdown brake (any → 1 lot at 35% DD)
permanently crippled compounding after Oct-Dec 2023. The strategy hit
₹1.3 crore at 35 lots, drew down 58%, and could never recover at 1 lot.

Root cause: the brake reference (all-time peak at maximum leverage) was
incompatible with a 1-lot recovery mechanism. A ₹1.3 crore peak requires
₹87 lakh of cumulative recovery at ₹12k/month → ~600 months.

This experiment tests CONTINUOUS drawdown management — lot count scales
smoothly with distance from high-water mark (HWM). No cliff edge.

Five configs tested, all using the same base mechanics as EXP-0016:
  - P70_L40d ATR filter + VIX×1.1 IV + VIX tilt sizing
  - 30% tax reserve, slippage model at scale
  - ₹20k and ₹50k start capital

Config A: Cliff-edge 1-lot (EXP-0016 result — recomputed here for comparison)
Config B: Linear decay    lot_mult = max(0.10, 1.0 - 2×dd)   [0% DD: 1.0x → 50%: 0.0x]
Config C: Quadratic decay lot_mult = max(0.10, (1-dd)²)       [forgiving early, steep late]
Config D: Step-down tiers 0-15%: 1.0x | 15-25%: 0.65x | 25-40%: 0.35x | >40%: 0.12x
Config E: Sigmoid decay   lot_mult = 1/(1+exp(10×(dd-0.25))) [smooth S-curve, inflects at 25%]

All configs:
  - base_max_lots starts at 20 (moderate — same across configs for fair comparison)
  - max_lots_cap grows by 5 every 3 consecutive profitable months (ONLY when lot_mult=1.0)
  - HWM updates whenever net_capital > HWM (after tax)
  - dd = (HWM - net_capital) / HWM  (current drawdown from HWM)
  - effective_max_lots = max(1, int(base_max_lots × lot_mult))
"""
import sys, math
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
daily_ohlcv = df.resample("B").agg(open=("open","first"), high=("high","max"),
    low=("low","min"), close=("close","last")).dropna()
tr = pd.concat([df["high"]-df["low"], (df["high"]-df["close"].shift(1)).abs(),
                (df["low"]-df["close"].shift(1)).abs()], axis=1).max(axis=1)
df["atr10"] = tr.rolling(10).mean()
atr_mask    = df["atr10"] > df["atr10"].rolling(3000).quantile(0.70)

brok    = instruments_cfg.get("transaction_costs", {}).get("brokerage_per_order", 20.0)
stt_pct = instruments_cfg.get("transaction_costs", {}).get("stt_options_pct", 0.15) / 100.0
lot_sz  = nifty_cfg["lot_size"]
VIX_LOOKBACK = 40

def vix_iv_fn(ts):
    day = ts.normalize()
    try:
        val = vix_daily["vix"].reindex([day], method="ffill").iloc[0]
        return (val/100.0)*1.1 if not pd.isna(val) else 0.14
    except: return 0.14

def vix_size_mult(pctile):
    if 50 <= pctile < 60: return 1.5
    if 60 <= pctile < 75: return 0.5
    return 1.0


# ── Collect base trades once ───────────────────────────────────────────────────
print("Collecting P70_L40d trades (VIX×1.1 IV + VIX tilt, 2023-2025)...")
pricer = OptionsPricer(lot_size=lot_sz, expiry_weekday=nifty_cfg["weekly_expiry_weekday"],
    strike_step=nifty_cfg["strike_step"], iv=0.14, iv_fn=vix_iv_fn)
filtered = df[atr_mask | df["atr10"].isna()]
strategy = PivotCprStrategy(config={"tolerance_pct":0.18,"min_levels_for_confluence":2,
    "momentum_enabled":True,"momentum_body_pct":0.50,"momentum_accel_multiplier":1.8,
    "momentum_min_criteria":2})
strategy._daily_ohlc = daily_ohlcv
harness = BacktestHarness(strategy=strategy, instruments_config=instruments_cfg,
    risk_config=risk_cfg, cooldown_minutes=0, allow_hedge=True, initial_capital=20_000.0)
result = harness.run(filtered[["open","high","low","close","volume"]], pricer=pricer)

rows = []
for t in result.trades:
    dirn = "LONG" if t.direction == SignalDirection.LONG else "SHORT"
    leg  = pricer.price_trade(dirn, t.entry_price, t.entry_time, t.exit_price, t.exit_time)
    base_net = leg.pnl_rupees - (brok*2 + leg.entry_premium*stt_pct*lot_sz + 5.0)
    entry_day = t.entry_time.normalize()
    try:
        vix_val = vix_daily["vix"].reindex([entry_day], method="ffill").iloc[0]
        hist    = vix_daily["vix"].loc[:entry_day].tail(VIX_LOOKBACK)
        pctile  = float((hist < vix_val).mean() * 100)
    except: pctile = 50.0
    mult = vix_size_mult(pctile)
    rows.append({
        "net_per_lot": round(base_net * mult, 2),
        "premium_per_lot": round(leg.entry_premium * lot_sz, 2),
        "month": t.entry_time.strftime("%Y-%m"),
        "ts": t.entry_time,
    })

td = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
print(f"  {len(td)} trades | avg pnl/lot: ₹{td['net_per_lot'].mean():+.0f} | avg premium/lot: ₹{td['premium_per_lot'].mean():.0f}")
print()


# ── Drawdown multiplier functions ──────────────────────────────────────────────
def dd_mult_cliff(dd):     return 1.0 if dd < 0.35 else 0.0   # EXP-0016: 0 → forced to 1 lot min
def dd_mult_linear(dd):    return max(0.10, 1.0 - 2.0 * dd)
def dd_mult_quadratic(dd): return max(0.10, (1.0 - dd) ** 2)
def dd_mult_steps(dd):
    if dd < 0.15: return 1.00
    if dd < 0.25: return 0.65
    if dd < 0.40: return 0.35
    return 0.12
def dd_mult_sigmoid(dd):
    # Inflects at 25% DD; above 50% → ~2% of max lots
    return max(0.02, 1.0 / (1.0 + math.exp(10.0 * (dd - 0.25))))


CONFIGS = [
    ("A_cliff",     "Cliff: any→1 lot at 35% DD (EXP-0016)",    dd_mult_cliff),
    ("B_linear",    "Linear decay (floor 10%)",                   dd_mult_linear),
    ("C_quadratic", "Quadratic decay (floor 10%)",                dd_mult_quadratic),
    ("D_steps",     "Step-down tiers (4 levels)",                 dd_mult_steps),
    ("E_sigmoid",   "Sigmoid S-curve (inflects at 25%)",          dd_mult_sigmoid),
]

RISK_PER_TRADE   = 0.30
TAX_RATE         = 0.30
INITIAL_MAX_LOTS = 20     # same start for all configs — fair comparison
LOT_STEP         = 5
CONSEC_POS_MONTHS = 3
SLIPPAGE_PER_LOT = 2 * lot_sz
MONTHS           = sorted(td["month"].unique())


def run_config(start_capital: float, dd_fn, config_key: str) -> dict:
    capital      = float(start_capital)
    tax_reserve  = 0.0
    hwm          = capital                 # high water mark (net capital)
    base_max_lots = INITIAL_MAX_LOTS
    consec_pos   = 0

    monthly_log  = []
    cur_month    = None
    month_pnl    = 0.0
    month_lots   = []
    months_in_reduced = 0

    def close_month():
        nonlocal capital, tax_reserve, hwm, base_max_lots, consec_pos, month_pnl
        if cur_month is None: return
        if month_pnl > 0:
            tax_reserve += month_pnl * TAX_RATE
        net_cap = capital - tax_reserve
        if net_cap > hwm: hwm = net_cap
        dd = max(0.0, (hwm - net_cap) / hwm) if hwm > 0 else 0.0
        mult = dd_fn(dd)
        reduced = mult < 1.0
        # Only unlock higher lots when operating at full capacity
        if month_pnl > 0 and not reduced:
            consec_pos += 1
        elif month_pnl <= 0:
            consec_pos = 0
        if consec_pos >= CONSEC_POS_MONTHS:
            base_max_lots += LOT_STEP
            consec_pos = 0
        eff_max = max(1, int(base_max_lots * mult))
        avg_lots = np.mean(month_lots) if month_lots else 0
        monthly_log.append({
            "month": cur_month, "net_capital": round(net_cap, 0),
            "month_pnl": round(month_pnl, 0), "dd_pct": round(dd*100, 1),
            "lot_mult": round(mult, 2), "eff_max_lots": eff_max,
            "avg_lots": round(avg_lots, 1), "reduced": reduced,
        })
        month_pnl = 0.0
        month_lots.clear()

    for _, row in td.iterrows():
        if row["month"] != cur_month:
            close_month()
            cur_month = row["month"]

        net_cap      = capital - tax_reserve
        if net_cap > hwm: hwm = net_cap
        dd           = max(0.0, (hwm - net_cap) / hwm) if hwm > 0 else 0.0
        mult         = dd_fn(dd)
        eff_max      = max(1, int(base_max_lots * mult))
        prem_per_lot = max(row["premium_per_lot"], 500.0)
        lots_from_cap = max(1, int(net_cap * RISK_PER_TRADE / prem_per_lot))
        lots          = min(lots_from_cap, eff_max)

        extra_slip  = max(0, lots - 10) * SLIPPAGE_PER_LOT
        trade_pnl   = row["net_per_lot"] * lots - extra_slip
        capital    += trade_pnl
        capital     = max(capital, 500.0)
        month_pnl  += trade_pnl
        month_lots.append(lots)

    close_month()

    net_final = capital - tax_reserve
    months_reduced = sum(1 for r in monthly_log if r["reduced"])
    max_dd_abs    = max((r["dd_pct"] for r in monthly_log), default=0.0)
    peak_net      = max(r["net_capital"] for r in monthly_log)
    return {
        "net_final": round(net_final, 0),
        "gross_capital": round(capital, 0),
        "tax_reserve": round(tax_reserve, 0),
        "total_return_pct": round((net_final - start_capital) / start_capital * 100, 0),
        "months_reduced": months_reduced,
        "months_total": len(monthly_log),
        "max_dd_pct": round(max_dd_abs, 1),
        "peak_net": round(peak_net, 0),
        "base_max_lots_final": base_max_lots,
        "monthly_log": monthly_log,
    }


# ── Run all configs ────────────────────────────────────────────────────────────
print("=" * 72)
print("EXP-0017: DRAWDOWN-ADAPTIVE LOT SIZING")
print("=" * 72)

for start_cap in [20_000, 50_000]:
    print(f"\n{'─'*72}")
    print(f"  START CAPITAL: ₹{start_cap:,}  |  Initial max lots: {INITIAL_MAX_LOTS}")
    print(f"{'─'*72}")
    print(f"  {'Config':<42} {'Net ₹':>10} {'Return':>8} {'Max DD':>8} {'Mo↓':>5} {'PeakNet':>12}")
    print(f"  {'─'*72}")

    all_results = {}
    for key, label, fn in CONFIGS:
        r = run_config(start_cap, fn, key)
        all_results[key] = r
        print(f"  {label:<42} {r['net_final']:>+10,.0f} {r['total_return_pct']:>+7.0f}% "
              f"{r['max_dd_pct']:>7.1f}% {r['months_reduced']:>3}/{r['months_total']} "
              f"{r['peak_net']:>+12,.0f}")

    # Detailed monthly breakdown for best non-cliff config
    best_key = max(
        (k for k, _, _ in CONFIGS if k != "A_cliff"),
        key=lambda k: all_results[k]["net_final"]
    )
    best_label = dict((k,l) for k,l,_ in CONFIGS)[best_key]

    print(f"\n  Monthly breakdown: {best_label}  (start ₹{start_cap:,})")
    print(f"  {'Month':<10} {'Net cap ₹':>12} {'Mo PnL ₹':>12} {'DD%':>6} {'Mult':>6} {'AvgLts':>7} {'MaxLts':>7}")
    print(f"  {'─'*65}")
    for r in all_results[best_key]["monthly_log"]:
        flag = "⬇" if r["reduced"] else " "
        print(f"  {r['month']:<10} {r['net_capital']:>+12,.0f} {r['month_pnl']:>+12,.0f} "
              f"{r['dd_pct']:>5.1f}% {r['lot_mult']:>5.2f}x {r['avg_lots']:>7.1f} "
              f"{r['eff_max_lots']:>7}  {flag}")


# ── Drawdown multiplier visualization ─────────────────────────────────────────
print()
print("=" * 72)
print("DRAWDOWN MULTIPLIER COMPARISON (lot_mult at given DD level)")
print("=" * 72)
print(f"  {'DD from HWM':>12}  {'Cliff':>8}  {'Linear':>8}  {'Quadratic':>10}  {'Steps':>8}  {'Sigmoid':>8}")
print(f"  {'─'*60}")
for dd_pct in [0, 10, 15, 20, 25, 30, 35, 40, 50, 60]:
    dd = dd_pct / 100.0
    row = [f"{dd_pct:>11}%",
           f"{max(1, int(20 * (1.0 if dd<0.35 else 0.0))):>7}L",
           f"{max(0.10, 1.0-2*dd):>8.2f}x",
           f"{max(0.10, (1-dd)**2):>10.2f}x",
           f"{dd_mult_steps(dd):>8.2f}x",
           f"{dd_mult_sigmoid(dd):>8.2f}x"]
    print("  " + "  ".join(row))


# ── Conclusion ────────────────────────────────────────────────────────────────
print()
print("=" * 72)
print("VERDICT — best config for production compounding engine")
print("=" * 72)
print()

# Recompute for 50k (most representative scenario) to find winner
r50 = {}
for key, label, fn in CONFIGS:
    r50[key] = run_config(50_000, fn, key)

for key, label, fn in CONFIGS:
    r = r50[key]
    marker = " ← RECOMMENDED" if key == max(
        (k for k, _, _ in CONFIGS if k != "A_cliff"), key=lambda k: r50[k]["net_final"]
    ) else ""
    print(f"  {label:<42} ₹{r['net_final']:>10,.0f}  {r['months_reduced']:>2}/{r['months_total']} mo reduced{marker}")

print()
best_key_50 = max((k for k, _, _ in CONFIGS if k != "A_cliff"), key=lambda k: r50[k]["net_final"])
best_r = r50[best_key_50]
best_label = dict((k,l) for k,l,_ in CONFIGS)[best_key_50]
print(f"  Winner: {best_label}")
print(f"  Net after tax (₹50k start): ₹{best_r['net_final']:,.0f}  ({best_r['total_return_pct']:+.0f}%)")
print(f"  Peak net capital: ₹{best_r['peak_net']:,.0f}")
print(f"  Months in reduced-lots mode: {best_r['months_reduced']}/{best_r['months_total']}")
print(f"  Max drawdown observed: {best_r['max_dd_pct']:.1f}%")
