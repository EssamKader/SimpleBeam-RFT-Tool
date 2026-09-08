"""Pure-core tests for rft.core.grades (S7, issue #20): the role -> grade
assignment (rev 2 section 1.1, A34), the no-fallback explicit-selection
guards, the 180-degree hook-angle check (issue #25), and the diameter
consistency cross-check (this ticket's named trap).
"""

import pytest

from rft.core.grades import (
    GRADE_HIGH_TENSILE,
    GRADE_MILD,
    ROLE_BOTTOM_MAIN,
    ROLE_CRACK,
    ROLE_GRADE,
    ROLE_SPACER,
    ROLE_STIRRUP,
    ROLE_TOP_MAIN,
    bar_type_for_role,
    diameter_consistency_message,
    grade_for_role,
    hook_angle_guard_message,
    missing_bar_type_selection_message,
    missing_hook_type_selection_message,
)


# --- Role -> grade mapping (rev 2 section 1.1, A34) -- every row --------


def test_stirrups_are_mild():
    assert grade_for_role(ROLE_STIRRUP) == GRADE_MILD


def test_top_main_bars_are_high_tensile():
    assert grade_for_role(ROLE_TOP_MAIN) == GRADE_HIGH_TENSILE


def test_bottom_main_bars_are_high_tensile():
    assert grade_for_role(ROLE_BOTTOM_MAIN) == GRADE_HIGH_TENSILE


def test_crack_bars_are_high_tensile():
    assert grade_for_role(ROLE_CRACK) == GRADE_HIGH_TENSILE


def test_spacer_bars_are_high_tensile_applied_literally_per_a34():
    """The spacer row is the literal, deliberate reading of A34 -- not a
    'mild is more realistic' correction. This test exists specifically so
    a future edit that 'fixes' the spacer grade back to mild breaks a
    named, commented test, not just an unnoticed data row."""
    assert grade_for_role(ROLE_SPACER) == GRADE_HIGH_TENSILE


def test_role_grade_table_has_exactly_the_five_specified_roles():
    assert set(ROLE_GRADE) == {
        ROLE_STIRRUP, ROLE_TOP_MAIN, ROLE_BOTTOM_MAIN, ROLE_CRACK, ROLE_SPACER,
    }


def test_grade_for_role_raises_for_unknown_role():
    with pytest.raises(KeyError):
        grade_for_role("some role not in the spec")


# --- bar_type_for_role: no fallback, missing selection is a hard error ---


def test_bar_type_for_role_returns_the_mild_selection_for_stirrups():
    mild, high = object(), object()
    assert bar_type_for_role(ROLE_STIRRUP, mild, high) is mild


def test_bar_type_for_role_returns_the_high_tensile_selection_for_top_bars():
    mild, high = object(), object()
    assert bar_type_for_role(ROLE_TOP_MAIN, mild, high) is high


def test_bar_type_for_role_returns_the_high_tensile_selection_for_spacer_bars():
    mild, high = object(), object()
    assert bar_type_for_role(ROLE_SPACER, mild, high) is high


def test_bar_type_for_role_raises_when_required_grade_not_supplied():
    """A missing explicit selection is a BLOCKING error, never a silent
    fallback to the other grade or to None reaching the Revit API."""
    with pytest.raises(ValueError, match="No RebarBarType selected"):
        bar_type_for_role(ROLE_STIRRUP, mild_bar_type=None, high_tensile_bar_type=object())


def test_bar_type_for_role_does_not_care_about_the_unused_slot():
    """A role needing high tensile must not be blocked by a missing mild
    selection it never uses."""
    high = object()
    assert bar_type_for_role(ROLE_TOP_MAIN, mild_bar_type=None, high_tensile_bar_type=high) is high


# --- missing-selection guard messages ------------------------------------


def test_missing_bar_type_selection_message_names_the_grade_and_spec_section():
    guard = missing_bar_type_selection_message(GRADE_MILD)
    assert GRADE_MILD in guard.message
    assert "1.1" in guard.spec_section
    assert "A35" in guard.spec_section


def test_missing_hook_type_selection_message_names_180_degrees_and_issue_25():
    guard = missing_hook_type_selection_message()
    assert "180" in guard.message
    assert "7.3" in guard.spec_section


# --- hook angle guard (issue #25) ----------------------------------------


def test_hook_angle_guard_passes_at_exactly_180():
    assert hook_angle_guard_message(180.0) is None


def test_hook_angle_guard_passes_within_tolerance():
    assert hook_angle_guard_message(180.9) is None
    assert hook_angle_guard_message(179.1) is None


def test_hook_angle_guard_blocks_a_90_degree_hook():
    guard = hook_angle_guard_message(90.0, hook_type_name="Standard-90")
    assert guard is not None
    assert "90.0" in guard.message
    assert "Standard-90" in guard.message
    assert "180" in guard.message


def test_hook_angle_guard_blocks_a_135_degree_hook():
    """A33 supersedes the 135-degree ACI recommendation the §7 research
    considered (deformed-bar assumption) -- confirms 135 is rejected here
    too, not only a wildly wrong angle."""
    guard = hook_angle_guard_message(135.0)
    assert guard is not None


# --- diameter consistency (this ticket's named trap) ---------------------


def test_diameter_consistency_passes_on_exact_match():
    assert diameter_consistency_message("Bottom bar", 16.0, 16.0) is None


def test_diameter_consistency_passes_within_tolerance():
    assert diameter_consistency_message("Bottom bar", 16.0, 16.3) is None


def test_diameter_consistency_blocks_on_mismatch():
    guard = diameter_consistency_message("Bottom bar (O_BTM)", 16.0, 20.0)
    assert guard is not None
    assert "16.0" in guard.message
    assert "20.0" in guard.message
    assert "Bottom bar (O_BTM)" in guard.condition


def test_diameter_consistency_exact_boundary_of_tolerance_passes():
    """0.5 mm is the tolerance itself -- exactly at the boundary must still
    pass, not be treated as a violation by a strict '<' vs '<=' slip."""
    guard = diameter_consistency_message("Stirrup", 10.0, 10.5)
    assert guard is None
