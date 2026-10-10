#!/usr/bin/env python3
"""
Test with live/future expiry dates to find active contracts.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from core.broker.upstox_adapter import UpstoxAdapter

load_dotenv()

adapter = UpstoxAdapter(config={
    "api_key": "",
    "api_secret": "",
    "redirect_uri": "",
    "analytics_token": os.environ["UPSTOX_ANALYTICS_TOKEN"],
    "sandbox": True,
})

print("=" * 80)
print("TESTING WITH FUTURE EXPIRY DATES")
print("=" * 80)

# Try next few weekly expiries (Tuesdays for Nifty)
today = datetime(2026, 8, 14)  # Today

# Find next Tuesday
days_until_tuesday = (1 - today.weekday()) % 7
if days_until_tuesday == 0:
    days_until_tuesday = 7  # If today is Tuesday, get next Tuesday
    
next_tuesday = today + timedelta(days=days_until_tuesday)

expiry_dates = [
    next_tuesday.strftime("%Y-%m-%d"),
    (next_tuesday + timedelta(days=7)).strftime("%Y-%m-%d"),
    (next_tuesday + timedelta(days=14)).strftime("%Y-%m-%d"),
]

print(f"\nToday: {today.strftime('%Y-%m-%d')}")
print(f"Testing expiries: {', '.join(expiry_dates)}")

# Try to get current Nifty spot for ATM strike
print("\nFetching Nifty spot...")
# This will likely fail during off-hours, so use a reasonable guess
test_strike = 24350

for expiry in expiry_dates:
    print(f"\n{'='*80}")
    print(f"Testing Expiry: {expiry}")
    print(f"{'='*80}")
    
    quote = adapter.get_option_quote(
        instrument="NIFTY",
        strike=test_strike,
        option_type="PE",
        expiry_date=expiry
    )
    
    if quote:
        print(f"✅ SUCCESS!")
        print(f"Contract: NIFTY {datetime.fromisoformat(expiry).strftime('%d%b%y').upper()} {test_strike} PE")
        print(f"LTP:  ₹{quote['ltp']:.2f}")
        print(f"Bid:  ₹{quote['bid']:.2f}")
        print(f"Ask:  ₹{quote['ask']:.2f}")
        print(f"OI:   {quote['oi']:,}")
        print(f"\n✅ Real option premiums are working!")
        break
    else:
        print(f"❌ No contracts found for {expiry}")

print("\n" + "=" * 80)
