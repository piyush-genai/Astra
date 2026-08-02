"""
Run backtest for a strategy.

Usage:
    python scripts/run_backtest.py --strategy pivot_cpr --from 2026-05-01 --to 2026-07-31
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure project root is on sys.path when run as a script.
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()

from src.backtest.harness import BacktestHarness
from src.broker.upstox_adapter import UpstoxAdapter
from src.config_loader import load_instruments, load_risk
from src.strategies.pivot_cpr_strategy import PivotCprStrategy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run strategy backtest")
    parser.add_argument("--strategy", default="pivot_cpr", choices=["pivot_cpr"])
    parser.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--tolerance", type=float, default=0.18, help="Zone tolerance %")
    parser.add_argument("--min-levels", type=int, default=2, help="Min levels for confluence")
    args = parser.parse_args()

    instruments_cfg = load_instruments()
    risk_cfg = load_risk()

    # Create strategy with specified params.
    if args.strategy == "pivot_cpr":
        strategy = PivotCprStrategy(config={
            "tolerance_pct": args.tolerance,
            "min_levels_for_confluence": args.min_levels,
        })
    else:
        raise ValueError(f"Unknown strategy: {args.strategy}")

    harness = BacktestHarness(strategy=strategy, instruments_config=instruments_cfg)

    # Fetch historical data via Upstox adapter (Analytics Token only — no OAuth needed for data).
    logger.info("Fetching historical data: %s to %s", args.from_date, args.to_date)
    adapter = UpstoxAdapter(config={
        "api_key":         os.environ.get("UPSTOX_SANDBOX_API_KEY", ""),
        "api_secret":      os.environ.get("UPSTOX_SANDBOX_API_SECRET", ""),
        "redirect_uri":    os.environ.get("UPSTOX_SANDBOX_REDIRECT_URI", ""),
        "analytics_token": os.environ["UPSTOX_ANALYTICS_TOKEN"],
        "sandbox":         True,
    })

    # Fetch 1-min data (Upstox doesn't support 5-min directly) and resample.
    ohlcv_1min = adapter.get_ohlcv(
        symbol="NSE_INDEX|Nifty 50",
        interval="1minute",
        from_date=args.from_date,
        to_date=args.to_date,
    )

    if ohlcv_1min is None or ohlcv_1min.empty:
        logger.error("No data returned from adapter. Aborting.")
        return

    # Resample to 5-min bars (strategy requirement).
    ohlcv = ohlcv_1min.resample("5min").agg({
        "open":  "first",
        "high":  "max",
        "low":   "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["open"])

    logger.info("Resampled to %d 5-min bars. Running backtest...", len(ohlcv))

    # Run the backtest.
    result = harness.run(ohlcv)

    # ── Trade-level results ───────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("BACKTEST RESULTS  —  Nifty 5-min Pivot CPR")
    print(f"Period : {args.from_date}  →  {args.to_date}")
    print(f"Params : tolerance={args.tolerance}%  min_levels={args.min_levels}")
    print("=" * 65)

    if not result.trades:
        print("No trades executed.")
    else:
        print(f"\n{'#':<4} {'Dir':<6} {'Entry time':<26} {'Entry':>8} {'Exit time':<26} "
              f"{'Exit':>8} {'PnL pts':>9} {'Reason'}")
        print("-" * 105)
        for i, t in enumerate(result.trades, 1):
            direction = "LONG" if t.direction.name == "LONG" else "SHORT"
            print(
                f"{i:<4} {direction:<6} {str(t.entry_time):<26} {t.entry_price:>8.2f} "
                f"{str(t.exit_time):<26} {t.exit_price:>8.2f} "
                f"{t.pnl_points:>+9.2f} {t.exit_reason}"
            )

        m = result.metrics
        print("\n" + "=" * 65)
        print("SUMMARY")
        print("=" * 65)
        print(f"  Trades       : {m['total_trades']}  (W:{m['winners']}  L:{m['losers']})")
        print(f"  Win rate     : {m['win_rate_pct']}%")
        print(f"  Total P&L    : {m['total_pnl_pts']:+.2f} pts")
        print(f"  Avg win      : {m['avg_win_pts']:+.2f} pts")
        print(f"  Avg loss     : {m['avg_loss_pts']:+.2f} pts")
        print(f"  Profit factor: {m['profit_factor']}")
        print(f"  Max drawdown : {m['max_drawdown_pts']:.2f} pts")
        print(f"  Exit reasons : {m['exit_reasons']}")

    print("\n  NOTE: P&L is in Nifty index points, not rupees.")
    print("  Options premium overlay (task 10) not yet implemented.")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
