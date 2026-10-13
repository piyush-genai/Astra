"""
Unit tests for the compounding lot manager (TASK-5 / EXP-0017 config D_steps).

Covers the four areas where a sizing bug would be expensive and silent:
  1. Tier boundary behaviour — an off-by-one at 15%/25%/40% changes exposure by ~2x
  2. Drawdown measured on NET capital, so the tax reserve cannot mask a drawdown
  3. Lot-cap growth gated on the 1.00x tier, so a recovery streak cannot enlarge risk
  4. Configured risk ceilings enforced rather than silently clamped

The EXP-0017 narrative figures (0.35x × 20 = 7 lots, 1.00x → 20 restored) are pinned as
regression anchors — they are the only recorded evidence of how the validated run actually
applied the drawdown multiplier.
"""

import math

import pytest

from src.astra.risk.lot_manager import (
    STEP_DOWN_TIERS,
    DrawdownApplication,
    HwmMarking,
    LotManager,
    LotManagerConfig,
    RiskLimitConflict,
    dd_multiplier_for,
)


# ── tier boundaries ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "drawdown, expected",
    [
        (0.0, 1.00),
        (0.1499, 1.00),
        (0.15, 0.65),   # boundary is inclusive-below: 15% exactly drops to caution
        (0.2499, 0.65),
        (0.25, 0.35),
        (0.3999, 0.35),
        (0.40, 0.12),
        (0.99, 0.12),
    ],
)
def test_tier_boundaries(drawdown: float, expected: float) -> None:
    assert dd_multiplier_for(drawdown) == expected


def test_negative_drawdown_rejected() -> None:
    with pytest.raises(ValueError):
        dd_multiplier_for(-0.01)


def test_final_tier_must_be_unbounded() -> None:
    with pytest.raises(ValueError, match="unbounded"):
        LotManagerConfig(tiers=((0.15, 1.0), (0.40, 0.35)))


def test_tiers_cover_every_drawdown() -> None:
    assert STEP_DOWN_TIERS[-1][0] == math.inf
    for dd in (0.0, 0.14999, 0.15, 0.3, 0.75, 10.0):
        assert dd_multiplier_for(dd) > 0


# ── drawdown is measured on net capital ──────────────────────────────────────────────


def test_tax_reserve_excluded_from_sizing_capital() -> None:
    mgr = LotManager(gross_capital=100_000.0, tax_reserve=30_000.0)
    assert mgr.net_capital == 70_000.0


def test_tax_withholding_does_not_create_a_drawdown() -> None:
    """
    Under the default MONTH_CLOSE marking, the HWM is set on post-withholding capital, so
    withholding can never by itself register as a drawdown.
    """
    mgr = LotManager(gross_capital=20_000.0)
    mgr.record_trade_pnl(10_000.0)
    mgr.close_month()  # profitable → 30% of 10k withheld

    assert mgr.tax_reserve == pytest.approx(3_000.0)
    assert mgr.net_capital == pytest.approx(27_000.0)
    assert mgr.drawdown == 0.0
    assert mgr.dd_multiplier == 1.00


def test_per_trade_marking_demotes_a_tier_after_a_strong_month() -> None:
    """
    Pins the artifact that makes MONTH_CLOSE the default. EXP-0017.json recommends
    per-trade HWM marking; under it, a month earning 100% of capital withholds 30% of
    the new peak at close and demotes the engine two tiers on accounting alone, with no
    actual loss having occurred.
    """
    cfg = LotManagerConfig(hwm_marking=HwmMarking.PER_TRADE)
    mgr = LotManager(config=cfg, gross_capital=100_000.0)
    mgr.record_trade_pnl(100_000.0)  # HWM marked at 200,000 pre-tax
    assert mgr.high_water_mark == pytest.approx(200_000.0)

    mgr.close_month()  # withholds 30,000
    assert mgr.net_capital == pytest.approx(170_000.0)
    assert mgr.drawdown == pytest.approx(0.15)
    assert mgr.dd_multiplier == 0.65  # demoted despite a doubling month

    # The default marking does not do this.
    default_mgr = LotManager(gross_capital=100_000.0)
    default_mgr.record_trade_pnl(100_000.0)
    default_mgr.close_month()
    assert default_mgr.drawdown == 0.0
    assert default_mgr.dd_multiplier == 1.00


