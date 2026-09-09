# -*- coding: utf-8 -*-
"""Unit tests for ``rft.ui.inputs`` (issue #48, U4) -- the only part of this
ticket a plain-CPython test can reach, per this ticket's brief. ``script.py``
itself imports ``pyrevit`` and cannot be imported here; these tests exercise
the same parsing/validation logic it calls.
"""

import pytest

from rft.core.layout import MAX_LAYERS
from rft.ui import inputs


# --- parse_optional_positive_int (bar counts, layer counts -- A44/#50) -----


def test_blank_count_parses_to_none_not_zero_or_default():
    assert inputs.parse_optional_positive_int("", "Top bar count per layer") is None
    assert inputs.parse_optional_positive_int("   ", "Top bar count per layer") is None
    assert inputs.parse_optional_positive_int(None, "Top bar count per layer") is None


def test_non_blank_count_parses_to_int():
    assert inputs.parse_optional_positive_int("3", "Top bar count per layer") == 3


def test_count_zero_is_rejected_by_name():
    with pytest.raises(ValueError) as exc_info:
        inputs.parse_optional_positive_int("0", "Top bar count per layer")
    assert "Top bar count per layer" in str(exc_info.value)


def test_count_negative_is_rejected():
    with pytest.raises(ValueError):
        inputs.parse_optional_positive_int("-1", "Bottom bar count per layer")


def test_count_non_numeric_is_rejected_by_name():
    with pytest.raises(ValueError) as exc_info:
        inputs.parse_optional_positive_int("abc", "Top bar count per layer")
    assert "Top bar count per layer" in str(exc_info.value)


def test_layer_count_outside_1_to_max_layers_is_rejected_by_name():
    field = "Number of top layers"
    with pytest.raises(ValueError) as exc_info:
        inputs.parse_optional_positive_int(str(MAX_LAYERS + 1), field, max_value=MAX_LAYERS)
    assert field in str(exc_info.value)
    # in range: no error
    assert inputs.parse_optional_positive_int(str(MAX_LAYERS), field, max_value=MAX_LAYERS) == MAX_LAYERS
    assert inputs.parse_optional_positive_int("1", field, max_value=MAX_LAYERS) == 1


def test_layer_count_ships_blank_parses_to_none():
    field = "Number of bottom layers"
    assert inputs.parse_optional_positive_int("", field, max_value=MAX_LAYERS) is None


# --- parse_positive_float (Ø_spacer, dense/normal spacing, LD mult, s_max) -


def test_positive_float_parses():
    assert inputs.parse_positive_float("16", "O_spacer") == 16.0


def test_positive_float_blank_is_rejected():
    with pytest.raises(ValueError) as exc_info:
        inputs.parse_positive_float("", "O_spacer")
    assert "O_spacer" in str(exc_info.value)


def test_positive_float_non_numeric_is_rejected():
    with pytest.raises(ValueError):
        inputs.parse_positive_float("xyz", "Dense spacing")


def test_positive_float_zero_or_negative_is_rejected():
    with pytest.raises(ValueError):
        inputs.parse_positive_float("0", "Dense spacing")
    with pytest.raises(ValueError):
        inputs.parse_positive_float("-5", "Dense spacing")


# --- parse_optional_positive_float (D_agg, min-spacing override -- A29/A36) -


def test_blank_d_agg_yields_none_not_zero():
    """A36: D_agg BLANK by default so section 6.2's 50 mm fallback governs
    -- a blank must parse to ``None``, never ``0.0`` (0 would select the
    formula branch of governing_min_spacing_mm, not the fallback).
    """
    result = inputs.parse_optional_positive_float("", "D_agg")
    assert result is None
    assert result != 0


def test_blank_min_spacing_override_yields_none():
    assert inputs.parse_optional_positive_float("  ", "min-spacing override") is None


def test_non_blank_d_agg_parses_to_float():
    assert inputs.parse_optional_positive_float("20", "D_agg") == 20.0


