"""Unit tests for rft.core.crack_bars: trigger, H_avail (A26), layer
count/spacing (section 5.2), vertical/horizontal positions (A24), and
embedment (A23, R2). Pure Python, no Revit imports needed -- runs under
plain CPython.
"""

import pytest

from rft.core.crack_bars import (
    DEFAULT_S_MAX_MM,
    H_TRIGGER_MM,
    available_height_mm,
    crack_bar_embedment_mm,
    crack_bar_end_result,
    crack_bar_u_positions_mm,
    crack_layer_plan,
    crack_layer_v_positions_mm,
    crack_reinforcement_triggered,
    spacing_validation_exemption_note,
)
from rft.core.layout import first_layer_offset_mm, layer_offset_mm


# --- section 5 trigger --------------------------------------------------


def test_trigger_at_exactly_700_does_not_fire():
    assert crack_reinforcement_triggered(700.0) is False


def test_trigger_at_701_fires():
    assert crack_reinforcement_triggered(701.0) is True


def test_h_trigger_constant_is_700():
    assert H_TRIGGER_MM == 700.0


# --- section 5.1 / A26 available height ---------------------------------


def test_available_height_basic():
    # h=900, offset_top=50, offset_btm=60 -> H_avail = 790
    assert available_height_mm(900.0, 50.0, 60.0) == pytest.approx(790.0)


def test_a26_multilayer_beam_has_fewer_crack_layers_than_single_layer():
    """A26: H_avail must be measured to the INNERMOST main bar layer. A
    2-layer beam's innermost offset is LARGER than a 1-layer beam's only
    offset, so H_avail is SMALLER and n_crack_layers must be <= the
    1-layer case (strictly fewer for these numbers).
    """
    cover, stirrup, bar_dia, spacer, h = 25.0, 10.0, 20.0, 16.0, 900.0
    s_max = 150.0

    offset_1layer = layer_offset_mm(cover, stirrup, bar_dia, spacer, 1)
    offset_2layer = layer_offset_mm(cover, stirrup, bar_dia, spacer, 2)
    assert offset_2layer > offset_1layer  # sanity: innermost really is larger

    h_avail_1 = available_height_mm(h, offset_1layer, offset_1layer)
    h_avail_2 = available_height_mm(h, offset_2layer, offset_2layer)
    assert h_avail_2 < h_avail_1

    plan_1 = crack_layer_plan(h_avail_1, s_max)
    plan_2 = crack_layer_plan(h_avail_2, s_max)
    assert plan_2.n_crack_layers < plan_1.n_crack_layers


# --- section 5.2 layer count and spacing ---------------------------------


def test_exact_multiple_gives_no_extra_gap():
    # H_avail = 600, s_max = 200 -> exactly 3 gaps, 2 crack layers, 200 spacing
    plan = crack_layer_plan(600.0, 200.0)
    assert plan.n_gaps == 3
    assert plan.n_crack_layers == 2
    assert plan.actual_spacing_mm == pytest.approx(200.0)


def test_exact_multiple_from_float_division_noise_does_not_invent_a_gap():
    # 600.0 / 200.0 in IEEE float division can land fractionally above 3.0;
    # a bare math.ceil would push that to 4 gaps. Confirm it does not here.
    h_avail = 200.0 * 3  # constructed the same way a real caller would
    plan = crack_layer_plan(h_avail, 200.0)
    assert plan.n_gaps == 3
    assert plan.n_crack_layers == 2


def test_non_multiple_spacing_is_even_and_not_over_max():
    # H_avail = 700, s_max = 200 -> ceil(3.5) = 4 gaps, 3 crack layers,
    # actual spacing = 175 <= 200
    plan = crack_layer_plan(700.0, 200.0)
    assert plan.n_gaps == 4
    assert plan.n_crack_layers == 3
    assert plan.actual_spacing_mm == pytest.approx(175.0)
    assert plan.actual_spacing_mm <= 200.0


def test_h_avail_less_than_or_equal_s_max_gives_zero_crack_layers():
    plan = crack_layer_plan(150.0, 200.0)
    assert plan.n_gaps == 1
    assert plan.n_crack_layers == 0
    assert plan.actual_spacing_mm == pytest.approx(150.0)


def test_h_avail_exactly_equal_s_max_gives_zero_crack_layers():
    plan = crack_layer_plan(200.0, 200.0)
    assert plan.n_gaps == 1
    assert plan.n_crack_layers == 0


