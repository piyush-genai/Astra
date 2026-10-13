"""
Data integrity verification for ASTRA research datasets (TASK-3 / RISK-7).

Every experiment from EXP-0009 onward reads the 2023-2025 NIFTY 5-min and India VIX
CSVs. Those files are gitignored, so each clone re-sources them by hand from NSE and
nothing has ever confirmed that a re-download matches what the experiments actually
ran on. Silent corruption — a missing week, a timezone shift, a duplicated session —
would invalidate EXP-0009 through EXP-0017 without any visible error.

This script fails loudly instead. It runs structural checks and maintains a SHA-256
manifest so a re-download can be compared byte-for-byte against the copy that
produced the recorded results.

Usage:
    python scripts/verify_data.py                     # verify every known dataset
    python scripts/verify_data.py --dataset nifty_2026
    python scripts/verify_data.py --record-checksums   # stamp current files into the manifest

Exit code is 0 when all checks on all present datasets pass, 1 otherwise, so this
can gate a paper-trading or experiment run from CI or a shell script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DATA_DIR = _REPO_ROOT / "data" / "live_data"
_MANIFEST_PATH = _DATA_DIR / "CHECKSUMS.json"

# NSE cash-session bars: 09:15–15:30 is 375 minutes → 75 five-minute bars per day.
_SESSION_MINUTES = 375
_BARS_PER_DAY_5MIN = _SESSION_MINUTES // 5

# A gap of 1-3 business days is a normal NSE holiday cluster (e.g. Diwali, or a
# Thu-Fri pair around a weekend). Anything longer means genuinely absent data, not
# a holiday — that is the line between WARN and FAIL.
_MAX_BENIGN_GAP_BDAYS = 3

# Observed bar count may fall short of the theoretical maximum because of holidays
# and the occasional short/special session, but should never wildly exceed it.
_MIN_BARS_PER_DAY_RATIO = 0.90
_MAX_BARS_PER_DAY_RATIO = 1.01


@dataclass(frozen=True)
class DatasetSpec:
    """Declares what a dataset file is expected to contain."""

    name: str
    filename: str
    kind: str  # "ohlcv_5min" | "vix_daily"
    timestamp_column: str
    required_columns: tuple[str, ...]
    first_date: str
    last_date: str
    required_by: str

    @property
    def path(self) -> Path:
        return _DATA_DIR / self.filename


# Expected row counts are derived from the declared date range rather than hardcoded.
# HANDOFF.md TASK-3 quotes "~220,000 rows" for the 3-year 5-min file; that is ~4x too
# high (≈740 trading days × 75 bars/day ≈ 55,000), so it is deliberately not used here.
DATASETS: tuple[DatasetSpec, ...] = (
    DatasetSpec(
        name="nifty_2023_2025",
        filename="nifty_5min_20230101_to_20251231.csv",
        kind="ohlcv_5min",
        timestamp_column="timestamp",
        required_columns=("open", "high", "low", "close"),
        first_date="2023-01-02",
        last_date="2025-12-31",
        required_by="EXP-0009 … EXP-0017",
    ),
    DatasetSpec(
        name="vix_2023_2025",
        filename="india_vix_daily_20230101_to_20251231.csv",
        kind="vix_daily",
        timestamp_column="date",
        required_columns=("vix",),
        first_date="2023-01-02",
        last_date="2025-12-31",
        required_by="EXP-0013 … EXP-0017",
    ),
    DatasetSpec(
        name="nifty_2026",
        filename="nifty_5min_20260201_to_20260731.csv",
        kind="ohlcv_5min",
        timestamp_column="timestamp",
        required_columns=("open", "high", "low", "close"),
        first_date="2026-02-01",
        last_date="2026-07-31",
        required_by="EXP-0001 (ATLAS baseline)",
    ),
)


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str

    @property
    def marker(self) -> str:
        return "PASS" if self.passed else "FAIL"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_manifest() -> dict[str, Any]:
    if not _MANIFEST_PATH.exists():
        return {}
    return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))


def _check_columns(df: pd.DataFrame, spec: DatasetSpec) -> CheckResult:
    missing = [c for c in spec.required_columns if c not in df.columns]
    if missing:
        return CheckResult("columns", False, f"missing column(s): {', '.join(missing)}")
    return CheckResult("columns", True, f"all present: {', '.join(spec.required_columns)}")


def _check_index(df: pd.DataFrame, spec: DatasetSpec) -> list[CheckResult]:
    results: list[CheckResult] = []

    duplicates = int(df.index.duplicated().sum())
    results.append(
        CheckResult("no_duplicate_timestamps", duplicates == 0, f"{duplicates} duplicate(s)")
    )
    results.append(
        CheckResult(
            "chronological",
            bool(df.index.is_monotonic_increasing),
            "strictly increasing" if df.index.is_monotonic_increasing else "OUT OF ORDER",
        )
    )

    # Compare against the declared range in naive local terms; the 5-min files carry a
    # +05:30 offset while the VIX file is date-only, and tz-awareness must not decide this.
    observed_first = df.index.min().tz_localize(None) if df.index.tz else df.index.min()
    observed_last = df.index.max().tz_localize(None) if df.index.tz else df.index.max()
    expected_first = pd.Timestamp(spec.first_date)
    expected_last = pd.Timestamp(spec.last_date)

    # Allow the first/last bar to sit anywhere inside the expected boundary days.
    starts_ok = observed_first.normalize() <= expected_first + pd.Timedelta(4, unit="D")
    ends_ok = observed_last.normalize() >= expected_last - pd.Timedelta(4, unit="D")
    results.append(
        CheckResult(
            "date_range",
            starts_ok and ends_ok,
            f"{observed_first.date()} → {observed_last.date()} "
            f"(expected ≈{expected_first.date()} → {expected_last.date()})",
        )
    )
    return results


def _check_session_gaps(df: pd.DataFrame) -> list[CheckResult]:
    """Flag stretches of absent business days that holidays cannot explain."""
    results: list[CheckResult] = []
    index = df.index.tz_localize(None) if df.index.tz else df.index
    trading_days = pd.DatetimeIndex(sorted(set(index.normalize())))

    long_gaps: list[str] = []
    for prev, nxt in zip(trading_days[:-1], trading_days[1:]):
        # len() of a bdate_range excluding both endpoints = absent business days between.
        absent = len(pd.bdate_range(prev, nxt)) - 2
        if absent > _MAX_BENIGN_GAP_BDAYS:
            long_gaps.append(f"{prev.date()}→{nxt.date()} ({absent} bdays)")

    results.append(
        CheckResult(
            "no_unexplained_gaps",
            not long_gaps,
            "none"
            if not long_gaps
            else f"{len(long_gaps)} gap(s) > {_MAX_BENIGN_GAP_BDAYS} bdays: "
            + "; ".join(long_gaps[:5])
            + (" …" if len(long_gaps) > 5 else ""),
        )
    )
    results.append(
        CheckResult("trading_days", True, f"{len(trading_days)} distinct session(s)")
    )
    return results


def _check_ohlcv(df: pd.DataFrame) -> list[CheckResult]:
    results: list[CheckResult] = []

    price_cols = ["open", "high", "low", "close"]
    nulls = int(df[price_cols].isna().sum().sum())
    results.append(CheckResult("no_null_prices", nulls == 0, f"{nulls} null price cell(s)"))

    nonpositive = int((df[price_cols] <= 0).sum().sum())
    results.append(
        CheckResult("prices_positive", nonpositive == 0, f"{nonpositive} non-positive price(s)")
    )

    # high must bound open/close/low on every bar, else the bar is malformed.
    bad_bars = int(
        (
            (df["high"] < df["low"])
            | (df["high"] < df["open"])
            | (df["high"] < df["close"])
            | (df["low"] > df["open"])
            | (df["low"] > df["close"])
        ).sum()
    )
    results.append(CheckResult("ohlc_consistent", bad_bars == 0, f"{bad_bars} malformed bar(s)"))

    index = df.index.tz_localize(None) if df.index.tz else df.index
    sessions = len(set(index.normalize()))
    ratio = (len(df) / sessions) / _BARS_PER_DAY_5MIN if sessions else 0.0
    results.append(
        CheckResult(
            "bars_per_session",
            _MIN_BARS_PER_DAY_RATIO <= ratio <= _MAX_BARS_PER_DAY_RATIO,
            f"{len(df) / sessions:.1f} avg vs {_BARS_PER_DAY_5MIN} expected "
            f"({ratio:.1%} of full session)",
        )
    )
    return results


def _check_vix(df: pd.DataFrame) -> list[CheckResult]:
    nulls = int(df["vix"].isna().sum())
    in_range = bool(df["vix"].between(5.0, 100.0).all())
    return [
        CheckResult("no_null_vix", nulls == 0, f"{nulls} null value(s)"),
        CheckResult(
            "vix_plausible",
            in_range,
            f"range {df['vix'].min():.2f} – {df['vix'].max():.2f} (expected 5–100)",
        ),
    ]


def _check_checksum(spec: DatasetSpec, manifest: dict[str, Any]) -> CheckResult:
    actual = sha256(spec.path)
    recorded = manifest.get(spec.name, {}).get("sha256")
    if recorded is None:
        # Not a failure: the manifest is opt-in and starts empty.
        return CheckResult("checksum", True, f"not recorded yet (actual {actual[:16]}…)")
    if recorded == actual:
        return CheckResult("checksum", True, f"matches manifest ({actual[:16]}…)")
    return CheckResult(
        "checksum",
        False,
        f"MISMATCH — file has changed since it was recorded "
        f"(manifest {recorded[:16]}…, actual {actual[:16]}…)",
    )


def verify(spec: DatasetSpec, manifest: dict[str, Any]) -> tuple[bool, pd.DataFrame | None]:
    """Run every applicable check for one dataset. Returns (all_passed, loaded_frame)."""
    print(f"\n{spec.name}  ({spec.filename})")
    print(f"  required by: {spec.required_by}")

    if not spec.path.exists():
        print(f"  ABSENT — {spec.path.relative_to(_REPO_ROOT)} not found")
        print("  → re-source from NSE historical data; see HANDOFF.md section 7")
        return False, None

    size_mb = spec.path.stat().st_size / (1024 * 1024)
    df = pd.read_csv(spec.path, parse_dates=[spec.timestamp_column], index_col=spec.timestamp_column)
    df.index = pd.DatetimeIndex(df.index)
    print(f"  {len(df):,} rows | {size_mb:.1f} MB")

    results = [_check_columns(df, spec)]
    if results[0].passed:
        results += _check_index(df, spec)
        results += _check_session_gaps(df)
        results += _check_ohlcv(df) if spec.kind == "ohlcv_5min" else _check_vix(df)
    results.append(_check_checksum(spec, manifest))

    for r in results:
        print(f"  [{r.marker}] {r.name:<24} {r.detail}")
    return all(r.passed for r in results), df


def cross_check_alignment(frames: dict[str, pd.DataFrame]) -> bool:
    """VIX must cover every NIFTY session, since exp scripts ffill VIX onto trade days."""
    nifty, vix = frames.get("nifty_2023_2025"), frames.get("vix_2023_2025")
    if nifty is None or vix is None:
        return True  # nothing to cross-check

    print("\ncross-check: VIX ↔ NIFTY alignment")
    n_days = {d.date() for d in (nifty.index.tz_localize(None) if nifty.index.tz else nifty.index).normalize()}
    v_days = {d.date() for d in vix.index.normalize()}
    uncovered = sorted(n_days - v_days)

    # A NIFTY session with no VIX row on or before it would silently fall back to the
    # flat 0.14 IV default in the exp scripts — that is a real pricing error, not a gap.
    passed = not uncovered
    detail = "every NIFTY session has a VIX row" if passed else (
        f"{len(uncovered)} NIFTY session(s) lack a VIX row, first: {uncovered[0]}"
    )
    print(f"  [{'PASS' if passed else 'FAIL'}] vix_covers_nifty      {detail}")
    return passed


def record_checksums(specs: tuple[DatasetSpec, ...]) -> None:
    manifest = _load_manifest()
    for spec in specs:
        if not spec.path.exists():
            continue
        manifest[spec.name] = {
            "filename": spec.filename,
            "sha256": sha256(spec.path),
            "bytes": spec.path.stat().st_size,
            "recorded_at": pd.Timestamp.now(tz="Asia/Kolkata").isoformat(),
        }
        print(f"  recorded {spec.name}: {manifest[spec.name]['sha256'][:16]}…")
    _MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\nmanifest written: {_MANIFEST_PATH.relative_to(_REPO_ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify ASTRA research data integrity.")
    parser.add_argument("--dataset", help="verify only this dataset by name")
    parser.add_argument(
        "--record-checksums",
        action="store_true",
        help="write SHA-256 of present files into the manifest, then exit",
    )
    args = parser.parse_args()

    specs = DATASETS
    if args.dataset:
        specs = tuple(s for s in DATASETS if s.name == args.dataset)
        if not specs:
            print(f"unknown dataset '{args.dataset}'. known: {', '.join(s.name for s in DATASETS)}")
            return 1

    if args.record_checksums:
        record_checksums(specs)
        return 0

    print("=" * 72)
    print("ASTRA DATA INTEGRITY VERIFICATION")
    print("=" * 72)

    manifest = _load_manifest()
    if not manifest:
        print("\nno checksum manifest yet — run with --record-checksums once files are trusted")

    ok: dict[str, bool] = {}
    frames: dict[str, pd.DataFrame] = {}
    for spec in specs:
        passed, df = verify(spec, manifest)
        ok[spec.name] = passed
        if df is not None:
            frames[spec.name] = df

    alignment_ok = cross_check_alignment(frames)

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    for name, passed in ok.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
    if not alignment_ok:
        print("  FAIL  vix_nifty_alignment")

    all_ok = all(ok.values()) and alignment_ok
    print(f"\n{'ALL CHECKS PASSED' if all_ok else 'VERIFICATION FAILED — see FAIL rows above'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
