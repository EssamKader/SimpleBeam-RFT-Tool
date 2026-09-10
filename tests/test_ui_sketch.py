# -*- coding: utf-8 -*-
"""#49 (U5) -- the live sketch's pure geometry (rft.ui.sketch).

Pinned against the same 300x900 verification beam tests/test_core_plan.py
uses: 25 mm cover, O10 stirrups, O16 mains, O12 crack bars, 400 mm supports,
6000 mm c/c span. Every shape asserted here traces to an rft.core.plan
value already pinned by test_core_plan.py -- A48 is checked here by
EXECUTION (a drawn shape's coordinate must equal the plan's own number),
not by reading the source and trusting it.
"""

import pytest

from rft.core import plan
from rft.core.anchorage import ClearanceResult
from rft.core.spacing import LayerSpacingResult
from rft.core.stirrups import centreline_leg_dimensions_mm, outer_leg_dimensions_mm
from rft.ui import sketch

B_MM, H_MM, COVER_MM = 300.0, 900.0, 25.0
STIRRUP_DIA_MM, BAR_DIA_MM, SPACER_DIA_MM, CRACK_DIA_MM = 10.0, 16.0, 16.0, 12.0
SUPPORT_HALF_WIDTH_MM = 200.0  # 400 mm supports, half-width offset
L_MM = 6000.0


def _face(is_top, layer_count=2, bar_count=3):
    return plan.face_plan(
        is_top, H_MM, B_MM, COVER_MM, COVER_MM, COVER_MM,
        STIRRUP_DIA_MM, BAR_DIA_MM, BAR_DIA_MM, SPACER_DIA_MM,
        bar_count, layer_count, 55.0 if not is_top else 60.0,
        True, 400.0, 40.0, True, 400.0, 40.0,
    )


def _all_styles(shapes):
    return set(s.style for s in shapes)


# --- cross-section -----------------------------------------------------------


def test_concrete_outline_matches_b_and_h():
    shapes = sketch.section_shapes(
        B_MM, H_MM, COVER_MM, COVER_MM, COVER_MM, COVER_MM, STIRRUP_DIA_MM
    )
    outline = [s for s in shapes if s.style == "concrete"][0]
    us = [u for u, _v in outline.points]
    vs = [v for _u, v in outline.points]
    assert max(us) - min(us) == pytest.approx(B_MM)
    assert max(vs) - min(vs) == pytest.approx(H_MM)


def test_stirrup_rectangles_come_from_the_core_not_reinvented():
    """A48: the centreline and outer rectangles drawn must equal what
    rft.core.stirrups itself returns for the same inputs -- never a
    second (b - 2*cover...) computed inside the sketch.
    """
    shapes = sketch.section_shapes(
        B_MM, H_MM, COVER_MM, COVER_MM, COVER_MM, COVER_MM, STIRRUP_DIA_MM
    )
    centre_w, centre_h = centreline_leg_dimensions_mm(B_MM, H_MM, COVER_MM, STIRRUP_DIA_MM)
    outer_w, outer_h = outer_leg_dimensions_mm(B_MM, H_MM, COVER_MM)

    centreline = [s for s in shapes if s.style == "stirrup"][0]
    outer = [s for s in shapes if s.style == "stirrup_outer"][0]
    us_c = [u for u, _v in centreline.points]
    vs_c = [v for _u, v in centreline.points]
    us_o = [u for u, _v in outer.points]
    vs_o = [v for _u, v in outer.points]
    assert max(us_c) - min(us_c) == pytest.approx(centre_w)
    assert max(vs_c) - min(vs_c) == pytest.approx(centre_h)
    assert max(us_o) - min(us_o) == pytest.approx(outer_w)
    assert max(vs_o) - min(vs_o) == pytest.approx(outer_h)


