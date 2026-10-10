"""
Daily authentication script.

Run this once at the start of each trading session (before market pre-open).
It prints the Upstox login URL, waits for you to complete 2FA in a browser,
then exchanges the code for an access token and prints it.

Usage:
    python scripts/auth.py             # sandbox (default)
    python scripts/auth.py --live      # live app

The printed access token can be pasted into config or used directly by
the engine on the same session.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from core.broker.upstox_adapter import UpstoxAdapter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Upstox daily authentication")
    parser.add_argument("--live", action="store_true", help="Use live app (default: sandbox)")
    args = parser.parse_args()

    if args.live:
        config = {
            "api_key": os.environ["UPSTOX_LIVE_API_KEY"],
            "api_secret": os.environ["UPSTOX_LIVE_API_SECRET"],
            "redirect_uri": os.environ["UPSTOX_LIVE_REDIRECT_URI"],
            "sandbox": False,
        }
        print("Mode: LIVE")
    else:
        config = {
            "api_key": os.environ["UPSTOX_SANDBOX_API_KEY"],
            "api_secret": os.environ["UPSTOX_SANDBOX_API_SECRET"],
            "redirect_uri": os.environ["UPSTOX_SANDBOX_REDIRECT_URI"],
            "sandbox": True,
        }
        print("Mode: SANDBOX")

    adapter = UpstoxAdapter(config)
    adapter.authenticate()

    print("\n" + "="*60)
    print("ACCESS TOKEN:")
    print(adapter._access_token)
    print("="*60)
    print("\nCopy this token — it's valid for the rest of today's session.")


if __name__ == "__main__":
    main()
