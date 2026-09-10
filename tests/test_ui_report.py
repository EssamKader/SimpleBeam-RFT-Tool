# -*- coding: utf-8 -*-
"""The Review report (rev 2 section 8.2, A37), executed.

Until the report was moved out of ``script.py`` into ``rft.ui.report``,
not one line of it could run in a test: ``script.py`` imports ``pyrevit``
and cannot be imported under CPython at all. ~400 lines of the most
detailed prose the tool produces -- every layer offset, every achieved
spacing, every anchorage `a` and `b` -- had never been executed anywhere
but a live Revit session, and it is the text the engineer reads before
committing steel to a model.

Numbers here are checked against the 300x900 beam the tool was verified
on, the same one tests/test_core_plan.py uses, so the report and the plan
are pinned to one beam rather than to each other.

The refusal branches matter as much as the happy path: the report's job
includes saying what it could NOT compute and why, and those branches had
never run either.
"""

import pytest

from rft.ui import report as ui_report
from rft.ui.derivation import compute_review_derivation

# The live-verified beam: 300 x 900, 25 mm cover, O10 stirrups, O16 mains,
# O12 crack bars, on 400 mm supports 6 m apart centre to centre.
B_MM, H_MM = 300.0, 900.0


def _inputs(**overrides):
    fields = dict(
        top_bar_type_name="16M", btm_bar_type_name="16M",
        stirrup_bar_type_name="10M", crack_bar_type_name="12M",
        hook_type_name="Stirrup/Tie 135 deg", hook_angle_deg=135.0,
        top_dia_mm=16.0, btm_dia_mm=16.0, stirrup_dia_mm=10.0, crack_dia_mm=12.0,
        top_count_text="3", btm_count_text="3",
        top_layers_text="2", btm_layers_text="2",
        top_option_label="2 -- stacked rows, separated by a spacer bar",
        btm_option_label="2 -- stacked rows, separated by a spacer bar",
        spacer_dia_text="16", d_agg_text="20", min_spacing_override_text="",
        ld_top_mult_text="55", ld_btm_mult_text="55",
        dense_spacing_text="100", normal_spacing_text="200",
        closure_type_label="1 -- closed loop, hooks meet at the TOP-RIGHT corner",
        crack_s_max_text="200",
    )
    fields.update(overrides)
    return ui_report.ReportInputs(**fields)


def _geometry(**overrides):
    geometry = dict(
        b_mm=B_MM, h_mm=H_MM,
        cover_top_mm=25.0, cover_btm_mm=25.0, cover_side_mm=25.0,
        cover_end_start_mm=25.0, cover_end_end_mm=25.0,
        is_supported_start=True, is_supported_end=True,
        support_width_start_mm=400.0, support_width_end_mm=400.0,
        support_cover_start_mm=40.0, support_cover_end_mm=40.0,
        l_mm=6000.0,
    )
    geometry.update(overrides)
    return geometry


def _review(**overrides):
    kwargs = dict(
        top_bar_type_selected="16M", top_bar_count=3,
        bottom_bar_type_selected="16M", bottom_bar_count=3,
        hook_type_selected="hook",
        crack_bar_type_selected="12M", h_mm=H_MM,
        layers_top=2, layers_btm=2,
    )
    kwargs.update(overrides)
    return compute_review_derivation(**kwargs)


def _text(lines):
    return "\n".join(lines)


# --- the derivation header -------------------------------------------------


def test_derivation_lines_state_every_section():
    lines = ui_report.derivation_lines(_review())
    assert lines[0] == "Derivation (rev 2 section 8, A47/A50):"
    assert len(lines) == 5
    assert "Top main bars: will be placed (3 bars/layer)." in lines[1]
    assert "Crack bars: will be placed." in lines[4]


def test_derivation_says_place_is_disabled_when_nothing_is_requested():
    review = _review(
        top_bar_type_selected=None, bottom_bar_type_selected=None,
        hook_type_selected=None, crack_bar_type_selected=None,
    )
    assert "**Nothing is requested. Place is disabled.**" in _text(
        ui_report.derivation_lines(review))


# --- main bars -------------------------------------------------------------


