"""
Run a strategy in paper-trading mode (live data, simulated orders).

Usage:
    python scripts/run_paper.py --strategy pivot_cpr
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config_loader import load_instruments, load_risk

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run strategy in paper-trading mode")
    parser.add_argument("--strategy", default="pivot_cpr", choices=["pivot_cpr"])
    args = parser.parse_args()

    instruments_cfg = load_instruments()
    risk_cfg = load_risk()

    logger.info(
        "Paper trading requires LiveFeed and UpstoxAdapter implementations. "
        "Run this script once those are complete."
    )
    # TODO: wire StrategyRegistry, PositionManager, RiskManager, ExecutionEngine
    # with dry_run=True and a live feed.


if __name__ == "__main__":
    main()
