"""
Unit tests for pivot and CPR indicator formulas.

Sample values are hand-computed. If these tests fail, the formula
implementation is wrong — do NOT adjust expected values to match a
broken implementation.

Hand-computed from sample: H=22500, L=22000, C=22300
    P  = (22500+22000+22300)/3 = 22266.6667
    R1 = 2*P - L              = 22533.3333
    S1 = 2*P - H              = 22033.3333
    R2 = P + (H-L)            = 22766.6667
    S2 = P - (H-L)            = 21766.6667
    CPR BC = (H+L)/2          = 22250.0000
    CPR TC = 2*P - BC         = 22283.3333

Pivot formula cross-check from real data (29 Jul 2026 → 30 Jul levels):
    H=24283.55  L=24136.75  C=24250.20
    P  = (24283.55+24136.75+24250.20)/3 = 24223.50
    R1 = 2*24223.50 - 24136.75         = 24310.25
    S1 = 2*24223.50 - 24283.55         = 24163.45
    R2 = 24223.50 + (24283.55-24136.75)= 24370.30
    S2 = 24223.50 - (24283.55-24136.75)= 24076.70
"""

import pytest
import pandas as pd

from core.data.indicators import (
    Zone,
    build_pivot_table,
    classic_pivot,
    cpr,
    find_zones,
    zone_above,
    zone_below,
)

PRECISION = 2   # decimal places


# ---------------------------------------------------------------------------
# classic_pivot formula
# ---------------------------------------------------------------------------

class TestClassicPivot:
    def setup_method(self):
        self.result = classic_pivot(22500, 22000, 22300)

    def test_P(self):
        assert round(self.result["P"], PRECISION) == round((22500+22000+22300)/3, PRECISION)

    def test_R1(self):
        assert round(self.result["R1"], PRECISION) == round(2*self.result["P"] - 22000, PRECISION)

    def test_S1(self):
        assert round(self.result["S1"], PRECISION) == round(2*self.result["P"] - 22500, PRECISION)

    def test_R2(self):
        assert round(self.result["R2"], PRECISION) == round(self.result["P"] + (22500-22000), PRECISION)

    def test_S2(self):
        assert round(self.result["S2"], PRECISION) == round(self.result["P"] - (22500-22000), PRECISION)

    def test_known_values(self):
        assert round(self.result["P"],  4) == 22266.6667
        assert round(self.result["R1"], 4) == 22533.3333
        assert round(self.result["S1"], 4) == 22033.3333
        assert round(self.result["R2"], 4) == 22766.6667
        assert round(self.result["S2"], 4) == 21766.6667

    def test_real_data_cross_check(self):
        """Verify against screenshot data: 29 Jul 2026 OHLC → 30 Jul levels."""
        r = classic_pivot(24283.55, 24136.75, 24250.20)
        assert round(r["P"],  2) == 24223.50
        assert round(r["R1"], 2) == 24310.25
        assert round(r["S1"], 2) == 24163.45
        assert round(r["R2"], 2) == 24370.30
        assert round(r["S2"], 2) == 24076.70


# ---------------------------------------------------------------------------
# cpr formula
# ---------------------------------------------------------------------------

class TestCPR:
    def setup_method(self):
        self.result = cpr(22500, 22000, 22300)

    def test_P_equals_pivot_P(self):
        p = classic_pivot(22500, 22000, 22300)
        assert round(self.result["P"], PRECISION) == round(p["P"], PRECISION)

    def test_BC(self):
        assert round(self.result["BC"], 4) == 22250.0000

    def test_TC(self):
        assert round(self.result["TC"], 4) == 22283.3333

    def test_TC_gte_BC(self):
        assert self.result["TC"] >= self.result["BC"]

    def test_width(self):
        assert round(self.result["width"], 4) == round(abs(self.result["TC"] - self.result["BC"]), 4)

    def test_doji_TC_gte_BC(self):
        result = cpr(22300, 22000, 22300)
        assert result["TC"] >= result["BC"]


# ---------------------------------------------------------------------------
# build_pivot_table — no look-ahead
# ---------------------------------------------------------------------------