def test_hwm_only_ever_rises() -> None:
    cfg = LotManagerConfig(hwm_marking=HwmMarking.PER_TRADE)
    mgr = LotManager(config=cfg, gross_capital=20_000.0)
    mgr.record_trade_pnl(5_000.0)
    peak = mgr.high_water_mark
    assert peak == pytest.approx(25_000.0)

    mgr.record_trade_pnl(-8_000.0)
    assert mgr.high_water_mark == pytest.approx(peak)
    assert mgr.drawdown == pytest.approx(8_000.0 / 25_000.0)


def test_hwm_does_not_move_intra_month_by_default() -> None:
    mgr = LotManager(gross_capital=20_000.0)
    mgr.record_trade_pnl(5_000.0)
    assert mgr.high_water_mark == pytest.approx(20_000.0)  # unchanged until close
    mgr.close_month()
    assert mgr.high_water_mark == pytest.approx(23_500.0)  # 25,000 less 1,500 tax


def test_drawdown_floored_at_zero_on_new_high() -> None:
    mgr = LotManager(gross_capital=20_000.0)
    mgr.record_trade_pnl(50_000.0)
    assert mgr.drawdown == 0.0
    assert mgr.dd_multiplier == 1.00


# ── EXP-0017 recorded narrative, pinned ──────────────────────────────────────────────


def test_exp0017_defense_tier_yields_seven_lots_at_cap_twenty() -> None:
    """
    EXP-0017 FINDING-3: "7 lots at 0.35x tier (step-down: 0.35x × 20 = 7 lots max)".

    Only reachable if the multiplier scales the cap. Capital here is deliberately huge so
    the cap, not the capital, is the binding constraint.
    """
    cfg = LotManagerConfig(initial_max_lots=20)
    mgr = LotManager(config=cfg, gross_capital=10_000_000.0)
    mgr.record_trade_pnl(0.0)  # mark HWM at current net capital

    # Drive net capital to a 30% drawdown → defense tier (0.35x)
    mgr.record_trade_pnl(-3_000_000.0)
    assert mgr.dd_multiplier == 0.35
    assert mgr.effective_lot_cap == 7
    assert mgr.lots_for(premium_per_lot=5_000.0) == 7


def test_exp0017_crisis_tier_yields_two_lots_at_cap_twenty() -> None:
    """EXP-0017 FINDING-3: the 0.12x tier bottoms out at 2 lots on a cap of 20."""
    cfg = LotManagerConfig(initial_max_lots=20)
    mgr = LotManager(config=cfg, gross_capital=10_000_000.0)
    mgr.record_trade_pnl(0.0)
    mgr.record_trade_pnl(-5_000_000.0)  # 50% drawdown → crisis
    assert mgr.dd_multiplier == 0.12
    assert mgr.effective_lot_cap == 2


def test_exp0017_full_recovery_restores_full_cap() -> None:
    """"Jul 2024: DD dropped to 13.3% → fully recovered to 1.00x → 20 lots restored"."""
    cfg = LotManagerConfig(initial_max_lots=20)
    mgr = LotManager(config=cfg, gross_capital=1_000_000.0)
    mgr.record_trade_pnl(0.0)
    mgr.record_trade_pnl(-400_000.0)
    assert mgr.effective_lot_cap < 20

    mgr.record_trade_pnl(+267_000.0)  # back to ~13.3% drawdown
    assert mgr.drawdown < 0.15
    assert mgr.dd_multiplier == 1.00
    assert mgr.effective_lot_cap == 20


# ── the two drawdown applications differ, and CAP_SCALED is the default ──────────────


def test_default_application_is_cap_scaled() -> None:
    assert LotManagerConfig().dd_application is DrawdownApplication.CAP_SCALED


def test_capital_scaled_form_cannot_reproduce_seven_lots() -> None:
    """
    The documented formula clamps to the unscaled cap, so it yields 20 where EXP-0017
    recorded 7. This test pins the discrepancy rather than hiding it.
    """
    cfg = LotManagerConfig(
        initial_max_lots=20, dd_application=DrawdownApplication.CAPITAL_SCALED
    )
    mgr = LotManager(config=cfg, gross_capital=10_000_000.0)
    mgr.record_trade_pnl(0.0)
    mgr.record_trade_pnl(-3_000_000.0)

    assert mgr.dd_multiplier == 0.35
    assert mgr.lots_for(premium_per_lot=5_000.0) == 20  # not 7


