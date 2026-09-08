"""Unit tests for the pure anchorage core (rev 2 section 2.2/2.3).

Runs under plain CPython -- ``rft.core.anchorage`` imports nothing from the
Revit API.
"""

import re

import pytest

from rft.core.anchorage import (
    DEFAULT_LD_BTM_MULTIPLIER,
    DEFAULT_LD_TOP_MULTIPLIER,
    MIN_BEND_LEG_MM,
    bottom_bar_anchorage,
    development_length,
    free_end_configuration_warning,
    top_bar_anchorage,
    top_bottom_clearance_mm,
    top_bottom_clearance_warning,
    placed_clearance_mm,
    placed_clearance_warning,
    unsupported_end_anchorage,
    unsupported_end_straight_run_mm,
)


def test_development_length_is_multiplier_times_diameter():
    assert development_length(16, 55) == 880
    assert development_length(16, DEFAULT_LD_BTM_MULTIPLIER) == 880


def test_comfortable_fit_no_cap_no_clamp():
    """Support wide enough, LD long enough: neither the §2.3 cap nor the
    200 mm floor changes the raw §2.2 a_btm/LD-a values."""
    result = bottom_bar_anchorage(
        support_width_mm=300, support_cover_mm=25, ld_btm_mm=880
    )
    assert result.a == 275  # a_btm = 300 - 25, uncapped (LD - 200 = 680 > 275)
    assert result.b == 605  # LD - a, unclamped (605 > 200)
    assert result.a + result.b == result.ld


def test_straight_leg_cap_fires_when_ld_short_vs_support_width():
    """Spec §2.3 worked example: a 600 mm support with LD = 300 mm would,
    uncapped, deliver 559 + 200 = 759 mm against a 300 mm requirement. The
    cap must bring total anchorage back down to exactly LD."""
    result = bottom_bar_anchorage(
        support_width_mm=600, support_cover_mm=41, ld_btm_mm=300
    )
    a_formula = 600 - 41  # = 559, what a_btm would be uncapped
    assert a_formula > result.ld - MIN_BEND_LEG_MM  # confirms the cap condition holds
    assert result.a == result.ld - MIN_BEND_LEG_MM  # a capped to LD - 200 = 100
    assert result.a == 100
    assert result.b == MIN_BEND_LEG_MM  # floor also lands at exactly 200 here
    assert result.a + result.b == result.ld  # total anchorage == LD exactly, not 759


def test_200mm_minimum_bend_clamp_fires():
    """Support wide enough to drive `a` to (or near) the cap, LD short
    enough that LD - a would undershoot 200 mm without the floor."""
    result = bottom_bar_anchorage(
        support_width_mm=500, support_cover_mm=50, ld_btm_mm=200
    )
    assert result.a == 0  # min(450, 200 - 200) = 0
    assert result.b == MIN_BEND_LEG_MM  # max(200, 200 - 0) clamps to the floor
    assert result.a + result.b == result.ld


def test_exact_minimum_boundary_cap_and_clamp_coincide():
    """a_formula == LD - 200 exactly: the cap and the floor land on the same
    value from both directions, a boundary worth pinning explicitly."""
    result = bottom_bar_anchorage(
        support_width_mm=400, support_cover_mm=100, ld_btm_mm=500
    )
    assert result.a == 300  # a_formula = 300 = LD - 200, min() picks either arm
    assert result.b == MIN_BEND_LEG_MM
    assert result.a + result.b == result.ld


@pytest.mark.parametrize(
    "support_width_mm,support_cover_mm,ld_btm_mm",
    [
        (300, 25, 880),
        (600, 41, 300),
        (500, 50, 200),
    ],
)
def test_total_anchorage_always_equals_ld(support_width_mm, support_cover_mm, ld_btm_mm):
    """§2.3: total anchorage = LD exactly, regardless of which branch fires."""
    result = bottom_bar_anchorage(support_width_mm, support_cover_mm, ld_btm_mm)
    assert result.a + result.b == pytest.approx(ld_btm_mm)


def test_ld_below_minimum_bend_leg_raises_instead_of_negative_a():
    """Issue #14 review finding #3: a free-input LD multiplier (script.py)
    can drive LD below the 200 mm minimum bend leg -- e.g. multiplier 10
    with Ø16 gives LD = 160. Uncapped this would give a = min(a_formula,
    -40) = -40, a negative straight run reversing the segment direction.
    Must raise, never reach the Revit API with a negative/zero `a`."""
    with pytest.raises(ValueError, match="minimum bend leg"):
        bottom_bar_anchorage(support_width_mm=600, support_cover_mm=41, ld_btm_mm=160)