def test_layer_1_and_layer_2_offsets_land_at_the_right_v():
    """Pinned exactly as test_core_plan.py pins them: offset_1 = 43.0 mm,
    offset_2 = 75.0 mm, on the verification beam.
    """
    bottom = _face(False, layer_count=2).layers
    assert bottom[0].offset_mm == pytest.approx(43.0)
    assert bottom[1].offset_mm == pytest.approx(75.0)

    shapes = sketch.section_shapes(
        B_MM, H_MM, COVER_MM, COVER_MM, COVER_MM, COVER_MM, STIRRUP_DIA_MM,
        bottom_bar_dia_mm=BAR_DIA_MM, bottom_layers=bottom,
    )
    circles_v = sorted(set(s.v for s in shapes if s.style == "bar_main"))
    assert circles_v[0] == pytest.approx(-H_MM / 2.0 + 43.0)
    assert circles_v[1] == pytest.approx(-H_MM / 2.0 + 75.0)


def test_v_increases_upward_top_above_bottom():
    top = _face(True, layer_count=1).layers
    bottom = _face(False, layer_count=1).layers
    shapes = sketch.section_shapes(
        B_MM, H_MM, COVER_MM, COVER_MM, COVER_MM, COVER_MM, STIRRUP_DIA_MM,
        top_bar_dia_mm=BAR_DIA_MM, top_layers=top,
        bottom_bar_dia_mm=BAR_DIA_MM, bottom_layers=bottom,
    )
    top_v = [s.v for s in shapes if s.style == "bar_main" and s.v > 0]
    bottom_v = [s.v for s in shapes if s.style == "bar_main" and s.v < 0]
    assert top_v and bottom_v
    assert min(top_v) > max(bottom_v)


def test_a_drawn_bar_circle_equals_the_plan_value_it_came_from():
    """A48, checked by EXECUTION: every (u, v) drawn for a main bar must
    equal an entry in layer.u_positions_mm / layer.v_mm exactly -- not
    merely "close", since both numbers come from the identical plan
    object with no unit conversion in between.
    """
    bottom = _face(False, layer_count=2, bar_count=4).layers
    shapes = sketch.section_shapes(
        B_MM, H_MM, COVER_MM, COVER_MM, COVER_MM, COVER_MM, STIRRUP_DIA_MM,
        bottom_bar_dia_mm=BAR_DIA_MM, bottom_layers=bottom,
    )
    drawn = set(
        (s.u, s.v) for s in shapes if s.style == "bar_main"
    )
    expected = set(
        (u, layer.v_mm) for layer in bottom for u in layer.u_positions_mm
    )
    assert drawn == expected
    assert len(expected) == 8  # 2 layers x 4 bars


def test_compliance_colouring_differs_between_pass_and_fail():
    bottom = _face(False, layer_count=1, bar_count=3).layers
    passing = LayerSpacingResult(
        layer_index=1, bar_count=3, governing_min_mm=50.0,
        achieved_clear_mm=55.3, passes=True,
    )
    failing = LayerSpacingResult(
        layer_index=1, bar_count=3, governing_min_mm=50.0,
        achieved_clear_mm=41.0, passes=False,
    )
    pass_shapes = sketch.section_shapes(
        B_MM, H_MM, COVER_MM, COVER_MM, COVER_MM, COVER_MM, STIRRUP_DIA_MM,
        bottom_bar_dia_mm=BAR_DIA_MM, bottom_layers=bottom, bottom_spacing=[passing],
    )
    fail_shapes = sketch.section_shapes(
        B_MM, H_MM, COVER_MM, COVER_MM, COVER_MM, COVER_MM, STIRRUP_DIA_MM,
        bottom_bar_dia_mm=BAR_DIA_MM, bottom_layers=bottom, bottom_spacing=[failing],
    )
    assert "dimension_pass" in _all_styles(pass_shapes)
    assert "dimension_fail" not in _all_styles(pass_shapes)
    assert "dimension_fail" in _all_styles(fail_shapes)
    assert "dimension_pass" not in _all_styles(fail_shapes)