def test_optional_float_zero_or_negative_when_given_is_rejected():
    with pytest.raises(ValueError):
        inputs.parse_optional_positive_float("0", "D_agg")
    with pytest.raises(ValueError):
        inputs.parse_optional_positive_float("-1", "D_agg")


def test_optional_float_non_numeric_is_rejected_by_name():
    with pytest.raises(ValueError) as exc_info:
        inputs.parse_optional_positive_float("abc", "D_agg")
    assert "D_agg" in str(exc_info.value)


# --- parse_layer_option (section 6.3) --------------------------------------


def test_layer_option_1_and_2_accepted():
    assert inputs.parse_layer_option("1", "Top face option") == 1
    assert inputs.parse_layer_option("2", "Top face option") == 2


def test_layer_option_other_value_rejected_by_name():
    with pytest.raises(ValueError) as exc_info:
        inputs.parse_layer_option("3", "Top face option")
    assert "Top face option" in str(exc_info.value)


def test_layer_option_blank_rejected():
    with pytest.raises(ValueError):
        inputs.parse_layer_option("", "Bottom face option")


# --- closure_type_from_label (A31 -- type 3 never offered) -----------------


def test_closure_type_accepts_1_2_4():
    assert inputs.closure_type_from_label("1") == 1
    assert inputs.closure_type_from_label("2") == 2
    assert inputs.closure_type_from_label("4") == 4


def test_closure_type_none_selected_returns_none():
    assert inputs.closure_type_from_label(None) is None


def test_closure_type_3_is_rejected_even_if_it_reaches_this_function():
    """A31: the ComboBox never offers "3" as an item, so this path should
    be unreachable in the live window -- but the function itself must
    still refuse it by name rather than silently accept it, in case a
    persisted/stale value (#50) ever reaches it.
    """
    with pytest.raises(ValueError) as exc_info:
        inputs.closure_type_from_label("3")
    assert "3" in str(exc_info.value)


# --- try_parse_float (crack tab's h re-evaluation -- never raises) ---------


def test_try_parse_float_blank_returns_none():
    assert inputs.try_parse_float("") is None
    assert inputs.try_parse_float(None) is None


def test_try_parse_float_unparseable_returns_none_not_raise():
    assert inputs.try_parse_float("70x") is None


def test_try_parse_float_valid_returns_float():
    assert inputs.try_parse_float("700") == 700.0
    assert inputs.try_parse_float("701") == 701.0


# --- H_avail missing-input reporting (rev 2 section 5.1, A26) --------------


def test_missing_h_avail_inputs_all_present_returns_empty():
    missing = inputs.missing_h_avail_inputs(
        h_mm=900.0, top_bar_dia_mm=16.0, btm_bar_dia_mm=16.0, stirrup_dia_mm=10.0,
        layers_top=1, layers_btm=1,
    )
    assert missing == []


def test_missing_h_avail_inputs_names_each_missing_field():
    missing = inputs.missing_h_avail_inputs(
        h_mm=None, top_bar_dia_mm=None, btm_bar_dia_mm=16.0, stirrup_dia_mm=10.0,
        layers_top=None, layers_btm=1,
    )
    assert inputs.MISSING_H_AVAIL_FIELD_LABELS["h"] in missing
    assert inputs.MISSING_H_AVAIL_FIELD_LABELS["top_bar_type"] in missing
    assert inputs.MISSING_H_AVAIL_FIELD_LABELS["layers_top"] in missing
    assert inputs.MISSING_H_AVAIL_FIELD_LABELS["bottom_bar_type"] not in missing
    assert inputs.MISSING_H_AVAIL_FIELD_LABELS["stirrup_bar_type"] not in missing
    assert inputs.MISSING_H_AVAIL_FIELD_LABELS["layers_btm"] not in missing


def test_h_avail_missing_message_names_the_missing_input():
    message = inputs.h_avail_missing_message(["number of top layers"])
    assert "number of top layers" in message
    # never a number and never a formatted None
    assert "None" not in message


def test_no_beam_picked_h_avail_message_is_distinct():
    message = inputs.no_beam_picked_h_avail_message()
    assert "beam picked" in message