def test_ld_exactly_at_minimum_bend_leg_does_not_raise():
    """200 mm exactly is still valid (a can legitimately be 0) -- only
    below the floor is an error; pins the boundary against an off-by-one
    guard."""
    result = bottom_bar_anchorage(support_width_mm=500, support_cover_mm=50, ld_btm_mm=200)
    assert result.a == 0
    assert result.b == MIN_BEND_LEG_MM


# --- issue #15 (S2): top bar anchorage --------------------------------------


def test_development_length_top_uses_default_60_multiplier():
    assert development_length(12, DEFAULT_LD_TOP_MULTIPLIER) == 720


def test_top_bar_comfortable_fit_subtracts_bottom_bar_diameter():
    """a_t = Support width - Cover - O_BTM (§2.1/§2.2, A7) -- deliberately
    the BOTTOM bar's own diameter, not the top bar's."""
    result = top_bar_anchorage(
        support_width_mm=300, support_cover_mm=25, bottom_bar_diameter_mm=16, ld_top_mm=720
    )
    assert result.a == 300 - 25 - 16  # = 259
    assert result.a + result.b == result.ld


def test_top_bar_uses_bottom_diameter_not_top_diameter():
    """Regression guard against the exact mistake this ticket warns about:
    swapping O_BTM for O_TOP in the formula changes the result, so a test
    that only checked the formula's SHAPE (not this specific term) would
    not catch the "fix"."""
    result_with_correct_term = top_bar_anchorage(
        support_width_mm=300, support_cover_mm=25, bottom_bar_diameter_mm=16, ld_top_mm=720
    )
    # If O_TOP (12) were used instead of O_BTM (16), a would be 263, not 259.
    assert result_with_correct_term.a == 259
    assert result_with_correct_term.a != 300 - 25 - 12


def test_top_bar_straight_leg_cap_fires():
    """Same §2.3 cap/clamp discipline as the bottom bar, exercised via the
    top-bar formula's own (smaller, O_BTM-reduced) a_formula."""
    result = top_bar_anchorage(
        support_width_mm=600, support_cover_mm=41, bottom_bar_diameter_mm=16, ld_top_mm=300
    )
    a_formula = 600 - 41 - 16  # = 543
    assert a_formula > result.ld - MIN_BEND_LEG_MM
    assert result.a == result.ld - MIN_BEND_LEG_MM  # capped to 100
    assert result.b == MIN_BEND_LEG_MM
    assert result.a + result.b == result.ld


def test_top_bar_ld_below_minimum_bend_leg_raises():
    with pytest.raises(ValueError, match="minimum bend leg"):
        top_bar_anchorage(support_width_mm=600, support_cover_mm=41, bottom_bar_diameter_mm=16, ld_top_mm=160)


# --- issue #15 (S2): top/bottom centreline clearance (§2.2, A7) -------------


def test_clearance_holds_for_top12_bottom16():
    """Worked example from the ticket: O_TOP=12, O_BTM=16 -- achieved
    16 mm against required 14 mm, 2 mm of slack."""
    result = top_bottom_clearance_mm(top_bar_diameter_mm=12, bottom_bar_diameter_mm=16)
    assert result.achieved_mm == 16
    assert result.required_mm == pytest.approx(14.0)
    assert result.ok is True
    assert top_bottom_clearance_warning(12, 16) is None


def test_clearance_fails_when_top_diameter_exceeds_bottom():
    """Worked example from the ticket: O_TOP=25, O_BTM=16 -- achieved
    16 mm against required 20.5 mm, a clash. Confirms the derivation that
    the clearance rule only protects O_TOP <= O_BTM."""
    result = top_bottom_clearance_mm(top_bar_diameter_mm=25, bottom_bar_diameter_mm=16)
    assert result.achieved_mm == 16
    assert result.required_mm == pytest.approx(20.5)
    assert result.ok is False

    warning = top_bottom_clearance_warning(25, 16)
    assert warning is not None
    assert "16.0" in warning
    assert "20.5" in warning