def test_single_bar_layer_draws_no_spacing_dimension():
    """achieved_clear_mm is None for a 1-bar layer (A43) -- no spacing
    question, so no dimension line/label at all, pass or fail.

    section_shapes never calls the corner-bar rule itself (A48 -- the
    caller supplies a ready-made LayerPlan), so a single-bar layer is
    expressed directly as a LayerPlan with one u position, sidestepping
    corner_bar_u_positions_mm's own bar_count >= 2 requirement (section
    6.1), which is a placement-side concern, not a drawing-side one.
    """
    one_bar_layer = plan.LayerPlan(layer_n=1, offset_mm=43.0, v_mm=-407.0, u_positions_mm=[0.0])
    result = LayerSpacingResult(
        layer_index=1, bar_count=1, governing_min_mm=50.0,
        achieved_clear_mm=None, passes=True,
    )
    shapes = sketch.section_shapes(
        B_MM, H_MM, COVER_MM, COVER_MM, COVER_MM, COVER_MM, STIRRUP_DIA_MM,
        bottom_bar_dia_mm=BAR_DIA_MM, bottom_layers=[one_bar_layer],
        bottom_spacing=[result],
    )
    assert "dimension_pass" not in _all_styles(shapes)
    assert "dimension_fail" not in _all_styles(shapes)
    assert "bar_main" in _all_styles(shapes)


def test_h_avail_crack_plan_spans_the_innermost_layers():
    """750.0 mm on the verification beam: two layers per face, innermost
    offset 75.0 mm each side, H_avail = 900 - 75 - 75 = 750.0 mm -- the
    same figure the caption must carry, sourced from CrackPlan.h_avail_mm.
    """
    offset_innermost = plan.innermost_layer_offset_mm(
        COVER_MM, STIRRUP_DIA_MM, BAR_DIA_MM, SPACER_DIA_MM, 2
    )
    assert offset_innermost == pytest.approx(75.0)
    crack_plan = plan.crack_plan(
        H_MM, B_MM, COVER_MM, STIRRUP_DIA_MM, CRACK_DIA_MM,
        offset_innermost, offset_innermost, 200.0,
    )
    assert crack_plan.h_avail_mm == pytest.approx(750.0)

    shapes = sketch.section_shapes(
        B_MM, H_MM, COVER_MM, COVER_MM, COVER_MM, COVER_MM, STIRRUP_DIA_MM,
        crack_dia_mm=CRACK_DIA_MM, crack_plan=crack_plan,
    )
    caption = [s for s in shapes if s.style == "caption"][0]
    assert "750.0" in caption.text

    top_limit = H_MM / 2.0 - offset_innermost
    btm_limit = -H_MM / 2.0 + offset_innermost
    crack_vs = [s.v for s in shapes if s.style == "bar_crack"]
    assert crack_vs
    for v in crack_vs:
        assert btm_limit < v < top_limit


def test_no_crack_plan_draws_no_crack_bars():
    shapes = sketch.section_shapes(
        B_MM, H_MM, COVER_MM, COVER_MM, COVER_MM, COVER_MM, STIRRUP_DIA_MM,
        crack_dia_mm=CRACK_DIA_MM, crack_plan=None,
    )
    assert "bar_crack" not in _all_styles(shapes)


# --- face-gap captions (issue #65, corrected rule) ---------------------------
#
# ``missing`` here is always what ``rft.ui.derivation.main_bar_face_gap``
# actually produces for a refusing face: a non-empty subset of
# {"bar type", "layer count"} -- never "bar count", since a gap only ever
# fires when the count IS present. ``()`` stands for every face that does
# NOT refuse: fully blank, fully filled, or a type/layers with no count
# (the #54 restored-beam state) -- all three must stay silent.


def test_missing_face_label_none_when_nothing_missing():
    assert sketch.missing_face_label("Top", ()) is None


def test_missing_face_label_names_face_and_both_missing_fields():
    label = sketch.missing_face_label("Bottom", ("bar type", "layer count"))
    assert label == "Bottom: no type/layers"


def test_missing_face_label_names_face_and_one_missing_field():
    label = sketch.missing_face_label("Top", ("bar type",))
    assert label == "Top: no type"


def test_missing_face_label_is_short():
    # Issue #62's budget: the longest label on this canvas is ~20-30
    # characters, not the Review tab's full sentence.
    label = sketch.missing_face_label("Bottom", ("bar type", "layer count"))
    assert len(label) <= 30


def test_section_shapes_draws_no_caption_for_a_face_that_does_not_refuse():
    # #65's corrected rule: a face with () passed (blank, filled, or the
    # #54 restored-but-uncounted state) must stay silent.
    shapes = sketch.section_shapes(
        B_MM, H_MM, COVER_MM, COVER_MM, COVER_MM, COVER_MM, STIRRUP_DIA_MM,
        top_missing=(), bottom_missing=(),
    )
    assert "caption" not in _all_styles(shapes)


