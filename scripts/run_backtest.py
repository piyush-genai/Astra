"""
Run backtest for a strategy.

Usage:
    python scripts/run_backtest.py --strategy pivot_cpr --from 2024-01-01 --to 2024-12-31
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path when run as a script.
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest.harness import BacktestHarness
from src.config_loader import load_instruments, load_risk
from src.strategies.pivot_cpr_strategy import PivotCprStrategy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run strategy backtest")
    parser.add_argument("--strategy", default="pivot_cpr", choices=["pivot_cpr"])
    parser.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()

    instruments_cfg = load_instruments()
    risk_cfg = load_risk()

    if args.strategy == "pivot_cpr":
        strategy = PivotCprStrategy(config={"confluence_tolerance_pct": 0.15})
    else:
        raise ValueError(f"Unknown strategy: {args.strategy}")

    harness = BacktestHarness(strategy=strategy, instruments_config=instruments_cfg)

    logger.info(
        "Backtest not runnable yet — UpstoxAdapter.get_ohlcv() not implemented. "
        "Load historical data from a CSV file as an interim step."
    )
    # TODO: wire up historical data source (CSV or adapter) and call harness.run(ohlcv).


if __name__ == "__main__":
    main()
