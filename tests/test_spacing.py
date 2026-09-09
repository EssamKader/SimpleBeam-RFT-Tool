# -*- coding: utf-8 -*-
"""Unit tests for rft.core.spacing: governing minimum, A43's achieved clear
spacing, per-layer/per-face validation, A44's suggested layer count, and
the section 6.3 option/layer-count cross-check (rev 2 sections 6.2-6.4).
Pure Python, no Revit imports needed -- runs under plain CPython.
"""

import pytest

from rft.core.spacing import (
    max_bars_per_layer,
    MAX_LAYERS,
    OPTION_SINGLE_ROW,
    OPTION_STACKED,
    achieved_clear_spacing_mm,
    governing_min_spacing_mm,
    suggest_min_layer_count,
    validate_face_spacing,
    validate_layer_spacing,
)


# --- section 6.2: governing minimum -----------------------------------------


def test_d_agg_defined_governs_formula_branch():
    # O_bar=12, D_agg=20 -> max(25, 12, 1.33*20=26.6) = 26.6, well under 50.
    assert governing_min_spacing_mm(bar_dia_mm=12.0, d_agg_mm=20.0) == pytest.approx(26.6)


def test_d_agg_undefined_falls_back_to_50_only():
    assert governing_min_spacing_mm(bar_dia_mm=12.0, d_agg_mm=None) == pytest.approx(50.0)


def test_d_agg_is_not_folded_into_the_same_max_as_the_50mm_fallback():
    # If someone "fixed" this to max(25, O_bar, 1.33*D_agg, 50) it would
    # over-refuse: 26.6 would become 50. Pin the correct (lower) value.
    result = governing_min_spacing_mm(bar_dia_mm=12.0, d_agg_mm=20.0)
    assert result < 50.0
    assert result == pytest.approx(26.6)


def test_d_agg_large_enough_to_govern_over_25_and_bar_dia():
    # O_bar=16, D_agg=45 -> 1.33*45 = 59.85, the largest term.
    assert governing_min_spacing_mm(bar_dia_mm=16.0, d_agg_mm=45.0) == pytest.approx(59.85)


def test_a29_override_above_formula_result_is_used_as_floor():
    formula_only = governing_min_spacing_mm(bar_dia_mm=12.0, d_agg_mm=20.0)  # 26.6
    result = governing_min_spacing_mm(bar_dia_mm=12.0, d_agg_mm=20.0, user_override_mm=40.0)
    assert result == pytest.approx(40.0)
    assert result > formula_only


def test_a29_override_below_formula_result_is_ignored_entirely():
    # formula_result = 26.6; an override of 20 (below it) must NOT reduce
    # the governing value below 26.6 -- assert on the RETURNED VALUE, not
    # on a message.
    result = governing_min_spacing_mm(bar_dia_mm=12.0, d_agg_mm=20.0, user_override_mm=20.0)
    assert result == pytest.approx(26.6)


# --- section 6.4 (A43-corrected datum): achieved clear spacing --------------


def test_a43_numeric_pin_correct_value():
    # b=250, Cover=25 (SIDE cover), O_stirrup=10, 3xO16 -> A43-corrected
    # clear = (250 - 50 - 20 - 48) / 2 = 66.0 mm.
    result = achieved_clear_spacing_mm(
        b_mm=250.0, cover_side_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=16.0, bar_count=3
    )
    assert result == pytest.approx(66.0)


def test_a43_numeric_pin_diverges_from_printed_formula_wrong_answer():
    # The PRINTED (uncorrected) section 6.4 formula -- offset per §4,
    # clear = (b - 2*offset_1 - n*O_bar)/(n-1) -- gives 58.0 mm for the
    # same inputs (offset_1 = 25+10+8 = 43; (250-86-48)/2 = 58.0). A43's
    # corrected datum must NOT reproduce that under-reported value.
    result = achieved_clear_spacing_mm(
        b_mm=250.0, cover_side_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=16.0, bar_count=3
    )
    assert result != pytest.approx(58.0)
    assert result == pytest.approx(66.0)


def test_a43_section_passes_under_corrected_formula_but_would_refuse_under_printed_one():
    # Same section as above; D_agg=45 -> governing = 59.85 mm. The
    # corrected achieved value (66.0) PASSES; the printed formula's wrong
    # value (58.0) would have REFUSED (58.0 < 59.85).
    governing_mm = governing_min_spacing_mm(bar_dia_mm=16.0, d_agg_mm=45.0)
    assert governing_mm == pytest.approx(59.85)
    achieved_mm = achieved_clear_spacing_mm(
        b_mm=250.0, cover_side_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=16.0, bar_count=3
    )
    assert achieved_mm >= governing_mm  # PASSES
    printed_formula_wrong_value = 58.0
    assert printed_formula_wrong_value < governing_mm  # would have REFUSED