def test_section_shapes_draws_a_caption_for_a_refusing_face():
    shapes = sketch.section_shapes(
        B_MM, H_MM, COVER_MM, COVER_MM, COVER_MM, COVER_MM, STIRRUP_DIA_MM,
        bottom_missing=("bar type", "layer count"),
    )
    captions = [s for s in shapes if s.style == "caption"]
    assert len(captions) == 1
    assert captions[0].text == "Bottom: no type/layers"


def test_section_shapes_refusing_captions_are_independent_per_face():
    shapes = sketch.section_shapes(
        B_MM, H_MM, COVER_MM, COVER_MM, COVER_MM, COVER_MM, STIRRUP_DIA_MM,
        top_missing=("layer count",), bottom_missing=("bar type",),
    )
    captions = sorted(s.text for s in shapes if s.style == "caption")
    assert captions == ["Bottom: no type", "Top: no layers"]


def test_spacer_bar_spans_between_the_two_stacked_layers():
    bottom = _face(False, layer_count=2).layers
    from rft.core.layout import spacer_length_mm
    length_mm = spacer_length_mm(B_MM, COVER_MM, STIRRUP_DIA_MM)
    shapes = sketch.section_shapes(
        B_MM, H_MM, COVER_MM, COVER_MM, COVER_MM, COVER_MM, STIRRUP_DIA_MM,
        bottom_bar_dia_mm=BAR_DIA_MM, bottom_layers=bottom,
        spacer_length_mm=length_mm,
    )
    spacer = [s for s in shapes if s.style == "spacer"][0]
    assert abs(spacer.u2 - spacer.u1) == pytest.approx(length_mm)
    assert spacer.v1 == pytest.approx((bottom[0].v_mm + bottom[1].v_mm) / 2.0)


def test_every_emitted_style_is_in_the_closed_set():
    bottom = _face(False, layer_count=2, bar_count=3).layers
    top = _face(True, layer_count=1, bar_count=2).layers
    shapes = sketch.section_shapes(
        B_MM, H_MM, COVER_MM, COVER_MM, COVER_MM, COVER_MM, STIRRUP_DIA_MM,
        top_bar_dia_mm=BAR_DIA_MM, top_layers=top,
        bottom_bar_dia_mm=BAR_DIA_MM, bottom_layers=bottom,
    )
    assert _all_styles(shapes) <= sketch.STYLE_KEYS


# --- longitudinal elevation ---------------------------------------------------


def test_span_dimension_matches_l_mm():
    shapes = sketch.elevation_shapes(L_MM, 400.0, 400.0, H_MM)
    outline = [s for s in shapes if s.style == "concrete"][0]
    us = [u for u, _v in outline.points]
    assert max(us) - min(us) == pytest.approx(L_MM)
    dim_text = [
        s for s in shapes
        if s.style == "dimension" and isinstance(s, sketch.SketchText) and "L (c/c)" in s.text
    ][0]
    assert "6000.0" in dim_text.text


def test_stirrup_zone_bands_use_the_plans_own_boundaries():
    stirrups = plan.stirrup_plan(
        L_MM, B_MM, H_MM, COVER_MM, STIRRUP_DIA_MM, 1, 150.0, 200.0,
        SUPPORT_HALF_WIDTH_MM, SUPPORT_HALF_WIDTH_MM,
    )
    shapes = sketch.elevation_shapes(
        L_MM, 400.0, 400.0, H_MM, stirrup_plan=stirrups,
    )
    zone_polys = {
        "zone_dense": [
            s for s in shapes
            if s.style == "zone_dense" and isinstance(s, sketch.SketchPolygon)
        ],
        "zone_normal": [
            s for s in shapes
            if s.style == "zone_normal" and isinstance(s, sketch.SketchPolygon)
        ],
    }
    assert len(zone_polys["zone_dense"]) == 2  # zone1, zone3
    assert len(zone_polys["zone_normal"]) == 1  # zone2

    zone1 = stirrups.zones[0]
    band = [
        s for s in zone_polys["zone_dense"]
        if min(u for u, _v in s.points) == pytest.approx(zone1.zone.start)
    ]
    assert band
    us = [u for u, _v in band[0].points]
    assert max(us) == pytest.approx(zone1.zone.end)