def test_clearance_boundary_top_equals_bottom_holds_exactly():
    """O_TOP == O_BTM: achieved == required exactly (both equal the shared
    diameter), a boundary worth pinning since the rule is `>=`."""
    result = top_bottom_clearance_mm(top_bar_diameter_mm=16, bottom_bar_diameter_mm=16)
    assert result.achieved_mm == result.required_mm == 16
    assert result.ok is True


# --- issue #15 (S2): unsupported-end anchorage (§2.5, A12, R3 resolved) -----


def test_unsupported_end_straight_run_subtracts_beam_end_cover():
    assert unsupported_end_straight_run_mm(distance_to_beam_end_mm=0.0, beam_end_cover_mm=25.0) == -25.0
    assert unsupported_end_straight_run_mm(distance_to_beam_end_mm=100.0, beam_end_cover_mm=25.0) == 75.0


def test_unsupported_end_anchorage_warns_naming_both_lengths():
    """R3 requires the warning to state both the required LD and the
    achieved length. The achieved EMBEDMENT at an unsupported end is 0 --
    there is no support to embed into -- and the bar's termination short of
    the beam end is reported as the separate geometric fact it is, not as a
    negative anchorage length (issue #15 review)."""
    result = unsupported_end_anchorage(
        achieved_length_mm=0.0, ld_mm=880.0, terminates_short_of_end_mm=25.0
    )
    assert result.achieved_length_mm == 0.0
    assert result.ld_mm == 880.0
    assert result.warning is not None
    assert "880.0" in result.warning
    assert "0.0" in result.warning
    assert "25.0" in result.warning
    assert re.search(r"-\d", result.warning) is None  # no negative length reported


def test_placed_clearance_catches_an_asymmetric_cap_the_formula_check_misses():
    """Issue #15 review: O_TOP = O_BTM = 16 on an 800 mm support with 25 mm
    cover. The formula-level A7 check passes (achieved O_BTM = 16 against a
    required 16), but section 2.3's cap fires on the bottom bar and not the
    top, so the bars as built have crossed."""
    support_width_mm, cover_mm, dia_mm = 800.0, 25.0, 16.0
    ld_top = development_length(dia_mm, DEFAULT_LD_TOP_MULTIPLIER)
    ld_btm = development_length(dia_mm, DEFAULT_LD_BTM_MULTIPLIER)

    btm = bottom_bar_anchorage(support_width_mm, cover_mm, ld_btm)
    top = top_bar_anchorage(support_width_mm, cover_mm, dia_mm, ld_top)
    assert btm.a == pytest.approx(680.0)  # capped at LD - 200
    assert top.a == pytest.approx(759.0)  # uncapped formula value

    # The formula-level check is satisfied ...
    assert top_bottom_clearance_mm(dia_mm, dia_mm).ok is True
    # ... while the as-built one is not, and by a negative margin.
    placed = placed_clearance_mm(btm.a, top.a, dia_mm, dia_mm)
    assert placed.achieved_mm == pytest.approx(-79.0)
    assert placed.required_mm == pytest.approx(16.0)
    assert placed.ok is False

    warning = placed_clearance_warning(btm.a, top.a, dia_mm, dia_mm, end_label="Start end")
    assert warning is not None
    assert "Start end" in warning
    assert "CROSSED" in warning
    assert "-79.0" in warning and "16.0" in warning


def test_placed_clearance_holds_for_the_default_case():
    """The ordinary case still passes: O_TOP 12 / O_BTM 16 on a 600 mm
    support, where the top bar caps and the bottom bar does not."""
    btm = bottom_bar_anchorage(600.0, 25.0, development_length(16.0, DEFAULT_LD_BTM_MULTIPLIER))
    top = top_bar_anchorage(600.0, 25.0, 16.0, development_length(12.0, DEFAULT_LD_TOP_MULTIPLIER))
    placed = placed_clearance_mm(btm.a, top.a, 12.0, 16.0)
    assert placed.ok is True
    assert placed_clearance_warning(btm.a, top.a, 12.0, 16.0) is None


def test_unsupported_end_anchorage_does_not_warn_when_ld_is_achieved():
    """If the achieved length happens to meet or exceed LD, no warning
    fires -- the rule is literally "warn that LD was not achieved"."""
    result = unsupported_end_anchorage(achieved_length_mm=900.0, ld_mm=880.0)
    assert result.warning is None


def test_free_end_configuration_warning_names_the_v1_scope_boundary():
    warning = free_end_configuration_warning()
    assert "cantilever" in warning.lower()
    assert "out of scope" in warning.lower() or "OUT OF SCOPE" in warning