class TestBuildPivotTable:
    def _sample_daily(self):
        return pd.DataFrame({
            "open":  [24250.0,  24296.50],
            "high":  [24283.55, 24317.15],
            "low":   [24136.75, 24296.50],
            "close": [24250.20, 24317.15],
        }, index=pd.to_datetime(["2026-07-29", "2026-07-30"]))

    def test_daily_levels_on_day2_use_day1_ohlc(self):
        pt = build_pivot_table(self._sample_daily())
        row = pt.loc["2026-07-30"]
        # 30 Jul daily levels must be computed from 29 Jul H/L/C
        assert round(row["daily_P"],  2) == 24223.50
        assert round(row["daily_R1"], 2) == 24310.25
        assert round(row["daily_S1"], 2) == 24163.45

    def test_first_row_daily_levels_are_nan(self):
        pt = build_pivot_table(self._sample_daily())
        assert pd.isna(pt.loc["2026-07-29"]["daily_P"])

    def test_cpr_columns_present(self):
        pt = build_pivot_table(self._sample_daily())
        for col in ["cpr_P", "cpr_BC", "cpr_TC", "cpr_width"]:
            assert col in pt.columns

    def test_weekly_column_present(self):
        pt = build_pivot_table(self._sample_daily())
        assert "weekly_P" in pt.columns

    def test_monthly_column_present(self):
        pt = build_pivot_table(self._sample_daily())
        assert "monthly_P" in pt.columns


# ---------------------------------------------------------------------------
# find_zones
# ---------------------------------------------------------------------------

class TestFindZones:
    def _make_series(self, levels: dict) -> pd.Series:
        from core.data.indicators import LEVEL_COLUMNS
        data = {col: float("nan") for col in LEVEL_COLUMNS}
        data.update(levels)
        return pd.Series(data)

    def test_single_level_forms_one_zone(self):
        s = self._make_series({"daily_P": 22000.0})
        zones = find_zones(s, tolerance_pct=0.18)
        assert len(zones) == 1
        assert not zones[0].is_confluence

    def test_two_close_levels_form_confluence(self):
        # daily_R1 (daily timeframe) and weekly_R1 (weekly timeframe) are independent sources.
        # Two different timeframes within tolerance → confluence.
        s = self._make_series({"daily_R1": 22250.0, "weekly_R1": 22270.0})
        zones = find_zones(s, tolerance_pct=0.18)
        assert len(zones) == 1
        assert zones[0].is_confluence

    def test_daily_and_cpr_same_timeframe_not_confluence(self):
        # daily_P and cpr_BC both derive from the same prior-day OHLC — one independent
        # source, not two. Clustering them does NOT produce confluence.
        s = self._make_series({"daily_P": 22250.0, "cpr_BC": 22270.0})
        zones = find_zones(s, tolerance_pct=0.18)
        assert len(zones) == 1
        assert not zones[0].is_confluence
        assert zones[0].is_daily_cpr_only

    def test_two_far_levels_in_separate_zones(self):
        s = self._make_series({"daily_P": 22000.0, "daily_R1": 22500.0})
        zones = find_zones(s, tolerance_pct=0.18)
        assert len(zones) == 2

    def test_zones_sorted_low_to_high(self):
        s = self._make_series({"daily_R1": 22500.0, "daily_S1": 21500.0})
        zones = find_zones(s, tolerance_pct=0.18)
        assert zones[0].center < zones[1].center

    def test_anchor_prevents_tolerance_chaining(self):
        # Three levels each just within tolerance of the previous one,
        # but level 3 is outside tolerance of the anchor (level 1).
        # Should form 2 zones, not 1.
        ref = 22000.0
        delta = ref * (0.18 / 100)   # exactly at tolerance
        s = self._make_series({
            "daily_P":  ref,
            "cpr_BC":   ref + delta,          # within tolerance of anchor
            "cpr_TC":   ref + delta * 2.1,    # within tolerance of cpr_BC but NOT anchor
        })
        zones = find_zones(s, tolerance_pct=0.18)
        assert len(zones) == 2

    def test_empty_series_returns_no_zones(self):
        from core.data.indicators import LEVEL_COLUMNS
        s = pd.Series({col: float("nan") for col in LEVEL_COLUMNS})
        zones = find_zones(s, tolerance_pct=0.18)
        assert zones == []


# ---------------------------------------------------------------------------
# zone_above / zone_below helpers
# ---------------------------------------------------------------------------

class TestZoneNavigation:
    def _zones(self):
        return [
            Zone(price_low=21500, price_high=21510, members=["daily_S2"], anchor=21500),
            Zone(price_low=22000, price_high=22010, members=["daily_P"], anchor=22000),
            Zone(price_low=22500, price_high=22515, members=["daily_R1", "weekly_R1"], anchor=22500),
        ]

    def test_zone_above_returns_nearest_above(self):
        z = zone_above(self._zones(), price=22100)
        assert z.price_low == 22500

    def test_zone_above_returns_none_if_none_above(self):
        assert zone_above(self._zones(), price=23000) is None

    def test_zone_below_returns_nearest_below(self):
        z = zone_below(self._zones(), price=22100)
        assert z.price_high == 22010

    def test_zone_below_returns_none_if_none_below(self):
        assert zone_below(self._zones(), price=21000) is None