# ── lot-cap growth ───────────────────────────────────────────────────────────────────


def test_cap_grows_after_three_consecutive_profitable_months() -> None:
    mgr = LotManager(config=LotManagerConfig(initial_max_lots=10), gross_capital=100_000.0)

    for _ in range(2):
        mgr.record_trade_pnl(10_000.0)
        mgr.close_month()
    assert mgr.max_lots_cap == 10  # not yet

    mgr.record_trade_pnl(10_000.0)
    summary = mgr.close_month()
    assert mgr.max_lots_cap == 15
    assert summary["cap_grew"] is True
    assert mgr.consecutive_profitable_months == 0  # streak spent


def test_losing_month_resets_the_streak() -> None:
    mgr = LotManager(config=LotManagerConfig(initial_max_lots=10), gross_capital=100_000.0)

    for _ in range(2):
        mgr.record_trade_pnl(10_000.0)
        mgr.close_month()
    assert mgr.consecutive_profitable_months == 2

    mgr.record_trade_pnl(-1_000.0)
    mgr.close_month()
    assert mgr.consecutive_profitable_months == 0

    mgr.record_trade_pnl(10_000.0)
    mgr.close_month()
    assert mgr.max_lots_cap == 10  # streak restarted, no growth


def test_cap_does_not_grow_while_in_drawdown() -> None:
    """
    The gate that matters: three profitable months during a recovery must not enlarge the
    cap while the strategy is still impaired.
    """
    mgr = LotManager(config=LotManagerConfig(initial_max_lots=20), gross_capital=1_000_000.0)
    mgr.record_trade_pnl(0.0)
    mgr.record_trade_pnl(-500_000.0)  # 50% drawdown → crisis tier
    mgr.close_month()
    assert mgr.dd_multiplier == 0.12

    # Three profitable months that are too small to climb out of the drawdown.
    for _ in range(3):
        mgr.record_trade_pnl(1_000.0)
        mgr.close_month()

    assert mgr.drawdown >= 0.15
    assert not mgr.at_full_tier
    assert mgr.max_lots_cap == 20  # held
    assert mgr.consecutive_profitable_months >= 3  # streak preserved, not spent


def test_streak_is_spent_once_the_tier_recovers() -> None:
    """A streak banked during drawdown applies on the first month back at 1.00x."""
    mgr = LotManager(config=LotManagerConfig(initial_max_lots=20), gross_capital=1_000_000.0)
    mgr.record_trade_pnl(0.0)
    mgr.record_trade_pnl(-500_000.0)
    mgr.close_month()

    for _ in range(3):
        mgr.record_trade_pnl(1_000.0)
        mgr.close_month()
    assert mgr.max_lots_cap == 20

    mgr.record_trade_pnl(1_000_000.0)  # new high → back to 1.00x
    mgr.close_month()
    assert mgr.at_full_tier
    assert mgr.max_lots_cap == 25


# ── sizing arithmetic ────────────────────────────────────────────────────────────────


def test_lots_from_capital_when_capital_is_binding() -> None:
    # 30% of 100,000 = 30,000 budget; at 4,000/lot → 7 lots, below the cap of 10.
    mgr = LotManager(config=LotManagerConfig(initial_max_lots=10), gross_capital=100_000.0)
    assert mgr.lots_for(premium_per_lot=4_000.0) == 7


def test_cap_binds_when_capital_is_ample() -> None:
    mgr = LotManager(config=LotManagerConfig(initial_max_lots=10), gross_capital=10_000_000.0)
    assert mgr.lots_for(premium_per_lot=4_000.0) == 10


def test_premium_floor_prevents_absurd_lot_counts() -> None:
    """HANDOFF G2: a ₹1 deep-OTM quote must not imply thousands of lots."""
    mgr = LotManager(config=LotManagerConfig(initial_max_lots=10), gross_capital=100_000.0)
    assert mgr.lots_for(premium_per_lot=1.0) == 10  # floored to ₹500, then cap-bound


def test_minimum_one_lot_even_on_tiny_capital() -> None:
    mgr = LotManager(gross_capital=600.0)
    assert mgr.lots_for(premium_per_lot=50_000.0) == 1