def test_non_positive_h_avail_raises():
    with pytest.raises(ValueError):
        crack_layer_plan(0.0, 200.0)
    with pytest.raises(ValueError):
        crack_layer_plan(-10.0, 200.0)


def test_non_positive_s_max_raises():
    with pytest.raises(ValueError):
        crack_layer_plan(600.0, 0.0)
    with pytest.raises(ValueError):
        crack_layer_plan(600.0, -1.0)


# --- vertical positions: innermost bottom layer centreline datum --------


def test_topmost_crack_layer_sits_one_spacing_below_innermost_top_layer():
    h_mm = 900.0
    offset_top_mm = 55.0
    offset_btm_mm = 60.0
    h_avail = available_height_mm(h_mm, offset_top_mm, offset_btm_mm)
    plan = crack_layer_plan(h_avail, 150.0)

    v_positions = crack_layer_v_positions_mm(
        h_mm, offset_btm_mm, plan.n_crack_layers, plan.actual_spacing_mm
    )
    assert len(v_positions) == plan.n_crack_layers

    innermost_top_layer_v = (h_mm / 2.0) - offset_top_mm
    topmost_crack_layer_v = v_positions[-1]
    assert topmost_crack_layer_v == pytest.approx(innermost_top_layer_v - plan.actual_spacing_mm)


def test_bottommost_crack_layer_is_one_spacing_above_innermost_bottom_layer():
    h_mm = 900.0
    offset_btm_mm = 60.0
    plan = crack_layer_plan(available_height_mm(h_mm, 55.0, offset_btm_mm), 150.0)
    v_positions = crack_layer_v_positions_mm(
        h_mm, offset_btm_mm, plan.n_crack_layers, plan.actual_spacing_mm
    )
    innermost_bottom_layer_v = -(h_mm / 2.0) + offset_btm_mm
    assert v_positions[0] == pytest.approx(innermost_bottom_layer_v + plan.actual_spacing_mm)


def test_v_positions_evenly_spaced_and_never_zero_length_for_zero_layers():
    assert crack_layer_v_positions_mm(900.0, 60.0, 0, 150.0) == []


# --- A24 horizontal (u) positions ----------------------------------------


def test_u_positions_symmetric_and_match_first_layer_offset_formula():
    b_mm, cover_side, stirrup_dia, crack_dia = 400.0, 25.0, 10.0, 12.0
    u_left, u_right = crack_bar_u_positions_mm(b_mm, cover_side, stirrup_dia, crack_dia)
    side_offset = first_layer_offset_mm(cover_side, stirrup_dia, crack_dia)
    assert u_left == pytest.approx(-(b_mm / 2.0 - side_offset))
    assert u_right == pytest.approx(b_mm / 2.0 - side_offset)
    assert u_left == pytest.approx(-u_right)


# --- A23 / R2 embedment ---------------------------------------------------


def test_supported_end_embedment_is_support_width_minus_cover():
    assert crack_bar_embedment_mm(400.0, 40.0) == pytest.approx(360.0)


def test_embedment_has_no_ld_cap_even_for_a_tiny_support():
    # Unlike rft.core.anchorage._capped_anchorage, there is no 200mm-bend
    # floor or LD-based cap here -- A23 forbids applying section 2.3's
    # machinery to crack bars at all.
    assert crack_bar_embedment_mm(50.0, 40.0) == pytest.approx(10.0)


def test_crack_bar_end_result_supported():
    result = crack_bar_end_result(True, support_width_mm=400.0, support_cover_mm=40.0)
    assert result.is_supported is True
    assert result.embedment_mm == pytest.approx(360.0)
    assert result.terminates_short_of_end_mm is None


def test_crack_bar_end_result_unsupported_reports_explicitly_no_negative_length():
    result = crack_bar_end_result(False, beam_end_cover_mm=40.0)
    assert result.is_supported is False
    assert result.embedment_mm == pytest.approx(0.0)
    assert result.terminates_short_of_end_mm == pytest.approx(40.0)
    assert result.terminates_short_of_end_mm >= 0.0


# --- A25 exemption --------------------------------------------------------


def test_spacing_validation_exemption_note_names_a25():
    note = spacing_validation_exemption_note()
    assert "A25" in note
    assert "6.2" in note


def test_s_max_default_is_a36s_200_not_a_hand_picked_value():
    # A36 fixes the v1 default at 200 mm. Section 5.2 itself gives none, so
    # a hand-picked form pre-fill (250) would be this tool inventing a
    # detailing value -- the one thing CONTEXT.md forbids outright.
    assert DEFAULT_S_MAX_MM == 200.0
