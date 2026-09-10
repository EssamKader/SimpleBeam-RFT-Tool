# -*- coding: utf-8 -*-
"""Unit tests for ``rft.ui.derivation`` (issue #50, U6) -- the Review tab's
derivation rule. This is the part of #50 a plain-CPython test can actually
reach; ``script.py`` imports ``pyrevit`` and cannot be imported here.

A stand-in ``object()`` plays the role of a picked ``RebarBarType``/
``RebarHookType`` throughout -- the derivation rule only ever asks "is this
None or not", never anything Revit-specific about it, so a bare sentinel is
enough and deliberately carries no Revit shape to assume.
"""

from rft.ui import derivation


BAR_TYPE = object()
HOOK_TYPE = object()


# --- main bars, per face (A44's blank-count semantics) ---------------------


def test_main_bar_face_requested_when_type_and_count_given():
    result = derivation.main_bar_face_derivation("Top main bars", BAR_TYPE, 3)
    assert result.requested is True
    assert "Top main bars" in result.reason
    assert "will be placed" in result.reason


def test_main_bar_face_not_requested_when_type_missing():
    result = derivation.main_bar_face_derivation("Top main bars", None, 3)
    assert result.requested is False
    assert "no bar type selected" in result.reason


def test_main_bar_face_not_requested_when_count_blank():
    result = derivation.main_bar_face_derivation("Top main bars", BAR_TYPE, None)
    assert result.requested is False
    assert "no bar count entered" in result.reason


def test_main_bar_face_not_requested_when_both_missing():
    result = derivation.main_bar_face_derivation("Top main bars", None, None)
    assert result.requested is False
    assert "no bar type selected" in result.reason
    assert "no bar count entered" in result.reason


def test_top_requested_bottom_not_are_independent():
    review = derivation.compute_review_derivation(
        top_bar_type_selected=BAR_TYPE, top_bar_count=3,
        bottom_bar_type_selected=None, bottom_bar_count=None,
        hook_type_selected=None,
        crack_bar_type_selected=None, h_mm=None,
        layers_top=None, layers_btm=None,
    )
    assert review.top_main.requested is True
    assert review.bottom_main.requested is False
    assert review.any_requested is True


def test_bottom_requested_top_not_are_independent():
    review = derivation.compute_review_derivation(
        top_bar_type_selected=None, top_bar_count=None,
        bottom_bar_type_selected=BAR_TYPE, bottom_bar_count=4,
        hook_type_selected=None,
        crack_bar_type_selected=None, h_mm=None,
        layers_top=None, layers_btm=None,
    )
    assert review.top_main.requested is False
    assert review.bottom_main.requested is True
    assert review.any_requested is True


# --- main bars: face gap (issue #65, corrected rule) ------------------------
#
# The bar COUNT is the statement of intent; a bar type or a layer count
# present alone is not (either can be a default, a leftover, or a value
# #54's persistence restored on purpose while withholding the count). So
# a face refuses ONLY when a count is entered and the type and/or the
# layer count is still missing. Every row below is exercised explicitly.


def test_face_fully_blank_does_not_refuse():
    result = derivation.main_bar_face_gap(None, None, None)
    assert result.refuses is False
    assert result.missing == ()


def test_face_type_and_layers_without_count_does_not_refuse():
    # The #54 restored-beam state: both bar types and both layer counts
    # restored, both bar counts deliberately withheld. This is the
    # regression the old (wrong) symmetric rule broke.
    result = derivation.main_bar_face_gap(BAR_TYPE, None, 2)
    assert result.refuses is False
    assert result.missing == ()


def test_face_type_only_does_not_refuse():
    # Bar types picked up front on the Beam & Materials tab, before any
    # face has a count or a layer count entered yet.
    result = derivation.main_bar_face_gap(BAR_TYPE, None, None)
    assert result.refuses is False
    assert result.missing == ()


def test_face_layers_only_does_not_refuse():
    # A leftover layer count with nothing else entered for this face.
    result = derivation.main_bar_face_gap(None, None, 2)
    assert result.refuses is False
    assert result.missing == ()


def test_face_count_without_type_or_layers_refuses():
    result = derivation.main_bar_face_gap(None, 8, None)
    assert result.refuses is True
    assert result.missing == ("bar type", "layer count")


def test_face_count_and_layers_without_type_refuses():
    result = derivation.main_bar_face_gap(None, 4, 2)
    assert result.refuses is True
    assert result.missing == ("bar type",)


