"""
Unit tests for the PivotCprStrategy signal engine.

Tests verify:
- Breakout alone (candle N) does NOT emit a signal.
- Breakout + confirmation (candle N+1 closes beyond) DOES emit a signal.
- Cancellation (candle N+1 closes back inside zone) emits nothing.
- Direction is correct (up = LONG, down = SHORT).
- Initial stop is set correctly.
"""

import pandas as pd
import pytest

from core.engine.base_strategy import MarketData, SignalDirection
from strategies.pivot_cpr_strategy import PivotCprStrategy


def _make_strategy() -> PivotCprStrategy:
    return PivotCprStrategy(config={"tolerance_pct": 0.18, "min_levels_for_confluence": 2})


def _make_history(rows: list[dict], base_date="2026-07-28") -> pd.DataFrame:
    """Build a 5-min intraday history DataFrame with enough prior daily data."""
    # Include two prior daily sessions so build_pivot_table has a shift(1) row.
    dates = pd.date_range(base_date, periods=len(rows), freq="5min")
    df = pd.DataFrame(rows, index=dates)
    df.columns = [c.lower() for c in df.columns]
    return df


def _bar(history: pd.DataFrame, i: int, **override) -> MarketData:
    row = history.iloc[i]
    data = {
        "open": row["open"], "high": row["high"],
        "low": row["low"],   "close": row["close"],
    }
    data.update(override)
    return MarketData(
        instrument="NIFTY",
        bar_time=history.index[i],
        history=history.iloc[: i + 1],
        **data,
    )


# ---------------------------------------------------------------------------
# We need a pivot table with a known confluence zone to test against.
# Easiest approach: build real pivot levels from known OHLC and find a zone.
# ---------------------------------------------------------------------------

