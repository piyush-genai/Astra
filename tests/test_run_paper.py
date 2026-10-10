"""
Unit tests for the refactored PaperTradingEngine.

All external I/O (broker, strategy, SQLite) is mocked. Tests verify that
the engine correctly delegates to RiskManager, PositionManager, and StateManager
instead of reimplementing those concerns inline.
"""
from __future__ import annotations

from datetime import datetime, date
from unittest.mock import MagicMock, patch, PropertyMock

import pandas as pd
import pytest

from core.engine.base_strategy import Signal, SignalDirection
from core.engine.position_manager import ConcurrencyConfig, PositionManager
from core.engine.risk_manager import RiskConfig, RiskManager
from live.state_manager import StateManager


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

INSTRUMENTS_CFG = {
    "instruments": {
        "NIFTY": {
            "lot_size": 65,
            "weekly_expiry_weekday": 1,
            "strike_step": 50,
        }
    }
}

RISK_CFG = {
    "capital": {"starting_capital": 100_000},
    "per_trade": {
        "max_loss_per_trade_pct": 10.0,   # 10% of 100k = 10k > 101*65=6565
        "max_capital_deployed_pct": 50.0,
    },
    "circuit_breaker": {"daily_loss_limit_pct": 5.0},
    "position_limits": {"hard_cap_lots": 5},
}


def _make_engine(capital: float = 100_000.0):
    """Create a PaperTradingEngine with all dependencies mocked."""
    from scripts.run_paper import PaperTradingEngine

    strategy = MagicMock()
    adapter = MagicMock()
    pricer = MagicMock()
    pricer.strike_step = 50
    pricer.expiry_weekday = 1
    pricer.lot_size = 65

    state_manager = MagicMock(spec=StateManager)
    state_manager.get_capital.return_value = capital
    state_manager.get_daily_pnl.return_value = 0.0

    engine = PaperTradingEngine(
        strategy=strategy,
        adapter=adapter,
        pricer=pricer,
        instruments_cfg=INSTRUMENTS_CFG,
        risk_cfg=RISK_CFG,
        state_manager=state_manager,
        strategy_id="pivot_cpr",
    )
    return engine


def _make_signal(direction: SignalDirection = SignalDirection.LONG) -> Signal:
    """Build a minimal Signal with a PivotCPR-style setup in metadata."""
    zone = MagicMock()
    zone.price_low = 24300.0
    zone.price_high = 24350.0

    setup = MagicMock()
    setup.zone = zone
    setup.initial_stop = 24200.0

    return Signal(
        strategy_id="pivot_cpr",
        instrument="NIFTY",
        direction=direction,
        metadata={"setup": setup},
    )


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

class TestConstructor:
    def test_loads_capital_from_state_manager(self):
        engine = _make_engine(capital=75_000.0)
        assert engine.capital == 75_000.0

    def test_initialises_capital_on_first_run(self):
        from scripts.run_paper import PaperTradingEngine

        sm = MagicMock(spec=StateManager)
        sm.get_capital.return_value = 0.0  # first run

        engine = PaperTradingEngine(
            strategy=MagicMock(), adapter=MagicMock(), pricer=MagicMock(),
            instruments_cfg=INSTRUMENTS_CFG, risk_cfg=RISK_CFG,
            state_manager=sm,
        )

        # Should have called update_capital with the starting_capital from config.
        sm.update_capital.assert_called_once_with(100_000.0, "initial_deposit")

    def test_rm_and_pm_instantiated(self):
        engine = _make_engine()
        assert isinstance(engine._rm, RiskManager)
        assert isinstance(engine._pm, PositionManager)


# ---------------------------------------------------------------------------
# _enter — entry gates
# ---------------------------------------------------------------------------

