"""Unit tests for the pure anchorage core (rev 2 section 2.2/2.3).

Runs under plain CPython -- ``rft.core.anchorage`` imports nothing from the
Revit API.
"""

import pytest

from rft.core.anchorage import (
    DEFAULT_LD_BTM_MULTIPLIER,
    MIN_BEND_LEG_MM,
    bottom_bar_anchorage,
    development_length,
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
