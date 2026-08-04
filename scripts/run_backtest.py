"""
Run backtest for a strategy.

Usage:
    python scripts/run_backtest.py --strategy pivot_cpr --from 2026-07-01 --to 2026-07-31
    python scripts/run_backtest.py --from 2026-07-01 --to 2026-07-31 --tolerance 0.20
    python scripts/run_backtest.py --from 2026-07-01 --to 2026-07-31 --csv trades.csv
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure project root is on sys.path when run as a script.
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()

from src.backtest.harness import BacktestHarness
from src.backtest.options_pricer import OptionsPricer
from src.broker.upstox_adapter import UpstoxAdapter
from src.config_loader import load_instruments, load_risk
from src.strategies.pivot_cpr_strategy import PivotCprStrategy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run strategy backtest")
    parser.add_argument("--strategy", default="pivot_cpr", choices=["pivot_cpr"])
    parser.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to",   dest="to_date",   required=True, help="YYYY-MM-DD")
    parser.add_argument("--tolerance",  type=float, default=0.18, help="Zone tolerance %%")
    parser.add_argument("--min-levels", type=int,   default=2,    help="Min levels for confluence")
    parser.add_argument("--iv",         type=float, default=14.0, help="Implied volatility %% (e.g. 14 = 14%%)")
    parser.add_argument("--csv",        type=str,   default=None, help="Export trades to CSV file")
    args = parser.parse_args()

    instruments_cfg = load_instruments()
    risk_cfg        = load_risk()

    nifty_cfg  = instruments_cfg["instruments"]["NIFTY"]
    lot_size   = nifty_cfg["lot_size"]            # from config — never hardcoded
    strike_step = nifty_cfg["strike_step"]
    expiry_wd  = nifty_cfg["weekly_expiry_weekday"]
    tx_costs   = instruments_cfg.get("transaction_costs", {})
    brokerage  = tx_costs.get("brokerage_per_order", 20.0)
    stt_pct    = tx_costs.get("stt_options_pct", 0.15) / 100.0

    # Options pricer — uses Black-Scholes with configurable IV.
    pricer = OptionsPricer(
        lot_size=lot_size,
        expiry_weekday=expiry_wd,
        strike_step=strike_step,
        iv=args.iv / 100.0,
    )

    # Create strategy.
    if args.strategy == "pivot_cpr":
        strategy = PivotCprStrategy(config={
            "tolerance_pct": args.tolerance,
            "min_levels_for_confluence": args.min_levels,
            # Momentum breakout settings (VOLUME-FREE, more aggressive)
            "momentum_enabled": True,
            "momentum_volume_multiplier": 1.5,    # Not used (no volume)
            "momentum_body_pct": 0.50,             # Lower: 50% body (was 60%)
            "momentum_accel_multiplier": 1.8,      # Higher: 1.8x range explosion (was 1.3x)
            "momentum_min_criteria": 2,            # Need 2 of 3 criteria
        })
    else:
        raise ValueError(f"Unknown strategy: {args.strategy}")

    harness = BacktestHarness(
        strategy=strategy, 
        instruments_config=instruments_cfg,
        cooldown_minutes=0,    # DISABLED: capture all valid breakouts
        allow_hedge=True,      # Allow opposite-direction entries (reversals)
    )

    # Fetch historical index data via Analytics Token.
    logger.info("Fetching historical data: %s to %s", args.from_date, args.to_date)
    adapter = UpstoxAdapter(config={
        "api_key":         os.environ.get("UPSTOX_SANDBOX_API_KEY", ""),
        "api_secret":      os.environ.get("UPSTOX_SANDBOX_API_SECRET", ""),
        "redirect_uri":    os.environ.get("UPSTOX_SANDBOX_REDIRECT_URI", ""),
        "analytics_token": os.environ["UPSTOX_ANALYTICS_TOKEN"],
        "sandbox":         True,
    })

    ohlcv_1min = adapter.get_ohlcv(
        symbol="NSE_INDEX|Nifty 50",
        interval="1minute",
        from_date=args.from_date,
        to_date=args.to_date,
    )

    if ohlcv_1min is None or ohlcv_1min.empty:
        logger.error("No data returned from adapter. Aborting.")
        return

    ohlcv = ohlcv_1min.resample("5min").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }).dropna(subset=["open"])

    logger.info("Resampled to %d 5-min bars. Running backtest...", len(ohlcv))

    result = harness.run(ohlcv)

    # ── Apply options P&L overlay + track ALL breakout attempts ─────────────
    rows = []
    missed_signals = []  # Track every breakout that didn't result in a trade
    total_option_pnl = 0.0
    total_tx_cost    = 0.0
    option_winners   = 0
    option_losers    = 0
    
    # Build a map of which signals actually traded
    traded_signal_times = {s.bar_time: s for s in result.signals if any(t.signal == s for t in result.trades)}

    for i, t in enumerate(result.trades, 1):
        direction = "LONG" if t.direction.name == "LONG" else "SHORT"
        setup     = t.signal.metadata["setup"]
        zone      = setup.zone

        leg = pricer.price_trade(
            direction  = direction,
            entry_spot = t.entry_price,
            entry_time = t.entry_time,
            exit_spot  = t.exit_price,
            exit_time  = t.exit_time,
        )

        # ── Determine zone type ───────────────────────────────────────────────
        from src.backtest.options_pricer import next_expiry
        is_expiry_day = (t.entry_time.date() == leg.expiry_date)
        
        # Zone classification
        if zone.is_confluence:
            zone_type = "CONFLUENCE"
        elif zone.is_daily_cpr_only:
            zone_type = "DAILY_CPR"
        elif zone.is_strong_single_level:
            zone_type = "STRONG_SINGLE"
        else:
            zone_type = "OTHER"
        
        # Signal type (regular vs momentum)
        signal_type = t.signal.metadata.get("signal_type", "regular")

        # ── Transaction costs (corrected) ────────────────────────────────────
        # STT: 0.15% on OPTIONS PREMIUM PAID (buy side only) × lot_size
        # Brokerage: ₹20 per order × 2 legs
        # SEBI turnover charge + GST: ~₹5 flat approximation
        tx_cost = (
            brokerage * 2
            + leg.entry_premium * stt_pct * lot_size   # STT on premium (not spot)
            + 5.0                                       # SEBI + GST approx
        )
        net_pnl = leg.pnl_rupees - tx_cost
        total_option_pnl += net_pnl
        total_tx_cost    += tx_cost

        if net_pnl > 0:
            option_winners += 1
        else:
            option_losers  += 1

        rows.append({
            "trade_no":        i,
            "signal_type":     signal_type,
            "direction":       direction,
            "zone_type":       zone_type,
            "zone_members":    ", ".join(zone.members),
            "option_type":     leg.option_type.upper(),
            "strike":          leg.strike,
            "expiry":          str(leg.expiry_date),
            "expiry_day":      "YES" if is_expiry_day else "NO",
            "entry_time":      str(t.entry_time),
            "entry_spot":      round(t.entry_price, 2),
            "entry_premium":   leg.entry_premium,
            "exit_time":       str(t.exit_time),
            "exit_spot":       round(t.exit_price, 2),
            "exit_premium":    leg.exit_premium,
            "premium_chg_pts": round(leg.exit_premium - leg.entry_premium, 2),
            "lot_size":        lot_size,
            "gross_pnl_rs":    round(leg.pnl_rupees, 2),
            "tx_cost_rs":      round(tx_cost, 2),
            "net_pnl_rs":      round(net_pnl, 2),
            "index_pts":       round(t.pnl_points, 2),
            "exit_reason":     t.exit_reason,
            "initial_stop":    round(t.initial_stop, 2),
            "zone_low":        round(zone.price_low, 2),
            "zone_high":       round(zone.price_high, 2),
            "breakout_time":   str(setup.breakout_time),
            "confirm_time":    str(setup.confirm_time),
        })
    
    # ── Track missed signals (breakouts that fired but didn't trade) ──────────
    for suppressed in result.suppressed_signals:
        missed_signals.append({
            "signal_time":   suppressed["signal_time"],
            "direction":     suppressed["direction"],
            "zone_low":      suppressed["zone_key"][0],
            "zone_high":     suppressed["zone_key"][1],
            "zone_members":  ", ".join(suppressed["zone_members"]),
            "missed_reason": suppressed["reason"],
            "cooldown_ends": suppressed.get("cooldown_ends", ""),
            "active_since":  suppressed.get("active_since", ""),
        })

    # ── Print results ─────────────────────────────────────────────────────────
    print("\n" + "=" * 120)
    print("BACKTEST RESULTS  —  Nifty 5-min Pivot CPR  (Options P&L via Black-Scholes)")
    print(f"Period  : {args.from_date}  →  {args.to_date}")
    print(f"Params  : tolerance={args.tolerance}%  min_levels={args.min_levels}  IV={args.iv}%  lot_size={lot_size}")
    print(f"Cooldown: {harness._cooldown_minutes} minutes per zone")
    print("=" * 120)

    if not rows:
        print("\n  No tradeable signals.")
    else:
        print(f"\n{'#':<4} {'Dir':<6} {'ZoneType':<12} {'Type':<5} {'Strike':>7} "
              f"{'Entry time':<22} {'Prem':>7}  "
              f"{'Exit time':<22} {'Prem':>7}  "
              f"{'Net ₹':>9} {'Reason'}")
        print("-" * 120)
        for r in rows:
            print(
                f"{r['trade_no']:<4} {r['direction']:<6} {r['zone_type']:<12} {r['option_type']:<5} {r['strike']:>7.0f} "
                f"{r['entry_time'][:22]:<22} {r['entry_premium']:>7.2f}  "
                f"{r['exit_time'][:22]:<22} {r['exit_premium']:>7.2f}  "
                f"{r['net_pnl_rs']:>+9.2f} {r['exit_reason']}"
            )

        win_rate = round(100 * option_winners / len(rows), 1)
        gross_total = sum(r["gross_pnl_rs"] for r in rows)
        
        # Count by zone type and signal type
        momentum_count = sum(1 for r in rows if r["signal_type"] == "momentum")
        regular_count = len(rows) - momentum_count
        confluence_count = sum(1 for r in rows if r["zone_type"] == "CONFLUENCE")
        daily_cpr_count  = sum(1 for r in rows if r["zone_type"] == "DAILY_CPR")
        
        print("\n" + "=" * 120)
        print("SUMMARY (Options P&L — 1 lot per trade)")
        print("=" * 120)
        print(f"  Signals generated : {len(result.signals)}")
        print(f"  Trades executed   : {len(result.trades)}")
        print(f"  Missed signals    : {len(missed_signals)}")
        print(f"  ")
        print(f"  SIGNAL TYPE BREAKDOWN:")
        print(f"  — Regular breakouts (2-bar confirm): {regular_count}")
        print(f"  — Momentum breakouts (immediate):    {momentum_count}")
        print(f"  ")
        print(f"  ZONE TYPE BREAKDOWN:")
        print(f"  — Confluence      : {confluence_count}")
        print(f"  — Daily/CPR only  : {daily_cpr_count}")
        print(f"  ")
        print(f"  Winners / Losers  : {option_winners} / {option_losers}")
        print(f"  Win rate          : {win_rate}%")
        print(f"  Gross P&L         : ₹{gross_total:+,.2f}")
        print(f"  Total tx costs    : ₹{total_tx_cost:+,.2f}")
        print(f"  Net P&L           : ₹{total_option_pnl:+,.2f}")
        print(f"  ")
        print(f"  INDEX MOVEMENT (reference only):")
        print(f"  — Index pts P&L   : {result.metrics.get('total_pnl_pts', 0):+.2f} Nifty pts")
        print(f"  ")
        print(f"  PREMIUM CAPTURE (actual options P&L):")
        premium_pts_total = sum(r["premium_chg_pts"] for r in rows)
        print(f"  — Premium pts     : {premium_pts_total:+.2f} pts captured")
        print(f"  — Gross options   : ₹{gross_total:+,.2f} (premium × lot_size)")
        print()
        
        if missed_signals:
            print(f"\n  MISSED SIGNALS BREAKDOWN:")
            cooldown_count = sum(1 for m in missed_signals if m["missed_reason"] == "cooldown")
            position_count = sum(1 for m in missed_signals if m["missed_reason"] == "position_active")
            print(f"  — Suppressed (position active): {position_count}")
            print(f"  — Suppressed (zone cooldown):   {cooldown_count}")
        print()
        print("  NOTE: Black-Scholes uses fixed IV. Real premiums vary with live IV.")
        print("  STT = 0.15% on premium paid × lot_size.")
        print("  Zone cooldown prevents re-entry on same zone within 45 minutes.")

    print("=" * 120 + "\n")

    # ── CSV export ────────────────────────────────────────────────────────────
    csv_path = args.csv or f"backtest_{args.from_date}_to_{args.to_date}.csv"
    with open(csv_path, "w", newline="") as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    print(f"  Trade log exported → {csv_path}\n")
    
    # Export missed signals for analysis
    if missed_signals:
        missed_path = csv_path.replace(".csv", "_missed.csv")
        with open(missed_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=missed_signals[0].keys())
            writer.writeheader()
            writer.writerows(missed_signals)
        print(f"  Missed signals exported → {missed_path}")
        print(f"  ↑ Analyze this to see which breakouts you couldn't trade and why\n")


if __name__ == "__main__":
    main()
