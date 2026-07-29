"""
Unit tests for pivot and CPR indicator formulas — task 1a of pivot-cpr-strategy spec.

Sample values are hand-computed. If these tests fail, the formula implementation
is wrong — do NOT adjust expected values to match a broken implementation.

Sample input (from spec requirements.md placeholder — replace with actual
hand-computed values from the source video / spec once confirmed):
    H = 22500.00
    L = 22000.00
    C = 22300.00

Hand-computed:
    P  = (22500 + 22000 + 22300) / 3 = 22266.6667
    R1 = 2 * 22266.6667 - 22000      = 22533.3333
    S1 = 2 * 22266.6667 - 22500      = 22033.3333
    R2 = 22266.6667 + (22500-22000)  = 22766.6667
    S2 = 22266.6667 - (22500-22000)  = 21766.6667
    R3 = 22500 + 2*(22266.6667-22000)= 23033.3333
    S3 = 22000 - 2*(22500-22266.6667)= 21533.3333

    CPR:
    PP  = 22266.6667  (same as P)
    BC  = (22500+22000) / 2 = 22250.0000
    TC  = 2*22266.6667 - 22250 = 22283.3333
"""

import pytest

from src.data.indicators import (
    compute_cpr,
    compute_pivot_set,
    group_levels_into_zones,
    zone_midpoint,
    zone_width_pct,
)

# Test input
H = 22500.00
L = 22000.00
C = 22300.00
PRECISION = 4   # decimal places for comparison


class TestComputePivotSet:
    def setup_method(self):
        self.ps = compute_pivot_set(H, L, C, period="daily")

    def test_pivot_P(self):
        assert round(self.ps.P, PRECISION) == round((H + L + C) / 3, PRECISION)

    def test_R1(self):
        expected = round(2 * self.ps.P - L, PRECISION)
        assert round(self.ps.R1, PRECISION) == expected

    def test_S1(self):
        expected = round(2 * self.ps.P - H, PRECISION)
        assert round(self.ps.S1, PRECISION) == expected

    def test_R2(self):
        expected = round(self.ps.P + (H - L), PRECISION)
        assert round(self.ps.R2, PRECISION) == expected

    def test_S2(self):
        expected = round(self.ps.P - (H - L), PRECISION)
        assert round(self.ps.S2, PRECISION) == expected

    def test_R3(self):
        expected = round(H + 2 * (self.ps.P - L), PRECISION)
        assert round(self.ps.R3, PRECISION) == expected

    def test_S3(self):
        expected = round(L - 2 * (H - self.ps.P), PRECISION)
        assert round(self.ps.S3, PRECISION) == expected

    def test_known_values(self):
        """Verify exact hand-computed values from docstring."""
        assert round(self.ps.P, 4) == 22266.6667
        assert round(self.ps.R1, 4) == 22533.3333
        assert round(self.ps.S1, 4) == 22033.3333
        assert round(self.ps.R2, 4) == 22766.6667
        assert round(self.ps.S2, 4) == 21766.6667
        assert round(self.ps.R3, 4) == 23033.3333
        assert round(self.ps.S3, 4) == 21533.3333

    def test_period_label_stored(self):
        assert self.ps.period == "daily"


class TestComputeCPR:
    def setup_method(self):
        self.cpr = compute_cpr(H, L, C, period="daily")

    def test_PP_equals_pivot_P(self):
        ps = compute_pivot_set(H, L, C)
        assert round(self.cpr.PP, PRECISION) == round(ps.P, PRECISION)

    def test_BC(self):
        expected = round((H + L) / 2, PRECISION)
        assert round(self.cpr.BC, PRECISION) == expected

    def test_TC(self):
        expected = round(2 * self.cpr.PP - self.cpr.BC, PRECISION)
        assert round(self.cpr.TC, PRECISION) == expected

    def test_TC_gte_BC(self):
        assert self.cpr.TC >= self.cpr.BC

    def test_known_values(self):
        assert round(self.cpr.PP, 4) == 22266.6667
        assert round(self.cpr.BC, 4) == 22250.0000
        assert round(self.cpr.TC, 4) == 22283.3333

    def test_doji_like_candle_tc_gte_bc(self):
        """When H == C, TC and BC might be equal or reversed — ensure TC >= BC."""
        cpr = compute_cpr(high=22300, low=22000, close=22300, period="daily")
        assert cpr.TC >= cpr.BC


class TestGroupLevelsIntoZones:
    def test_single_level_forms_one_group(self):
        zones = group_levels_into_zones([100.0], tolerance_pct=0.15)
        assert len(zones) == 1
        assert zones[0] == [100.0]

    def test_empty_levels(self):
        zones = group_levels_into_zones([], tolerance_pct=0.15)
        assert zones == []

    def test_within_tolerance_grouped_together(self):
        # 22250 and 22280 — difference is ~0.13% of ~22265, within 0.15%
        zones = group_levels_into_zones([22250.0, 22280.0], tolerance_pct=0.15)
        assert len(zones) == 1
        assert len(zones[0]) == 2

    def test_outside_tolerance_in_separate_groups(self):
        # 22000 and 22500 — clearly separate
        zones = group_levels_into_zones([22000.0, 22500.0], tolerance_pct=0.15)
        assert len(zones) == 2

    def test_boundary_case_at_exactly_tolerance(self):
        # Place a level exactly at the tolerance boundary.
        ref = 22000.0
        delta = ref * (0.15 / 100)  # exact 0.15%
        other = ref + delta
        zones = group_levels_into_zones([ref, other], tolerance_pct=0.15)
        # At exactly the boundary, should be grouped (≤ tolerance).
        assert len(zones) == 1

    def test_boundary_case_just_outside_tolerance(self):
        ref = 22000.0
        delta = ref * (0.15 / 100) + 0.01  # just over 0.15%
        other = ref + delta
        zones = group_levels_into_zones([ref, other], tolerance_pct=0.15)
        assert len(zones) == 2

    def test_multiple_levels_sorted_into_correct_zones(self):
        # Three levels: two close together, one far away.
        levels = [22500.0, 22510.0, 21000.0]
        zones = group_levels_into_zones(levels, tolerance_pct=0.15)
        assert len(zones) == 2
        # The small-value zone should contain [21000.0]
        assert [21000.0] in zones


class TestZoneHelpers:
    def test_zone_midpoint(self):
        assert zone_midpoint([100.0, 200.0]) == 150.0

    def test_zone_width_pct_single_level(self):
        assert zone_width_pct([22000.0]) == 0.0

    def test_zone_width_pct_two_levels(self):
        levels = [22000.0, 22100.0]
        width = zone_width_pct(levels)
        expected = (22100 - 22000) / 22050 * 100
        assert abs(width - expected) < 0.001