def test_schematic_tick_positions_are_capped():
    """A wide dense zone can imply far more stations than are legible to
    draw; the cap must fire, and the true count (not the drawn tick
    count) is still what the "n @ s" text label states.
    """
    ticks = sketch._schematic_tick_positions_mm(0.0, 10000.0, 500)
    assert len(ticks) == sketch.MAX_SCHEMATIC_TICKS_PER_ZONE
    assert min(ticks) == pytest.approx(0.0)
    assert max(ticks) == pytest.approx(10000.0)


def test_schematic_ticks_are_drawn_and_labelled_schematic():
    stirrups = plan.stirrup_plan(
        L_MM, B_MM, H_MM, COVER_MM, STIRRUP_DIA_MM, 1, 150.0, 200.0,
        SUPPORT_HALF_WIDTH_MM, SUPPORT_HALF_WIDTH_MM,
    )
    shapes = sketch.elevation_shapes(
        L_MM, 400.0, 400.0, H_MM, stirrup_plan=stirrups,
    )
    ticks = [s for s in shapes if s.style == "schematic" and isinstance(s, sketch.SketchLine)]
    total_true_count = sum(z.count for z in stirrups.zones)
    assert 0 < len(ticks) <= min(
        total_true_count, 3 * sketch.MAX_SCHEMATIC_TICKS_PER_ZONE
    )
    caption = [
        s for s in shapes
        if s.style == "schematic" and isinstance(s, sketch.SketchText) and "SCHEMATIC" in s.text
    ]
    assert caption


def test_anchorage_dimensions_come_from_the_end_plan_exactly():
    face = _face(False, layer_count=1, bar_count=2)
    shapes = sketch.elevation_shapes(
        L_MM, 400.0, 400.0, H_MM,
        bottom_end_start=face.start_end, bottom_end_end=face.end_end,
    )
    labels = [
        s.text for s in shapes
        if s.style == "dimension" and isinstance(s, sketch.SketchText) and "a=" in s.text
    ]
    assert labels
    assert "{:.1f}".format(face.start_end.a_mm) in labels[0]
    assert "{:.1f}".format(face.start_end.b_mm) in labels[0]


def test_a_refused_end_draws_no_bar_segment_and_does_not_crash():
    """The exact defect found in the initial draft: a refused EndPlan has
    a_mm/b_mm both None, and a naive "{:.1f}".format(None) raises
    TypeError.

    Updated by #62. This used to require the plan's FULL refusal text on
    the drawing. A51's reason is four sentences; drawn across the beam it
    was unreadable and buried the drawing it was annotating. The sketch
    now says which face, which end, and that it is refused -- and points
    at the Review tab, which states the reason in full and is tested for
    that in tests/test_ui_report.py.
    """
    refused = plan.face_plan(
        True, H_MM, B_MM, COVER_MM, COVER_MM, COVER_MM,
        STIRRUP_DIA_MM, BAR_DIA_MM, None, SPACER_DIA_MM, 3, 1, 60.0,
        True, 400.0, 40.0, True, 400.0, 40.0,
    )
    assert refused.start_end.refused_reason is not None

    shapes = sketch.elevation_shapes(
        L_MM, 400.0, 400.0, H_MM,
        top_end_start=refused.start_end, top_end_end=refused.end_end,
    )
    assert not [s for s in shapes if s.style == "bar_main"]
    captions = [s for s in shapes if s.style == "dimension_fail"]
    assert captions, "a refused end must still be announced on the drawing"

    text = " ".join(c.text for c in captions)
    assert "REFUSED" in text
    assert "Top" in text                    # which face
    assert "start" in text                  # which end
    assert "Review" in text                 # where the full reason is

    # The point of the change: no caption is a paragraph any more.
    for caption in captions:
        assert len(caption.text) <= 60, (
            "in-canvas label is %d characters -- prose belongs in the "
            "caption under the canvas (#62): %r"
            % (len(caption.text), caption.text)
        )


