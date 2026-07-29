"""
Run a strategy in live trading mode.

⚠️  GATE CHECK — this script refuses to run unless the strategy has
    passed all three gates mandated by trading-risk-rules.md:
      1. Unit tests on indicator formulas
      2. Backtest vs kill-criteria
      3. Minimum paper-trading period

Usage:
    python scripts/run_live.py --strategy pivot_cpr
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Gate status — manually updated by operator after each gate is cleared.
# Never skip or bypass these gates (Rule 9 in trading-risk-rules.md).
GATE_STATUS: dict[str, dict[str, bool]] = {
    "pivot_cpr": {
        "unit_tests_passed": False,
        "backtest_passed": False,
        "paper_trading_completed": False,
    }
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run strategy in live trading mode")
    parser.add_argument("--strategy", default="pivot_cpr", choices=["pivot_cpr"])
    args = parser.parse_args()

    gates = GATE_STATUS.get(args.strategy, {})
    failed = [name for name, passed in gates.items() if not passed]

    if failed:
        logger.error(
            "LIVE TRADING BLOCKED for '%s'. The following gates have not been cleared:\n%s\n"
            "Complete each gate before enabling live trading.",
            args.strategy,
            "\n".join(f"  ✗ {g}" for g in failed),
        )
        sys.exit(1)

    logger.info("All gates cleared for '%s'. Starting live trading...", args.strategy)
    # TODO: wire live engine here once gates are cleared.


if __name__ == "__main__":
    main()