def test_main_bars_report_the_verified_beams_layer_offsets():
    """43 mm and 75 mm: 25 cover + 10 stirrup + 16/2, then + 16/2 + 16
    spacer + 16/2. The same two numbers tests/test_core_plan.py checks
    against the notation drawing -- pinned here as the TEXT an engineer
    reads, which is a different failure mode from a wrong return value.
    """
    text = _text(ui_report.main_bars_lines(_inputs(), _review(), _geometry()))
    assert "- layer 1: offset_1 = 43.0 mm, v = 407.0 mm" in text
    assert "- layer 2: offset_2 = 75.0 mm, v = 375.0 mm" in text
    # The bottom face mirrors it: same offsets, negated v (section 4).
    assert "- layer 1: offset_1 = 43.0 mm, v = -407.0 mm" in text
    assert "- layer 2: offset_2 = 75.0 mm, v = -375.0 mm" in text


def test_main_bars_report_corner_bar_positions_symmetric_about_the_centre():
    text = _text(ui_report.main_bars_lines(_inputs(), _review(), _geometry()))
    assert "corner-bar u positions (3 bars): -107.0, 0.0, 107.0" in text


def test_top_and_bottom_anchorage_differ_because_the_top_bar_needs_the_other_diameter():
    """Section 2.1: a_t is derived from the BOTTOM bar's diameter, a_b is
    not. Identical `a` on both faces would mean the top-bar formula had
    quietly become the bottom-bar one.
    """
    text = _text(ui_report.main_bars_lines(_inputs(), _review(), _geometry()))
    assert "start: a=344.0 mm, b=536.0 mm" in text     # top face
    assert "start: a=360.0 mm, b=520.0 mm" in text     # bottom face


def test_a_face_that_is_not_requested_says_so_and_computes_nothing():
    review = _review(top_bar_type_selected=None)
    text = _text(ui_report.main_bars_lines(_inputs(), review, _geometry()))
    assert "- Top face: not requested." in text
    assert "v = 407.0 mm" not in text


def test_main_bars_refuse_without_a_stirrup_bar_type_and_say_why():
    """The stirrup type positions every main bar (section 4.1's offsets,
    section 6.1's corner inset) even when no stirrup is placed, so its
    absence blocks the main-bar layout rather than only the stirrups.
    """
    text = _text(ui_report.main_bars_lines(
        _inputs(stirrup_bar_type_name=None), _review(), _geometry()))
    assert "Cannot compute main bar layout: no stirrup RebarBarType" in text
    assert "even when this run does not also place stirrups" in text
    assert "offset_1" not in text


def test_an_unparseable_input_is_reported_in_the_parsers_own_words():
    text = _text(ui_report.main_bars_lines(
        _inputs(spacer_dia_text="abc"), _review(), _geometry()))
    assert "Cannot compute main bar layout:" in text
    assert "O_spacer" in text


def test_a51_refuses_the_top_end_by_name_when_no_bottom_type_is_selected():
    """A51: the top bar's anchorage needs the BOTTOM bar's diameter. With
    no bottom type selected at all there is no diameter and none is
    invented (A42) -- the END is refused, by name, and the report says so
    instead of printing an `a` computed from a placeholder.
    """
    review = _review(bottom_bar_type_selected=None)
    text = _text(ui_report.main_bars_lines(
        _inputs(btm_bar_type_name=None, btm_dia_mm=None), review, _geometry()))
    assert "**REFUSED (A51):**" in text
    assert "needs the BOTTOM bar's diameter" in text
    assert "Top face, start end" in text


def test_an_unsupported_end_warns_rather_than_refusing():
    text = _text(ui_report.main_bars_lines(
        _inputs(), _review(),
        _geometry(is_supported_start=False, support_width_start_mm=None,
                  support_cover_start_mm=None, l_mm=None)))
    assert "**WARNING:** Start end:" in text
    assert "achieved=" in text          # no hook at a free end


def test_the_a7_clearance_line_states_achieved_against_required():
    """#26 is still open on what to DO about a clearance shortfall. What
    the report must not do is stay silent about it: both numbers are
    printed so the engineer can see the comparison the tool is not yet
    enforcing.
    """
    text = _text(ui_report.main_bars_lines(_inputs(), _review(), _geometry()))
    assert ("Top/bottom centreline clearance (section 2.2, A7): achieved "
            "= O_BTM = 16.0 mm, required = (O_TOP+O_BTM)/2 = 16.0 mm.") in text


