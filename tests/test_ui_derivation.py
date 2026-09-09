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
