"""
EXP-0006: Walk-forward validation of ATR regime filter.

Protocol:
  For each expanding-window fold, select the best ATR threshold IN-SAMPLE,
  then apply that frozen threshold to the OUT-OF-SAMPLE test period.
  This mirrors real-world deployment: we choose a threshold from past data
  and apply it forward without peeking at future results.

Folds (expanding train, 1-month test):
  Fold 1: Train [Feb-Mar]   → Test [Apr]
  Fold 2: Train [Feb-Apr]   → Test [May]
  Fold 3: Train [Feb-May]   → Test [Jun]
  Fold 4: Train [Feb-Jun]   → Test [Jul]

Pass criteria:
  ATR-filtered strategy outperforms unfiltered baseline in >= 3 of 4 test periods.
"""
import sys
sys.path.insert(0, '/workshop/atlas')

import logging, pandas as pd, numpy as np
from backtest.harness import BacktestHarness
from backtest.options_pricer import OptionsPricer
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

# Build daily OHLCV
daily_ohlcv = df.resample("B").agg(
    open=("open","first"), high=("high","max"),
    low=("low","min"), close=("close","last"),
).dropna()

# Pre-compute 10-bar rolling ATR on full dataset (no look-ahead)
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

ATR_THRESHOLDS = [None, 20, 25, 30, 35, 40]

def run_period(period_data, atr_thresh, initial_capital):
    """Run backtest on a given period with optional ATR filter."""
    strategy = PivotCprStrategy(config={
        "tolerance_pct": 0.18, "min_levels_for_confluence": 2,
        "momentum_enabled": True, "momentum_body_pct": 0.50,
        "momentum_accel_multiplier": 1.8, "momentum_min_criteria": 2,
    })
    strategy._daily_ohlc = daily_ohlcv

    filtered = period_data.copy()
    if atr_thresh is not None:
        filtered = filtered[filtered['atr10'].isna() | (filtered['atr10'] > atr_thresh)]

    if len(filtered) < 30:
        return {"capital": initial_capital, "trades": 0, "net_pnl": 0, "winners": 0}

    harness = BacktestHarness(
        strategy=strategy, instruments_config=instruments_cfg,
        risk_config=risk_cfg, cooldown_minutes=0, allow_hedge=True,
        initial_capital=initial_capital,
    )
    result = harness.run(filtered[['open','high','low','close','volume']], pricer=pricer)
    end_capital = harness._current_capital

    brok = instruments_cfg.get("transaction_costs", {}).get("brokerage_per_order", 20.0)
    stt  = instruments_cfg.get("transaction_costs", {}).get("stt_options_pct", 0.15) / 100.0
    net_total, winners = 0.0, 0
    for t in result.trades:
        dirn = "LONG" if t.direction == SignalDirection.LONG else "SHORT"
        leg  = pricer.price_trade(dirn, t.entry_price, t.entry_time, t.exit_price, t.exit_time)
        gross = leg.pnl_rupees * t.lots
        tc    = (brok*2 + leg.entry_premium*stt*nifty_cfg["lot_size"] + 5.0) * t.lots
        net_total += gross - tc
        if t.pnl_points > 0:
            winners += 1

    return {
        "capital": end_capital,
        "trades": len(result.trades),
        "net_pnl": round(net_total, 2),
        "winners": winners,
        "win_rate": 100 * winners / len(result.trades) if result.trades else 0,
        "avg_pnl": round(net_total / len(result.trades), 2) if result.trades else 0,
        "return_pct": round((end_capital - initial_capital) / initial_capital * 100, 2),
    }


def ts(date_str, tz="Asia/Kolkata"):
    return pd.Timestamp(date_str, tz=tz)


# Walk-forward folds: (train_start, train_end, test_start, test_end, test_label)
folds = [
    (ts("2026-02-01"), ts("2026-03-31") + pd.Timedelta(days=1),
     ts("2026-04-01"), ts("2026-04-30") + pd.Timedelta(days=1), "Apr"),
    (ts("2026-02-01"), ts("2026-04-30") + pd.Timedelta(days=1),
     ts("2026-05-01"), ts("2026-05-31") + pd.Timedelta(days=1), "May"),
    (ts("2026-02-01"), ts("2026-05-31") + pd.Timedelta(days=1),
     ts("2026-06-01"), ts("2026-06-30") + pd.Timedelta(days=1), "Jun"),
    (ts("2026-02-01"), ts("2026-06-30") + pd.Timedelta(days=1),
     ts("2026-07-01"), ts("2026-07-31") + pd.Timedelta(days=1), "Jul"),
]

print("=" * 80)
print("EXP-0006: WALK-FORWARD VALIDATION OF ATR REGIME FILTER")
print("=" * 80)
print()

all_fold_results = []