# --- stirrups --------------------------------------------------------------


def test_stirrups_report_the_centreline_rectangle_not_the_outer_one():
    """240 x 840, not 260 x 860. ``Rebar.CreateFromCurves`` receives the
    CENTRELINE loop; reporting the outer rectangle would describe every
    stirrup as one full diameter larger than the one placed (A30).
    """
    text = _text(ui_report.stirrups_lines(_inputs(), _geometry()))
    assert "CENTRELINE rectangle = 240.0 x 840.0 mm" in text
    assert "closure type = 1" in text


def test_stirrup_zones_are_dense_at_both_ends_and_normal_in_the_middle():
    text = _text(ui_report.stirrups_lines(_inputs(), _geometry()))
    assert "zone1: [250.0, 2000.0] mm" in text
    assert "zone2: [2000.0, 4000.0] mm" in text
    assert "zone3: [4000.0, 5750.0] mm" in text
    assert "**Beam total stirrup count = 47**" in text


def test_the_achieved_stirrup_spacing_never_exceeds_the_maximum_asked_for():
    """The spacing entered is a MAXIMUM (section 3.1). 97.2 mm where 100
    was asked for is the count being rounded up, which is the safe
    direction; a number above the maximum would mean the opposite.
    """
    text = _text(ui_report.stirrups_lines(_inputs(), _geometry()))
    assert "achieved spacing = 97.2 mm (max 100.0 mm)" in text
    assert "achieved spacing = 200.0 mm (max 200.0 mm)" in text


def test_an_unverified_hook_angle_is_reported_as_unverified():
    """A45. An angle that could not be read back is ACCEPTED but must
    never be reported as though it had been checked -- the engineer is
    told to confirm 135 degrees by hand.
    """
    text = _text(ui_report.stirrups_lines(
        _inputs(hook_angle_deg=None), _geometry()))
    assert "could NOT be read back and verified" in text
    assert "Confirm the 135-degree angle manually" in text


def test_stirrup_zones_need_both_ends_supported_and_say_so():
    text = _text(ui_report.stirrups_lines(
        _inputs(), _geometry(is_supported_end=False, l_mm=None)))
    assert "zones need BOTH ends supported" in text
    assert "zone1:" not in text


def test_an_unselected_closure_type_blocks_the_distribution_by_name():
    text = _text(ui_report.stirrups_lines(
        _inputs(closure_type_label=None), _geometry()))
    assert "no closure type selected" in text


# --- crack / skin bars -----------------------------------------------------


def test_h_avail_is_measured_between_the_innermost_layers():
    """750 mm on this beam: 900 - 75 - 75. Measured to the INNERMOST
    main-bar layer of each face (A26), not to the concrete faces -- which
    would give 850 and put a crack layer where a main bar already is.
    """
    text = _text(ui_report.crack_bars_lines(_inputs(), _geometry()))
    assert ("offset_top (innermost, layer 2) = 75.0 mm, offset_btm "
            "(innermost, layer 2) = 75.0 mm (A26)") in text
    assert "H_avail = 750.0 mm (section 5.1)" in text


def test_crack_layers_are_one_fewer_than_the_gaps():
    """Section 5.2 divides H_avail into n gaps and puts a layer at each
    INTERIOR division. Reporting n_gaps as the layer count would claim one
    layer more than is placed, sitting on top of a main bar.
    """
    text = _text(ui_report.crack_bars_lines(_inputs(), _geometry()))
    assert "n_gaps = 4, n_crack_layers = 3, actual_spacing = 187.5 mm" in text
    assert "**Total crack/skin bar count = 6** (2 per layer x 3 layers)" in text


def test_crack_bar_positions_are_symmetric_and_inside_the_main_layers():
    text = _text(ui_report.crack_bars_lines(_inputs(), _geometry()))
    assert "left = -109.0 mm, right = 109.0 mm" in text
    assert "v positions: -187.5, 0.0, 187.5" in text


