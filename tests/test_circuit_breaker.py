"""
Circuit breaker integration test for PaperTradingEngine.

Verifies that the engine correctly delegates circuit-breaker state to
RiskManager and blocks new entries after the daily loss limit is hit.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from live.state_manager import StateManager
from scripts.run_paper import PaperTradingEngine


INSTRUMENTS_CFG = {
    "instruments": {
        "NIFTY": {"lot_size": 65, "weekly_expiry_weekday": 1, "strike_step": 50}
    }
}

RISK_CFG = {
    "capital": {"starting_capital": 10_000},
    "per_trade": {
        "max_loss_per_trade_pct": 10.0,
        "max_capital_deployed_pct": 50.0,
    },
    "circuit_breaker": {"daily_loss_limit_pct": 7.5},
    "position_limits": {"hard_cap_lots": 5},
}


def _make_engine():
    sm = MagicMock(spec=StateManager)
    sm.get_capital.return_value = 10_000.0
    sm.get_daily_pnl.return_value = 0.0
    pricer = MagicMock()
    pricer.strike_step = 50
    pricer.expiry_weekday = 1
    pricer.lot_size = 65
    return PaperTradingEngine(
        strategy=MagicMock(), adapter=MagicMock(), pricer=pricer,
        instruments_cfg=INSTRUMENTS_CFG, risk_cfg=RISK_CFG,
        state_manager=sm,
    )


def test_circuit_breaker():
    """Circuit breaker should trip and block new entries after daily loss limit."""
    engine = _make_engine()
    rm = engine._rm

    # Daily limit: 7.5% of 10k = ₹750.
    limit = rm._config.daily_loss_limit
    assert limit == 750.0

    # Loss 1: ₹400 (well under the ₹750 threshold).
    rm.record_realized_loss(-400.0)
    assert not rm.circuit_breaker_tripped, "Should not trip at ₹400 loss"

    # Loss 2: another ₹400, total ₹800 → exceeds ₹750 threshold.
    rm.record_realized_loss(-400.0)
    assert rm.circuit_breaker_tripped, "Circuit breaker should have tripped at ₹800 total loss"

    # Verify pre-trade check is blocked.
    allowed, reason = rm.check_pre_trade(max_loss_for_trade=100.0, current_unrealized_loss=0.0)
    assert not allowed
    assert "circuit breaker" in reason.lower()