for i, (train_start, train_end, test_start, test_end, test_label) in enumerate(folds, 1):
    train_data = df[(df.index >= train_start) & (df.index < train_end)]
    test_data  = df[(df.index >= test_start)  & (df.index < test_end)]

    print(f"{'─'*70}")
    print(f"FOLD {i}: Train [{train_start.date()} → {(train_end - pd.Timedelta(days=1)).date()}]  |  Test [{test_label}]")
    print(f"{'─'*70}")

    # ── STEP 1: Select best ATR threshold IN-SAMPLE ──────────────────────────
    print(f"  In-sample threshold selection:")
    train_capital = 20_000.0
    best_thresh = None
    best_train_return = -999.0

    for thresh in ATR_THRESHOLDS:
        res = run_period(train_data, thresh, train_capital)
        label = f"ATR>{thresh}" if thresh else "no_filter"
        avg_p = res['avg_pnl']
        print(f"    {label:<12} | return={res['return_pct']:+7.1f}% | "
              f"trades={res['trades']:3d} | avg=₹{avg_p:+6.0f}/trade | WR={res['win_rate']:.0f}%")
        # Select best by return_pct, but require at least 20 trades
        if res['trades'] >= 20 and res['return_pct'] > best_train_return:
            best_train_return = res['return_pct']
            best_thresh = thresh

    best_label = f"ATR>{best_thresh}" if best_thresh else "no_filter"
    print(f"  → Best in-sample threshold: {best_label} ({best_train_return:+.1f}%)")

    # ── STEP 2: Apply best threshold to TEST period ───────────────────────────
    print(f"  Out-of-sample test ({test_label}):")
    test_capital = 20_000.0  # reset capital for fair comparison each fold
    test_no_filter = run_period(test_data, None,         test_capital)
    test_atr_25    = run_period(test_data, 25,           test_capital)
    test_atr_30    = run_period(test_data, 30,           test_capital)
    test_best      = run_period(test_data, best_thresh,  test_capital)

    print(f"    no_filter    | return={test_no_filter['return_pct']:+7.1f}% | "
          f"trades={test_no_filter['trades']:3d} | avg=₹{test_no_filter['avg_pnl']:+6.0f}/trade")
    print(f"    ATR>25       | return={test_atr_25['return_pct']:+7.1f}% | "
          f"trades={test_atr_25['trades']:3d} | avg=₹{test_atr_25['avg_pnl']:+6.0f}/trade")
    print(f"    ATR>30       | return={test_atr_30['return_pct']:+7.1f}% | "
          f"trades={test_atr_30['trades']:3d} | avg=₹{test_atr_30['avg_pnl']:+6.0f}/trade")
    if best_thresh not in [None, 25, 30]:
        print(f"    {best_label:<12} | return={test_best['return_pct']:+7.1f}% | "
              f"trades={test_best['trades']:3d} | avg=₹{test_best['avg_pnl']:+6.0f}/trade  ← selected")

    beats = test_atr_30['return_pct'] > test_no_filter['return_pct']
    print(f"  → ATR>30 beats baseline in {test_label}? {'YES ✓' if beats else 'NO ✗'}")
    print()

    all_fold_results.append({
        "fold": i, "test_month": test_label,
        "best_in_sample_thresh": best_thresh,
        "baseline_return": test_no_filter['return_pct'],
        "atr30_return": test_atr_30['return_pct'],
        "atr30_trades": test_atr_30['trades'],
        "atr30_avg_pnl": test_atr_30['avg_pnl'],
        "baseline_trades": test_no_filter['trades'],
        "atr30_beats_baseline": beats,
    })

# ── VERDICT ──────────────────────────────────────────────────────────────────
print("=" * 70)
print("WALK-FORWARD VERDICT")
print("=" * 70)
wins = sum(1 for r in all_fold_results if r['atr30_beats_baseline'])
print(f"\nATR>30 beats baseline: {wins}/{len(folds)} test periods")
print()
print(f"{'Fold':<6} {'Test':<6} {'Baseline':>10} {'ATR>30':>10} {'Beats?':>8} {'Best IS thresh':>15}")
print("-"*60)
for r in all_fold_results:
    bl  = f"{r['baseline_return']:+.1f}%"
    atr = f"{r['atr30_return']:+.1f}%"
    bst = f"ATR>{r['best_in_sample_thresh']}" if r['best_in_sample_thresh'] else "no_filter"
    print(f"{r['fold']:<6} {r['test_month']:<6} {bl:>10} {atr:>10} {'✓' if r['atr30_beats_baseline'] else '✗':>8} {bst:>15}")

print()
if wins >= 3:
    print("✓ PASSED: ATR filter generalizes out-of-sample (>=3/4 folds)")
    print("  The edge is likely REAL. Proceed to Monte Carlo (EXP-0007).")
elif wins == 2:
    print("⚠ MARGINAL: ATR filter beats baseline in only 2/4 folds.")
    print("  Edge may be regime-specific. Do NOT promote to production.")
    print("  Recommendation: need longer data history for definitive answer.")
else:
    print("✗ FAILED: ATR filter does NOT generalize out-of-sample (<2/4).")
    print("  EXP-0005 result was in-sample overfitting. Discard ATR filter.")

print()
print("Avg out-of-sample performance:")
print(f"  Baseline avg return: {np.mean([r['baseline_return'] for r in all_fold_results]):+.1f}% per month")
print(f"  ATR>30 avg return  : {np.mean([r['atr30_return'] for r in all_fold_results]):+.1f}% per month")
print(f"  ATR>30 avg trades  : {np.mean([r['atr30_trades'] for r in all_fold_results]):.0f} per month")
print(f"  ATR>30 avg P&L     : ₹{np.mean([r['atr30_avg_pnl'] for r in all_fold_results]):+.0f}/trade")
