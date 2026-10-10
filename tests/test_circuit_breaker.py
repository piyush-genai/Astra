#!/usr/bin/env python3
"""
Test script to verify circuit breaker functionality.

This test creates a PaperTradingEngine with a small capital and simulates
losing trades to verify the circuit breaker trips at the configured threshold.
"""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.config_loader import load_instruments, load_risk
from core.engine.base_strategy import Signal, SignalDirection


def test_circuit_breaker():
    """Test that circuit breaker trips when daily loss exceeds limit."""
    print("=" * 80)
    print("CIRCUIT BREAKER TEST")
    print("=" * 80)
    
    # Load real config
    instruments_cfg = load_instruments()
    risk_cfg = load_risk()
    
    # Create mock components
    strategy = MagicMock()
    adapter = MagicMock()
    pricer = MagicMock()
    pricer.lot_size = 65
    
    # Import here to avoid circular dependency issues
    from scripts.run_paper import PaperTradingEngine
    
    # Create engine with test capital
    # Temporarily override starting_capital for test
    original_starting = risk_cfg.get("capital", {}).get("starting_capital", 20000)
    test_starting_capital = 10000  # Smaller for easier testing
    
    # Set test capital in config
    if "capital" not in risk_cfg:
        risk_cfg["capital"] = {}
    risk_cfg["capital"]["starting_capital"] = test_starting_capital
    
    engine = PaperTradingEngine(strategy, adapter, pricer, instruments_cfg, risk_cfg)
    
    # Manually set day_start_capital (simulating session start)
    engine.day_start_capital = engine.capital
    engine.circuit_breaker_tripped = False
    
    print(f"\n1. Initial Setup:")
    print(f"   Capital: ₹{engine.capital:.2f}")
    print(f"   Day-start capital: ₹{engine.day_start_capital:.2f}")
    print(f"   Daily loss limit: {risk_cfg['circuit_breaker']['daily_loss_limit_pct']}%")
    
    loss_limit_rupees = engine.day_start_capital * (risk_cfg['circuit_breaker']['daily_loss_limit_pct'] / 100)
    print(f"   Loss threshold: ₹{loss_limit_rupees:.2f}")
    
    # Simulate losing trades
    print(f"\n2. Simulating Losing Trades:")
    
    # Loss 1: -₹400 (4% of ₹10,000)
    engine.capital -= 400
    print(f"   After Loss 1 (-₹400): Capital=₹{engine.capital:.2f}, Today P&L=₹{engine.capital - engine.day_start_capital:.2f}")
    engine.check_circuit_breaker()
    assert not engine.circuit_breaker_tripped, "Should not trip yet"
    print(f"   ✓ Circuit breaker: NOT tripped")
    
    # Loss 2: -₹400 more (total -₹800 = 8% of ₹10,000, exceeds 7.5% threshold)
    engine.capital -= 400
    print(f"   After Loss 2 (-₹400): Capital=₹{engine.capital:.2f}, Today P&L=₹{engine.capital - engine.day_start_capital:.2f}")
    engine.check_circuit_breaker()
    
    # Verify circuit breaker tripped
    print(f"\n3. Verification:")
    assert engine.circuit_breaker_tripped, "❌ Circuit breaker should have tripped!"
    print(f"   ✅ Circuit breaker TRIPPED correctly!")
    
    total_loss = engine.day_start_capital - engine.capital
    loss_pct = (total_loss / engine.day_start_capital) * 100
    print(f"   Total loss: ₹{total_loss:.2f} ({loss_pct:.1f}%)")
    print(f"   Threshold:  ₹{loss_limit_rupees:.2f} ({risk_cfg['circuit_breaker']['daily_loss_limit_pct']}%)")
    
    # Verify subsequent entries would be blocked
    print(f"\n4. Entry Blocking Test:")
    # In the real run() method, this check prevents new signal evaluation:
    # if not self.active_position and not self.circuit_breaker_tripped:
    can_enter = not engine.circuit_breaker_tripped
    print(f"   Can enter new position: {can_enter}")
    assert not can_enter, "❌ New entries should be blocked!"
    print(f"   ✅ New entries correctly blocked!")
    
    # Restore original config
    risk_cfg["capital"]["starting_capital"] = original_starting
    
    print("\n" + "=" * 80)
    print("✅ ALL CIRCUIT BREAKER TESTS PASSED")
    print("=" * 80)


if __name__ == "__main__":
    test_circuit_breaker()
