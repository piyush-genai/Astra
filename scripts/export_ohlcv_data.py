#!/usr/bin/env python3
"""
Export raw 5-minute NIFTY OHLCV data to CSV.

Usage:
    python scripts/export_ohlcv_data.py --from 2026-02-01 --to 2026-07-31
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.broker.upstox_adapter import UpstoxAdapter

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Export raw 5-min OHLCV data")
    parser.add_argument("--from", dest="from_date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--output", default=None, help="Output CSV filename (default: nifty_5min_DATES.csv)")
    args = parser.parse_args()
    
    # Create adapter
    adapter = UpstoxAdapter(config={
        "api_key": os.environ.get("UPSTOX_SANDBOX_API_KEY", ""),
        "api_secret": os.environ.get("UPSTOX_SANDBOX_API_SECRET", ""),
        "redirect_uri": os.environ.get("UPSTOX_SANDBOX_REDIRECT_URI", ""),
        "analytics_token": os.environ["UPSTOX_ANALYTICS_TOKEN"],
        "sandbox": True,
    })
    
    logger.info(f"Fetching 1-min OHLCV data from {args.from_date} to {args.to_date}...")
    
    # Fetch 1-min data
    ohlcv_1min = adapter.get_ohlcv(
        symbol="NSE_INDEX|Nifty 50",
        interval="1minute",
        from_date=args.from_date,
        to_date=args.to_date,
    )
    
    if ohlcv_1min is None or ohlcv_1min.empty:
        logger.error("No data fetched!")
        return
    
    logger.info(f"Fetched {len(ohlcv_1min)} 1-min bars. Resampling to 5-min...")
    
    # Resample to 5-min
    ohlcv_5min = ohlcv_1min.resample("5min").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["open"])
    
    logger.info(f"Resampled to {len(ohlcv_5min)} 5-min bars.")
    
    # Determine output filename
    if args.output:
        output_path = args.output
    else:
        from_str = args.from_date.replace("-", "")
        to_str = args.to_date.replace("-", "")
        output_path = f"nifty_5min_{from_str}_to_{to_str}.csv"
    
    # Save to CSV
    ohlcv_5min.to_csv(output_path)
    
    logger.info(f"✅ Exported {len(ohlcv_5min)} rows to {output_path}")
    logger.info(f"   Date range: {ohlcv_5min.index[0]} to {ohlcv_5min.index[-1]}")
    logger.info(f"   Columns: {list(ohlcv_5min.columns)}")
    
    # Show sample
    print("\nFirst 5 rows:")
    print(ohlcv_5min.head())
    print("\nLast 5 rows:")
    print(ohlcv_5min.tail())


if __name__ == "__main__":
    main()
