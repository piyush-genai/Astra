#!/usr/bin/env python3
"""
Test script to verify real option quote fetching from Upstox using option chain.

Tests the CORRECT approach: query option chain endpoint for real instrument keys.
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from src.broker.upstox_adapter import UpstoxAdapter

load_dotenv()


def test_option_chain():
    """Test fetching real option quotes via option chain endpoint."""
    
    print("=" * 80)
    print("TESTING REAL OPTION QUOTE FETCHING VIA OPTION CHAIN")
    print("=" * 80)
    
    # Initialize adapter
    adapter = UpstoxAdapter(config={
        "api_key": os.environ.get("UPSTOX_SANDBOX_API_KEY", ""),
        "api_secret": os.environ.get("UPSTOX_SANDBOX_API_SECRET", ""),
        "redirect_uri": os.environ.get("UPSTOX_SANDBOX_REDIRECT_URI", ""),
        "analytics_token": os.environ["UPSTOX_ANALYTICS_TOKEN"],
        "sandbox": True,
    })
    
    # Test with weekly expiry (adjust date as needed)
    print("\n1. Testing option chain fetch for NIFTY weekly expiry...")
    print("   Expiry: 2026-08-13 (Tuesday)")
    print("   Strike: 24350")
    print("   Type: PE (Put)")
    
    quote = adapter.get_option_quote(
        instrument="NIFTY",
        strike=24350,
        option_type="PE",
        expiry_date="2026-08-13"
    )
    
    if quote:
        print(f"\n   ✅ SUCCESS!")
        print(f"   Instrument Key: {quote['instrument_key']}")
        print(f"   LTP:  ₹{quote['ltp']:.2f}")
        print(f"   Bid:  ₹{quote['bid']:.2f}")
        print(f"   Ask:  ₹{quote['ask']:.2f}")
        print(f"   OI:   {quote['oi']:,}")
        print(f"\n   📊 Bid-Ask Spread: ₹{quote['ask'] - quote['bid']:.2f}")
        print(f"   💡 For buying (entry), use Ask: ₹{quote['ask']:.2f}")
        print(f"   💡 For selling (exit), use Bid:  ₹{quote['bid']:.2f}")
    else:
        print(f"\n   ❌ Failed to fetch option chain")
        print(f"   Possible reasons:")
        print(f"   - Analytics Token expired/invalid")
        print(f"   - Expiry date has no contracts (expired)")
        print(f"   - Strike not available in chain")
        print(f"   - Market closed (option chain unavailable)")
    
    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)
    
    if quote:
        print("\n✅ Real option premiums are working!")
        print("   Paper trading will now use:")
        print(f"   - Entry: Ask price (₹{quote['ask']:.2f})")
        print(f"   - Exit:  Bid price (₹{quote['bid']:.2f})")
        print("   - Realistic bid-ask spread included")
    else:
        print("\n⚠️  Falling back to Black-Scholes in paper trading")
        print("   Check Analytics Token and try again during market hours")


if __name__ == "__main__":
    test_option_chain()
