"""
Unit tests for PositionManager — tasks 4a and 4b of trading-engine-core spec.

4a. Two signals on the same instrument, max_concurrent = 1 → second rejected.
4b. Same config with limit = 2 → second accepted, tracked as distinct position.
"""

import pytest
from datetime import datetime, timezone

from core.engine.base_strategy import Signal, SignalDirection
from core.engine.position_manager import ConcurrencyConfig, PositionManager


def _nifty_signal(strategy_id: str = "strat_a") -> Signal:
    return Signal(
        strategy_id=strategy_id,
        instrument="NIFTY",
        direction=SignalDirection.LONG,
    )


def _make_pm(max_concurrent: int, allocated_capital: float = 1_000_000) -> PositionManager:
    cfg = ConcurrencyConfig(
        max_concurrent_positions_per_instrument=max_concurrent,
        max_total_capital_deployed_pct=100.0,
        allocated_capital=allocated_capital,
    )
    return PositionManager(cfg)


def _open_one(pm: PositionManager, signal: Signal) -> None:
    """Helper: open a position and confirm it succeeded."""
    allowed, reason = pm.can_open(signal, estimated_capital=5_000)
    assert allowed, f"Expected allowed but got: {reason}"
    pm.open_position(
        signal=signal,
        entry_time=datetime.now(timezone.utc),
        contract_symbol="NIFTY24AUG25000CE",
        lot_size=75,
        premium_paid=66.67,
        num_lots=1,
    )


# ── Task 4a ────────────────────────────────────────────────────────────────

class TestConcurrencyLimitOne:
    def test_first_signal_allowed(self):
        pm = _make_pm(max_concurrent=1)
        signal = _nifty_signal()
        allowed, reason = pm.can_open(signal, estimated_capital=5_000)
        assert allowed
        assert reason == ""

    def test_second_signal_rejected_when_limit_is_one(self):
        pm = _make_pm(max_concurrent=1)
        sig1 = _nifty_signal("strat_a")
        sig2 = _nifty_signal("strat_b")

        _open_one(pm, sig1)

        allowed, reason = pm.can_open(sig2, estimated_capital=5_000)
        assert not allowed
        assert "max_concurrent_positions_per_instrument" in reason
        assert "1" in reason

    def test_different_instrument_not_blocked(self):
        pm = _make_pm(max_concurrent=1)
        nifty_sig = _nifty_signal()
        bnf_sig = Signal(
            strategy_id="strat_a",
            instrument="BANKNIFTY",
            direction=SignalDirection.SHORT,
        )

        _open_one(pm, nifty_sig)

        allowed, _ = pm.can_open(bnf_sig, estimated_capital=5_000)
        assert allowed, "Different instrument should not be blocked by NIFTY's concurrency limit"


# ── Task 4b ────────────────────────────────────────────────────────────────

class TestConcurrencyLimitTwo:
    def test_second_signal_accepted_when_limit_is_two(self):
        pm = _make_pm(max_concurrent=2)
        sig1 = _nifty_signal("strat_a")
        sig2 = _nifty_signal("strat_b")

        _open_one(pm, sig1)

        allowed, reason = pm.can_open(sig2, estimated_capital=5_000)
        assert allowed, f"Expected second signal allowed, got: {reason}"

    def test_second_position_tracked_as_distinct(self):
        pm = _make_pm(max_concurrent=2)
        sig1 = _nifty_signal("strat_a")
        sig2 = _nifty_signal("strat_b")

        _open_one(pm, sig1)
        _open_one(pm, sig2)

        assert len(pm) == 2
        ids = {p.strategy_id for p in pm.open_positions()}
        assert ids == {"strat_a", "strat_b"}

    def test_third_signal_rejected_when_limit_is_two(self):
        pm = _make_pm(max_concurrent=2)
        for sid in ("strat_a", "strat_b"):
            _open_one(pm, _nifty_signal(sid))

        allowed, reason = pm.can_open(_nifty_signal("strat_c"), estimated_capital=5_000)
        assert not allowed
        assert "2" in reason


# ── Capital limit ──────────────────────────────────────────────────────────

class TestCapitalLimit:
    def test_second_position_rejected_by_capital_limit(self):
        # allocated_capital=10_000, max_deployed=50% → limit=5_000
        pm = _make_pm(max_concurrent=5, allocated_capital=10_000)
        cfg = pm._config
        cfg.max_total_capital_deployed_pct = 50.0

        sig1 = _nifty_signal("strat_a")
        sig2 = _nifty_signal("strat_b")

        _open_one_with_capital(pm, sig1, capital=4_900)

        # Would bring total to 4_900 + 200 = 5_100 > 5_000
        allowed, reason = pm.can_open(sig2, estimated_capital=200)
        assert not allowed
        assert "capital" in reason.lower()


def _open_one_with_capital(pm: PositionManager, signal: Signal, capital: float) -> None:
    allowed, reason = pm.can_open(signal, estimated_capital=capital)
    assert allowed, reason
    # premium_paid * num_lots * lot_size = capital  → e.g. lot_size=75, num_lots=1
    lot_size = 75
    premium = capital / lot_size
    pm.open_position(
        signal=signal,
        entry_time=datetime.now(timezone.utc),
        contract_symbol="NIFTY24AUG25000CE",
        lot_size=lot_size,
        premium_paid=premium,
        num_lots=1,
    )
