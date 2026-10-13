"""
EXP-0021: Monte Carlo over the sizing arms — does the staged lot-cap recommendation
hold on a distribution, or only on the one historical path?

EXP-0020 compared sizing configurations on the single realised 2023-2025 sequence and
concluded that a staged lot ceiling (10 → 20 → 35) recovers 80-84% of the validated
outcome at materially lower drawdown. That is one path. Its CAVEAT-3 flagged that a
recommendation about risk limits should rest on a distribution, which is what this
experiment supplies.

Resampling unit: the MONTH, not the trade. The compounding engine has a monthly cadence
— tax is withheld at month close, the lot cap grows on monthly streaks, the drawdown
tier is re-evaluated against a monthly high-water mark. Resampling individual trades
(as EXP-0012 did, correctly, for signal quality) would destroy that structure and the
within-month ordering the tier logic responds to. So each simulation draws 34 month
blocks with replacement from the 34 observed months and replays them in the drawn
order, preserving each month's internal trade sequence intact.

What this does NOT do: generate unseen market conditions. A block bootstrap recombines
observed months, so every simulated path is built from regimes that actually occurred
in 2023-2025. It measures sensitivity to the ORDER and REPETITION of those regimes —
which is the relevant question for a drawdown-tiered engine, since tier behaviour
depends heavily on whether bad months cluster — but it cannot price a regime absent
from the sample.

Usage:
    python3 scripts/exp_0021_sizing_monte_carlo.py [--sims N]
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import logging
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.harness import BacktestHarness
from backtest.options_pricer import OptionsPricer
from core.config_loader import load_instruments, load_risk
from core.engine.base_strategy import SignalDirection
from strategies.pivot_cpr_strategy import PivotCprStrategy

logging.basicConfig(level=logging.WARNING)

DATA_PATH = Path("data/live_data/nifty_5min_20230101_to_20251231.csv")
VIX_PATH  = Path("data/live_data/india_vix_daily_20230101_to_20251231.csv")
for p in (DATA_PATH, VIX_PATH):
    if not p.exists():
        sys.exit(f"Missing {p} — run scripts/data_001_fetch_historical.py / data_002_fetch_vix.py")

instruments_cfg = load_instruments()
risk_cfg        = load_risk()
nifty_cfg       = instruments_cfg["instruments"]["NIFTY"]
CFG_DEPLOY_PCT  = risk_cfg["per_trade"]["max_capital_deployed_pct"]
CFG_HARD_LOTS   = risk_cfg["position_limits"]["hard_cap_lots"]

SEED              = 42      # EXP-0012 used 42; keep it so seeds are consistent across the repo
TAX_RATE          = 0.30
LOT_STEP          = 5
CONSEC_POS_MONTHS = 3
PREMIUM_FLOOR     = 500.0
RUIN_THRESHOLD    = 0.50    # same definition as EXP-0012: max drawdown >= 50%

df = pd.read_csv(DATA_PATH, parse_dates=["timestamp"], index_col="timestamp")
df.index = pd.DatetimeIndex(df.index)
vix_daily = pd.read_csv(VIX_PATH, parse_dates=["date"], index_col="date")
vix_daily.index = pd.DatetimeIndex(vix_daily.index)

daily_ohlcv = df.resample("B").agg(
    open=("open", "first"), high=("high", "max"),
    low=("low", "min"), close=("close", "last"),
).dropna()
tr = pd.concat([df["high"] - df["low"],
                (df["high"] - df["close"].shift(1)).abs(),
                (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1)
df["atr10"] = tr.rolling(10).mean()
atr_mask    = df["atr10"] > df["atr10"].rolling(3000).quantile(0.70)

brok    = instruments_cfg.get("transaction_costs", {}).get("brokerage_per_order", 20.0)
stt_pct = instruments_cfg.get("transaction_costs", {}).get("stt_options_pct", 0.15) / 100.0
lot_sz  = nifty_cfg["lot_size"]
SLIPPAGE_PER_LOT = 2 * lot_sz
VIX_LOOKBACK = 40


def vix_iv_fn(ts):
    day = ts.normalize()
    try:
        val = vix_daily["vix"].reindex([day], method="ffill").iloc[0]
        return (val / 100.0) * 1.1 if not pd.isna(val) else 0.14
    except Exception:
        return 0.14


def vix_size_mult(pctile: float) -> float:
    if 50 <= pctile < 60:
        return 1.5
    if 60 <= pctile < 75:
        return 0.5
    return 1.0


def dd_mult_steps(dd: float) -> float:
    if dd < 0.15:
        return 1.00
    if dd < 0.25:
        return 0.65
    if dd < 0.40:
        return 0.35
    return 0.12


# ── Collect base trades once ───────────────────────────────────────────────────
print("Collecting P70_L40d trades (VIX×1.1 IV + VIX tilt, 2023-2025)...")
pricer = OptionsPricer(lot_size=lot_sz, expiry_weekday=nifty_cfg["weekly_expiry_weekday"],
                       strike_step=nifty_cfg["strike_step"], iv=0.14, iv_fn=vix_iv_fn)
filtered = df[atr_mask | df["atr10"].isna()]
strategy = PivotCprStrategy(config={
    "tolerance_pct": 0.18, "min_levels_for_confluence": 2, "momentum_enabled": True,
    "momentum_body_pct": 0.50, "momentum_accel_multiplier": 1.8, "momentum_min_criteria": 2,
})
strategy._daily_ohlc = daily_ohlcv
harness = BacktestHarness(strategy=strategy, instruments_config=instruments_cfg,
                          risk_config=risk_cfg, cooldown_minutes=0, allow_hedge=True,
                          initial_capital=20_000.0)
result = harness.run(filtered[["open", "high", "low", "close", "volume"]], pricer=pricer)

rows = []
for t in result.trades:
    dirn = "LONG" if t.direction == SignalDirection.LONG else "SHORT"
    leg  = pricer.price_trade(dirn, t.entry_price, t.entry_time, t.exit_price, t.exit_time)
    base_net = leg.pnl_rupees - (brok * 2 + leg.entry_premium * stt_pct * lot_sz + 5.0)
    entry_day = t.entry_time.normalize()
    try:
        vix_val = vix_daily["vix"].reindex([entry_day], method="ffill").iloc[0]
        hist    = vix_daily["vix"].loc[:entry_day].tail(VIX_LOOKBACK)
        pctile  = float((hist < vix_val).mean() * 100)
    except Exception:
        pctile = 50.0
    rows.append((round(base_net * vix_size_mult(pctile), 2),
                 round(leg.entry_premium * lot_sz, 2),
                 t.entry_time.strftime("%Y-%m")))

# Group into month blocks of plain tuples — pandas iterrows is far too slow to run
# thousands of simulations through.
month_keys = sorted({r[2] for r in rows})
MONTH_BLOCKS: list[list[tuple[float, float]]] = [
    [(r[0], max(r[1], PREMIUM_FLOOR)) for r in rows if r[2] == mk] for mk in month_keys
]
N_MONTHS = len(MONTH_BLOCKS)
print(f"  {len(rows)} trades across {N_MONTHS} months "
      f"({min(len(b) for b in MONTH_BLOCKS)}-{max(len(b) for b in MONTH_BLOCKS)} trades/month)")
print()


@dataclass(frozen=True)
class Arm:
    key: str
    label: str
    deploy_pct: float
    initial_max_lots: int
    hard_cap_lots: int | None


ARMS = (
    Arm("validated",  "Validated (30%, 20 lots, uncapped)",      30.0, 20, None),
    Arm("compliant",  f"Compliant ({CFG_DEPLOY_PCT:.0f}%, {CFG_HARD_LOTS} lots)",
        CFG_DEPLOY_PCT, CFG_HARD_LOTS, CFG_HARD_LOTS),
    Arm("staged_20",  f"Staged shadow ({CFG_DEPLOY_PCT:.0f}%, 20 lots)",
        CFG_DEPLOY_PCT, 10, 20),
    Arm("staged_35",  f"Staged live ({CFG_DEPLOY_PCT:.0f}%, 35 lots)",
        CFG_DEPLOY_PCT, 10, 35),
)


def simulate(blocks: list[list[tuple[float, float]]], arm: Arm, start_capital: float) -> tuple[float, float]:
    """Replay a month-block sequence under one arm. Returns (net_after_tax, max_dd)."""
    capital       = start_capital
    tax_reserve   = 0.0
    hwm           = start_capital
    base_max_lots = arm.initial_max_lots
    consec_pos    = 0
    deploy        = arm.deploy_pct / 100.0

    peak_net = start_capital
    max_dd   = 0.0

    for block in blocks:
        month_pnl = 0.0
        for net_per_lot, prem in block:
            net_cap = capital - tax_reserve
            if net_cap > hwm:          # mark before sizing — see EXP-0020 harness_validation
                hwm = net_cap
            dd      = max(0.0, (hwm - net_cap) / hwm) if hwm > 0 else 0.0
            mult    = dd_mult_steps(dd)
            eff_max = max(1, int(base_max_lots * mult))

            lots = min(max(1, int(net_cap * deploy / prem)), eff_max)
            trade_pnl = net_per_lot * lots - max(0, lots - 10) * SLIPPAGE_PER_LOT
            capital   = max(capital + trade_pnl, 500.0)
            month_pnl += trade_pnl

        # month close
        if month_pnl > 0:
            tax_reserve += month_pnl * TAX_RATE
        net_cap = capital - tax_reserve
        if net_cap > hwm:
            hwm = net_cap
        reduced = dd_mult_steps(max(0.0, (hwm - net_cap) / hwm) if hwm > 0 else 0.0) < 1.0

        if month_pnl > 0 and not reduced:
            consec_pos += 1
        elif month_pnl <= 0:
            consec_pos = 0
        if consec_pos >= CONSEC_POS_MONTHS:
            proposed = base_max_lots + LOT_STEP
            if arm.hard_cap_lots is not None:
                proposed = min(proposed, arm.hard_cap_lots)
            if proposed > base_max_lots:
                base_max_lots = proposed
                consec_pos = 0

        peak_net = max(peak_net, net_cap)
        if peak_net > 0:
            max_dd = max(max_dd, (peak_net - net_cap) / peak_net)

    return capital - tax_reserve, max_dd


def pct(a: np.ndarray, q: float) -> float:
    return float(np.percentile(a, q))


def main() -> int:
    parser = argparse.ArgumentParser(description="Monte Carlo over sizing arms.")
    parser.add_argument("--sims", type=int, default=2000, help="simulations per arm (default 2000)")
    parser.add_argument("--start", type=float, default=50_000.0, help="start capital")
    args = parser.parse_args()

    rng = np.random.default_rng(SEED)
    # One shared set of month orderings across all arms, so arms are compared on identical
    # paths rather than on independent draws. Paired comparison, far lower variance.
    orderings = rng.integers(0, N_MONTHS, size=(args.sims, N_MONTHS))

    print("=" * 92)
    print(f"EXP-0021: MONTE CARLO OVER SIZING ARMS  ({args.sims:,} sims, "
          f"month-block bootstrap, seed {SEED})")
    print("=" * 92)
    print(f"  Start capital ₹{args.start:,.0f} | all arms share the same {args.sims:,} "
          f"month orderings (paired)")
    print()

    results: dict[str, dict] = {}
    for arm in ARMS:
        nets, dds = np.empty(args.sims), np.empty(args.sims)
        for i in range(args.sims):
            blocks = [MONTH_BLOCKS[j] for j in orderings[i]]
            nets[i], dds[i] = simulate(blocks, arm, args.start)
        results[arm.key] = {
            "label": arm.label, "nets": nets, "dds": dds,
            "median": pct(nets, 50), "p5": pct(nets, 5), "p25": pct(nets, 25),
            "p75": pct(nets, 75), "p95": pct(nets, 95),
            "median_dd": pct(dds, 50) * 100, "p95_dd": pct(dds, 95) * 100,
            "p_ruin": float((dds >= RUIN_THRESHOLD).mean()) * 100,
            "p_loss": float((nets < args.start).mean()) * 100,
        }
        print(f"  {arm.label:<42} done")
    print()

    print(f"  {'Arm':<42}{'p5 ₹':>12}{'median ₹':>13}{'p95 ₹':>13}{'medDD':>8}{'P(ruin)':>9}")
    print("  " + "-" * 88)
    for arm in ARMS:
        r = results[arm.key]
        print(f"  {r['label']:<42}{r['p5']:>12,.0f}{r['median']:>13,.0f}"
              f"{r['p95']:>13,.0f}{r['median_dd']:>7.1f}%{r['p_ruin']:>8.1f}%")
    print()

    base = results["validated"]
    print("  Paired comparison vs the validated arm (same path, every sim):")
    for key in ("compliant", "staged_20", "staged_35"):
        r = results[key]
        ratio = r["nets"] / base["nets"]
        beats = float((r["nets"] > base["nets"]).mean()) * 100
        print(f"    {r['label']:<42} median ratio {pct(ratio, 50):.2f}x  "
              f"beats validated in {beats:>5.1f}% of paths  "
              f"P(ruin) {r['p_ruin']:.1f}% vs {base['p_ruin']:.1f}%")
    print()
    print("  Note: a block bootstrap recombines OBSERVED months. It measures sensitivity to")
    print("  the order and repetition of 2023-2025 regimes, not to unseen market conditions.")
    print("  G1 still applies — arms reaching 30+ lots are directional.")
    print("=" * 92)
    return 0


if __name__ == "__main__":
    sys.exit(main())