def test_non_positive_premium_rejected() -> None:
    mgr = LotManager()
    with pytest.raises(ValueError):
        mgr.lots_for(premium_per_lot=0.0)


def test_capital_floor_on_catastrophic_loss() -> None:
    mgr = LotManager(gross_capital=20_000.0)
    mgr.record_trade_pnl(-1_000_000.0)
    assert mgr.gross_capital == 500.0


# ── configured risk ceilings are enforced ────────────────────────────────────────────


def test_risk_per_trade_above_configured_deployment_cap_raises() -> None:
    """The live conflict: EXP-0017 wants 30%, config/risk.yaml allows 25%."""
    with pytest.raises(RiskLimitConflict, match="max_capital_deployed_pct"):
        LotManagerConfig(risk_per_trade_pct=30.0, max_capital_deployed_pct=25.0)


def test_initial_lots_above_hard_cap_raises() -> None:
    """The other live conflict: EXP-0017 starts at 20 lots, risk.yaml hard-caps at 10."""
    with pytest.raises(RiskLimitConflict, match="hard_cap_lots"):
        LotManagerConfig(initial_max_lots=20, hard_cap_lots=10)


def test_from_risk_config_reads_ceilings_and_accepts_compliant_sizing() -> None:
    risk_cfg = {
        "per_trade": {"max_capital_deployed_pct": 25.0},
        "position_limits": {"hard_cap_lots": 10},
    }
    cfg = LotManagerConfig.from_risk_config(
        risk_cfg, risk_per_trade_pct=25.0, initial_max_lots=10
    )
    assert cfg.hard_cap_lots == 10
    assert cfg.max_capital_deployed_pct == 25.0


def test_from_risk_config_rejects_the_validated_stack_as_configured_today() -> None:
    """
    Documents the real state: the validated EXP-0017 sizing cannot be instantiated against
    the current config/risk.yaml. Reconciling that is a human risk-limit decision.
    """
    risk_cfg = {
        "per_trade": {"max_capital_deployed_pct": 25.0},
        "position_limits": {"hard_cap_lots": 10},
    }
    with pytest.raises(RiskLimitConflict):
        LotManagerConfig.from_risk_config(
            risk_cfg, risk_per_trade_pct=30.0, initial_max_lots=10
        )


def test_cap_growth_respects_hard_cap() -> None:
    cfg = LotManagerConfig(initial_max_lots=10, hard_cap_lots=12)
    mgr = LotManager(config=cfg, gross_capital=100_000.0)
    for _ in range(3):
        mgr.record_trade_pnl(10_000.0)
        mgr.close_month()
    assert mgr.max_lots_cap == 12  # clamped from 15


def test_cap_at_hard_ceiling_preserves_streak() -> None:
    """A cap already at the ceiling must not burn qualifying months pointlessly."""
    cfg = LotManagerConfig(initial_max_lots=10, hard_cap_lots=10)
    mgr = LotManager(config=cfg, gross_capital=100_000.0)
    for _ in range(3):
        mgr.record_trade_pnl(10_000.0)
        mgr.close_month()
    assert mgr.max_lots_cap == 10
    assert mgr.consecutive_profitable_months == 3  # not reset


# ── month summary ────────────────────────────────────────────────────────────────────


def test_close_month_summary_shape() -> None:
    mgr = LotManager(gross_capital=20_000.0)
    mgr.record_trade_pnl(5_000.0)
    summary = mgr.close_month()

    assert summary["month_pnl"] == pytest.approx(5_000.0)
    assert summary["tax_withheld"] == pytest.approx(1_500.0)
    assert summary["gross_capital"] == pytest.approx(25_000.0)
    assert summary["net_capital"] == pytest.approx(23_500.0)
    assert summary["dd_multiplier"] == 1.00
    assert summary["cap_grew"] is False


def test_losing_month_withholds_no_tax() -> None:
    mgr = LotManager(gross_capital=20_000.0)
    mgr.record_trade_pnl(-2_000.0)
    summary = mgr.close_month()
    assert summary["tax_withheld"] == 0.0
    assert mgr.tax_reserve == 0.0


def test_month_pnl_resets_between_months() -> None:
    mgr = LotManager(gross_capital=20_000.0)
    mgr.record_trade_pnl(1_000.0)
    mgr.close_month()
    summary = mgr.close_month()
    assert summary["month_pnl"] == 0.0
