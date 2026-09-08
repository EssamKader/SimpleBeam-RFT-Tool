"""Pure-core tests for `rft.core.guards`: the continuous-run angular
classification and every guard's message text (S9, GitHub issue #22).
"""

import math

import pytest

from rft.core.guards import (
    CONTINUOUS_RUN_ANGLE_THRESHOLD_DEG,
    CONTINUOUS_RUN_AXIS_DOT_TOLERANCE,
    classify_neighbour_axis,
    continuous_run_guard_message,
    free_end_guard_message,
    no_support_detected_message,
    stirrup_type3_guard_message,
)


def _dot_at_angle(angle_deg):
    return math.cos(math.radians(angle_deg))


# --- classify_neighbour_axis --------------------------------------------

def test_parallel_axis_is_continuous():
    result = classify_neighbour_axis(1.0)
    assert result.is_continuous
    assert result.angle_from_collinear_deg == pytest.approx(0.0)


def test_anti_parallel_axis_is_also_continuous():
    """A beam continuing past a support is only 'the same direction' if
    both are traversed consistently start-to-end -- a real continuation is
    just as likely to be anti-parallel as parallel, so BOTH signs must
    count as collinear."""
    result = classify_neighbour_axis(-1.0)
    assert result.is_continuous
    assert result.angle_from_collinear_deg == pytest.approx(0.0)


def test_perpendicular_axis_is_transverse_girder_not_continuous():
    result = classify_neighbour_axis(0.0)
    assert not result.is_continuous
    assert result.angle_from_collinear_deg == pytest.approx(90.0)


def test_ambiguous_45_degrees_resolves_to_continuous():
    """Case 3 from this ticket: an ambiguous 45-degree angle. Resolved
    toward CONTINUOUS (refusal), the safer side per this ticket's stated
    bias -- a false-positive refusal costs a re-check; a false-negative
    pass-through silently ships wrong detailing."""
    result = classify_neighbour_axis(_dot_at_angle(45.0))
    assert result.is_continuous
    assert result.angle_from_collinear_deg == pytest.approx(45.0, abs=1e-6)


def test_just_inside_tolerance_is_continuous():
    result = classify_neighbour_axis(_dot_at_angle(44.0))
    assert result.is_continuous


def test_just_outside_tolerance_is_transverse():
    result = classify_neighbour_axis(_dot_at_angle(46.0))
    assert not result.is_continuous


def test_dot_product_clamped_beyond_unit_range_does_not_raise():
    """Floating-point error can push abs(dot) fractionally past 1.0 for two
    numerically-normalised near-identical vectors; acos would raise a
    domain error unclamped."""
    result = classify_neighbour_axis(1.0000000002)
    assert result.is_continuous
    assert result.angle_from_collinear_deg == pytest.approx(0.0)


def test_threshold_constant_matches_stated_45_degrees():
    assert CONTINUOUS_RUN_ANGLE_THRESHOLD_DEG == 45.0
    assert CONTINUOUS_RUN_AXIS_DOT_TOLERANCE == pytest.approx(math.cos(math.radians(45.0)))


# --- message content: every guard names its condition and spec section --

def test_continuous_run_message_names_condition_and_section():
    result = continuous_run_guard_message("Start end", 12.3)
    assert "Start end" in result.message
    assert "continuous" in result.message.lower() or "CONTINUOUS" in result.message
    assert "section 9 item 2" in result.message
    assert "A39" in result.message
    assert result.spec_section == "rev 2 section 9 item 2 (A39)"
    assert "Start end" in result.condition


def test_continuous_run_message_states_the_angle():
    result = continuous_run_guard_message("End end", 7.5)
    assert "7.5" in result.message


def test_free_end_message_names_condition_and_section():
    result = free_end_guard_message("Start end")
    assert "Start end" in result.message
    assert "cantilever" in result.message.lower()
    assert "section 2.5" in result.message
    assert "A14" in result.message
    assert result.spec_section == "rev 2 section 2.5 (A14)"


def test_stirrup_type3_message_names_condition_and_section():
    result = stirrup_type3_guard_message()
    assert "parked" in result.message.lower()
    assert "section 7.2" in result.spec_section
    assert "A31" in result.spec_section
    assert "R6" in result.spec_section


def test_no_support_message_names_condition_and_section():
    result = no_support_detected_message("End end")
    assert "End end" in result.message
    assert "section 2.4" in result.message
    assert result.spec_section.startswith("rev 2 section 2.4/2.5")
