"""
Astra Orchestrator — the production trading loop.

Wires together all components and runs the daily market-hours cycle:

  Pre-market  (09:00–09:15): Detect regime, select strategies, health check
  Market loop (09:15–15:20): Every 5 min — fetch data, scan, rank, execute
  Post-market (15:20–15:30): Close all positions, daily summary, persist state

Component wiring:
  BrokerAdapter
    └─ ExecutionEngine
         ├─ RiskManager
         ├─ PositionManager
         └─ StrategyRegistry
  RegimeDetector
  StrategySelector ── strategies[]
  UniverseScanner
  OpportunityRanker
  StateManager
  SystemMonitor
"""
from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Optional

import yaml

from live.monitor import SystemMonitor
from live.state_manager import StateManager
from ml.regime_detector import RegimeDetector
from ml.strategy_selector import StrategySelector
from strategies.base import MarketData
from universe.opportunity_ranker import OpportunityRanker
from universe.scanner import ScanResult, UniverseScanner

logger = logging.getLogger(__name__)

MARKET_OPEN  = dt_time(9, 15)
MARKET_EOD   = dt_time(15, 20)   # start closing positions
MARKET_CLOSE = dt_time(15, 30)
PRE_MARKET   = dt_time(9, 0)
BAR_INTERVAL = 300  # 5 minutes in seconds


