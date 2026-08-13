#!/usr/bin/env python3
"""
Debug Analytics Token - check expiry and exact error codes.
"""

import os
import sys
import json
import base64
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
import requests

load_dotenv()

token = os.environ["UPSTOX_ANALYTICS_TOKEN"]

print("=" * 80)
print("STEP 1: DECODE JWT AND CHECK EXPIRY")
print("=" * 80)

# Decode JWT payload
try:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)  # pad
    decoded = json.loads(base64.urlsafe_b64decode(payload))
    
    print("\nJWT Payload:")
    print(json.dumps(decoded, indent=2))
    
    if "exp" in decoded:
        exp_timestamp = decoded["exp"]
        exp_datetime = datetime.fromtimestamp(exp_timestamp)
        now = datetime.now()
        
        print(f"\nExpiry: {exp_datetime}")
        print(f"Now:    {now}")
        
        if now < exp_datetime:
            print(f"✅ Token is VALID (expires in {(exp_datetime - now).days} days)")
        else:
            print(f"❌ Token is EXPIRED (expired {(now - exp_datetime).days} days ago)")
    else:
        print("\n⚠️  No 'exp' field found in JWT")
        
except Exception as e:
    print(f"❌ Failed to decode JWT: {e}")

print("\n" + "=" * 80)
print("STEP 2: CHECK EXACT ERROR CODE")
print("=" * 80)

# Test v3 market-quote/ltp and capture exact error
url = "https://api.upstox.com/v3/market-quote/ltp"
params = {"instrument_key": "NSE_INDEX|Nifty 50"}
headers = {
    "Accept": "application/json",
    "Authorization": f"Bearer {token}",
}

print(f"\nTesting: {url}")
resp = requests.get(url, headers=headers, params=params, timeout=10)

print(f"\nStatus Code: {resp.status_code}")
print(f"\nFull Response Body:")
print(json.dumps(resp.json(), indent=2))

if resp.status_code == 401:
    error_data = resp.json()
    if "errors" in error_data:
        for err in error_data["errors"]:
            error_code = err.get("errorCode") or err.get("error_code")
            if error_code == "UDAPI100050":
                print("\n" + "=" * 80)
                print("🔍 CONFIRMED: UDAPI100050 - Known Upstox Bug")
                print("=" * 80)
                print("\nThis is the EXACT error reported by multiple developers:")
                print("- 4 days ago: 401 on /v2/market-quote/ltp")
                print("- 1 week ago: Analytics Token fails on Option Contract, Market Quote")
                print("- Same month: Analytics Token works on profile but not market data")
                print("\n⚠️  This is NOT your code - it's an Upstox platform issue")
                print("\nNext steps:")
                print("1. Try OAuth token (Step 3 below)")
                print("2. File support ticket with Upstox")
                print("3. Reference community reports (see Claude's message)")

print("\n" + "=" * 80)
print("STEP 3: TEST WITH OAUTH TOKEN (if available)")
print("=" * 80)

# Check if OAuth token exists
oauth_token = os.environ.get("UPSTOX_ACCESS_TOKEN")
if oauth_token:
    print("\nFound OAuth token in .env, testing...")
    headers_oauth = {
        "Accept": "application/json",
        "Authorization": f"Bearer {oauth_token}",
    }
    
    resp_oauth = requests.get(url, headers=headers_oauth, params=params, timeout=10)
    print(f"\nOAuth Status Code: {resp_oauth.status_code}")
    
    if resp_oauth.status_code == 200:
        print("✅ OAuth token WORKS!")
        print("→ Problem is Analytics Token scoping, not your code")
        print("→ Use OAuth for option chain / LTP calls")
    else:
        print(f"❌ OAuth also failed: {resp_oauth.status_code}")
else:
    print("\nNo UPSTOX_ACCESS_TOKEN found in .env")
    print("To test OAuth: Run authenticate() and try option chain endpoint")

print("\n" + "=" * 80)
