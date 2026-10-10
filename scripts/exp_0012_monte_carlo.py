"""
EXP-0012: Monte Carlo stress test of the validated P70_L40d adaptive ATR strategy.

Method: bootstrap resampling of individual trade P&Ls.
  - Collect all trades from P70_L40d filter across 2023-2025 (full validated dataset)
  - Run 10,000 simulations: each draws N trades randomly with replacement
    (N = avg trades per year from the actual data)
  - For each simulation: compute final capital, max drawdown, Sharpe ratio
  - Report the full distribution of outcomes

NOTE: We resample TRADE P&Ls, not price series.
  Resampling individual trade outcomes is valid Monte Carlo methodology.
  NEVER shuffle the underlying financial time series (ASTRA rule).

Key questions answered:
  1. What is the realistic range of annual returns?
  2. What is the worst-case drawdown at 95% confidence?
  3. What is the probability of losing money in a year?
  4. What is the probability of ruin (drawdown > 50%)?
  5. Is the strategy viable at ₹20,000 starting capital?
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
    sys.exit("Missing DATA-001 file.")

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

# ── Step 1: Collect all P70_L40d trades across full 2023-2025 dataset ─────────
print("Collecting validated strategy trades (P70_L40d, 2023-2025)...")

rolling_pctile = df["atr10"].rolling(3000).quantile(0.70)
adaptive_mask  = df["atr10"] > rolling_pctile

filtered = df[adaptive_mask | df["atr10"].isna()]

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

trade_pnls = []
for t in result.trades:
    dirn = "LONG" if t.direction == SignalDirection.LONG else "SHORT"
    leg  = pricer.price_trade(dirn, t.entry_price, t.entry_time, t.exit_price, t.exit_time)
    net  = leg.pnl_rupees - (brok*2 + leg.entry_premium*stt_pct*lot_sz + 5.0)
    trade_pnls.append(round(net, 2))

pnls = np.array(trade_pnls)
n_trades = len(pnls)

print(f"  Total trades collected: {n_trades}")
print(f"  Date range: 2023-01-02 → 2025-12-31 (36 months)")
print(f"  Avg trades/month: {n_trades/36:.0f}")
print(f"  Avg P&L/trade: ₹{pnls.mean():+.0f}")
print(f"  Std dev/trade: ₹{pnls.std():.0f}")
print(f"  Win rate: {100*(pnls > 0).mean():.1f}%")
print(f"  Best trade: ₹{pnls.max():+,.0f}  |  Worst: ₹{pnls.min():+,.0f}")
print()

# ── Step 2: Monte Carlo simulation ────────────────────────────────────────────
N_SIMS         = 10_000
INITIAL_CAPITAL = 20_000.0
TRADES_PER_SIM  = int(round(n_trades / 3))   # ~1 year of trades (dataset is 3 years)
RUIN_THRESHOLD  = 0.50                        # drawdown > 50% = "ruin"
rng             = np.random.default_rng(seed=42)

print(f"Running {N_SIMS:,} Monte Carlo simulations ({TRADES_PER_SIM} trades each)...")

final_capitals   = np.zeros(N_SIMS)
max_drawdowns    = np.zeros(N_SIMS)
annual_returns   = np.zeros(N_SIMS)
ruin_flags       = np.zeros(N_SIMS, dtype=bool)

for i in range(N_SIMS):
    # Bootstrap: draw TRADES_PER_SIM trades with replacement
    sampled = rng.choice(pnls, size=TRADES_PER_SIM, replace=True)

    # Build equity curve
    equity = np.zeros(TRADES_PER_SIM + 1)
    equity[0] = INITIAL_CAPITAL
    for j, p in enumerate(sampled):
        equity[j+1] = equity[j] + p
        if equity[j+1] < 1:          # floor at ₹1 (can't go below 0)
            equity[j+1:] = 1.0
            break

    # Drawdown
    peak = np.maximum.accumulate(equity)
    dd   = (peak - equity) / peak
    max_dd = dd.max()

    final_capitals[i] = equity[-1]
    max_drawdowns[i]  = max_dd
    annual_returns[i] = (equity[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    ruin_flags[i]     = max_dd >= RUIN_THRESHOLD

print("  Done.")
print()

# ── Step 3: Report ─────────────────────────────────────────────────────────────
def pct(x): return f"{x:.1f}%"
def rs(x):  return f"₹{x:,.0f}"
def rspct(x): return f"₹{x:,.0f} ({x/INITIAL_CAPITAL*100:.0f}%)"

print("=" * 70)
print("MONTE CARLO RESULTS — P70_L40d Adaptive ATR Strategy")
print(f"  {N_SIMS:,} simulations × {TRADES_PER_SIM} trades each  |  Start: {rs(INITIAL_CAPITAL)}")
print("=" * 70)

print(f"\n── ANNUAL RETURN DISTRIBUTION ──────────────────────────────────────")
print(f"  5th  pctile (unlucky year) : {pct(np.percentile(annual_returns,  5))} → {rs(np.percentile(final_capitals,  5))}")
print(f"  25th pctile                : {pct(np.percentile(annual_returns, 25))} → {rs(np.percentile(final_capitals, 25))}")
print(f"  Median (50th pctile)       : {pct(np.percentile(annual_returns, 50))} → {rs(np.percentile(final_capitals, 50))}")
print(f"  75th pctile                : {pct(np.percentile(annual_returns, 75))} → {rs(np.percentile(final_capitals, 75))}")
print(f"  95th pctile (lucky year)   : {pct(np.percentile(annual_returns, 95))} → {rs(np.percentile(final_capitals, 95))}")
print(f"  Mean return                : {pct(annual_returns.mean())}")
print(f"  Std deviation of return    : {pct(annual_returns.std())}")

print(f"\n── DRAWDOWN DISTRIBUTION ───────────────────────────────────────────")
print(f"  Median max drawdown        : {pct(np.percentile(max_drawdowns, 50)*100)}")
print(f"  75th pctile max drawdown   : {pct(np.percentile(max_drawdowns, 75)*100)}")
print(f"  95th pctile max drawdown   : {pct(np.percentile(max_drawdowns, 95)*100)}")
print(f"  99th pctile max drawdown   : {pct(np.percentile(max_drawdowns, 99)*100)}")

print(f"\n── RISK METRICS ────────────────────────────────────────────────────")
prob_loss  = 100 * (annual_returns < 0).mean()
prob_ruin  = 100 * ruin_flags.mean()
prob_2x    = 100 * (final_capitals >= INITIAL_CAPITAL * 2).mean()
prob_3x    = 100 * (final_capitals >= INITIAL_CAPITAL * 3).mean()
print(f"  Probability of annual loss : {pct(prob_loss)}")
print(f"  Probability of ruin (DD>50%): {pct(prob_ruin)}")
print(f"  Probability of 2x capital  : {pct(prob_2x)}")
print(f"  Probability of 3x capital  : {pct(prob_3x)}")

# Sharpe ratio (annualised, assume 252 trading days, risk-free ~7% India)
per_trade_mean = pnls.mean()
per_trade_std  = pnls.std()
trades_per_year = TRADES_PER_SIM
ann_return_abs   = per_trade_mean * trades_per_year
ann_vol_abs      = per_trade_std  * np.sqrt(trades_per_year)
sharpe = (ann_return_abs - INITIAL_CAPITAL * 0.07) / ann_vol_abs
print(f"\n── QUALITY METRICS ─────────────────────────────────────────────────")
print(f"  Sharpe ratio (7% risk-free): {sharpe:.2f}")
print(f"  Profit factor              : {pnls[pnls>0].sum() / abs(pnls[pnls<0].sum()):.2f}")
print(f"  Avg win  : ₹{pnls[pnls>0].mean():+,.0f}  |  Avg loss: ₹{pnls[pnls<0].mean():+,.0f}")
print(f"  Win/loss ratio             : {pnls[pnls>0].mean() / abs(pnls[pnls<0].mean()):.2f}")
print(f"  Expectancy/trade           : ₹{pnls.mean():+,.0f}")

print(f"\n── CAPITAL SCENARIOS ───────────────────────────────────────────────")
for start_cap in [20_000, 50_000, 1_00_000, 5_00_000]:
    # Scale P&L proportionally (more lots with more capital)
    # Assume: 1 lot per ₹20k capital (conservative, ~7.5% premium exposure per trade)
    scale = start_cap / 20_000
    scaled_pnls = pnls * scale
    sc_finals = np.zeros(N_SIMS)
    for i in range(N_SIMS):
        sampled = rng.choice(scaled_pnls, size=TRADES_PER_SIM, replace=True)
        equity = start_cap + sampled.cumsum()
        equity = np.maximum(equity, 1)
        sc_finals[i] = equity[-1]
    sc_returns = (sc_finals - start_cap) / start_cap * 100
    print(f"  Start ₹{start_cap:>7,}  |  "
          f"Median: {rs(np.percentile(sc_finals,50))} ({np.percentile(sc_returns,50):+.0f}%)  |  "
          f"5th pctile: {rs(np.percentile(sc_finals,5))} ({np.percentile(sc_returns,5):+.0f}%)")

print(f"\n── VERDICT ─────────────────────────────────────────────────────────")
sharpe_ok = sharpe > 0.5
ruin_ok   = prob_ruin < 20.0
loss_ok   = prob_loss < 35.0
passed    = sharpe_ok and ruin_ok and loss_ok
print(f"  Sharpe > 0.5      : {'✓' if sharpe_ok else '✗'} ({sharpe:.2f})")
print(f"  P(ruin) < 20%     : {'✓' if ruin_ok else '✗'} ({prob_ruin:.1f}%)")
print(f"  P(annual loss) < 35%: {'✓' if loss_ok else '✗'} ({prob_loss:.1f}%)")
print(f"\n  Monte Carlo gate  : {'✓ PASSED — proceed to paper trading' if passed else '✗ FAILED — strategy needs further work'}")
