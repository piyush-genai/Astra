"""
EXP-0020: What the compounding engine produces under the risk limits that are
actually configured — and what the tax-withholding HWM artifact costs.

Motivation (DECISION-010). The validated EXP-0017 stack deploys 30% of net capital
per trade and scales to 20-35 lots. config/risk.yaml permits 25%
(`max_capital_deployed_pct`) and 10 lots (`hard_cap_lots`). So the ₹49.2L figure on
record does not describe the system as it is configured to run, and the choice is
between raising the limits to match a backtest — the failure mode AGENTS.md section
14 warns about — or measuring honestly what the permitted limits deliver.

This experiment measures. It changes no limits and touches no execution path.

Secondary question (DECISION-009). EXP-0017 marks the high-water mark per closed
trade on capital that has not yet had the month's tax withheld. At month close 30%
of the month's profit moves to the reserve, net capital drops below that peak, and
the engine registers a drawdown it never suffered — demoting a tier after
*profitable* months (2023-03 at 0.65x on +₹116,587; 2023-05 at 0.35x on +₹509,869).
One arm re-marks the HWM only at month close, after withholding, to price that.

Method is EXP-0017's: collect the 1,522 one-lot trades once (P70_L40d + VIX×1.1 IV +
VIX tilt), then replay them under each sizing configuration. G1 applies unchanged —
per-lot P&L is assumed independent of position size, so anything above ~15-20 lots
is directional rather than precise. That caveat cuts *against* the high-lot configs,
which is the conservative direction for this question.

Usage:
    python3 scripts/exp_0020_sizing_constraints.py
"""
import sys, math
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
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

# Read the governing limits rather than restating them, so this experiment cannot
# drift out of sync with the config it is measuring against.
CFG_DEPLOY_PCT = risk_cfg["per_trade"]["max_capital_deployed_pct"]
CFG_HARD_LOTS  = risk_cfg["position_limits"]["hard_cap_lots"]

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
VIX_LOOKBACK = 40

TAX_RATE          = 0.30
LOT_STEP          = 5
CONSEC_POS_MONTHS = 3
SLIPPAGE_PER_LOT  = 2 * lot_sz
PREMIUM_FLOOR     = 500.0


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
    """EXP-0017 winner D_steps. Every arm here uses it; only the limits vary."""
    if dd < 0.15:
        return 1.00
    if dd < 0.25:
        return 0.65
    if dd < 0.40:
        return 0.35
    return 0.12


# ── Collect base trades once (identical to EXP-0017, for comparability) ────────
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
    rows.append({
        "net_per_lot":     round(base_net * vix_size_mult(pctile), 2),
        "premium_per_lot": round(leg.entry_premium * lot_sz, 2),
        "month":           t.entry_time.strftime("%Y-%m"),
        "ts":              t.entry_time,
    })

td = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
print(f"  {len(td)} trades | avg pnl/lot: ₹{td['net_per_lot'].mean():+.0f} "
      f"| avg premium/lot: ₹{td['premium_per_lot'].mean():.0f}")
print()


@dataclass(frozen=True)
class SizingConfig:
    key: str
    label: str
    deploy_pct: float          # % of net capital deployable per trade
    initial_max_lots: int
    hard_cap_lots: int | None  # absolute ceiling; None = uncapped growth
    hwm_per_trade: bool = True # False re-marks the HWM only at month close
    compliant: bool = False    # True if it satisfies config/risk.yaml as written


