"""
Astra Live Trading — production entry point.

Usage:
    python scripts/run_live.py                     # dry-run mode (safe default)
    python scripts/run_live.py --no-dry-run        # LIVE mode — places real orders
    python scripts/run_live.py --capital 50000     # override starting capital
    python scripts/run_live.py --config config/    # custom config directory

Default: dry-run=True. You must explicitly pass --no-dry-run to place real orders.
"""
import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from live.orchestrator import AstraOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("astra.run_live")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Astra Live Trading",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/run_live.py                    # dry-run (safe, no real orders)
  python scripts/run_live.py --no-dry-run       # LIVE — places real Upstox orders
  python scripts/run_live.py --capital 50000    # start with ₹50,000
        """,
    )
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        default=True,
        help="Place REAL orders via Upstox. Omit this flag for safe simulation.",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=None,
        help="Override starting capital (₹). If omitted, uses StateManager's persisted value.",
    )
    parser.add_argument(
        "--config",
        default="config/",
        help="Path to config directory (default: config/)",
    )
    args = parser.parse_args()

    mode = "DRY RUN (no real orders)" if args.dry_run else "⚠️  LIVE TRADING (real orders)"
    logger.info("=" * 60)
    logger.info("Astra starting — mode: %s", mode)
    if args.capital:
        logger.info("Capital override: ₹%.0f", args.capital)
    logger.info("=" * 60)

    if not args.dry_run:
        confirm = input("\nYou are about to place REAL orders. Type 'CONFIRM' to proceed: ")
        if confirm.strip() != "CONFIRM":
            logger.info("Aborted.")
            sys.exit(0)

    orchestrator = AstraOrchestrator(config_path=args.config)
    orchestrator._dry_run = args.dry_run
    orchestrator.run()


if __name__ == "__main__":
    main()