def test_face_count_and_type_without_layers_refuses():
    # A50/#65: bar type AND bar count present (REQUESTED per
    # main_bar_face_derivation), no layer count -- the exact shape that
    # reaches core.plan.face_plan and raises TypeError inside an open
    # transaction (confirmed directly against face_plan; see this
    # module's own docstring reference).
    result = derivation.main_bar_face_gap(BAR_TYPE, 4, None)
    assert result.refuses is True
    assert result.missing == ("layer count",)


def test_face_fully_filled_does_not_refuse():
    result = derivation.main_bar_face_gap(BAR_TYPE, 4, 2)
    assert result.refuses is False
    assert result.missing == ()


def test_a_full_restore_leaves_no_face_refusing():
    """Pins the #54 interaction so the old symmetric rule cannot come
    back (modelled on ``tests/test_ui_persistence.py``'s
    ``test_a_full_restore_leaves_every_section_not_requested``): run the
    REAL ``to_store``/``from_store`` round trip over a full set of
    inputs, feed the restored bar types and layer counts into
    ``main_bar_face_gap`` with the withheld bar counts absent, and
    require neither face to refuse.
    """
    from rft.ui.persistence import from_store, to_store

    text = {
        "top_layers_tb": "2",
        "bottom_layers_tb": "2",
        "spacer_dia_tb": "16",
        "d_agg_tb": "20",
        "min_spacing_override_tb": "30",
        "ld_top_mult_tb": "55",
        "ld_btm_mult_tb": "55",
        "dense_spacing_tb": "150",
        "normal_spacing_tb": "200",
        "crack_s_max_tb": "200",
    }
    choices = {
        "top_face_option_combo": "2 -- stacked rows, separated by a spacer bar",
        "bottom_face_option_combo": "2 -- stacked rows, separated by a spacer bar",
        "closure_type_combo": "1 -- closed loop, hooks meet at the TOP-RIGHT corner",
    }
    types = {
        "top_main_bar_type": "<restored top type>",
        "bottom_main_bar_type": "<restored bottom type>",
        "stirrup_bar_type": "<restored stirrup type>",
    }
    restored_text, restored_choices, restored_types = from_store(
        to_store(text, choices, types)
    )
    assert restored_text and restored_choices and restored_types, (
        "the restore under test is not empty"
    )

    top = derivation.main_bar_face_gap(
        restored_types.get("top_main_bar_type"),
        None,  # withheld by #54
        int(restored_text["top_layers_tb"]),
    )
    bottom = derivation.main_bar_face_gap(
        restored_types.get("bottom_main_bar_type"),
        None,  # withheld by #54
        int(restored_text["bottom_layers_tb"]),
    )

    assert top.refuses is False, (
        "a restore made Place refuse the top face -- restoring values "
        "must not restore intent (U10/#54)"
    )
    assert bottom.refuses is False, (
        "a restore made Place refuse the bottom face -- restoring values "
        "must not restore intent (U10/#54)"
    )


# --- stirrups: hook-selection only -------------------------------------------


def test_stirrups_requested_when_hook_selected():
    result = derivation.stirrups_derivation(HOOK_TYPE)
    assert result.requested is True
    assert "will be placed" in result.reason


def test_stirrups_not_requested_when_hook_missing():
    result = derivation.stirrups_derivation(None)
    assert result.requested is False
    assert "no RebarHookType selected" in result.reason


# --- crack bars (A50) --------------------------------------------------------


def test_crack_bars_not_requested_no_bar_type():
    result = derivation.crack_bars_derivation(
        crack_bar_type_selected=None, h_mm=900.0,
        top_bar_type_selected=BAR_TYPE, layers_top=1,
        bottom_bar_type_selected=BAR_TYPE, layers_btm=1,
    )
    assert result.requested is False
    assert "no crack bar type selected" in result.reason


def test_crack_bars_not_requested_h_exactly_700_strict():
    result = derivation.crack_bars_derivation(
        crack_bar_type_selected=BAR_TYPE, h_mm=700.0,
        top_bar_type_selected=BAR_TYPE, layers_top=1,
        bottom_bar_type_selected=BAR_TYPE, layers_btm=1,
    )
    assert result.requested is False
    assert "h = 700.0 mm" in result.reason
    assert "h > 700" in result.reason