def test_no_crack_layers_is_reported_as_a_legitimate_outcome():
    """H_avail <= s_max is a valid answer (section 5.2), not a failure --
    and it must not read like one, or the engineer will go looking for a
    fault that is not there.
    """
    text = _text(ui_report.crack_bars_lines(
        _inputs(crack_s_max_text="2000"), _geometry()))
    assert "**n_crack_layers = 0**" in text
    assert "a legitimate outcome" in text
    assert "u positions" not in text


def test_crack_bars_are_exempt_from_the_horizontal_spacing_check():
    text = _text(ui_report.crack_bars_lines(_inputs(), _geometry()))
    assert "EXEMPT from rev 2 section 6.2 spacing validation" in text


def test_a_free_end_crack_bar_stops_short_of_the_beam_end_and_warns():
    text = _text(ui_report.crack_bars_lines(
        _inputs(),
        _geometry(is_supported_start=False, support_width_start_mm=None,
                  support_cover_start_mm=None, l_mm=None)))
    assert "Start end: **UNSUPPORTED**" in text
    assert "terminating 25.0 mm short of the beam's own end" in text


# --- the shared end formatter ---------------------------------------------


def test_end_result_formatting_distinguishes_a_hooked_end_from_a_free_one():
    assert ui_report.format_end_result(344.0, 536.0) == "a=344.0 mm, b=536.0 mm"
    assert ui_report.format_end_result(880.0, None) == (
        "achieved=880.0 mm (no hook, unsupported)")


# --- the report is a formatter, not a second calculator -------------------


def test_the_report_agrees_with_the_plan_it_describes():
    """The rule #56 exists to enforce, checked by execution rather than by
    reading the source: every layer offset the report prints must be the
    one core_plan computes from the same inputs.
    """
    from rft.core import plan as core_plan

    text = _text(ui_report.main_bars_lines(_inputs(), _review(), _geometry()))
    layers = core_plan.face_layer_plans(
        True, H_MM, B_MM, 25.0, 25.0, 10.0, 16.0, 16.0, 3, 2)
    for layer in layers:
        assert "offset_{} = {:.1f} mm".format(
            layer.layer_n, layer.offset_mm) in text
        assert "v = {:.1f} mm".format(layer.v_mm) in text


def test_h_avail_agrees_with_the_plan_the_placer_executes():
    from rft.core import plan as core_plan

    offset_mm = core_plan.innermost_layer_offset_mm(25.0, 10.0, 16.0, 16.0, 2)
    crack = core_plan.crack_plan(
        H_MM, B_MM, 25.0, 10.0, 12.0, offset_mm, offset_mm, 200.0)
    text = _text(ui_report.crack_bars_lines(_inputs(), _geometry()))
    assert "H_avail = {:.1f} mm".format(crack.h_avail_mm) in text
    assert "n_crack_layers = {},".format(crack.n_layers) in text
    assert "actual_spacing = {:.1f} mm".format(crack.spacing_mm) in text
    assert "**Total crack/skin bar count = {}**".format(crack.n_layers * 2) in text
    for v_mm in crack.v_positions_mm:
        assert "{:.1f}".format(v_mm) in text


def test_every_report_input_field_is_actually_read():
    """A field carried into ReportInputs and never used is a field the
    engineer fills in that changes nothing -- the silent kind of dead
    input, since the report looks complete either way.
    """
    import io
    import os

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "RFT.lib", "rft", "ui", "report.py")
    source = io.open(path, encoding="utf-8").read()
    body = source[source.index("def derivation_lines"):]
    unread = [f for f in ui_report.ReportInputs._fields
              if "inputs.{}".format(f) not in body]
    assert not unread, (
        "these ReportInputs fields are never read by the report: %s" % unread)


@pytest.mark.parametrize("h_mm,expected", [(701.0, True), (700.0, False)])
def test_the_crack_trigger_stays_strict_in_the_derivation(h_mm, expected):
    """Section 5 is ``h > 700``, strict. The report only ever renders the
    crack section when the derivation says so, so the boundary is worth
    pinning where the decision is made.
    """
    review = _review(h_mm=h_mm)
    assert review.crack_bars.requested is expected