def test_n_equals_1_skips_the_check_returns_none():
    assert achieved_clear_spacing_mm(
        b_mm=250.0, cover_side_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=16.0, bar_count=1
    ) is None


def test_bar_count_less_than_1_raises():
    with pytest.raises(ValueError, match="section 6.4"):
        achieved_clear_spacing_mm(
            b_mm=250.0, cover_side_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=16.0, bar_count=0
        )


# --- validate_layer_spacing --------------------------------------------------


def test_layer_spacing_comfortable_fit_passes():
    result = validate_layer_spacing(
        layer_index=1, bar_count=3, b_mm=400.0, cover_side_mm=25.0, stirrup_dia_mm=10.0,
        bar_dia_mm=12.0, governing_min_mm=25.0,
    )
    assert result.passes
    assert result.achieved_clear_mm > result.governing_min_mm


def test_layer_spacing_exact_minimum_boundary_passes_not_fails():
    # Construct a bar_count/b combination whose achieved clear spacing is
    # EXACTLY the governing minimum -- section 6.4 only refuses `clear <
    # governing_min_spacing` (strict), so achieved == governing must PASS.
    cover_side_mm, stirrup_dia_mm, bar_dia_mm, bar_count = 25.0, 10.0, 16.0, 3
    governing_min_mm = 66.0  # engineer sets D_agg such that this equals 66.0 exactly
    b_mm = 250.0  # achieved_clear_spacing_mm(...) == 66.0 for these inputs (A43 pin)
    result = validate_layer_spacing(
        layer_index=1, bar_count=bar_count, b_mm=b_mm, cover_side_mm=cover_side_mm,
        stirrup_dia_mm=stirrup_dia_mm, bar_dia_mm=bar_dia_mm, governing_min_mm=governing_min_mm,
    )
    assert result.achieved_clear_mm == pytest.approx(governing_min_mm)
    assert result.passes is True


def test_layer_spacing_one_below_minimum_fails():
    result = validate_layer_spacing(
        layer_index=1, bar_count=3, b_mm=250.0, cover_side_mm=25.0, stirrup_dia_mm=10.0,
        bar_dia_mm=16.0, governing_min_mm=66.01,
    )
    assert result.passes is False


def test_layer_spacing_n1_always_passes_regardless_of_governing_min():
    result = validate_layer_spacing(
        layer_index=1, bar_count=1, b_mm=100.0, cover_side_mm=25.0, stirrup_dia_mm=10.0,
        bar_dia_mm=16.0, governing_min_mm=1000.0,
    )
    assert result.passes is True
    assert result.achieved_clear_mm is None


# --- suggest_min_layer_count (A44, reporting only) --------------------------


def test_suggest_min_layer_count_finds_smaller_k_when_more_layers_help():
    # 12 bars, single layer of 12 badly violates; splitting across more
    # layers reduces bars-per-layer and increases achieved clear spacing.
    b_mm, cover_side_mm, stirrup_dia_mm, bar_dia_mm = 400.0, 25.0, 10.0, 16.0
    governing_min_mm = 40.0
    k = suggest_min_layer_count(
        total_bar_count=12, b_mm=b_mm, cover_side_mm=cover_side_mm,
        stirrup_dia_mm=stirrup_dia_mm, bar_dia_mm=bar_dia_mm, governing_min_mm=governing_min_mm,
    )
    assert k is not None
    # Confirm k actually satisfies the minimum via the same even-split rule.
    import math
    bars_in_fullest_layer = int(math.ceil(12 / float(k)))
    achieved_mm = achieved_clear_spacing_mm(
        b_mm, cover_side_mm, stirrup_dia_mm, bar_dia_mm, bars_in_fullest_layer
    )
    assert achieved_mm is None or achieved_mm >= governing_min_mm
    # And k-1 (if >=1) must NOT satisfy it, confirming k is the SMALLEST.
    if k > 1:
        bars_prev = int(math.ceil(12 / float(k - 1)))
        achieved_prev_mm = achieved_clear_spacing_mm(
            b_mm, cover_side_mm, stirrup_dia_mm, bar_dia_mm, bars_prev
        )
        assert achieved_prev_mm is not None and achieved_prev_mm < governing_min_mm


def test_suggest_min_layer_count_returns_none_when_unreachable_within_cap():
    # A tiny, narrow face that cannot satisfy the minimum even at 5 layers.
    k = suggest_min_layer_count(
        total_bar_count=20, b_mm=150.0, cover_side_mm=25.0, stirrup_dia_mm=10.0,
        bar_dia_mm=25.0, governing_min_mm=200.0,
    )
    assert k is None


# --- validate_face_spacing: options, refusals, cross-check ------------------


def test_face_spacing_option1_comfortable_fit_passes():
    report = validate_face_spacing(
        face_label="Top face", option=OPTION_SINGLE_ROW, layer_bar_counts=[3],
        b_mm=400.0, cover_side_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=12.0,
        governing_min_mm=25.0,
    )
    assert report.passes
    assert report.guard_messages == []


