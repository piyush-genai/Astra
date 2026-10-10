"""
DATA-001: Fetch NIFTY 5-min historical data from Upstox Analytics API.

Fetches Jan 2023 → Dec 2025 in month-aligned chunks.
Months with 31 days are split at day 15 to stay within Upstox v3's
30-calendar-day-per-call hard limit.

Credentials read from .env — never hardcoded.

Output: data/live_data/nifty_5min_20230101_to_20251231.csv
Schema: timestamp (IST, tz-aware), open, high, low, close, volume

Usage:
    python3 scripts/data_001_fetch_historical.py
    python3 scripts/data_001_fetch_historical.py --dry-run
"""
import sys, os, time, argparse, calendar
sys.path.insert(0, '/workshop/atlas')

from pathlib import Path
from datetime import date, timedelta
import pandas as pd
import requests
from urllib.parse import quote

# ── Load .env ──────────────────────────────────────────────────────────────────
def load_env(path=".env"):
    env_path = Path(path)
    if not env_path.exists():
        raise FileNotFoundError(f".env not found at {env_path.resolve()}.")
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
SYMBOL      = "NSE_INDEX|Nifty 50"
INTERVAL    = "minutes/5"            # v3 path segment
START_DATE  = date(2023, 1, 1)
END_DATE    = date(2025, 12, 31)
OUTPUT_PATH = Path("data/live_data/nifty_5min_20230101_to_20251231.csv")
SLEEP_SEC   = 1.5                    # between API calls
MAX_RETRIES = 3

API_URL     = "https://api.upstox.com/v3/historical-candle"
HEADERS     = {"Authorization": f"Bearer {ANALYTICS_TOKEN}", "Accept": "application/json"}
SYMBOL_ENC  = quote(SYMBOL, safe="")

# ── Month-aligned chunk generator ─────────────────────────────────────────────
def month_chunks(start: date, end: date):
    """
    Yield (from_date, to_date) pairs aligned to calendar months.
    Months with 31 days are split at day 15 to stay within the
    Upstox v3 30-day per-call hard limit.
    """
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        _, last_day = calendar.monthrange(y, m)
        month_start = date(y, m, 1)
        month_end   = date(y, m, last_day)

        # Clamp to requested range
        chunk_start = max(month_start, start)
        chunk_end   = min(month_end, end)

        if chunk_start > chunk_end:
            pass
        elif last_day == 31:
            # Split 31-day months at midpoint to stay ≤ 30 days
            mid = date(y, m, 15)
            yield chunk_start, min(mid, chunk_end)
            if mid < chunk_end:
                yield date(y, m, 16), chunk_end
        else:
            yield chunk_start, chunk_end

        m += 1
        if m > 12:
            m, y = 1, y + 1


def fetch_chunk(from_d: date, to_d: date, retries: int = MAX_RETRIES):
    url = f"{API_URL}/{SYMBOL_ENC}/{INTERVAL}/{to_d}/{from_d}"
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                candles = r.json().get("data", {}).get("candles", [])
                return candles
            err = r.json().get("errors", [{}])
            msg = err[0].get("message", r.text[:80]) if err else r.text[:80]
            if attempt < retries:
                time.sleep(2 ** attempt)  # exponential back-off
            else:
                print(f" [retry {attempt}/{retries} FAIL: {msg}]", end="")
        except Exception as e:
            if attempt < retries:
                time.sleep(2 ** attempt)
            else:
                print(f" [exception: {e}]", end="")
    return []


def candles_to_df(candles: list) -> pd.DataFrame:
    df = pd.DataFrame(candles,
        columns=["timestamp","open","high","low","close","volume","open_interest"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df = df.drop(columns=["open_interest"], errors="ignore")
    return df


def fetch_all(dry_run=False):
    chunks = list(month_chunks(START_DATE, END_DATE))
    total  = len(chunks)

    print(f"DATA-001: NIFTY 5-min  |  {START_DATE} → {END_DATE}  |  {total} chunks")
    print(f"  Output: {OUTPUT_PATH}")
    print()

    if dry_run:
        print("DRY RUN — one test call (Dec 2025 first 5 days)...")
        candles = fetch_chunk(date(2025, 12, 1), date(2025, 12, 5))
        if not candles:
            print("  FAILED — no data returned. Check token.")
            sys.exit(1)
        df = candles_to_df(candles)
        print(f"  OK — {len(df)} bars | {df.index[0]} → {df.index[-1]}")
        print("  Token valid. Run without --dry-run for full fetch.")
        return

    frames = []
    missing_chunks = []

    for i, (from_d, to_d) in enumerate(chunks, 1):
        print(f"  [{i:02d}/{total}] {from_d} → {to_d}  ", end="", flush=True)
        candles = fetch_chunk(from_d, to_d)

        if not candles:
            print("NO DATA")
            missing_chunks.append((from_d, to_d))
        else:
            df = candles_to_df(candles)
            frames.append(df)
            print(f"{len(df):6,} bars")

        time.sleep(SLEEP_SEC)

    # ── Retry missing chunks once more with smaller sub-splits ─────────────────
    if missing_chunks:
        print(f"\n  Retrying {len(missing_chunks)} missing chunk(s) with 14-day splits...")
        for from_d, to_d in missing_chunks:
            cursor = from_d
            while cursor <= to_d:
                sub_end = min(cursor + timedelta(days=13), to_d)
                print(f"    {cursor} → {sub_end}  ", end="", flush=True)
                candles = fetch_chunk(cursor, sub_end)
                if not candles:
                    print("NO DATA (data gap confirmed)")
                else:
                    df = candles_to_df(candles)
                    frames.append(df)
                    print(f"{len(df)} bars")
                cursor = sub_end + timedelta(days=1)
                time.sleep(SLEEP_SEC)

    if not frames:
        print("\nERROR: No data received.")
        sys.exit(1)

    # ── Combine, deduplicate, save ─────────────────────────────────────────────
    full = pd.concat(frames).sort_index()
    before = len(full)
    full = full[~full.index.duplicated(keep="first")]
    full.index.name = "timestamp"

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    full.to_csv(OUTPUT_PATH)

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("DATA-001 COMPLETE")
    print("=" * 60)
    print(f"  Total bars      : {len(full):,} ({before - len(full)} dupes dropped)")
    print(f"  Date range      : {full.index[0]} → {full.index[-1]}")
    print(f"  File            : {OUTPUT_PATH}  ({OUTPUT_PATH.stat().st_size/1024/1024:.1f} MB)")
    print()
    print("  Monthly bar counts (expected ~1,500-1,700 per full month):")
    monthly = full.resample("ME").size()
    expected = 75 * 20        # 75 bars/trading-day × ~20 trading days
    for ts, count in monthly.items():
        flag = "⚠" if count < expected * 0.5 else " "
        print(f"  {flag} {ts.strftime('%Y-%m')}: {count:5,} bars")

    if missing_chunks:
        print(f"\n  DATA GAPS (confirmed missing from API):")
        for f, t in missing_chunks:
            print(f"    {f} → {t}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    fetch_all(dry_run=args.dry_run)