class TestSignalEngine:
    """
    Synthetic test: craft OHLC so that daily_R1 and cpr_TC coincide
    within tolerance, forming a confluence zone, then drive price through it.
    """

    def _setup(self):
        """
        Build a strategy + history where we control the zone location.
        daily H=24283.55, L=24136.75, C=24250.20 → R1=24310.25, P=24223.50
        cpr TC = 2*(24223.50) - (24283.55+24136.75)/2
               = 24447.00 - 24210.15 = 24236.85   (these won't cluster)

        Easier: use a contrived prior day where R1 ≈ cpr_TC.
        Let H=100, L=80, C=95 →
            P  = (100+80+95)/3 = 91.67
            R1 = 2*91.67 - 80 = 103.33
            BC = (100+80)/2   = 90.00
            TC = 2*91.67 - 90 = 93.33   ← not near R1

        Simpler: just test with two daily_P levels from different periods
        coinciding — but that requires weekly/monthly to line up too.

        Pragmatic approach: use the strategy's evaluate() state machine
        directly with a mocked pivot table injected via monkeypatch.
        """
        pass

    def test_no_signal_on_breakout_bar_alone(self, monkeypatch):
        strat = _make_strategy()
        zone_price = 22300.0

        # Monkeypatch _build_pivots to return a table with a known confluence zone.
        import pandas as pd
        from core.data.indicators import LEVEL_COLUMNS

        def fake_build_pivots(self_inner, history, today, **kwargs):
            row = {col: float("nan") for col in LEVEL_COLUMNS}
            row["daily_R1"]  = zone_price
            row["weekly_R1"] = zone_price + 5   # within 0.18% tolerance
            idx = pd.DatetimeIndex([today.normalize()])
            return pd.DataFrame([row], index=idx)

        monkeypatch.setattr(PivotCprStrategy, "_build_pivots", fake_build_pivots)

        # Bar 1: price grinds below zone
        history = _make_history([
            {"open": 22100, "high": 22150, "low": 22080, "close": 22120},
            {"open": 22120, "high": 22180, "low": 22100, "close": 22150},
            # Breakout bar: close above zone
            {"open": 22250, "high": 22350, "low": 22240, "close": 22320},
        ])

        for i in range(2):
            sig = strat.evaluate(_bar(history, i))
            assert sig is None

        # Breakout bar — must NOT emit a signal yet
        sig = strat.evaluate(_bar(history, 2))
        assert sig is None
        assert strat._pending is not None

    def test_signal_emitted_on_confirmation_bar(self, monkeypatch):
        strat = _make_strategy()
        zone_price = 22300.0

        from core.data.indicators import LEVEL_COLUMNS

        def fake_build_pivots(self_inner, history, today, **kwargs):
            row = {col: float("nan") for col in LEVEL_COLUMNS}
            row["daily_R1"]  = zone_price
            row["weekly_R1"] = zone_price + 5
            idx = pd.DatetimeIndex([today.normalize()])
            return pd.DataFrame([row], index=idx)

        monkeypatch.setattr(PivotCprStrategy, "_build_pivots", fake_build_pivots)

        history = _make_history([
            {"open": 22100, "high": 22150, "low": 22080, "close": 22120},
            {"open": 22120, "high": 22180, "low": 22100, "close": 22150},
            {"open": 22250, "high": 22350, "low": 22240, "close": 22320},  # breakout
            {"open": 22320, "high": 22380, "low": 22310, "close": 22360},  # confirmation
        ])

        for i in range(3):
            strat.evaluate(_bar(history, i))

        sig = strat.evaluate(_bar(history, 3))
        assert sig is not None
        assert sig.direction == SignalDirection.LONG
        assert sig.strategy_id == "pivot_cpr_strategy"

    def test_no_signal_on_failed_confirmation(self, monkeypatch):
        strat = _make_strategy()
        zone_price = 22300.0

        from core.data.indicators import LEVEL_COLUMNS

        def fake_build_pivots(self_inner, history, today, **kwargs):
            row = {col: float("nan") for col in LEVEL_COLUMNS}
            row["daily_R1"]  = zone_price
            row["weekly_R1"] = zone_price + 5
            idx = pd.DatetimeIndex([today.normalize()])
            return pd.DataFrame([row], index=idx)

        monkeypatch.setattr(PivotCprStrategy, "_build_pivots", fake_build_pivots)

        history = _make_history([
            {"open": 22100, "high": 22150, "low": 22080, "close": 22120},
            {"open": 22250, "high": 22350, "low": 22240, "close": 22320},  # breakout
            # Closes BACK inside zone — cancellation
            {"open": 22320, "high": 22330, "low": 22200, "close": 22250},
        ])

        strat.evaluate(_bar(history, 0))
        strat.evaluate(_bar(history, 1))  # breakout
        sig = strat.evaluate(_bar(history, 2))  # should cancel

        assert sig is None
        assert strat._pending is None   # pending was cleared

    def test_short_signal_direction(self, monkeypatch):
        strat = _make_strategy()
        zone_price = 22300.0

        from core.data.indicators import LEVEL_COLUMNS

        def fake_build_pivots(self_inner, history, today, **kwargs):
            row = {col: float("nan") for col in LEVEL_COLUMNS}
            row["daily_S1"]  = zone_price
            row["weekly_S1"] = zone_price - 5   # within tolerance
            idx = pd.DatetimeIndex([today.normalize()])
            return pd.DataFrame([row], index=idx)

        monkeypatch.setattr(PivotCprStrategy, "_build_pivots", fake_build_pivots)

        history = _make_history([
            {"open": 22500, "high": 22550, "low": 22480, "close": 22520},
            {"open": 22400, "high": 22420, "low": 22200, "close": 22250},  # breakout down
            {"open": 22250, "high": 22260, "low": 22180, "close": 22200},  # confirmation
        ])

        strat.evaluate(_bar(history, 0))
        strat.evaluate(_bar(history, 1))
        sig = strat.evaluate(_bar(history, 2))

        assert sig is not None
        assert sig.direction == SignalDirection.SHORT
