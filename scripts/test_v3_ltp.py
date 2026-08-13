#!/usr/bin/env python3
"""
Test v3 LTP endpoint directly to isolate authentication issue.
"""

import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
import requests

load_dotenv()

token = os.environ["UPSTOX_ANALYTICS_TOKEN"]

print("=" * 80)
print("TESTING V3 LTP ENDPOINT (SANITY CHECK)")
print("=" * 80)

url = "https://api.upstox.com/v3/market-quote/ltp"
params = {"instrument_key": "NSE_INDEX|Nifty 50"}
headers = {
    "Accept": "application/json",
    "Authorization": f"Bearer {token}",
}

print(f"\nURL: {url}")
print(f"Params: {params}")
print(f"Token: {token[:20]}...{token[-20:]}")
print("\nSending request...")

resp = requests.get(url, headers=headers, params=params, timeout=10)

print(f"\nStatus Code: {resp.status_code}")
print(f"Response: {resp.text[:500]}")

if resp.status_code == 200:
    data = resp.json()
    print("\n✅ SUCCESS - Analytics Token works for v3 LTP!")
    print(f"Nifty LTP: ₹{data['data']['NSE_INDEX:Nifty 50']['last_price']:.2f}")
else:
    print(f"\n❌ FAILED - Status {resp.status_code}")
    print("This is an account-level permission issue, not a code bug.")
    print("Action: Contact Upstox support about Analytics Token access to market-quote endpoints.")

print("=" * 80)
