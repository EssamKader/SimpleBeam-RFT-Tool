"""Pure-core tests for rft.core.grades (S7, issue #20; reworked for A42,
ticket #27): the role -> grade assignment (rev 2 section 1.1, A34), the
per-role picker label, the no-fallback explicit-selection guards, the
180-degree hook-angle check (issue #25), and the stirrup/high-tensile
grade-conflict guard A42 introduces.
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
    grade_for_role,
    hook_angle_guard_message,
    missing_bar_type_selection_message,
    missing_hook_type_selection_message,
    role_grade_report_line,
    role_picker_label,
    stirrup_grade_conflict_message,
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
    named, commented test, not just an unnoticed data row. A42 does not
    place a spacer bar (no picker exists for that role either), so the
    row stays for when that lands -- see rft.core.grades module docstring."""
    assert grade_for_role(ROLE_SPACER) == GRADE_HIGH_TENSILE


def test_role_grade_table_has_exactly_the_five_specified_roles():
    assert set(ROLE_GRADE) == {
        ROLE_STIRRUP, ROLE_TOP_MAIN, ROLE_BOTTOM_MAIN, ROLE_CRACK, ROLE_SPACER,
    }


def test_grade_for_role_raises_for_unknown_role():
    with pytest.raises(KeyError):
        grade_for_role("some role not in the spec")


# --- role_picker_label (A42): built from ROLE_GRADE, never drifts --------


def test_role_picker_label_names_role_and_its_required_grade():
    label = role_picker_label(ROLE_BOTTOM_MAIN)
    assert "Bottom main bars" in label
    assert GRADE_HIGH_TENSILE in label


def test_role_picker_label_for_stirrups_names_mild_grade():
    label = role_picker_label(ROLE_STIRRUP)
    assert "Stirrups" in label
    assert GRADE_MILD in label


def test_role_picker_label_covers_every_role_in_role_grade():
    """A future role added to ROLE_GRADE must not crash the label builder
    -- catches a label/mapping drift at the same time a role is added."""
    for role in ROLE_GRADE:
        label = role_picker_label(role)
        assert ROLE_GRADE[role] in label


# --- role_grade_report_line (A42): report line names type used + required grade


def test_role_grade_report_line_names_bar_type_and_required_grade():
    line = role_grade_report_line(ROLE_TOP_MAIN, "High Tensile 12mm")
    assert "High Tensile 12mm" in line
    assert GRADE_HIGH_TENSILE in line
    assert "Top main bars" in line


# --- bar_type_for_role: no fallback, missing selection is a hard error ---


def test_bar_type_for_role_returns_the_selected_type():
    selected = object()
    assert bar_type_for_role(ROLE_STIRRUP, selected) is selected


def test_bar_type_for_role_returns_the_selected_type_for_any_role():
    selected = object()
    assert bar_type_for_role(ROLE_TOP_MAIN, selected) is selected
    assert bar_type_for_role(ROLE_BOTTOM_MAIN, selected) is selected


def test_bar_type_for_role_raises_when_no_selection_supplied():
    """A missing explicit selection is a BLOCKING error, never a silent
    fallback to None reaching the Revit API."""
    with pytest.raises(ValueError, match="No RebarBarType selected"):
        bar_type_for_role(ROLE_STIRRUP, None)


# --- missing-selection guard messages ------------------------------------


def test_missing_bar_type_selection_message_names_the_role_label_and_spec_section():
    guard = missing_bar_type_selection_message(ROLE_BOTTOM_MAIN)
    assert "Bottom main bars" in guard.message
    assert GRADE_HIGH_TENSILE in guard.message
    assert "1.1" in guard.spec_section
    assert "A42" in guard.spec_section


def test_missing_bar_type_selection_message_for_stirrups_names_mild_grade():
    guard = missing_bar_type_selection_message(ROLE_STIRRUP)
    assert GRADE_MILD in guard.message


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


# --- stirrup_grade_conflict_message (A42, ticket #27) --------------------


def test_stirrup_grade_conflict_message_blocks_on_matching_element_id():
    guard = stirrup_grade_conflict_message(
        stirrup_type_id=7, stirrup_type_name="St 24/35 Ø10",
        other_type_id=7, other_type_name="St 24/35 Ø10",
        other_role="top main bars",
    )
    assert guard is not None
    assert "top main bars" in guard.message
    assert "A34" in guard.message


def test_stirrup_grade_conflict_message_passes_on_different_element_ids():
    assert stirrup_grade_conflict_message(
        stirrup_type_id=7, stirrup_type_name="St 24/35 Ø10",
        other_type_id=9, other_type_name="St 36/52 Ø16",
        other_role="bottom main bars",
    ) is None


def test_stirrup_grade_conflict_message_ignores_equal_names_different_ids():
    """Compared by element id, never by name (A42's explicit instruction)
    -- two differently-graded types sharing a display name in a badly kept
    office template must NOT be flagged as a conflict."""
    assert stirrup_grade_conflict_message(
        stirrup_type_id=7, stirrup_type_name="Rebar Type A",
        other_type_id=9, other_type_name="Rebar Type A",
        other_role="bottom main bars",
    ) is None


def test_stirrup_grade_conflict_message_passes_when_nothing_to_compare_yet():
    assert stirrup_grade_conflict_message(
        stirrup_type_id=7, stirrup_type_name="St 24/35 Ø10",
        other_type_id=None, other_type_name="",
        other_role="bottom main bars",
    ) is None