class AstraOrchestrator:
    """
    Main production entry point for Astra.

    Usage:
        orchestrator = AstraOrchestrator("config/")
        orchestrator.run()  # blocks until market close or kill signal
    """

    def __init__(self, config_path: str = "config/") -> None:
        self._config_path = Path(config_path)
        self._config: dict = {}
        self._broker = None
        self._execution_engine = None
        self._risk_manager = None
        self._position_manager = None
        self._regime_detector: Optional[RegimeDetector] = None
        self._strategy_selector: Optional[StrategySelector] = None
        self._scanner: Optional[UniverseScanner] = None
        self._ranker: Optional[OpportunityRanker] = None
        self._state: Optional[StateManager] = None
        self._monitor: Optional[SystemMonitor] = None
        self._dry_run: bool = True
        self._running: bool = False

        # Register kill signals
        signal.signal(signal.SIGINT,  self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def run(self) -> None:
        """
        Main entry point. Blocks until market close or a kill signal.
        Call this from scripts/run_live.py.
        """
        self._initialize()
        self._running = True
        logger.info("Astra started. dry_run=%s", self._dry_run)

        try:
            # Wait for pre-market window
            self._wait_until(PRE_MARKET)
            self._pre_market()

            # Wait for market open
            self._wait_until(MARKET_OPEN)
            self._market_hours_loop()

        except Exception:
            logger.exception("Fatal error in orchestrator")
            self._emergency_shutdown()
        finally:
            self._post_market()
            logger.info("Astra session ended.")

    # ------------------------------------------------------------------
    # Lifecycle phases
    # ------------------------------------------------------------------

    def _initialize(self) -> None:
        """Load config and wire all components."""
        self._config = self._load_config()
        self._state = StateManager(db_path="astra_state.db")

        # TODO Phase 1: instantiate real UpstoxAdapter
        # from core.broker.upstox_adapter import UpstoxAdapter
        # self._broker = UpstoxAdapter(...)

        # TODO Phase 1: instantiate ExecutionEngine, RiskManager, PositionManager
        # from core.engine.execution_engine import ExecutionEngine
        # from core.engine.risk_manager import RiskManager
        # from core.engine.position_manager import PositionManager
        # self._risk_manager = RiskManager(config=self._config["risk"])
        # self._position_manager = PositionManager()
        # self._execution_engine = ExecutionEngine(self._broker, self._risk_manager, self._position_manager)

        # Regime detection + strategy selection
        model_path = "ml/models/regime.pkl"
        self._regime_detector = RegimeDetector(model_path if Path(model_path).exists() else None)

        strategies = self._load_strategies()
        self._strategy_selector = StrategySelector(
            strategies,
            min_regime_samples=self._config.get("ml", {}).get("strategy_selector", {}).get("min_regime_samples", 50),
        )

        self._scanner = UniverseScanner(
            broker_adapter=self._broker,
            strategy_selector=self._strategy_selector,
            regime_detector=self._regime_detector,
            risk_manager=self._risk_manager,
        )
        self._ranker = OpportunityRanker(
            max_opportunities=self._config.get("ml", {}).get("universe", {}).get("max_simultaneous_opportunities", 3),
        )

        # Monitoring
        telegram_cfg = self._config.get("telegram", {})
        if telegram_cfg.get("token") and telegram_cfg.get("chat_id"):
            self._monitor = SystemMonitor(
                telegram_token=telegram_cfg["token"],
                chat_id=telegram_cfg["chat_id"],
                state_manager=self._state,
            )
        logger.info("Astra initialized. Capital: ₹%.0f", self._state.get_capital())

    def _pre_market(self) -> None:
        """
        Pre-market routine (09:00–09:15).
        Detect today's regime, select strategies, run health checks.
        """
        logger.info("Pre-market routine starting")
        if self._monitor:
            health = self._monitor.check_system_health()
            if not all(health.values()):
                self._monitor.alert_on_anomaly(f"Pre-market health check failed: {health}")
            self._monitor.start_heartbeat(interval_seconds=300)

        # TODO Phase 2: fetch last 60 days of daily OHLCV for regime detection
        # daily_ohlcv = self._broker.get_ohlcv("NIFTY", "1day", lookback=60)
        # regime, confidence = self._regime_detector.detect_with_confidence(daily_ohlcv)
        # logger.info("Today's regime: %s (confidence=%.2f)", regime.value, confidence)
        # self._state.log_regime(date.today(), regime.value, confidence, {})

        logger.info("Pre-market complete")

    def _market_hours_loop(self) -> None:
        """
        Main trading loop. Runs every 5 minutes from 09:15 to 15:20.
        Each iteration: fetch → scan → rank → execute.
        """
        logger.info("Market hours loop started")
        while self._running:
            now = datetime.now().time()
            if now >= MARKET_EOD:
                logger.info("Reached EOD — exiting market loop")
                break

            try:
                self._run_one_bar()
            except Exception:
                logger.exception("Error in bar loop — continuing")

            self._sleep_to_next_bar()

    def _run_one_bar(self) -> None:
        """Execute one 5-minute bar cycle."""
        # TODO Phase 2: replace with real data fetch
        # market_data_map = self._fetch_all_market_data()
        market_data_map: dict[str, MarketData] = {}

        scan_results = self._scanner.scan(market_data_map) if self._scanner else []
        ranked = self._ranker.rank(scan_results) if self._ranker else []

        for result in ranked:
            self._handle_signal(result)

    def _post_market(self) -> None:
        """
        Post-market routine (15:20–15:30).
        Close all open positions, save state, send daily summary.
        """
        logger.info("Post-market routine starting")
        open_positions = self._state.get_open_positions() if self._state else []
        if open_positions:
            logger.info("Closing %d open positions at EOD", len(open_positions))
            for position in open_positions:
                # TODO Phase 1: execute EOD close via ExecutionEngine
                if self._state:
                    self._state.close_position(position["id"])

        if self._monitor:
            self._monitor.send_daily_summary()
            self._monitor.stop_heartbeat()
        logger.info("Post-market complete")

    def _handle_signal(self, scan_result: ScanResult) -> None:
        """
        Execute a ranked signal through the execution engine.

        Args:
            scan_result: Top-ranked opportunity from OpportunityRanker.
        """
        signal = scan_result.signal
        logger.info(
            "Handling signal: %s %s %s (score=%.3f, regime=%s)",
            signal.direction.value, signal.symbol, signal.signal_type,
            scan_result.priority_score, scan_result.regime.value,
        )
        if self._dry_run:
            logger.info("[DRY RUN] Would execute: %s", signal)
            return
        # TODO Phase 1: execute via self._execution_engine.execute(signal)

    def _emergency_shutdown(self) -> None:
        """Kill switch — close all positions immediately and halt."""
        logger.critical("EMERGENCY SHUTDOWN triggered")
        if self._monitor:
            self._monitor.alert_on_anomaly("Emergency shutdown triggered — closing all positions.")
        open_positions = self._state.get_open_positions() if self._state else []
        for position in open_positions:
            logger.critical("Emergency closing position: %s", position.get("id"))
            # TODO Phase 1: emergency close via broker directly, not ExecutionEngine
        self._running = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_config(self) -> dict:
        """Load all YAML config files from the config directory."""
        config: dict = {}
        for yaml_file in self._config_path.glob("*.yaml"):
            key = yaml_file.stem
            with open(yaml_file) as f:
                config[key] = yaml.safe_load(f)
        return config

    def _load_strategies(self) -> list:
        """Instantiate all registered strategies."""
        strategies = []
        # TODO Phase 1: import and instantiate PivotCPRStrategy with Astra-compatible interface
        # from strategies.pivot_cpr_strategy import PivotCPRStrategy
        # strategies.append(PivotCPRStrategy())
        return strategies

    def _wait_until(self, target_time: dt_time) -> None:
        """Block until wall clock reaches target_time, logging progress."""
        now = datetime.now().time()
        if now >= target_time:
            return
        wait_secs = (
            (target_time.hour - now.hour) * 3600
            + (target_time.minute - now.minute) * 60
            + (target_time.second - now.second)
        )
        logger.info("Waiting %.0f seconds until %s", wait_secs, target_time.strftime("%H:%M"))
        time.sleep(max(0, wait_secs))

    def _sleep_to_next_bar(self) -> None:
        """Sleep until the next 5-minute boundary."""
        now = datetime.now()
        seconds_into_bar = (now.minute % 5) * 60 + now.second
        sleep_for = BAR_INTERVAL - seconds_into_bar
        time.sleep(max(1, sleep_for))

    def _handle_signal(self, signum, frame=None) -> None:  # type: ignore[override]
        """Handle OS kill signals gracefully."""
        logger.info("Received signal %s — shutting down", signum)
        self._running = False
        self._emergency_shutdown()
        sys.exit(0)
