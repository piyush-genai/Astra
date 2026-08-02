"""
Quick smoke test for the Upstox sandbox connection.

Tests:
1. Auth — confirm token is accepted
2. Get profile — confirms the token is valid
3. Get LTP for Nifty 50 index
4. Get historical OHLCV (5-min, last 5 days)

Usage:
    python scripts/test_sandbox.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import requests

TOKEN   = os.environ["UPSTOX_SANDBOX_ACCESS_TOKEN"]
# Sandbox base URL — confirmed from upstox_client.Configuration(sandbox=True)
BASE    = "https://api-sandbox.upstox.com/v2"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

def get(path: str, params: dict = None):
    resp = requests.get(f"{BASE}{path}", headers=HEADERS, params=params, timeout=10)
    print(f"\n{'='*50}")
    print(f"GET {path}  →  HTTP {resp.status_code}")
    try:
        print(resp.json())
    except Exception:
        print(resp.text)
    return resp

if __name__ == "__main__":
    # 1. Profile — simplest auth check
    get("/user/profile")

    # 2. LTP for Nifty 50 index
    # Upstox sandbox instrument key for Nifty 50 index
    get("/market-quote/ltp", params={"instrument_key": "NSE_INDEX|Nifty 50"})

    # 3. Historical candles — 1-min (Upstox historical API does NOT support 5minute.
    #    Valid intervals: 1minute, 30minute, day, week, month.
    #    For the strategy we will use 1-min bars and resample to 5-min in-process.)
    to_date   = date.today().isoformat()
    from_date = (date.today() - timedelta(days=7)).isoformat()
    get(
        f"/historical-candle/NSE_INDEX|Nifty 50/1minute/{to_date}/{from_date}",
    )