def test_crack_bar_line_present_only_when_crack_plan_given():
    with_crack = sketch.elevation_shapes(
        L_MM, 400.0, 400.0, H_MM,
        crack_plan=plan.crack_plan(
            H_MM, B_MM, COVER_MM, STIRRUP_DIA_MM, CRACK_DIA_MM, 75.0, 75.0, 200.0
        ),
    )
    without_crack = sketch.elevation_shapes(L_MM, 400.0, 400.0, H_MM)
    assert "bar_crack" in _all_styles(with_crack)
    assert "bar_crack" not in _all_styles(without_crack)


def test_a7_clearance_colouring_differs_pass_vs_fail():
    passing = ClearanceResult(achieved_mm=16.0, required_mm=14.0, ok=True)
    failing = ClearanceResult(achieved_mm=16.0, required_mm=20.5, ok=False)
    pass_shapes = sketch.elevation_shapes(
        L_MM, 400.0, 400.0, H_MM, clearance_start=passing,
    )
    fail_shapes = sketch.elevation_shapes(
        L_MM, 400.0, 400.0, H_MM, clearance_start=failing,
    )
    assert "dimension_pass" in _all_styles(pass_shapes)
    assert "dimension_fail" in _all_styles(fail_shapes)


def test_no_clearance_given_draws_no_clearance_dimension():
    shapes = sketch.elevation_shapes(L_MM, 400.0, 400.0, H_MM)
    assert "dimension_pass" not in _all_styles(shapes)
    assert "dimension_fail" not in _all_styles(shapes)


def test_every_emitted_elevation_style_is_in_the_closed_set():
    face = _face(False, layer_count=1, bar_count=2)
    stirrups = plan.stirrup_plan(
        L_MM, B_MM, H_MM, COVER_MM, STIRRUP_DIA_MM, 1, 150.0, 200.0,
        SUPPORT_HALF_WIDTH_MM, SUPPORT_HALF_WIDTH_MM,
    )
    shapes = sketch.elevation_shapes(
        L_MM, 400.0, 400.0, H_MM,
        bottom_end_start=face.start_end, bottom_end_end=face.end_end,
        stirrup_plan=stirrups,
        clearance_start=ClearanceResult(16.0, 14.0, True),
        crack_plan=plan.crack_plan(
            H_MM, B_MM, COVER_MM, STIRRUP_DIA_MM, CRACK_DIA_MM, 75.0, 75.0, 200.0
        ),
    )
    assert _all_styles(shapes) <= sketch.STYLE_KEYS


# --- hook detail ---------------------------------------------------------


def test_hook_detail_leg_length_scales_and_labels_the_angle():
    shapes = sketch.hook_detail_shapes(75.0, 135.0, scale=2.0)
    lines = [s for s in shapes if isinstance(s, sketch.SketchLine)]
    # p0 to p1 is a vertical leg of length 2*leg_mm = 2*75*2 = 300.
    leg = lines[0]
    assert abs(leg.v2 - leg.v1) == pytest.approx(2 * 75.0 * 2.0)
    caption = [s for s in shapes if isinstance(s, sketch.SketchText)][0]
    assert "135.0" in caption.text
    assert "75.0" in caption.text
    assert "SCHEMATIC" in caption.text


# --- #62: labels, not prose ------------------------------------------------

MAX_LABEL_CHARS = 46


