"""
EXP-0016: Compounded equity simulation — full 3-year projection with
taxes, slippage at scale, and drawdown brakes.

The fixed-1-lot research backtests (EXP-0001 through EXP-0015) measure
SIGNAL QUALITY in isolation. This experiment measures CAPITAL GROWTH when
profits are compounded — i.e., what happens when you reinvest gains into
more lots each month.

Three real-world deductions not in prior experiments:
  1. Tax (30% STCG on options profits — India FY basis)
  2. Slippage at scale (NIFTY ATM options bid-ask widens beyond ~25 lots)
  3. Drawdown brake (freeze lot count if capital falls 35% from peak)

Strategy stack used (all validated):
  - P70_L40d adaptive ATR regime filter
  - VIX×1.1 dynamic IV pricing
  - VIX tilt sizing (sweet 1.5x / danger 0.5x / else 1x) — only at base 1-lot level;
    the lot-count compounding sits on top of the VIX tilt

Lot sizing rule:
  lots = min(floor(capital × RISK_PER_TRADE / premium_per_lot), max_lots_cap)
  RISK_PER_TRADE = 0.30  (30% of current capital deployed per trade max)
  max_lots_cap   = 10 initially; +5 every 3 consecutive profitable months

Tax model:
  Monthly: if month's net P&L > 0, add 30% of that profit to tax_reserve.
  Tax reserve is NOT available for lot sizing.
  Effective capital for sizing = total_capital - tax_reserve.

Slippage model:
  Above 10 lots per trade, each additional lot costs ₹2/unit extra in spread.
  Extra slippage = max(0, lots - 10) × 2 × lot_size
  This is conservative — NIFTY ATM options usually have ₹1-2 spread.
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
    open=("open","first"), high=("high","max"), low=("low","min"), close=("close","last"),
).dropna()
tr = pd.concat([df["high"]-df["low"], (df["high"]-df["close"].shift(1)).abs(),
                (df["low"]-df["close"].shift(1)).abs()], axis=1).max(axis=1)
df["atr10"]  = tr.rolling(10).mean()
atr_mask     = df["atr10"] > df["atr10"].rolling(3000).quantile(0.70)

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

def vix_size_mult(pctile: float) -> float:
    if 50 <= pctile < 60: return 1.5
    if 60 <= pctile < 75: return 0.5
    return 1.0


# ── Collect base trades (1 lot, VIX tilt sizing baked in as multiplier) ───────
print("Collecting P70_L40d trades (VIX×1.1 IV, 2023-2025)...")
pricer = OptionsPricer(lot_size=lot_sz, expiry_weekday=nifty_cfg["weekly_expiry_weekday"],
    strike_step=nifty_cfg["strike_step"], iv=0.14, iv_fn=vix_iv_fn)
filtered = df[atr_mask | df["atr10"].isna()]
strategy = PivotCprStrategy(config={"tolerance_pct":0.18,"min_levels_for_confluence":2,
    "momentum_enabled":True,"momentum_body_pct":0.50,"momentum_accel_multiplier":1.8,"momentum_min_criteria":2})
strategy._daily_ohlc = daily_ohlcv
harness = BacktestHarness(strategy=strategy, instruments_config=instruments_cfg,
    risk_config=risk_cfg, cooldown_minutes=0, allow_hedge=True, initial_capital=20_000.0)
result = harness.run(filtered[["open","high","low","close","volume"]], pricer=pricer)

rows = []
for t in result.trades:
    dirn = "LONG" if t.direction == SignalDirection.LONG else "SHORT"
    leg  = pricer.price_trade(dirn, t.entry_price, t.entry_time, t.exit_price, t.exit_time)
    base_net = leg.pnl_rupees - (brok*2 + leg.entry_premium*stt_pct*lot_sz + 5.0)
    # VIX bucket sizing multiplier
    entry_day = t.entry_time.normalize()
    try:
        vix_val = vix_daily["vix"].reindex([entry_day], method="ffill").iloc[0]
        hist    = vix_daily["vix"].loc[:entry_day].tail(VIX_LOOKBACK)
        pctile  = float((hist < vix_val).mean() * 100)
    except: pctile = 50.0
    mult = vix_size_mult(pctile)
    rows.append({
        "net_per_lot": round(base_net * mult, 2),  # VIX tilt already applied
        "premium_per_lot": round(leg.entry_premium * lot_sz, 2),
        "month": t.entry_time.strftime("%Y-%m"),
        "ts":    t.entry_time,
    })

td = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
print(f"  {len(td)} trades | avg pnl/lot (1x, with VIX tilt): ₹{td['net_per_lot'].mean():+.0f}")
print(f"  avg premium/lot: ₹{td['premium_per_lot'].mean():.0f}")
print()


# ── Compounding simulation ─────────────────────────────────────────────────────
RISK_PER_TRADE   = 0.30     # max 30% of capital per trade (premium cost)
TAX_RATE         = 0.30     # 30% STCG on monthly profit
DD_BRAKE_PCT     = 0.35     # freeze lot count if capital drops 35% from peak
BASE_MAX_LOTS    = 10       # starting max lots cap
LOT_STEP         = 5        # add this many max lots every CONSEC_POS_MONTHS positive months
CONSEC_POS_MONTHS = 3       # consecutive profitable months to unlock more lots
SLIPPAGE_PER_LOT = 2 * lot_sz  # ₹2/unit extra spread per lot above 10

def run_compounding(start_capital: float, initial_max_lots: int, label: str):
    capital      = float(start_capital)
    tax_reserve  = 0.0
    peak_capital = capital
    max_lots     = initial_max_lots
    consec_pos   = 0
    dd_brake     = False

    monthly_log  = []
    current_month = None
    month_pnl     = 0.0
    month_lots    = []

    def close_month():
        nonlocal capital, tax_reserve, peak_capital, max_lots, consec_pos, dd_brake, month_pnl
        if current_month is None: return
        # Tax
        if month_pnl > 0:
            tax = month_pnl * TAX_RATE
            tax_reserve += tax
        # Consecutive month counter for lot-cap unlock
        if month_pnl > 0:
            consec_pos += 1
        else:
            consec_pos = 0
        if consec_pos >= CONSEC_POS_MONTHS:
            max_lots += LOT_STEP
            consec_pos = 0
        # Drawdown brake check
        net_capital = capital - tax_reserve
        if net_capital > peak_capital:
            peak_capital = net_capital
            dd_brake = False
        elif peak_capital > 0 and (peak_capital - net_capital) / peak_capital >= DD_BRAKE_PCT:
            dd_brake = True
        avg_lots = np.mean(month_lots) if month_lots else 0
        monthly_log.append({
            "month": current_month, "capital": round(capital, 0),
            "tax_reserve": round(tax_reserve, 0), "net_capital": round(capital - tax_reserve, 0),
            "month_pnl": round(month_pnl, 0), "avg_lots": round(avg_lots, 1),
            "max_lots": max_lots, "dd_brake": dd_brake,
        })
        month_pnl = 0.0
        month_lots.clear()

    for _, row in td.iterrows():
        if row["month"] != current_month:
            close_month()
            current_month = row["month"]

        net_capital   = capital - tax_reserve
        prem_per_lot  = max(row["premium_per_lot"], 500.0)

        # Lot sizing
        if dd_brake:
            lots = 1  # frozen at minimum during brake
        else:
            lots_from_cap = max(1, int(net_capital * RISK_PER_TRADE / prem_per_lot))
            lots = min(lots_from_cap, max_lots)

        # Slippage at scale (above 10 lots)
        extra_slip = max(0, lots - 10) * SLIPPAGE_PER_LOT
        trade_pnl  = row["net_per_lot"] * lots - extra_slip
        capital   += trade_pnl
        capital    = max(capital, 500.0)
        month_pnl += trade_pnl
        month_lots.append(lots)

    close_month()  # final month

    total_return = (capital - tax_reserve - start_capital) / start_capital * 100
    print(f"\n{'='*68}")
    print(f"  {label}")
    print(f"{'='*68}")
    print(f"  Start: ₹{start_capital:>10,.0f}  |  Max lots cap (final): {max_lots}")
    print(f"  Gross capital:     ₹{capital:>12,.0f}")
    print(f"  Tax reserve:       ₹{tax_reserve:>12,.0f}")
    print(f"  Net (after tax):   ₹{capital-tax_reserve:>12,.0f}  ({total_return:+.0f}% on start)")
    print()
    print(f"  {'Month':<10} {'Net cap ₹':>12} {'Mo PnL ₹':>12} {'Avg lots':>9} {'MaxLots':>8} {'Brake':>6}")
    print(f"  {'-'*58}")
    for r in monthly_log:
        brake_str = "⛔" if r["dd_brake"] else ""
        print(f"  {r['month']:<10} {r['net_capital']:>+12,.0f} {r['month_pnl']:>+12,.0f} "
              f"{r['avg_lots']:>9.1f} {r['max_lots']:>8} {brake_str:>6}")

    return capital - tax_reserve


# ── Run scenarios ─────────────────────────────────────────────────────────────
print("=" * 68)
print("EXP-0016: COMPOUNDED EQUITY SIMULATION (2023-2025)")
print("  Includes: 30% tax reserve, slippage at scale, drawdown brake")
print("=" * 68)

scenarios = [
    (20_000,  10, "SCENARIO A — ₹20k start, 10-lot initial cap (conservative)"),
    (50_000,  20, "SCENARIO B — ₹50k start, 20-lot initial cap (moderate)"),
    (20_000,  25, "SCENARIO C — ₹20k start, 25-lot initial cap (growth mode)"),
]

results = {}
for start_cap, init_max, label in scenarios:
    net = run_compounding(start_cap, init_max, label)
    results[label] = net

print()
print("=" * 68)
print("SUMMARY — net after tax, 3 years (Jan 2023 – Dec 2025)")
print("=" * 68)
for label, net in results.items():
    start_cap = int(label.split("₹")[1].split("k")[0]) * 1000
    print(f"  {label.split('—')[1].strip():<45} → ₹{net:>12,.0f}")
print()
print("  Key risks in live trading not modeled here:")
print("  1. Strategy degradation (future returns ≠ past)")
print("  2. Market impact beyond the slippage model (>50 lots)")
print("  3. Psychological: May 2024 = -30.8% month at ₹7.76L capital = -₹2.4L loss")
print("  4. SEBI regulations (Algo-ID mandatory April 2026)")
print("  5. Tax is modeled as 30% STCG flat; actual tax may vary with ITR filing")
