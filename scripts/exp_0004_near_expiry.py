"""
EXP-0004: Near-expiry sub-strategy.
Enter only: Monday (1 day before Tuesday expiry), AFTERNOON/CLOSING session (13:00+).
Tests whether the near-expiry gamma trade is a viable standalone sub-strategy.
"""
import sys
sys.path.insert(0, '/workshop/atlas')

import logging
import pandas as pd
from backtest.harness import BacktestHarness
from backtest.options_pricer import OptionsPricer, next_expiry
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
daily_ohlcv = df.resample("B").agg(
    open=("open","first"), high=("high","max"),
    low=("low","min"), close=("close","last"),
).dropna()

pricer = OptionsPricer(lot_size=nifty_cfg["lot_size"], expiry_weekday=nifty_cfg["weekly_expiry_weekday"],
                        strike_step=nifty_cfg["strike_step"], iv=0.14)

months = [
    ("2026-02-01", "2026-02-28"),
    ("2026-03-01", "2026-03-31"),
    ("2026-04-01", "2026-04-30"),
    ("2026-05-01", "2026-05-31"),
    ("2026-06-01", "2026-06-30"),
    ("2026-07-01", "2026-07-31"),
]

for label, filt in [
    ("BASELINE",              lambda ts: True),
    ("NEAR_EXPIRY_MONDAY_PM", lambda ts: (
        ts.weekday() == 0 and  # Monday
        ts.hour >= 13 and      # Afternoon/Closing
        next_expiry(ts.date(), 1).toordinal() - ts.date().toordinal() == 1  # 1 day to expiry
    )),
]:
    strategy = PivotCprStrategy(config={
        "tolerance_pct": 0.18, "min_levels_for_confluence": 2,
        "momentum_enabled": True, "momentum_body_pct": 0.50,
        "momentum_accel_multiplier": 1.8, "momentum_min_criteria": 2,
    })
    strategy._daily_ohlc = daily_ohlcv

    capital = 20_000.0
    monthly = []
    all_trades = []

    for start_str, end_str in months:
        start = pd.Timestamp(start_str, tz="Asia/Kolkata")
        end   = pd.Timestamp(end_str, tz="Asia/Kolkata") + pd.Timedelta(days=1)
        month_data = df[(df.index >= start) & (df.index < end)].copy()

        filtered = month_data[[filt(ts) for ts in month_data.index]]

        if len(filtered) < 50:
            monthly.append({"month": start_str[:7], "start": capital, "end": capital, "trades": 0, "winners": 0})
            continue

        harness = BacktestHarness(
            strategy=strategy, instruments_config=instruments_cfg,
            risk_config=risk_cfg, cooldown_minutes=0, allow_hedge=True,
            initial_capital=capital,
        )
        result = harness.run(filtered[['open','high','low','close','volume']], pricer=pricer)
        end_capital = harness._current_capital
        winners = sum(1 for t in result.trades if t.pnl_points > 0)

        tx_costs = instruments_cfg.get("transaction_costs", {})
        brokerage = tx_costs.get("brokerage_per_order", 20.0)
        stt_pct   = tx_costs.get("stt_options_pct", 0.15) / 100.0
        net_total = 0
        for t in result.trades:
            direction = "LONG" if t.direction == SignalDirection.LONG else "SHORT"
            leg = pricer.price_trade(direction=direction,
                                      entry_spot=t.entry_price, entry_time=t.entry_time,
                                      exit_spot=t.exit_price, exit_time=t.exit_time)
            gross = leg.pnl_rupees * t.lots
            tc = (brokerage*2 + leg.entry_premium*stt_pct*nifty_cfg["lot_size"] + 5.0) * t.lots
            net_total += gross - tc
            all_trades.append({
                "month": start_str[:7], "direction": direction, "lots": t.lots,
                "net_pnl": round(gross - tc, 2), "hold_min": round((t.exit_time-t.entry_time).seconds/60, 1),
                "entry_prem": round(pricer.price_trade(direction, t.entry_price, t.entry_time, t.entry_price, t.entry_time).entry_premium, 2),
            })

        monthly.append({"month": start_str[:7], "start": capital, "end": end_capital,
                          "trades": len(result.trades), "winners": winners, "net_pnl": net_total})
        capital = end_capital

    total_t   = sum(s["trades"] for s in monthly)
    total_w   = sum(s["winners"] for s in monthly)
    avg_pnl_t = sum(t["net_pnl"] for t in all_trades) / len(all_trades) if all_trades else 0

    print(f"\n{'='*65}")
    print(f"  {label}")
    print(f"{'='*65}")
    print(f"  Final capital : ₹{capital:,.0f} ({(capital-20000)/20000*100:+.1f}%)")
    print(f"  Total trades  : {total_t}")
    print(f"  Win rate      : {100*total_w/total_t:.1f}%" if total_t else "  No trades")
    print(f"  Avg P&L/trade : ₹{avg_pnl_t:.0f}")
    for s in monthly:
        ret_m = (s['end']-s['start'])/s['start']*100 if s['start'] else 0
        print(f"    {s['month']}: {s['trades']:3d} trades | "
              f"₹{s['start']:>9,.0f} → ₹{s['end']:>9,.0f} ({ret_m:+6.1f}%)")

    if all_trades:
        td = pd.DataFrame(all_trades)
        top5 = td.nlargest(5, 'net_pnl')
        print(f"\n  Top 5 trades:")
        print(top5[['month','direction','lots','entry_prem','net_pnl','hold_min']].to_string(index=False))
