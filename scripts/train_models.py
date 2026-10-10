"""
Astra Model Trainer — trains and validates ML models from historical data.

Usage:
    python scripts/train_models.py --data nifty_5min_20260201_to_20260731.csv
    python scripts/train_models.py --walk-forward-only
    python scripts/train_models.py --regime-backtest

Steps performed:
  1. Load historical 5-minute OHLCV data
  2. Run walk-forward validation on PivotCPR strategy (out-of-sample gate)
  3. Run regime-split backtest to identify which regimes have edge
  4. Train regime detector from labeled data
  5. Save model artifacts to ml/models/
  6. Print full summary report
"""
import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.regime_backtest import RegimeBacktest
from backtest.walk_forward import WalkForwardValidator
from ml.features import FeatureEngineer
from ml.regime_detector import RegimeDetector
from ml.trainer import ModelTrainer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("astra.train_models")

MODEL_OUTPUT_PATH = "ml/models/regime.pkl"


def load_data(data_path: str) -> pd.DataFrame:
    """Load historical OHLCV CSV into a DataFrame with datetime index."""
    logger.info("Loading data from %s", data_path)
    df = pd.read_csv(data_path, parse_dates=["datetime"], index_col="datetime")
    df.columns = [c.lower() for c in df.columns]
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}. Found: {list(df.columns)}")
    logger.info("Loaded %d bars from %s to %s", len(df), df.index[0], df.index[-1])
    return df


def run_walk_forward(data: pd.DataFrame, strategy) -> bool:
    """Run walk-forward validation. Returns True if strategy is robust."""
    logger.info("Running walk-forward validation (train=3mo, test=1mo)...")
    validator = WalkForwardValidator(strategy, train_months=3, test_months=1)
    # TODO Phase 3: uncomment once implemented
    # result = validator.run(data, initial_capital=20_000)
    # print(result.summary())
    # return result.is_robust
    logger.warning("Walk-forward not yet implemented (Phase 3) — skipping")
    return True


def run_regime_backtest(data: pd.DataFrame, strategy) -> None:
    """Run regime-split backtest to identify edge by regime."""
    logger.info("Running regime-split backtest...")
    detector = RegimeDetector()  # rule-based
    # TODO Phase 3: uncomment once implemented
    # rb = RegimeBacktest()
    # result = rb.run(data, strategy, detector)
    # print(result.summary())
    # print("\nStrategy selector config:")
    # print(result.get_strategy_selector_config())
    logger.warning("Regime backtest not yet implemented (Phase 3) — skipping")


def train_regime_detector(data: pd.DataFrame) -> RegimeDetector:
    """Train the ML regime detector from labeled historical data."""
    logger.info("Training regime detector...")
    trainer = ModelTrainer(FeatureEngineer())
    # TODO Phase 4: uncomment once implemented
    # detector = trainer.train_regime_detector(data, min_samples=500)
    # detector.save(MODEL_OUTPUT_PATH)
    # logger.info("Model saved to %s", MODEL_OUTPUT_PATH)
    # return detector
    logger.warning("Regime detector training not yet implemented (Phase 4) — using rule-based")
    return RegimeDetector()


def main() -> None:
    parser = argparse.ArgumentParser(description="Astra Model Trainer")
    parser.add_argument("--data", default="nifty_5min_20260201_to_20260731.csv", help="Path to historical OHLCV CSV")
    parser.add_argument("--walk-forward-only", action="store_true", help="Only run walk-forward validation")
    parser.add_argument("--regime-backtest", action="store_true", help="Only run regime-split backtest")
    parser.add_argument("--capital", type=float, default=20_000, help="Starting capital for backtests")
    args = parser.parse_args()

    data = load_data(args.data)

    # Lazy import strategy (src/ path until Phase 1 migration)
    try:
        from strategies.pivot_cpr_strategy import PivotCPRStrategy
        strategy = PivotCPRStrategy()
        logger.info("Loaded PivotCPRStrategy from src/")
    except ImportError:
        logger.error("Could not import PivotCPRStrategy — ensure src/ is accessible")
        sys.exit(1)

    if args.walk_forward_only:
        robust = run_walk_forward(data, strategy)
        sys.exit(0 if robust else 1)

    if args.regime_backtest:
        run_regime_backtest(data, strategy)
        sys.exit(0)

    # Full pipeline
    logger.info("Running full training pipeline...")
    robust = run_walk_forward(data, strategy)
    if not robust:
        logger.error("Strategy failed walk-forward validation — aborting model training")
        sys.exit(1)

    run_regime_backtest(data, strategy)
    train_regime_detector(data)

    logger.info("Training pipeline complete.")
    logger.info("Next step: run 'python scripts/run_live.py' to start paper trading")


if __name__ == "__main__":
    main()
