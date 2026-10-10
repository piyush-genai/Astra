"""
Opportunity Ranker — prioritises signals from the universe scan.

Scoring formula per signal:
  score = confidence × regime_match × liquidity × time_of_day

The ExecutionEngine takes the top-N signals from this ranked list.
"""
from __future__ import annotations

import logging
from datetime import datetime

from strategies.base import Regime
from universe.instruments import Instrument, InstrumentType
from universe.scanner import ScanResult

logger = logging.getLogger(__name__)

# Liquidity tiers: rough bid-ask spread proxy (lower = more liquid = better)
_LIQUIDITY_SCORES: dict[str, float] = {
    "NIFTY":     1.0,
    "BANKNIFTY": 0.95,
    "FINNIFTY":  0.85,
    "MIDCPNIFTY":0.75,
    "RELIANCE":  0.80,
    "TCS":       0.78,
    "HDFCBANK":  0.80,
    "INFY":      0.78,
    "ICICIBANK": 0.78,
}
_DEFAULT_LIQUIDITY_SCORE = 0.60


class OpportunityRanker:
    """
    Ranks ScanResults so the orchestrator executes the highest-quality signals first.

    Usage:
        ranker = OpportunityRanker(max_opportunities=3)
        ranked = ranker.rank(scan_results)
        top = ranked[:3]
    """

    def __init__(self, max_opportunities: int = 3, min_score: float = 0.3) -> None:
        self._max = max_opportunities
        self._min_score = min_score

    def rank(self, scan_results: list[ScanResult]) -> list[ScanResult]:
        """
        Score and sort signals, best first.

        Signals scoring below min_score are dropped entirely.
        Returns at most max_opportunities results.
        """
        scored: list[ScanResult] = []
        for result in scan_results:
            score = self._compute_score(result)
            if score >= self._min_score:
                result.priority_score = score
                scored.append(result)
        scored.sort(key=lambda r: r.priority_score, reverse=True)
        return scored[: self._max]

    # ------------------------------------------------------------------
    # Scoring components (each returns 0.0–1.0)
    # ------------------------------------------------------------------

    def _compute_score(self, result: ScanResult) -> float:
        """Composite score: all components multiplied together."""
        confidence = result.signal.confidence
        regime_match = self._regime_match_score(result)
        liquidity = self._liquidity_score(result.instrument)
        time_score = self._time_of_day_score(result.signal.timestamp or datetime.now())
        score = confidence * regime_match * liquidity * time_score
        logger.debug(
            "Score %s: conf=%.2f regime=%.2f liq=%.2f time=%.2f → %.3f",
            result.instrument.symbol, confidence, regime_match, liquidity, time_score, score,
        )
        return score

    def _regime_match_score(self, result: ScanResult) -> float:
        """
        How well does the current regime match the strategy's preferred regimes?
        1.0 = regime is in strategy's preferred list.
        0.6 = regime is UNKNOWN (can't assess, don't fully penalise).
        0.3 = regime is actively bad for this strategy (not preferred).
        """
        preferred = result.strategy_used.metadata.preferred_regimes
        if result.regime == Regime.UNKNOWN:
            return 0.6
        if result.regime in preferred:
            return 1.0
        return 0.3

    def _liquidity_score(self, instrument: Instrument) -> float:
        """Score based on instrument's historical bid-ask spread / market depth."""
        return _LIQUIDITY_SCORES.get(instrument.symbol, _DEFAULT_LIQUIDITY_SCORE)

    def _time_of_day_score(self, timestamp: datetime) -> float:
        """
        Penalise signals in the first 15 min (9:15–9:30) and last 15 min (15:15–15:30).
        These windows have wide spreads, low depth, and erratic price action.
        """
        minutes = timestamp.hour * 60 + timestamp.minute
        market_open = 9 * 60 + 15
        market_close = 15 * 60 + 30

        minutes_since_open = minutes - market_open
        minutes_to_close = market_close - minutes

        if minutes_since_open < 0 or minutes_to_close < 0:
            return 0.0   # outside market hours
        if minutes_since_open < 15 or minutes_to_close < 15:
            return 0.2   # opening/closing auction noise
        if minutes_since_open < 30 or minutes_to_close < 30:
            return 0.7   # early/late session — reduced quality
        return 1.0       # core session
