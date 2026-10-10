"""
Test Upstox data plane (Analytics Token) via UpstoxAdapter.

Tests:
1. get_ltp() for Nifty 50
2. get_ohlcv() for 1-min candles (last 3 days)
3. Resample 1-min to 5-min (strategy needs 5-min bars)

Usage:
    python scripts/test_data.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from core.broker.upstox_adapter import UpstoxAdapter

if __name__ == "__main__":
    config = {
        "api_key": os.environ["UPSTOX_LIVE_API_KEY"],
        "api_secret": os.environ["UPSTOX_LIVE_API_SECRET"],
        "redirect_uri": os.environ["UPSTOX_LIVE_REDIRECT_URI"],
        "analytics_token": os.environ["UPSTOX_ANALYTICS_TOKEN"],
        "sandbox": True,  # Execution goes to sandbox, data comes from analytics token
    }

    adapter = UpstoxAdapter(config)

    print("="*60)
    print("TEST 1: Get LTP for Nifty 50")
    print("="*60)
    ltp = adapter.get_ltp("NSE_INDEX|Nifty 50")
    print(f"Nifty 50 LTP: {ltp}\n")

    print("="*60)
    print("TEST 2: Get 1-min OHLCV (last 3 days)")
    print("="*60)
    to_date = date.today().isoformat()
    from_date = (date.today() - timedelta(days=3)).isoformat()
    df_1min = adapter.get_ohlcv(
        symbol="NSE_INDEX|Nifty 50",
        interval="1minute",
        from_date=from_date,
        to_date=to_date,
    )
    print(f"Fetched {len(df_1min)} 1-min candles")
    print(df_1min.head(10))
    print()

    print("="*60)
    print("TEST 3: Resample 1-min → 5-min")
    print("="*60)
    df_5min = df_1min.resample("5min").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["open"])
    print(f"Resampled to {len(df_5min)} 5-min candles")
    print(df_5min.head(10))
