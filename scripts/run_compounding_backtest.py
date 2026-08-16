#!/usr/bin/env python3
"""
6-Month Compounding Backtest
Simulates compound growth by reinvesting profits each month.
Starting capital: ₹20,000
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backtest.harness import BacktestHarness
from src.backtest.options_pricer import OptionsPricer
from src.broker.upstox_adapter import UpstoxAdapter
from src.config_loader import load_instruments, load_risk
from src.strategies.pivot_cpr_strategy import PivotCprStrategy

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def run_month(start_date, end_date, capital, strategy, adapter, pricer, instruments_cfg, risk_cfg, cooldown_minutes=0):
    """Run backtest for one month with position sizing."""
    logger.info("")
    logger.info("=" * 80)
    logger.info(f"MONTH: {start_date} to {end_date} | Starting Capital: ₹{capital:,.2f}")
    logger.info("=" * 80)
    
    # Create harness with config-based position sizing
    harness = BacktestHarness(
        strategy=strategy,
        instruments_config=instruments_cfg,
        risk_config=risk_cfg,  # Pass risk config (reads from risk.yaml)
        cooldown_minutes=cooldown_minutes,
        allow_hedge=True,
        initial_capital=capital,
    )
    
    # Fetch data
    ohlcv_1min = adapter.get_ohlcv(
        symbol="NSE_INDEX|Nifty 50",
        interval="1minute",
        from_date=start_date,
        to_date=end_date,
    )
    
    if ohlcv_1min is None or ohlcv_1min.empty:
        logger.warning(f"No data for {start_date} to {end_date}")
        return None, []
    
    # Fetch DAILY data for pivot calculation (lookback 90 days)
    from datetime import datetime as dt
    start_dt = dt.strptime(start_date, "%Y-%m-%d")
    pivot_from_date = (start_dt - timedelta(days=90)).strftime("%Y-%m-%d")
    
    daily_ohlcv = adapter.get_ohlcv(
        symbol="NSE_INDEX|Nifty 50",
        interval="day",
        from_date=pivot_from_date,
        to_date=end_date,
    )
    
    if daily_ohlcv is None or daily_ohlcv.empty:
        logger.warning(f"Failed to fetch daily data for pivots - backtest will have NaN pivots!")
    else:
        # Inject daily OHLCV into strategy for pivot calculation
        strategy._daily_ohlc = daily_ohlcv
        logger.info(f"✓ Injected {len(daily_ohlcv)} days of historical data for pivot calculation")
    
    # Resample to 5-min
    ohlcv = ohlcv_1min.resample("5min").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }).dropna(subset=["open"])
    
    logger.info(f"Resampled to {len(ohlcv)} 5-min bars. Running backtest...")
    
    # Run backtest with pricer for position sizing
    result = harness.run(ohlcv, pricer=pricer)
    
    if not result.trades:
        logger.info("No trades this month.")
        return {
            "start_date": start_date,
            "end_date": end_date,
            "starting_capital": capital,
            "ending_capital": capital,
            "trades": 0,
            "total_lots": 0,
            "winners": 0,
            "losers": 0,
            "net_pnl": 0.0,
            "return_pct": 0.0,
            "momentum_signals": 0,
            "regular_signals": 0,
        }, []
    
    # Calculate final capital from harness
    ending_capital = harness._current_capital
    net_pnl = ending_capital - capital
    return_pct = (net_pnl / capital) * 100 if capital > 0 else 0
    
    # Count metrics
    total_lots = sum(t.lots for t in result.trades)
    winners = sum(1 for t in result.trades if t.pnl_points > 0)
    losers = len(result.trades) - winners
    momentum_count = sum(1 for t in result.trades if t.signal.metadata.get("signal_type") == "momentum")
    regular_count = len(result.trades) - momentum_count
    
    # Build detailed trade records for CSV export
    trade_records = []
    tx_costs = instruments_cfg.get("transaction_costs", {})
    brokerage = tx_costs.get("brokerage_per_order", 20.0)
    stt_pct = tx_costs.get("stt_options_pct", 0.15) / 100.0
    
    for i, trade in enumerate(result.trades, 1):
        direction = "LONG" if trade.direction.name == "LONG" else "SHORT"
        signal_type = trade.signal.metadata.get("signal_type", "regular")
        setup = trade.signal.metadata["setup"]
        zone = setup.zone
        
        # Calculate option P&L
        leg = pricer.price_trade(
            direction=direction,
            entry_spot=trade.entry_price,
            entry_time=trade.entry_time,
            exit_spot=trade.exit_price,
            exit_time=trade.exit_time,
        )
        
        # TX costs per lot
        tx_cost_per_lot = (
            brokerage * 2 +
            leg.entry_premium * stt_pct * pricer.lot_size +
            5.0
        )
        total_tx_cost = tx_cost_per_lot * trade.lots
        gross_pnl = leg.pnl_rupees * trade.lots
        net_pnl_trade = gross_pnl - total_tx_cost
        
        # Zone type classification
        if zone.is_confluence:
            zone_type = "CONFLUENCE"
        elif zone.is_daily_cpr_only:
            zone_type = "DAILY_CPR"
        elif zone.is_strong_single_level:
            zone_type = "STRONG_SINGLE"
        else:
            zone_type = "OTHER"
        
        # Time analysis
        entry_hour = trade.entry_time.hour
        entry_minute = trade.entry_time.minute
        time_of_day = f"{entry_hour:02d}:{entry_minute:02d}"
        
        # Session classification
        if 9 <= entry_hour < 10:
            session = "MORNING_OPEN"
        elif 10 <= entry_hour < 13:
            session = "MID_MORNING"
        elif 13 <= entry_hour < 15:
            session = "AFTERNOON"
        else:
            session = "CLOSING"
        
        # Hold duration
        hold_minutes = (trade.exit_time - trade.entry_time).total_seconds() / 60
        
        trade_records.append({
            "month": start_date[:7],  # YYYY-MM
            "trade_no": i,
            "signal_type": signal_type,
            "direction": direction,
            "zone_type": zone_type,
            "zone_members": ", ".join(zone.members),
            "entry_time": str(trade.entry_time),
            "entry_hour": entry_hour,
            "time_of_day": time_of_day,
            "session": session,
            "entry_spot": round(trade.entry_price, 2),
            "exit_time": str(trade.exit_time),
            "exit_spot": round(trade.exit_price, 2),
            "hold_minutes": round(hold_minutes, 1),
            "lots": trade.lots,
            "entry_premium": round(leg.entry_premium, 2),
            "exit_premium": round(leg.exit_premium, 2),
            "premium_change": round(leg.exit_premium - leg.entry_premium, 2),
            "gross_pnl_rs": round(gross_pnl, 2),
            "tx_cost_rs": round(total_tx_cost, 2),
            "net_pnl_rs": round(net_pnl_trade, 2),
            "exit_reason": trade.exit_reason,
            "initial_stop": round(trade.initial_stop, 2),
            "zone_low": round(zone.price_low, 2),
            "zone_high": round(zone.price_high, 2),
        })
    
    logger.info(f"Trades: {len(result.trades)} ({total_lots} total lots) | Winners: {winners} | Losers: {losers}")
    logger.info(f"Momentum: {momentum_count} | Regular: {regular_count}")
    logger.info(f"Net P&L: ₹{net_pnl:+,.2f} | Return: {return_pct:+.2f}%")
    logger.info(f"Ending Capital: ₹{ending_capital:,.2f}")
    
    summary = {
        "start_date": start_date,
        "end_date": end_date,
        "starting_capital": capital,
        "ending_capital": ending_capital,
        "trades": len(result.trades),
        "total_lots": total_lots,
        "winners": winners,
        "losers": losers,
        "net_pnl": net_pnl,
        "return_pct": return_pct,
        "momentum_signals": momentum_count,
        "regular_signals": regular_count,
    }
    
    return summary, trade_records


def main():
    parser = argparse.ArgumentParser(description="6-month compounding backtest")
    parser.add_argument("--start", default="2026-02-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--initial-capital", type=float, default=20000, help="Starting capital (₹)")
    parser.add_argument("--iv", type=float, default=14.0, help="Implied volatility (%)")
    parser.add_argument(
        "--config",
        default="baseline",
        choices=["baseline", "cooldown", "strict", "quality", "hybrid", "optimized"],
        help="Strategy configuration: baseline (current), cooldown (15min), strict (all 3 criteria), quality (extreme moves only), hybrid (cooldown + stricter momentum), optimized (data-driven fixes)"
    )
    args = parser.parse_args()
    
    # Config (correct key paths from working code)
    instruments_cfg = load_instruments()
    risk_cfg = load_risk()
    
    nifty_cfg = instruments_cfg["instruments"]["NIFTY"]
    lot_size = nifty_cfg["lot_size"]
    expiry_wd = nifty_cfg["weekly_expiry_weekday"]
    strike_step = nifty_cfg["strike_step"]
    
    # ═══════════════════════════════════════════════════════════════════════
    # STRATEGY CONFIGURATIONS
    # ═══════════════════════════════════════════════════════════════════════
    
    configs = {
        "baseline": {
            "name": "BASELINE (Current)",
            "description": "2/3 criteria, no cooldown, accel=1.8x",
            "cooldown_minutes": 0,
            "strategy_config": {
                "tolerance_pct": 0.18,
                "min_levels_for_confluence": 2,
                "momentum_enabled": True,
                "momentum_body_pct": 0.50,
                "momentum_accel_multiplier": 1.8,
                "momentum_min_criteria": 2,  # 2 of 3
            }
        },
        "cooldown": {
            "name": "OPTION 1: Add Cooldown",
            "description": "15-min cooldown after each zone trade",
            "cooldown_minutes": 15,
            "strategy_config": {
                "tolerance_pct": 0.18,
                "min_levels_for_confluence": 2,
                "momentum_enabled": True,
                "momentum_body_pct": 0.50,
                "momentum_accel_multiplier": 1.8,
                "momentum_min_criteria": 2,  # 2 of 3
            }
        },
        "strict": {
            "name": "OPTION 2: Tighten Momentum Criteria",
            "description": "Require ALL 3 criteria (range + body + penetration)",
            "cooldown_minutes": 0,
            "strategy_config": {
                "tolerance_pct": 0.18,
                "min_levels_for_confluence": 2,
                "momentum_enabled": True,
                "momentum_body_pct": 0.50,
                "momentum_accel_multiplier": 1.8,
                "momentum_min_criteria": 3,  # ALL 3 required
            }
        },
        "quality": {
            "name": "OPTION 3: Quality Over Quantity",
            "description": "Extreme moves only (accel=2.5x), regular as primary",
            "cooldown_minutes": 0,
            "strategy_config": {
                "tolerance_pct": 0.18,
                "min_levels_for_confluence": 2,
                "momentum_enabled": True,
                "momentum_body_pct": 0.50,
                "momentum_accel_multiplier": 2.5,  # Much higher threshold
                "momentum_min_criteria": 2,  # 2 of 3
            }
        },
        "hybrid": {
            "name": "HYBRID (Recommended)",
            "description": "Cooldown + stricter momentum (accel=2.2x, body=60%)",
            "cooldown_minutes": 15,
            "strategy_config": {
                "tolerance_pct": 0.18,
                "min_levels_for_confluence": 2,
                "momentum_enabled": True,
                "momentum_body_pct": 0.60,           # 🔧 Raised from 50% to 60%
                "momentum_accel_multiplier": 2.2,    # 🔧 Raised from 1.8 to 2.2
                "momentum_min_criteria": 2,          # Keep 2 of 3
            }
        },
        "optimized": {
            "name": "OPTIMIZED (Data-Driven Fixes)",
            "description": "Fix quick chop: min premium ₹10, momentum 3.0×/70%, breakeven stops",
            "cooldown_minutes": 15,
            "strategy_config": {
                "tolerance_pct": 0.18,
                "min_levels_for_confluence": 2,
                "momentum_enabled": True,
                "momentum_body_pct": 0.70,           # 🔧 Raised from 50% to 70%
                "momentum_accel_multiplier": 3.0,    # 🔧 Raised from 1.8 to 3.0
                "momentum_min_criteria": 2,          # Keep 2 of 3
                "min_premium_filter": 10.0,          # 🔧 NEW: Skip if premium < ₹10
            }
        },
    }
    
    selected_config = configs[args.config]
    
    # Create components (strategy and pricer are reused, harness is per-month)
    strategy = PivotCprStrategy(config=selected_config["strategy_config"])
    
    pricer = OptionsPricer(
        lot_size=lot_size,
        expiry_weekday=expiry_wd,
        strike_step=strike_step,
        iv=args.iv / 100.0,
    )
    
    adapter = UpstoxAdapter(config={
        "api_key": os.environ.get("UPSTOX_SANDBOX_API_KEY", ""),
        "api_secret": os.environ.get("UPSTOX_SANDBOX_API_SECRET", ""),
        "redirect_uri": os.environ.get("UPSTOX_SANDBOX_REDIRECT_URI", ""),
        "analytics_token": os.environ["UPSTOX_ANALYTICS_TOKEN"],
        "sandbox": True,
    })
    
    # Generate 6-month date ranges
    start = datetime.strptime(args.start, "%Y-%m-%d")
    months = []
    
    for i in range(6):
        month_start = start + timedelta(days=i * 30)  # Rough monthly increments
        # Find actual month boundaries
        first_day = month_start.replace(day=1)
        if first_day.month == 12:
            last_day = first_day.replace(day=31)
        else:
            next_month = first_day.replace(month=first_day.month + 1)
            last_day = next_month - timedelta(days=1)
        
        months.append({
            "start": first_day.strftime("%Y-%m-%d"),
            "end": last_day.strftime("%Y-%m-%d"),
        })
    
    # Run compounding backtest
    logger.info("")
    logger.info("="*80)
    logger.info("6-MONTH COMPOUNDING BACKTEST")
    logger.info(f"Configuration: {selected_config['name']}")
    logger.info(f"Description: {selected_config['description']}")
    logger.info(f"Starting Capital: ₹{args.initial_capital:,.2f}")
    logger.info(f"Lot Size: {lot_size} | IV: {args.iv}%")
    logger.info("="*80)
    
    capital = args.initial_capital
    month_results = []
    all_trades = []  # Collect all trades across months
    
    for i, month in enumerate(months, 1):
        summary, trades = run_month(
            month["start"], month["end"],
            capital,
            strategy, adapter, pricer, instruments_cfg, risk_cfg,
            selected_config["cooldown_minutes"]  # Pass cooldown setting
        )
        
        if summary:
            month_results.append(summary)
            all_trades.extend(trades)  # Add this month's trades
            capital = summary["ending_capital"]  # Compound: next month uses ending capital
    
    # Final summary
    print("\n" + "=" * 120)
    print(f"6-MONTH COMPOUNDING BACKTEST: {selected_config['name']}")
    print(f"({selected_config['description']})")
    print("=" * 120)
    print(f"{'Month':<8} {'Start Date':<12} {'End Date':<12} {'Start ₹':<12} {'Trades':<8} {'Lots':<8} "
          f"{'W/L':<8} {'Net P&L ₹':<15} {'Return %':<10} {'End ₹':<15} {'Signals (M/R)'}")
    print("-" * 120)
    
    for i, r in enumerate(month_results, 1):
        print(f"{i:<8} {r['start_date']:<12} {r['end_date']:<12} {r['starting_capital']:<12,.0f} "
              f"{r['trades']:<8} {r['total_lots']:<8} {r['winners']}/{r['losers']:<6} "
              f"{r['net_pnl']:<+15,.2f} {r['return_pct']:<+10.2f} {r['ending_capital']:<15,.2f} "
              f"{r['momentum_signals']}/{r['regular_signals']}")
    
    print("=" * 120)
    
    if month_results:
        total_trades = sum(r["trades"] for r in month_results)
        total_lots = sum(r["total_lots"] for r in month_results)
        total_winners = sum(r["winners"] for r in month_results)
        total_losers = sum(r["losers"] for r in month_results)
        total_momentum = sum(r["momentum_signals"] for r in month_results)
        total_regular = sum(r["regular_signals"] for r in month_results)
        
        starting = month_results[0]["starting_capital"]
        ending = month_results[-1]["ending_capital"]
        total_return = ((ending - starting) / starting) * 100
        
        print(f"\nFINAL RESULTS:")
        print(f"  Starting Capital    : ₹{starting:,.2f}")
        print(f"  Ending Capital      : ₹{ending:,.2f}")
        print(f"  Total P&L           : ₹{ending - starting:+,.2f}")
        print(f"  Total Return        : {total_return:+.2f}%")
        print(f"  ")
        print(f"  Total Trades        : {total_trades}")
        print(f"  Total Lots Traded   : {total_lots}")
        print(f"  Winners / Losers    : {total_winners} / {total_losers}")
        print(f"  Win Rate            : {100 * total_winners / total_trades if total_trades > 0 else 0:.1f}%")
        print(f"  Momentum / Regular  : {total_momentum} / {total_regular}")
        print(f"  Avg Trades/Day      : {total_trades / (6 * 22):.1f} (assuming 22 trading days/month)")
        print(f"  ")
        print(f"  CONFIGURATION: {selected_config['name']}")
        print(f"  {selected_config['description']}")
        print(f"  ")
        print(f"  NOTE: Position sizing with CONSERVATIVE limits:")
        print(f"       - Max 10 lots per trade (exchange freeze limit ~36, using 10 for safety)")
        print(f"       - Max 10% capital deployed per trade (2% risk per trade)")
        print(f"       - Stop trading if capital exhausted")
        print("=" * 120)
    
    # Export to CSV
    if month_results:
        df = pd.DataFrame(month_results)
        output_path = f"compounding_backtest_6months_{args.start}.csv"
        df.to_csv(output_path, index=False)
        logger.info(f"Results exported to {output_path}")
        
        # Export detailed trade-by-trade analysis
        if all_trades:
            trades_df = pd.DataFrame(all_trades)
            trades_output_path = f"compounding_backtest_trades_detailed_{args.start}.csv"
            trades_df.to_csv(trades_output_path, index=False)
            logger.info(f"Detailed trade log exported to {trades_output_path}")
            print(f"\n📊 DETAILED TRADE ANALYSIS EXPORTED: {trades_output_path}")
            print(f"   Total trades: {len(all_trades)}")
            print(f"   Use this CSV to analyze:")
            print(f"   - Momentum vs Regular performance")
            print(f"   - Time of day patterns")
            print(f"   - Zone type win rates")
            print(f"   - Hold duration analysis")
            print()


if __name__ == "__main__":
    main()
