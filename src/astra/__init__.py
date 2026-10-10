"""
ASTRA — Adaptive Strategy, Trading, Risk & Analytics

Platform layers:
  Data Plane          → ingestion, validation, normalization, storage
  Alpha Intelligence  → features, regime detection, ML discovery
  Signal Intelligence → direction, probability, trade setup
  Decision Plane      → trade/skip, strategy selection
  Risk Plane          → limits, circuit breakers (DETERMINISTIC)
  Execution Plane     → orders, broker adapter, paper/shadow/live
  Observability       → metrics, audit, feedback loop
"""

__version__ = "0.1.0-phase0"
__platform__ = "ASTRA"