def test_face_spacing_option1_violation_refuses():
    report = validate_face_spacing(
        face_label="Top face", option=OPTION_SINGLE_ROW, layer_bar_counts=[3],
        b_mm=250.0, cover_side_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=16.0,
        governing_min_mm=66.01,
    )
    assert report.passes is False
    assert len(report.guard_messages) == 1
    msg = report.guard_messages[0]
    assert msg.spec_section
    assert "66.0" in msg.message  # achieved value reported
    assert "66.01" in msg.message or "66.0" in msg.message  # governing reported


def test_face_spacing_option2_violation_refuses_not_auto_stacks():
    # A44 supersedes A27's Option 2 auto-stacking: a violating layer under
    # option 2 must ALSO refuse, never silently re-split into more layers.
    report = validate_face_spacing(
        face_label="Bottom face", option=OPTION_STACKED, layer_bar_counts=[3],
        b_mm=250.0, cover_side_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=16.0,
        governing_min_mm=66.01,
    )
    assert report.passes is False
    assert len(report.guard_messages) == 1
    # Reports the smallest layer count that WOULD satisfy the minimum, as
    # a suggestion only -- confirm the suggestion language is present.
    assert "A44" in report.guard_messages[0].message


def test_face_spacing_5_layer_hard_error_names_it_explicitly():
    # Every layer here is identical and violates; even the smallest-layer
    # search across the 5-layer cap cannot satisfy the minimum.
    report = validate_face_spacing(
        face_label="Top face", option=OPTION_STACKED,
        layer_bar_counts=[10, 10, 10, 10, 10],
        b_mm=150.0, cover_side_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=25.0,
        governing_min_mm=200.0,
    )
    assert report.passes is False
    assert any("HARD ERROR" in m.message for m in report.guard_messages)
    assert any("A28" in m.message for m in report.guard_messages)


def test_face_spacing_option1_with_more_than_one_layer_is_refused_as_contradiction():
    report = validate_face_spacing(
        face_label="Top face", option=OPTION_SINGLE_ROW, layer_bar_counts=[3, 3],
        b_mm=400.0, cover_side_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=12.0,
        governing_min_mm=25.0,
    )
    assert report.passes is False
    assert len(report.guard_messages) == 1
    assert "option 1" in report.guard_messages[0].message.lower()
    assert report.layer_results == []  # refused before per-layer validation


def test_face_spacing_n1_layer_skips_check_and_passes():
    report = validate_face_spacing(
        face_label="Bottom face", option=OPTION_SINGLE_ROW, layer_bar_counts=[1],
        b_mm=100.0, cover_side_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=25.0,
        governing_min_mm=1000.0,
    )
    assert report.passes is True
    assert report.guard_messages == []


def test_face_spacing_per_face_independence_one_face_failing_does_not_alter_other():
    # Validate a failing top face and a passing bottom face independently;
    # confirm the bottom face's report is unaffected by the top's failure
    # (per-face independence, section 6.3).
    top_report = validate_face_spacing(
        face_label="Top face", option=OPTION_SINGLE_ROW, layer_bar_counts=[3],
        b_mm=250.0, cover_side_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=16.0,
        governing_min_mm=66.01,
    )
    bottom_report = validate_face_spacing(
        face_label="Bottom face", option=OPTION_SINGLE_ROW, layer_bar_counts=[3],
        b_mm=400.0, cover_side_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=12.0,
        governing_min_mm=25.0,
    )
    assert top_report.passes is False
    assert bottom_report.passes is True
    assert bottom_report.guard_messages == []


def test_max_bars_per_layer_is_the_number_the_form_actually_takes():
    # b=250, Cover=25, O_stirrup=10 -> clear width 180 mm; governing 50 mm.
    # n=3: (180 - 48)/2 = 66.0 -> passes. n=4: (180 - 64)/3 = 38.7 -> fails.
    per_layer = max_bars_per_layer(
        b_mm=250.0, cover_side_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=16.0,
        governing_min_mm=50.0,
    )
    assert per_layer == 3


def test_max_bars_per_layer_never_returns_zero():
    # A single bar has no horizontal spacing question (A43), so one bar per
    # layer always satisfies the minimum however tight the section is.
    per_layer = max_bars_per_layer(
        b_mm=200.0, cover_side_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=32.0,
        governing_min_mm=200.0,
    )
    assert per_layer == 1


def test_suggested_layer_count_agrees_with_max_bars_per_layer():
    # The suggestion must be enterable: bars-per-layer x layers must cover
    # the total, since the form applies one count to every layer.
    kwargs = dict(
        b_mm=250.0, cover_side_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=16.0,
        governing_min_mm=50.0,
    )
    per_layer = max_bars_per_layer(**kwargs)
    k = suggest_min_layer_count(total_bar_count=8, **kwargs)
    assert per_layer * k >= 8
    assert (per_layer * (k - 1)) < 8
