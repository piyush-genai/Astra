"""
Unit tests for RiskManager — tasks 5a, 5b, 5c of trading-engine-core spec.

5a. Order with max loss above per-trade limit is rejected.
5b. Simulated daily loss crossing the circuit-breaker threshold halts subsequent orders.
5c. Kill switch halts new orders regardless of circuit-breaker state.
"""

import pytest

from src.engine.risk_manager import RiskConfig, RiskManager


def _make_rm(
    max_loss_per_trade: float = 5_000,
    daily_loss_limit: float = 15_000,
    kill_switch: bool = False,
) -> RiskManager:
    cfg = RiskConfig(
        max_loss_per_trade=max_loss_per_trade,
        daily_loss_limit=daily_loss_limit,
        kill_switch_active=kill_switch,
    )
    return RiskManager(cfg)


# ── Task 5a: per-trade max loss ────────────────────────────────────────────

class TestPerTradeLoss:
    def test_order_within_limit_allowed(self):
        rm = _make_rm(max_loss_per_trade=5_000)
        allowed, reason = rm.check_pre_trade(max_loss_for_trade=4_999, current_unrealized_loss=0)
        assert allowed
        assert reason == ""

    def test_order_at_exact_limit_allowed(self):
        rm = _make_rm(max_loss_per_trade=5_000)
        allowed, _ = rm.check_pre_trade(max_loss_for_trade=5_000, current_unrealized_loss=0)
        assert allowed

    def test_order_above_limit_rejected(self):
        rm = _make_rm(max_loss_per_trade=5_000)
        allowed, reason = rm.check_pre_trade(max_loss_for_trade=5_001, current_unrealized_loss=0)
        assert not allowed
        assert "per-trade limit" in reason or "5,000" in reason or "5001" in reason or "5,001" in reason


# ── Task 5b: circuit breaker ────────────────────────────────────────────────

class TestCircuitBreaker:
    def test_orders_allowed_below_daily_limit(self):
        rm = _make_rm(daily_loss_limit=15_000)
        rm.record_realized_loss(-10_000)  # 10k loss, below 15k limit
        allowed, _ = rm.check_pre_trade(max_loss_for_trade=1_000, current_unrealized_loss=0)
        assert allowed

    def test_circuit_breaker_trips_on_realized_loss(self):
        rm = _make_rm(daily_loss_limit=15_000)
        rm.record_realized_loss(-15_000)  # exactly at limit
        assert rm.circuit_breaker_tripped

    def test_subsequent_orders_halted_after_trip(self):
        rm = _make_rm(daily_loss_limit=15_000)
        rm.record_realized_loss(-15_000)

        allowed, reason = rm.check_pre_trade(max_loss_for_trade=100, current_unrealized_loss=0)
        assert not allowed
        assert "circuit breaker" in reason.lower()

    def test_circuit_breaker_trips_via_unrealized(self):
        rm = _make_rm(daily_loss_limit=15_000)
        rm.record_realized_loss(-10_000)   # 10k realized

        # Another 6k unrealized would push total to 16k → should trip
        allowed, reason = rm.check_pre_trade(
            max_loss_for_trade=500,
            current_unrealized_loss=-6_000,   # negative = loss
        )
        assert not allowed
        assert rm.circuit_breaker_tripped

    def test_session_reset_clears_circuit_breaker(self):
        rm = _make_rm(daily_loss_limit=15_000)
        rm.record_realized_loss(-15_000)
        assert rm.circuit_breaker_tripped

        rm.reset_session()
        assert not rm.circuit_breaker_tripped
        assert rm.session_realized_loss == 0.0

        allowed, _ = rm.check_pre_trade(max_loss_for_trade=1_000, current_unrealized_loss=0)
        assert allowed


# ── Task 5c: kill switch ────────────────────────────────────────────────────

class TestKillSwitch:
    def test_kill_switch_halts_when_active(self):
        rm = _make_rm(kill_switch=True)
        allowed, reason = rm.check_pre_trade(max_loss_for_trade=100, current_unrealized_loss=0)
        assert not allowed
        assert "kill switch" in reason.lower()

    def test_kill_switch_overrides_circuit_breaker_state(self):
        """Kill switch halts orders regardless of whether circuit breaker has tripped."""
        rm = _make_rm(kill_switch=True, daily_loss_limit=15_000)
        # Circuit breaker NOT tripped, but kill switch is on.
        assert not rm.circuit_breaker_tripped

        allowed, reason = rm.check_pre_trade(max_loss_for_trade=100, current_unrealized_loss=0)
        assert not allowed
        assert "kill switch" in reason.lower()

    def test_deactivating_kill_switch_allows_orders(self):
        rm = _make_rm(kill_switch=True)
        rm.deactivate_kill_switch()
        allowed, _ = rm.check_pre_trade(max_loss_for_trade=1_000, current_unrealized_loss=0)
        assert allowed

    def test_activating_kill_switch_halts_orders(self):
        rm = _make_rm(kill_switch=False)
        rm.activate_kill_switch()
        allowed, reason = rm.check_pre_trade(max_loss_for_trade=100, current_unrealized_loss=0)
        assert not allowed
        assert "kill switch" in reason.lower()
