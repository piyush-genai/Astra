#!/usr/bin/env python3
"""Daily Compounding Backtest - Capital grows after EVERY trade."""

import argparse
import logging
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backtest.harness import BacktestHarness
from src.broker.upstox_adapter import UpstoxAdapter
from src.config_loader import load_instruments
from src.strategies.pivot_cpr_strategy import PivotCprStrategy

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

def fetch_data_in_chunks(adapter, symbol, start_date, end_date):
    """Fetch data month by month to avoid API limits."""
    current = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    all_data = []
    
    while current <= end:
        # Get last day of current month
        if current.month == 12:
            month_end = current.replace(day=31)
        else:
            month_end = (current.replace(month=current.month + 1, day=1) - timedelta(days=1))
        
        # Don't go past the requested end_date
        if month_end > end:
            month_end = end
        
        month_start_str = current.strftime("%Y-%m-%d")
        month_end_str = month_end.strftime("%Y-%m-%d")
        
        logger.info(f"Fetching {month_start_str} to {month_end_str}")
        
        df = adapter.get_ohlcv(symbol, "1minute", month_start_str, month_end_str)
        if df is not None and not df.empty:
            all_data.append(df)
        
        # Move to next month
        current = month_end + timedelta(days=1)
    
    if not all_data:
        return pd.DataFrame()
    
    return pd.concat(all_data).sort_index()

def main():
    parser = argparse.ArgumentParser(description="Daily compounding backtest")
    parser.add_argument("--from", dest="from_date", required=True)
    parser.add_argument("--to", dest="to_date", required=True)
    parser.add_argument("--capital", type=float, default=20000.0)
    args = parser.parse_args()

    instruments_cfg = load_instruments()
    
    strategy = PivotCprStrategy(config={
        "tolerance_pct": 0.18,
        "min_levels_for_confluence": 2,
        "momentum_enabled": True,
        "momentum_body_pct": 0.50,
        "momentum_accel_multiplier": 1.8,
        "momentum_min_criteria": 2,
    })

    adapter = UpstoxAdapter(config={
        "api_key": os.environ.get("UPSTOX_SANDBOX_API_KEY", ""),
        "api_secret": os.environ.get("UPSTOX_SANDBOX_API_SECRET", ""),
        "redirect_uri": os.environ.get("UPSTOX_SANDBOX_REDIRECT_URI", ""),
        "analytics_token": os.environ["UPSTOX_ANALYTICS_TOKEN"],
        "sandbox": True,
    })

    # Fetch data in chunks
    ohlcv_1min = fetch_data_in_chunks(adapter, "NSE_INDEX|Nifty 50", args.from_date, args.to_date)
    
    if ohlcv_1min.empty:
        logger.error("No data returned")
        return
    
    # Fetch DAILY data for pivot calculation (lookback 90 days)
    start_dt = datetime.strptime(args.from_date, "%Y-%m-%d")
    pivot_from_date = (start_dt - timedelta(days=90)).strftime("%Y-%m-%d")
    
    daily_ohlcv = adapter.get_ohlcv(
        symbol="NSE_INDEX|Nifty 50",
        interval="day",
        from_date=pivot_from_date,
        to_date=args.to_date,
    )
    
    if daily_ohlcv is None or daily_ohlcv.empty:
        logger.warning("Failed to fetch daily data for pivots - backtest will have NaN pivots!")
    else:
        # Inject daily OHLCV into strategy for pivot calculation
        strategy._daily_ohlc = daily_ohlcv
        logger.info(f"✓ Injected {len(daily_ohlcv)} days of historical data for pivot calculation")

    # Resample to 5min
    ohlcv_5min = ohlcv_1min.resample("5min").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna(subset=["open"])

    logger.info(f"Total: {len(ohlcv_5min)} 5-min bars")

    # Run backtest with daily compounding
    harness = BacktestHarness(
        strategy=strategy,
        instruments_config=instruments_cfg,
        cooldown_minutes=0,
        allow_hedge=True,
        initial_capital=args.capital,
        risk_per_trade_pct=2.0,
        max_capital_deployed_pct=10.0,
        max_lots_per_trade=10,
    )

    trades = harness.run(ohlcv_5min, instrument="NIFTY", iv=0.14)

    if not trades:
        print("\nNo trades executed")
        return

    df = pd.DataFrame([{
        'exit_time': t.exit_time,
        'lots': t.lots,
        'net_pnl': t.net_pnl,
        'capital_after': t.capital_after,
    } for t in trades])

    ending_capital = df['capital_after'].iloc[-1]
    net_pnl = ending_capital - args.capital
    return_pct = (net_pnl / args.capital) * 100
    winners = len(df[df['net_pnl'] > 0])

    print("\n" + "="*80)
    print("DAILY COMPOUNDING BACKTEST")
    print("="*80)
    print(f"Period:           {args.from_date} → {args.to_date}")
    print(f"Starting Capital: ₹{args.capital:,.2f}")
    print(f"Ending Capital:   ₹{ending_capital:,.2f}")
    print(f"Net P&L:          ₹{net_pnl:+,.2f}")
    print(f"Return:           {return_pct:+.2f}%")
    print(f"\nTrades:           {len(df)}")
    print(f"Win Rate:         {winners}/{len(df)} ({(winners/len(df))*100:.1f}%)")
    print("\n✅ Capital compounded after EVERY trade")
    print("="*80)

if __name__ == "__main__":
    main()
