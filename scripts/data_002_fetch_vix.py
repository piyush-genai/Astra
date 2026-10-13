"""
DATA-002: Fetch India VIX daily history from the Upstox Analytics API.

Fills the gap that blocked EXP-0013 through EXP-0017. HANDOFF.md section 7 listed
this file as a manual NSE download with no fetcher in the repo, which made the VIX
half of the strategy stack unreproducible on any fresh clone. It turns out Upstox
serves it directly under the instrument key "NSE_INDEX|India VIX".

Unlike DATA-001, no chunking is needed: the 30-calendar-day limit applies to
intraday intervals, and the whole 2023-2025 range returns in one daily-interval
call (744 candles, matching the 744 trading sessions in the NIFTY 5-min dataset).

Credentials read from .env — never hardcoded.

Output: data/live_data/india_vix_daily_20230101_to_20251231.csv
Schema: date (IST, tz-aware), vix

The consuming experiments read only the `vix` column, which is the daily CLOSE.
Open/high/low are dropped deliberately: EXP-0013 through EXP-0017 all index VIX by
day and forward-fill, so carrying intraday columns would invite someone to use a
value the validated research never used.

Usage:
    python3 scripts/data_002_fetch_vix.py
    python3 scripts/data_002_fetch_vix.py --dry-run
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import time
from datetime import date
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests


# ── Load .env ──────────────────────────────────────────────────────────────────
def load_env(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        raise FileNotFoundError(
            f".env not found at {env_path.resolve()}. Copy .env.example and fill it in."
        )
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


load_env()

ANALYTICS_TOKEN = os.environ.get("UPSTOX_ANALYTICS_TOKEN", "")
if not ANALYTICS_TOKEN:
    sys.exit("UPSTOX_ANALYTICS_TOKEN not found in .env — aborting.")

# ── Config ─────────────────────────────────────────────────────────────────────
SYMBOL      = "NSE_INDEX|India VIX"   # the only accepted spelling; "INDIA VIX" 400s
INTERVAL    = "days/1"
START_DATE  = date(2023, 1, 1)
END_DATE    = date(2025, 12, 31)
OUTPUT_PATH = Path("data/live_data/india_vix_daily_20230101_to_20251231.csv")
MAX_RETRIES = 3

API_URL    = "https://api.upstox.com/v3/historical-candle"
HEADERS    = {"Authorization": f"Bearer {ANALYTICS_TOKEN}", "Accept": "application/json"}
SYMBOL_ENC = quote(SYMBOL, safe="")

# Upstox candle layout: [timestamp, open, high, low, close, volume, oi]
CLOSE_IDX = 4


def fetch(from_d: date, to_d: date, retries: int = MAX_RETRIES) -> list:
    url = f"{API_URL}/{SYMBOL_ENC}/{INTERVAL}/{to_d}/{from_d}"
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            if r.status_code == 200:
                return r.json().get("data", {}).get("candles", [])
            errs = r.json().get("errors", [{}])
            msg = errs[0].get("message", r.text[:80]) if errs else r.text[:80]
            print(f"  [attempt {attempt}/{retries}] HTTP {r.status_code}: {msg}")
        except Exception as exc:
            print(f"  [attempt {attempt}/{retries}] {type(exc).__name__}: {exc}")
        if attempt < retries:
            time.sleep(2 ** attempt)  # exponential back-off
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch India VIX daily history.")
    parser.add_argument(
        "--dry-run", action="store_true", help="single short call to validate the token"
    )
    args = parser.parse_args()

    print(f"DATA-002: India VIX daily  |  {START_DATE} → {END_DATE}")
    print(f"  Symbol: {SYMBOL}")
    print(f"  Output: {OUTPUT_PATH}")
    print()

    if args.dry_run:
        print("DRY RUN — one test call (Dec 2025)...")
        candles = fetch(date(2025, 12, 1), date(2025, 12, 31))
        if not candles:
            print("  FAILED — no candles returned.")
            return 1
        print(f"  OK — {len(candles)} candles | {candles[-1][0]} → {candles[0][0]}")
        print("  Token valid. Run without --dry-run for the full fetch.")
        return 0

    candles = fetch(START_DATE, END_DATE)
    if not candles:
        print("FAILED — no candles returned. Nothing written.")
        return 1

    # Upstox returns newest-first; the experiments expect chronological order.
    rows = [
        {"date": pd.Timestamp(c[0]).normalize(), "vix": float(c[CLOSE_IDX])}
        for c in candles
    ]
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)

    before = len(df)
    df = df.drop_duplicates(subset="date", keep="last")
    dupes = before - len(df)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)

    print("=" * 60)
    print("DATA-002 COMPLETE")
    print("=" * 60)
    print(f"  Total rows : {len(df):,} ({dupes} dupes dropped)")
    print(f"  Date range : {df['date'].iloc[0].date()} → {df['date'].iloc[-1].date()}")
    print(f"  VIX range  : {df['vix'].min():.2f} – {df['vix'].max():.2f}")
    print(f"  Written to : {OUTPUT_PATH}")
    print()
    print("  Next: python3 scripts/verify_data.py --record-checksums")
    return 0


if __name__ == "__main__":
    sys.exit(main())