CONFIGS = (
    SizingConfig("validated", "EXP-0017 validated (30%, 20 lots, uncapped)",
                 30.0, 20, None),
    SizingConfig("compliant", f"Config-compliant ({CFG_DEPLOY_PCT:.0f}%, {CFG_HARD_LOTS} lots hard)",
                 CFG_DEPLOY_PCT, CFG_HARD_LOTS, CFG_HARD_LOTS, compliant=True),
    SizingConfig("deploy_only", f"Isolate deploy cap ({CFG_DEPLOY_PCT:.0f}%, 20 lots, uncapped)",
                 CFG_DEPLOY_PCT, 20, None),
    SizingConfig("lots_only", f"Isolate lot cap (30%, {CFG_HARD_LOTS} lots hard)",
                 30.0, CFG_HARD_LOTS, CFG_HARD_LOTS),
    SizingConfig("staged_shadow", f"Staged: shadow ({CFG_DEPLOY_PCT:.0f}%, 20 lots hard)",
                 CFG_DEPLOY_PCT, 10, 20),
    SizingConfig("staged_live", f"Staged: live ({CFG_DEPLOY_PCT:.0f}%, 35 lots hard)",
                 CFG_DEPLOY_PCT, 10, 35),
    SizingConfig("validated_hwm_fix", "EXP-0017 but HWM marked post-tax (artifact removed)",
                 30.0, 20, None, hwm_per_trade=False),
)


def run_config(start_capital: float, cfg: SizingConfig) -> dict:
    capital       = float(start_capital)
    tax_reserve   = 0.0
    hwm           = capital
    base_max_lots = cfg.initial_max_lots
    consec_pos    = 0

    cur_month   = None
    month_pnl   = 0.0
    month_lots: list[int] = []
    monthly: list[dict] = []
    peak_eff_lots = 0

    def close_month() -> None:
        nonlocal capital, tax_reserve, hwm, base_max_lots, consec_pos, month_pnl
        if cur_month is None:
            return
        if month_pnl > 0:
            tax_reserve += month_pnl * TAX_RATE
        net_cap = capital - tax_reserve
        if net_cap > hwm:
            hwm = net_cap
        dd      = max(0.0, (hwm - net_cap) / hwm) if hwm > 0 else 0.0
        mult    = dd_mult_steps(dd)
        reduced = mult < 1.0

        if month_pnl > 0 and not reduced:
            consec_pos += 1
        elif month_pnl <= 0:
            consec_pos = 0
        if consec_pos >= CONSEC_POS_MONTHS:
            proposed = base_max_lots + LOT_STEP
            if cfg.hard_cap_lots is not None:
                proposed = min(proposed, cfg.hard_cap_lots)
            # Only spend the streak if the cap actually moved, so a config pinned at
            # its ceiling does not silently burn qualifying months.
            if proposed > base_max_lots:
                base_max_lots = proposed
                consec_pos = 0

        monthly.append({
            "month": cur_month, "net_capital": round(net_cap, 0),
            "month_pnl": round(month_pnl, 0), "dd_pct": round(dd * 100, 1),
            # eff_max_lots, not base_max_lots — matches exp_0017's log column so the two
            # monthly tables can be diffed directly.
            "lot_mult": round(mult, 2), "max_lots": base_max_lots,
            "eff_max_lots": max(1, int(base_max_lots * mult)),
            "avg_lots": round(float(np.mean(month_lots)) if month_lots else 0.0, 1),
            "reduced": reduced,
        })
        month_pnl = 0.0
        month_lots.clear()

    for _, row in td.iterrows():
        if row["month"] != cur_month:
            close_month()
            cur_month = row["month"]

        net_cap = capital - tax_reserve
        # Mark the HWM here, BEFORE this trade's P&L — matching exp_0017 line 201. The
        # ordering is load-bearing: marking after the trade instead would capture the
        # final trade of each month as a peak that month-end withholding then undercuts,
        # deepening every tier by one notch. That shifts 2023-03 from 0.65x to 0.35x and
        # costs ~0.7% of the three-year outcome.
        if cfg.hwm_per_trade and net_cap > hwm:
            hwm = net_cap
        dd      = max(0.0, (hwm - net_cap) / hwm) if hwm > 0 else 0.0
        mult    = dd_mult_steps(dd)
        eff_max = max(1, int(base_max_lots * mult))

        prem_per_lot  = max(row["premium_per_lot"], PREMIUM_FLOOR)
        lots_from_cap = max(1, int(net_cap * (cfg.deploy_pct / 100.0) / prem_per_lot))
        lots          = min(lots_from_cap, eff_max)
        peak_eff_lots = max(peak_eff_lots, lots)

        extra_slip = max(0, lots - 10) * SLIPPAGE_PER_LOT
        trade_pnl  = row["net_per_lot"] * lots - extra_slip
        capital    = max(capital + trade_pnl, 500.0)
        month_pnl += trade_pnl
        month_lots.append(lots)

    close_month()

    net_final = capital - tax_reserve
    nets      = [m["net_capital"] for m in monthly]
    running_peak, max_dd = -math.inf, 0.0
    for n in nets:
        running_peak = max(running_peak, n)
        if running_peak > 0:
            max_dd = max(max_dd, (running_peak - n) / running_peak)

    return {
        "key": cfg.key, "label": cfg.label, "compliant": cfg.compliant,
        "net_after_tax": net_final,
        "return_pct": (net_final - start_capital) / start_capital * 100,
        "tax_reserve": tax_reserve,
        "max_dd_pct": max_dd * 100,
        "months_reduced": sum(1 for m in monthly if m["reduced"]),
        "total_months": len(monthly),
        "final_max_lots": monthly[-1]["max_lots"] if monthly else cfg.initial_max_lots,
        "peak_lots_traded": peak_eff_lots,
        "monthly": monthly,
    }