class TestEnter:
    def _setup_quote(self, engine, ltp=100.0, bid=99.0, ask=101.0):
        engine.adapter.get_option_quote.return_value = {
            "instrument_key": "NSE_FO|12345",
            "ltp": ltp, "bid": bid, "ask": ask,
        }

    def test_entry_blocked_by_position_manager(self):
        engine = _make_engine()
        self._setup_quote(engine)

        # Pre-fill one position so concurrency limit is hit.
        signal = _make_signal()
        engine._pm.open_position(
            signal=signal, entry_time=datetime.now(),
            contract_symbol="DUMMY", lot_size=65,
            premium_paid=100.0, num_lots=1,
        )

        with patch("scripts.run_paper.atm_strike", return_value=24300.0), \
             patch("scripts.run_paper.next_expiry", return_value=date(2026, 10, 14)):
            engine._enter(_make_signal(), datetime.now(), 24300.0)

        # StateManager.open_position should NOT have been called (entry blocked).
        engine._sm.open_position.assert_not_called()

    def test_entry_blocked_by_circuit_breaker(self):
        engine = _make_engine()
        self._setup_quote(engine)
        engine._rm._circuit_breaker_tripped = True

        with patch("scripts.run_paper.atm_strike", return_value=24300.0), \
             patch("scripts.run_paper.next_expiry", return_value=date(2026, 10, 14)):
            engine._enter(_make_signal(), datetime.now(), 24300.0)

        engine._sm.open_position.assert_not_called()

    def test_successful_entry_records_in_state_manager(self):
        engine = _make_engine()
        self._setup_quote(engine)

        with patch("scripts.run_paper.atm_strike", return_value=24300.0), \
             patch("scripts.run_paper.next_expiry", return_value=date(2026, 10, 14)):
            engine._enter(_make_signal(), datetime.now(), 24300.0)

        engine._sm.open_position.assert_called_once()

    def test_successful_entry_tracks_active_position(self):
        engine = _make_engine()
        self._setup_quote(engine)

        with patch("scripts.run_paper.atm_strike", return_value=24300.0), \
             patch("scripts.run_paper.next_expiry", return_value=date(2026, 10, 14)):
            engine._enter(_make_signal(), datetime.now(), 24300.0)

        assert engine._active is not None
        assert engine._pm.open_positions()  # in-memory position registered

    def test_uses_ask_price_for_entry(self):
        engine = _make_engine()
        engine.adapter.get_option_quote.return_value = {
            "instrument_key": "NSE_FO|12345",
            "ltp": 100.0, "bid": 99.0, "ask": 105.0,
        }

        with patch("scripts.run_paper.atm_strike", return_value=24300.0), \
             patch("scripts.run_paper.next_expiry", return_value=date(2026, 10, 14)):
            engine._enter(_make_signal(), datetime.now(), 24300.0)

        # Ask=105 should be used as entry premium.
        assert engine._entry_details["premium"] == 105.0
        assert engine._entry_details["source"] == "REAL ASK"


# ---------------------------------------------------------------------------
# _exit — P&L, delegation, circuit breaker detection
# ---------------------------------------------------------------------------