def _every_label_the_sketch_can_draw():
    """Every SketchText the three views produce, across the awkward cases
    as well as the happy one -- a refused end, a failing spacing, an
    unsupported end -- since those are where the long strings lived.
    """
    from rft.core.spacing import governing_min_spacing_mm, validate_face_spacing

    labels = []

    top = plan.face_layer_plans(
        True, H_MM, B_MM, COVER_MM, COVER_MM, STIRRUP_DIA_MM,
        BAR_DIA_MM, SPACER_DIA_MM, 3, 2)
    btm = plan.face_layer_plans(
        False, H_MM, B_MM, COVER_MM, COVER_MM, STIRRUP_DIA_MM,
        BAR_DIA_MM, SPACER_DIA_MM, 3, 2)
    gov = governing_min_spacing_mm(BAR_DIA_MM, 20.0, None)
    passing = validate_face_spacing(
        "Top face", 2, [3, 3], B_MM, COVER_MM, STIRRUP_DIA_MM, BAR_DIA_MM, gov)
    failing = validate_face_spacing(
        "Top face", 2, [9, 9], B_MM, COVER_MM, STIRRUP_DIA_MM, BAR_DIA_MM, gov)
    crack = plan.crack_plan(
        H_MM, B_MM, COVER_MM, STIRRUP_DIA_MM, CRACK_DIA_MM, 75.0, 75.0, 200.0)

    for spacing in (passing.layer_results, failing.layer_results):
        labels += [
            s for s in sketch.section_shapes(
                b_mm=B_MM, h_mm=H_MM, cover_top_mm=COVER_MM,
                cover_btm_mm=COVER_MM, cover_side_mm=COVER_MM,
                stirrup_cover_mm=COVER_MM, stirrup_dia_mm=STIRRUP_DIA_MM,
                top_bar_dia_mm=BAR_DIA_MM, top_layers=top, top_spacing=spacing,
                bottom_bar_dia_mm=BAR_DIA_MM, bottom_layers=btm,
                crack_dia_mm=CRACK_DIA_MM, crack_plan=crack,
            )
            if isinstance(s, sketch.SketchText)
        ]

    supported = plan.face_plan(
        True, H_MM, B_MM, COVER_MM, COVER_MM, COVER_MM, STIRRUP_DIA_MM,
        BAR_DIA_MM, BAR_DIA_MM, SPACER_DIA_MM, 3, 2, 60.0,
        True, 400.0, 40.0, True, 400.0, 40.0)
    refused = plan.face_plan(
        True, H_MM, B_MM, COVER_MM, COVER_MM, COVER_MM, STIRRUP_DIA_MM,
        BAR_DIA_MM, None, SPACER_DIA_MM, 3, 2, 60.0,
        True, 400.0, 40.0, True, 400.0, 40.0)
    stirrups = plan.stirrup_plan(
        L_MM, B_MM, H_MM, COVER_MM, STIRRUP_DIA_MM, 1, 150.0, 200.0, 200.0, 200.0)

    for face in (supported, refused):
        labels += [
            s for s in sketch.elevation_shapes(
                L_MM, 400.0, 400.0, H_MM,
                top_end_start=face.start_end, top_end_end=face.end_end,
                stirrup_plan=stirrups, crack_plan=crack,
            )
            if isinstance(s, sketch.SketchText)
        ]

    labels += [s for s in sketch.hook_detail_shapes(135.0, 75.0)
               if isinstance(s, sketch.SketchText)]
    return labels


def test_no_label_drawn_inside_a_canvas_is_prose():
    """#62, generalised past the four strings that were actually wrong.

    On the first live run of v0.3.0-rc1 a 105-character sentence was drawn
    across the middle of the elevation, colliding with two zone labels and
    running off the right edge mid-word. Three others were long enough to
    clip. rft.ui.sketch_layout guarantees a label is never CUT OFF and
    never OVERLAPS -- but it does that by moving labels, and a paragraph
    that has been moved is still a paragraph lying across a drawing.

    So the length is capped here, at the source. A drawing carries labels;
    the explanation goes in the caption under the canvas, where there is
    room for a sentence and nothing to collide with.
    """
    too_long = [
        (len(s.text), s.text) for s in _every_label_the_sketch_can_draw()
        if len(s.text) > MAX_LABEL_CHARS
    ]
    assert not too_long, (
        "these in-canvas labels are longer than %d characters, which is "
        "prose rather than a label: %s" % (MAX_LABEL_CHARS, too_long)
    )


def test_the_schematic_elements_are_still_marked_schematic_on_the_drawing():
    """#49's acceptance criterion, which #62 must not quietly trade away.

    Shortening the schematic notes to fit is right; deleting the word
    would swap one ticket's requirement for another's. The marker stays on
    the drawing, the explanation moves to the caption.
    """
    labels = _every_label_the_sketch_can_draw()
    marked = [s.text for s in labels if "SCHEMATIC" in s.text.upper()]
    assert marked, (
        "nothing on the drawing says which elements are schematic any "
        "more -- #49 requires that labelling to be ON the drawing"
    )
    assert any("tick" in t.lower() for t in marked), marked
    assert any("bend" in t.lower() for t in marked), marked