def test_crack_bars_requested_h_above_700():
    result = derivation.crack_bars_derivation(
        crack_bar_type_selected=BAR_TYPE, h_mm=700.1,
        top_bar_type_selected=BAR_TYPE, layers_top=1,
        bottom_bar_type_selected=BAR_TYPE, layers_btm=1,
    )
    assert result.requested is True


def test_crack_bars_not_requested_h_none_not_yet_known():
    result = derivation.crack_bars_derivation(
        crack_bar_type_selected=BAR_TYPE, h_mm=None,
        top_bar_type_selected=BAR_TYPE, layers_top=1,
        bottom_bar_type_selected=BAR_TYPE, layers_btm=1,
    )
    assert result.requested is False
    assert "not yet known" in result.reason


def test_crack_bars_not_requested_top_face_missing_bar_type():
    result = derivation.crack_bars_derivation(
        crack_bar_type_selected=BAR_TYPE, h_mm=900.0,
        top_bar_type_selected=None, layers_top=1,
        bottom_bar_type_selected=BAR_TYPE, layers_btm=1,
    )
    assert result.requested is False
    assert "top face" in result.reason
    assert "no top main bar type selected" in result.reason
    assert "bottom face" not in result.reason


def test_crack_bars_not_requested_top_face_missing_layer_count():
    result = derivation.crack_bars_derivation(
        crack_bar_type_selected=BAR_TYPE, h_mm=900.0,
        top_bar_type_selected=BAR_TYPE, layers_top=None,
        bottom_bar_type_selected=BAR_TYPE, layers_btm=1,
    )
    assert result.requested is False
    assert "top face" in result.reason
    assert "no top layer count entered" in result.reason


def test_crack_bars_not_requested_bottom_face_missing():
    result = derivation.crack_bars_derivation(
        crack_bar_type_selected=BAR_TYPE, h_mm=900.0,
        top_bar_type_selected=BAR_TYPE, layers_top=1,
        bottom_bar_type_selected=None, layers_btm=None,
    )
    assert result.requested is False
    assert "bottom face" in result.reason
    assert "no bottom main bar type selected" in result.reason
    assert "no bottom layer count entered" in result.reason
    assert "top face" not in result.reason


def test_crack_bars_not_requested_both_faces_missing():
    result = derivation.crack_bars_derivation(
        crack_bar_type_selected=BAR_TYPE, h_mm=900.0,
        top_bar_type_selected=None, layers_top=None,
        bottom_bar_type_selected=None, layers_btm=None,
    )
    assert result.requested is False
    assert "top face" in result.reason
    assert "bottom face" in result.reason


def test_crack_bars_requested_when_everything_present():
    result = derivation.crack_bars_derivation(
        crack_bar_type_selected=BAR_TYPE, h_mm=900.0,
        top_bar_type_selected=BAR_TYPE, layers_top=2,
        bottom_bar_type_selected=BAR_TYPE, layers_btm=1,
    )
    assert result.requested is True
    assert "will be placed" in result.reason


def test_crack_bars_requested_independent_of_main_bar_count():
    # A50 needs a LAYER COUNT and a bar type on both faces, never the
    # per-layer bar COUNT -- crack bars can be requested even when main
    # bars themselves are not (e.g. bar count left blank).
    result = derivation.crack_bars_derivation(
        crack_bar_type_selected=BAR_TYPE, h_mm=900.0,
        top_bar_type_selected=BAR_TYPE, layers_top=1,
        bottom_bar_type_selected=BAR_TYPE, layers_btm=1,
    )
    assert result.requested is True


# --- nothing requested at all -> Place disabled ------------------------------


def test_nothing_requested_disables_place():
    review = derivation.compute_review_derivation(
        top_bar_type_selected=None, top_bar_count=None,
        bottom_bar_type_selected=None, bottom_bar_count=None,
        hook_type_selected=None,
        crack_bar_type_selected=None, h_mm=None,
        layers_top=None, layers_btm=None,
    )
    assert review.any_requested is False
    assert review.top_main.requested is False
    assert review.bottom_main.requested is False
    assert review.stirrups.requested is False
    assert review.crack_bars.requested is False


def test_any_one_section_requested_enables_place():
    review = derivation.compute_review_derivation(
        top_bar_type_selected=None, top_bar_count=None,
        bottom_bar_type_selected=None, bottom_bar_count=None,
        hook_type_selected=HOOK_TYPE,
        crack_bar_type_selected=None, h_mm=None,
        layers_top=None, layers_btm=None,
    )
    assert review.any_requested is True