class TestExit:
    def _enter_position(self, engine):
        """Helper: open a position so we can exit it."""
        engine.adapter.get_option_quote.return_value = {
            "instrument_key": "NSE_FO|12345",
            "ltp": 100.0, "bid": 99.0, "ask": 101.0,
        }
        with patch("scripts.run_paper.atm_strike", return_value=24300.0), \
             patch("scripts.run_paper.next_expiry", return_value=date(2026, 10, 14)):
            engine._enter(_make_signal(), datetime.now(), 24300.0)

    def test_exit_closes_position_manager_position(self):
        engine = _make_engine()
        self._enter_position(engine)
        assert engine._active is not None

        engine.adapter.get_option_quote.return_value = {
            "ltp": 110.0, "bid": 109.0, "ask": 111.0,
        }
        engine._exit(datetime.now(), 24300.0, "stop")

        assert engine._active is None
        assert len(engine._pm.open_positions()) == 0

    def test_exit_calls_state_manager_record_trade(self):
        engine = _make_engine()
        self._enter_position(engine)

        engine.adapter.get_option_quote.return_value = {
            "ltp": 110.0, "bid": 109.0, "ask": 111.0,
        }
        engine._exit(datetime.now(), 24300.0, "eod")

        engine._sm.record_trade.assert_called_once()
        trade_arg = engine._sm.record_trade.call_args[0][0]
        assert trade_arg["exit_reason"] == "eod"
        assert trade_arg["strategy_name"] == "pivot_cpr"

    def test_exit_updates_capital_in_state_manager(self):
        engine = _make_engine()
        self._enter_position(engine)

        engine.adapter.get_option_quote.return_value = {
            "ltp": 110.0, "bid": 109.0, "ask": 111.0,
        }
        engine._exit(datetime.now(), 24300.0, "stop")

        engine._sm.update_capital.assert_called()

    def test_exit_notifies_risk_manager_of_loss(self):
        engine = _make_engine()
        self._enter_position(engine)

        # Exit at a lower bid — guaranteed loss (entry ask=101, exit bid=80).
        engine.adapter.get_option_quote.return_value = {
            "ltp": 80.0, "bid": 80.0, "ask": 82.0,
        }
        pre_loss = engine._rm.session_realized_loss
        engine._exit(datetime.now(), 24250.0, "stop")

        assert engine._rm.session_realized_loss > pre_loss

    def test_circuit_breaker_trips_and_notifies(self):
        """A big loss should trip the circuit breaker and send an alert."""
        # Large capital so we can enter, but daily_loss_limit set so low
        # that even a small loss trips the breaker.
        engine = _make_engine(capital=100_000.0)
        # Force the daily limit very low so one losing trade trips it.
        engine._rm._config.daily_loss_limit = 1.0
        engine.adapter.get_option_quote.return_value = {
            "ltp": 100.0, "bid": 99.0, "ask": 101.0,
        }
        with patch("scripts.run_paper.atm_strike", return_value=24300.0), \
             patch("scripts.run_paper.next_expiry", return_value=date(2026, 10, 14)):
            engine._enter(_make_signal(), datetime.now(), 24300.0)

        # Exit at near-zero premium to create a large relative loss.
        engine.adapter.get_option_quote.return_value = {
            "ltp": 1.0, "bid": 1.0, "ask": 2.0,
        }

        with patch("scripts.run_paper.send_telegram_alert") as mock_alert, \
             patch.object(engine, "_update_status"):
            engine._exit(datetime.now(), 24000.0, "stop")

        # Circuit breaker should have tripped.
        assert engine._rm.circuit_breaker_tripped
        # At least one Telegram alert should mention the circuit breaker.
        mock_alert.assert_called()
        all_alerts = [call[0][0] for call in mock_alert.call_args_list]
        assert any("CIRCUIT BREAKER" in t for t in all_alerts)


# ---------------------------------------------------------------------------
# _in_cooldown
# ---------------------------------------------------------------------------

class TestCooldown:
    def test_no_cooldown_on_first_signal(self):
        engine = _make_engine()
        assert engine._in_cooldown(_make_signal()) is False

    def test_cooldown_blocks_same_zone(self):
        engine = _make_engine()
        signal = _make_signal()
        setup = signal.metadata["setup"]
        zone = setup.zone
        engine._last_exit_zone = (round(zone.price_low, 2), round(zone.price_high, 2))
        engine._last_exit_time = datetime.now()  # just exited
        assert engine._in_cooldown(signal) is True

    def test_no_cooldown_after_elapsed(self):
        from datetime import timedelta
        engine = _make_engine()
        signal = _make_signal()
        setup = signal.metadata["setup"]
        zone = setup.zone
        engine._last_exit_zone = (round(zone.price_low, 2), round(zone.price_high, 2))
        engine._last_exit_time = datetime.now() - timedelta(minutes=30)  # long ago
        assert engine._in_cooldown(signal) is False


# ---------------------------------------------------------------------------
# _calc_lots
# ---------------------------------------------------------------------------

class TestCalcLots:
    def test_returns_at_least_1(self):
        engine = _make_engine(capital=50_000.0)
        lots = engine._calc_lots(entry_premium=5.0)  # very cheap premium
        assert lots >= 1

    def test_respects_hard_cap(self):
        engine = _make_engine(capital=10_000_000.0)  # large capital
        lots = engine._calc_lots(entry_premium=1.0)  # very cheap
        assert lots <= RISK_CFG["position_limits"]["hard_cap_lots"]

    def test_zero_premium_returns_zero(self):
        engine = _make_engine()
        assert engine._calc_lots(entry_premium=0.0) == 0