def main() -> int:
    print("=" * 94)
    print("EXP-0020: SIZING UNDER CONFIGURED RISK LIMITS")
    print("=" * 94)
    print(f"  config/risk.yaml: max_capital_deployed_pct={CFG_DEPLOY_PCT} | "
          f"hard_cap_lots={CFG_HARD_LOTS}")
    print(f"  All arms use D_steps tiers, 30% tax reserve, slippage above 10 lots.")
    print()

    for start in (50_000.0, 20_000.0):
        print("=" * 94)
        print(f"  START CAPITAL: ₹{start:,.0f}")
        print("=" * 94)
        print(f"  {'Config':<52}{'Net ₹':>13}{'Return':>10}{'MaxDD':>8}{'Mo↓':>7}{'PkLots':>8}")
        print("  " + "-" * 90)

        results = [run_config(start, c) for c in CONFIGS]
        baseline = next(r for r in results if r["key"] == "validated")

        for r in results:
            flag = " ✓cfg" if r["compliant"] else ""
            print(f"  {r['label']:<52}{r['net_after_tax']:>13,.0f}"
                  f"{r['return_pct']:>9.0f}%{r['max_dd_pct']:>7.1f}%"
                  f"{r['months_reduced']:>4}/{r['total_months']:<2}"
                  f"{r['peak_lots_traded']:>8}{flag}")

        print()
        comp = next(r for r in results if r["compliant"])
        gap  = (1 - comp["net_after_tax"] / baseline["net_after_tax"]) * 100
        print(f"  Compliance cost: ₹{baseline['net_after_tax']:,.0f} → "
              f"₹{comp['net_after_tax']:,.0f}  ({gap:.1f}% of the validated outcome forgone)")
        hwm_fix = next(r for r in results if r["key"] == "validated_hwm_fix")
        delta   = (hwm_fix["net_after_tax"] / baseline["net_after_tax"] - 1) * 100
        print(f"  HWM artifact:    removing it moves the validated config "
              f"₹{baseline['net_after_tax']:,.0f} → ₹{hwm_fix['net_after_tax']:,.0f} "
              f"({delta:+.1f}%), months reduced {baseline['months_reduced']}→"
              f"{hwm_fix['months_reduced']}")
        print()

    print("=" * 94)
    print("  Reminder: G1 applies. Per-lot P&L is assumed independent of position size, so")
    print("  configs peaking above ~15-20 lots are directional, not precise. That caveat")
    print("  penalises the high-lot arms, i.e. it understates the case for compliance.")
    print("=" * 94)
    return 0


if __name__ == "__main__":
    sys.exit(main())
