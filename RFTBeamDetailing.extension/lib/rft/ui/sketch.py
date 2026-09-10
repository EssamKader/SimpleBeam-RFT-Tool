# -*- coding: utf-8 -*-
"""Live sketch geometry: cross-section and longitudinal elevation (issue
#49, U5), following docs/ui/sketch-notation.svg.

PURE MODULE (A48). No ``pyrevit`` import, no ``Autodesk`` import, no WPF
import -- this file must be importable under plain CPython, which is the
only way any of it can be tested (CONTEXT.md's Revit-free core rule).
It takes plain numbers plus ``rft.core.plan`` objects (``LayerPlan``,
``EndPlan``, ``StirrupPlan``, ``CrackPlan`` -- the SAME plan objects the
report and the placer already consume, per issue #56) and returns a plain
list of shape namedtuples, in millimetres, in the shared section-local
(u, v) frame: origin at the section centroid, ``u`` positive right, ``v``
positive UP (matching ``rft.core.layout``/``stirrups``/``crack_bars`` and
the #42 spike's ``translate(cx,cy) scale(s,-s)`` convention).

WHAT THIS MODULE DOES NOT DO. It composes and positions; it does not
derive a detailing value that ``rft.core`` does not already expose (A48).
Every offset, spacing, zone boundary, anchorage length and H_avail drawn
here is read off a plan object or a plain already-known input (``b``,
``h``, a cover, a diameter) -- never recomputed. The one arithmetic
operation performed directly here is a bar's drawn RADIUS
(``diameter / 2.0``), which is not a detailing rule -- it is what "draw
this diameter as a circle" means for any diameter, in the same way a line
needs two endpoints. Assembling a rectangle's four corners from a width
and a height that ``rft.core.stirrups`` already returned is likewise
positioning, not a new rule.

STYLE KEYS (never WPF brushes -- ``script.py``'s renderer maps these to
the XAML palette). See ``STYLE_KEYS`` below for the closed set.

TWO SCHEMATIC ELEMENTS, PER A48/A49: individual stirrup stations (drawn as
evenly spaced ticks labelled ``n @ s``, style "schematic" -- the count and
spacing are exact, from ``StirrupCount``; the individual positions are
Revit's own rebar-set layout, never predicted here) and the hook bend arc
(drawn as a straight angle and leg length, both exact, never a fillet --
the bend radius belongs to the ``RebarBarType``). Both are labelled
schematic in the shapes this module returns, and ``script.py`` must not
strip that labelling when it renders them.

A REFUSED END (``EndPlan.refused_reason`` set, e.g. A51's missing-opposite-
diameter case) has ``a_mm``/``b_mm`` both ``None`` -- there is no anchorage
to draw. ``elevation_shapes`` must not, and does not, try to format a
``None`` into a dimension: a refused end draws no bar segment and no hook,
only a caption carrying the plan's own refusal text (never a re-worded
one). A draft of this module skipped that check and would have raised
``TypeError`` from ``"{:.1f}".format(None)`` the first time a half-typed
Beam & Materials selection reached the sketch -- exactly the "half-typed
input must not kill the window" case this ticket's acceptance criteria
name.

Python 2/3 compatible: IronPython 2.7 is the runtime that loads this
module in production, alongside ``script.py`` (``tests/test_ironpython_
compat.py`` enforces the language constraints -- no f-strings, PEP 263
cookie above).
"""

from collections import namedtuple

from rft.core.stirrups import centreline_leg_dimensions_mm, outer_leg_dimensions_mm

# --- the shape vocabulary ----------------------------------------------------

SketchLine = namedtuple("SketchLine", ["u1", "v1", "u2", "v2", "style"])
SketchCircle = namedtuple("SketchCircle", ["u", "v", "r", "style"])
SketchText = namedtuple("SketchText", ["u", "v", "text", "style"])
# ``points`` is a list of (u, v) pairs, implicitly closed (first and last
# points are joined) -- matching WPF ``Polygon``, which closes itself.
SketchPolygon = namedtuple("SketchPolygon", ["points", "style"])

# The closed set of style keys this module ever emits. ``script.py``'s
# renderer must declare a brush mapping for every one of these (a text
# guard in tests/test_detail_beam_xaml.py checks this both ways), so a new
# style key added here without a matching renderer entry fails loudly
# instead of drawing invisible (default-black-on-white) shapes on a live
# host that nothing here can execute to notice.
STYLE_KEYS = frozenset([
    "concrete",          # the beam's own outline (b x h)
    "cover",              # the cover line, one face's own cover at a time
    "stirrup",            # the stirrup centreline rectangle / loop (§7.1, A30)
    "stirrup_outer",      # the stirrup OUTER rectangle (§7.1, A30, Gap 1)
    "bar_main",           # a main (top/bottom) bar, drawn as a circle
    "bar_crack",          # a crack/skin bar, circle (section) or line (elevation)
    "spacer",             # the spacer bar between two stacked layers (§6.3)
    "dimension",          # a neutral dimension/label (L, a, b, zone names)
    "dimension_pass",     # a dimension that complies (LayerSpacingResult.passes /
                          # ClearanceResult.ok)
    "dimension_fail",     # a dimension that violates
    "schematic",          # the two schematic elements (A48/A49): stirrup
                          # ticks and the hook bend arc
    "zone_dense",         # a dense stirrup zone band (zone 1 / zone 3)
    "zone_normal",        # the normal stirrup zone band (zone 2)
    "support",            # a supporting element, hatched, in elevation
    "caption",            # explanatory text, no compliance meaning
])


def _rect_points(width_mm, height_mm, cu_mm=0.0, cv_mm=0.0):
    """The four corners of a ``width_mm`` x ``height_mm`` rectangle
    centred at ``(cu_mm, cv_mm)``, in a fixed winding order.
    """
    hw = width_mm / 2.0
    hh = height_mm / 2.0
    return [
        (cu_mm - hw, cv_mm - hh), (cu_mm + hw, cv_mm - hh),
        (cu_mm + hw, cv_mm + hh), (cu_mm - hw, cv_mm + hh),
    ]


# --- 1: cross-section --------------------------------------------------------


def section_shapes(b_mm, h_mm, cover_top_mm, cover_btm_mm, cover_side_mm,
                    stirrup_cover_mm, stirrup_dia_mm,
                    top_bar_dia_mm=None, top_layers=None, top_spacing=None,
                    bottom_bar_dia_mm=None, bottom_layers=None, bottom_spacing=None,
                    spacer_length_mm=None,
                    crack_dia_mm=None, crack_plan=None):
    """Every drawn element of the cross-section (docs/ui/sketch-notation.svg
    section 1), true scale, at the section centroid.

    ``b_mm``/``h_mm`` and the four covers are already-read model values
    (``rft.revit.geometry.beam_section_dimensions_mm`` /
    ``rft.revit.host.read_beam_face_covers_mm``), positioned directly --
    not detailing arithmetic (A48's note above).

    ``stirrup_cover_mm`` is the SAME single cover value
    ``rft.core.plan.stirrup_plan`` is called with (today, the beam's own
    top cover -- see ``script.py``), reused here rather than re-derived,
    so the stirrup rectangle drawn matches the one actually placed.

    ``top_layers``/``bottom_layers`` are lists of ``rft.core.plan.
    LayerPlan`` (or ``None``/empty when that face is not detailed/placed).
    ``top_spacing``/``bottom_spacing`` are the matching lists of
    ``rft.core.spacing.LayerSpacingResult``, index-aligned with the layers
    list, or ``None`` when spacing was not validated (e.g. a single-bar
    layer, or the face is not requested) -- see
    ``rft.core.spacing.validate_face_spacing``.

    ``spacer_length_mm`` is ``rft.core.layout.spacer_length_mm``'s own
    return value, computed by the caller and handed in unchanged (A48):
    this module never calls ``b - 2*cover - 2*O_stirrup`` itself.

    ``crack_plan`` is an ``rft.core.plan.CrackPlan``, or ``None`` when
    crack bars are not requested/triggered (A50).
    """
    shapes = []
    half_b, half_h = b_mm / 2.0, h_mm / 2.0

    # 1: concrete outline, b x h (read from the model, section 1).
    shapes.append(SketchPolygon(_rect_points(b_mm, h_mm), "concrete"))

    # 2: cover line -- each face's OWN cover (section 1.1), never averaged
    # or assumed equal between faces.
    cover_left_mm = -half_b + cover_side_mm
    cover_right_mm = half_b - cover_side_mm
    cover_bottom_mm = -half_h + cover_btm_mm
    cover_top_v_mm = half_h - cover_top_mm
    shapes.append(SketchPolygon(
        [(cover_left_mm, cover_bottom_mm), (cover_right_mm, cover_bottom_mm),
         (cover_right_mm, cover_top_v_mm), (cover_left_mm, cover_top_v_mm)],
        "cover",
    ))

    # 3: stirrup rectangles (section 7.1, A30) -- both the CENTRELINE loop
    # (what Rebar.CreateFromCurves receives) and the OUTER rectangle (Gap
    # 1, why outer_leg_dimensions_mm exists at all: the sketch draws it,
    # placement never does).
    centre_w_mm, centre_h_mm = centreline_leg_dimensions_mm(
        b_mm, h_mm, stirrup_cover_mm, stirrup_dia_mm
    )
    shapes.append(SketchPolygon(_rect_points(centre_w_mm, centre_h_mm), "stirrup"))
    outer_w_mm, outer_h_mm = outer_leg_dimensions_mm(b_mm, h_mm, stirrup_cover_mm)
    shapes.append(SketchPolygon(_rect_points(outer_w_mm, outer_h_mm), "stirrup_outer"))

    # 4: main bars, one circle per bar -- position IS the plan's own
    # (layer.u_positions_mm, layer.v_mm), never recomputed (A48). Coloured
    # by compliance via a dimension line/label per layer, from
    # LayerSpacingResult.passes -- the story's real value (#49's brief).
    for is_top, bar_dia_mm, layers, spacing_results in (
        (True, top_bar_dia_mm, top_layers, top_spacing),
        (False, bottom_bar_dia_mm, bottom_layers, bottom_spacing),
    ):
        if not layers:
            continue
        r_mm = bar_dia_mm / 2.0
        results = spacing_results if spacing_results is not None else [None] * len(layers)
        for layer, spacing_result in zip(layers, results):
            for u_mm in layer.u_positions_mm:
                shapes.append(SketchCircle(u_mm, layer.v_mm, r_mm, "bar_main"))
            if (spacing_result is not None
                    and spacing_result.achieved_clear_mm is not None):
                style = "dimension_pass" if spacing_result.passes else "dimension_fail"
                u0_mm = layer.u_positions_mm[0]
                u1_mm = layer.u_positions_mm[1]
                sign = 1.0 if is_top else -1.0
                v_dim_mm = layer.v_mm + sign * (r_mm + 8.0)
                shapes.append(SketchLine(u0_mm, v_dim_mm, u1_mm, v_dim_mm, style))
                shapes.append(SketchText(
                    (u0_mm + u1_mm) / 2.0, v_dim_mm,
                    "{:.1f} mm ({}), min {:.1f} mm".format(
                        spacing_result.achieved_clear_mm,
                        "PASS" if spacing_result.passes else "FAIL",
                        spacing_result.governing_min_mm,
                    ),
                    style,
                ))

    # 5: spacer bar, between the first two stacked layers of a face that
    # has 2+ layers (section 6.3) -- length is the caller-supplied
    # ``spacer_length_mm`` (``rft.core.layout.spacer_length_mm``),
    # position is the midpoint between the two layers' own v (already
    # computed by the plan).
    if spacer_length_mm is not None:
        for layers in (top_layers, bottom_layers):
            if layers and len(layers) >= 2:
                v_mid_mm = (layers[0].v_mm + layers[1].v_mm) / 2.0
                shapes.append(SketchLine(
                    -spacer_length_mm / 2.0, v_mid_mm,
                    spacer_length_mm / 2.0, v_mid_mm, "spacer",
                ))

    # 6: crack/skin bars (section 5), present only when both faces are
    # detailed and h > 700 (A50) -- caller passes crack_plan=None
    # otherwise, and this function draws nothing for them.
    if crack_plan is not None:
        r_crack_mm = crack_dia_mm / 2.0
        u_left_mm, u_right_mm = crack_plan.u_positions_mm
        for v_mm in crack_plan.v_positions_mm:
            shapes.append(SketchCircle(u_left_mm, v_mm, r_crack_mm, "bar_crack"))
            shapes.append(SketchCircle(u_right_mm, v_mm, r_crack_mm, "bar_crack"))
        shapes.append(SketchText(
            0.0, half_h + 24.0,
            "H_avail = {:.1f} mm, {} @ {:.1f} mm".format(
                crack_plan.h_avail_mm, crack_plan.n_layers,
                crack_plan.spacing_mm,
            ),
            "caption",
        ))

    return shapes


# --- 2: longitudinal elevation -----------------------------------------------

# Fixed cap on how many schematic stirrup ticks are drawn per zone. A wide
# zone with dense spacing can imply dozens of stations; the ticks are
# already labelled schematic (A48/A49), so drawing every one buys nothing
# and can make the canvas unreadable. The exact count is stated in the
# "n @ s" label regardless of how many ticks are actually drawn.
# #62: was 24. Three zones of up to 24 ticks merged into a solid
# hatch on a 9.6 m beam, hiding the bar runs behind them. Eight is
# enough to read as "evenly spaced" -- which is all these claim to
# be, since the true stations belong to Revit's rebar set and the
# exact count and spacing are stated in the zone's own label.
MAX_SCHEMATIC_TICKS_PER_ZONE = 8


def _schematic_tick_positions_mm(zone_start_mm, zone_end_mm, count):
    """``count`` evenly spaced u positions across [start, end], capped at
    ``MAX_SCHEMATIC_TICKS_PER_ZONE`` -- SCHEMATIC (A48/A49): these are
    NOT the stations Revit's rebar set will actually place. Only the
    zone's true start/end and the true count/spacing (drawn separately,
    as text) are exact.
    """
    n = max(1, min(count, MAX_SCHEMATIC_TICKS_PER_ZONE))
    if n == 1:
        return [(zone_start_mm + zone_end_mm) / 2.0]
    step = (zone_end_mm - zone_start_mm) / float(n - 1)
    return [zone_start_mm + i * step for i in range(n)]


def elevation_shapes(l_mm, support_width_start_mm, support_width_end_mm, h_mm,
                      top_end_start=None, top_end_end=None,
                      bottom_end_start=None, bottom_end_end=None,
                      stirrup_plan=None,
                      clearance_start=None, clearance_end=None,
                      crack_plan=None):
    """Every drawn element of the longitudinal elevation
    (docs/ui/sketch-notation.svg section 2).

    ``u`` runs 0..``l_mm`` along the support-centreline-to-support-
    centreline datum ``rft.core.stirrups.stirrup_zones_mm`` already uses
    (support A's centreline at u=0); ``v`` is the same centroid-local
    frame as the section view, ``h_mm`` giving the beam's own true depth
    for the outline -- the RENDERER may scale ``u`` and ``v`` by
    different factors to keep the anchorage legible on a long span (the
    notation SVG does the same, stating so on its own face); that is a
    rendering choice, not a second detailing rule.

    ``top_end_start``/``top_end_end``/``bottom_end_start``/
    ``bottom_end_end`` are ``rft.core.plan.EndPlan`` (or ``None`` when
    that face is not requested). A refused end (``refused_reason`` set)
    draws no bar segment and no hook for that FACE -- both ends, since a
    segment needs two known endpoints -- only a caption carrying the
    plan's own refusal text. ``stirrup_plan`` is an
    ``rft.core.plan.StirrupPlan`` (or ``None`` when stirrups are not
    requested/computable). ``clearance_start``/``clearance_end`` are
    ``rft.core.anchorage.ClearanceResult`` (``placed_clearance_mm``, A7),
    or ``None`` when only one face is placed (A51) and no clearance
    exists to check.
    """
    shapes = []
    half_h_mm = h_mm / 2.0

    # 1: beam outline, true length and depth.
    shapes.append(SketchPolygon(
        [(0.0, -half_h_mm), (l_mm, -half_h_mm), (l_mm, half_h_mm), (0.0, half_h_mm)],
        "concrete",
    ))

    # 2: supports, hatched, centred on their own centreline (u=0, u=l_mm --
    # the same c/c datum stirrup_zones_mm uses).
    support_depth_mm = half_h_mm * 0.6
    shapes.append(SketchPolygon(
        _rect_points(support_width_start_mm, support_depth_mm,
                     cu_mm=0.0, cv_mm=-half_h_mm - support_depth_mm / 2.0),
        "support",
    ))
    shapes.append(SketchPolygon(
        _rect_points(support_width_end_mm, support_depth_mm,
                     cu_mm=l_mm, cv_mm=-half_h_mm - support_depth_mm / 2.0),
        "support",
    ))

    # 3: span dimension, exact (L, c/c).
    shapes.append(SketchLine(0.0, -half_h_mm - support_depth_mm - 20.0,
                             l_mm, -half_h_mm - support_depth_mm - 20.0, "dimension"))
    shapes.append(SketchText(l_mm / 2.0, -half_h_mm - support_depth_mm - 34.0,
                             "L (c/c) = {:.1f} mm".format(l_mm), "dimension"))

    # 4: three stirrup zones (section 3.1) -- TRUE boundaries, TRUE count
    # and spacing, from stirrup_plan.zones (rft.core.plan.stirrup_plan).
    # Individual stations inside a zone are SCHEMATIC (A48/A49): see
    # ``_schematic_tick_positions_mm``.
    if stirrup_plan is not None:
        band_bottom_mm = -half_h_mm - 6.0 - 16.0
        for zone_plan in stirrup_plan.zones:
            style = "zone_dense" if zone_plan.name in ("zone1", "zone3") else "zone_normal"
            band_top_mm = -half_h_mm - 6.0
            band_bottom_mm = band_top_mm - 16.0
            shapes.append(SketchPolygon(
                [(zone_plan.zone.start, band_bottom_mm), (zone_plan.zone.end, band_bottom_mm),
                 (zone_plan.zone.end, band_top_mm), (zone_plan.zone.start, band_top_mm)],
                style,
            ))
            shapes.append(SketchText(
                (zone_plan.zone.start + zone_plan.zone.end) / 2.0,
                (band_top_mm + band_bottom_mm) / 2.0,
                "{}: {} @ {:.1f} mm".format(zone_plan.name, zone_plan.count, zone_plan.spacing_mm),
                style,
            ))
            for u_tick_mm in _schematic_tick_positions_mm(
                    zone_plan.zone.start, zone_plan.zone.end, zone_plan.count):
                shapes.append(SketchLine(
                    u_tick_mm, -half_h_mm, u_tick_mm, half_h_mm, "schematic"
                ))
        # #62: this was a 105-character sentence across the middle of
        # the elevation -- "stirrup stations are SCHEMATIC, count and
        # spacing are exact, positions are laid out by Revit's rebar
        # set". It collided with two zone labels and ran off the right
        # edge mid-word.
        #
        # It is now a marker, not a sentence. #49's acceptance criterion
        # requires the schematic elements to be labelled AS schematic ON
        # THE DRAWING, so the word stays; the explanation of WHY they are
        # schematic moves to the caption under the canvas, which already
        # carried it. Deleting the marker outright would have traded one
        # ticket's requirement for another's.
        shapes.append(SketchText(
            stirrup_plan.zones[0].zone.start,
            band_bottom_mm - 16.0,
            "ticks SCHEMATIC",
            "schematic",
        ))

    # 5: main bar paths and anchorage. Straight run drawn from the
    # anchorage's own bend point (a_mm inside the support face, exact,
    # from EndPlan.a_mm) to the matching point at the far end; a short
    # bend stub (length b_mm, exact) turns the bar toward the support --
    # down for the top bar, up for the bottom (docs/ui/sketch-notation.svg
    # section 2's own convention). A REFUSED end (refused_reason set) has
    # no a_mm/b_mm to draw at all -- see this module's own docstring.
    for is_top, end_start, end_end, v_frac in (
        (True, top_end_start, top_end_end, 0.30),
        (False, bottom_end_start, bottom_end_end, -0.30),
    ):
        if end_start is None or end_end is None:
            continue
        refused = [e for e in (end_start, end_end) if e.refused_reason]
        if refused:
            for e in refused:
                # #62: e.refused_reason is a paragraph (A51's is four
                # sentences). Drawn across the beam it was unreadable and
                # buried the drawing. The Review tab states it in full;
                # the sketch says WHICH end and that it is refused, which
                # is what a drawing can usefully carry.
                shapes.append(SketchText(
                    l_mm / 2.0, half_h_mm * (0.6 if is_top else -0.6),
                    "{}, {}: REFUSED (see Review)".format(
                        "Top" if is_top else "Btm",
                        "start" if e is end_start else "end",
                    ),
                    "dimension_fail",
                ))
            continue

        v_run_mm = half_h_mm * v_frac
        bend_sign = -1.0 if is_top else 1.0
        u_bend_start_mm = -end_start.a_mm
        u_bend_end_mm = l_mm + end_end.a_mm
        shapes.append(SketchLine(u_bend_start_mm, v_run_mm, u_bend_end_mm, v_run_mm, "bar_main"))
        for end, u_mm in ((end_start, u_bend_start_mm), (end_end, u_bend_end_mm)):
            if end.b_mm is not None:
                v_bend_mm = v_run_mm + bend_sign * end.b_mm * 0.15
                shapes.append(SketchLine(u_mm, v_run_mm, u_mm, v_bend_mm, "bar_main"))
            label = "a={:.1f}, b={:.1f} mm".format(
                end.a_mm, end.b_mm
            ) if end.b_mm is not None else "achieved={:.1f} mm (no hook)".format(end.a_mm)
            shapes.append(SketchText(u_mm, v_run_mm + bend_sign * 14.0, label, "dimension"))

    # 6: crack bar, mid-depth, full length (present only when both faces
    # are detailed and h > 700, A50).
    if crack_plan is not None:
        shapes.append(SketchLine(0.0, 0.0, l_mm, 0.0, "bar_crack"))

    # 7: the A7 clearance, coloured by compliance (ClearanceResult.ok) --
    # the story's real value, drawn wherever it is available (A51: it is
    # unavailable when only one face is placed).
    for label, clearance in (("start", clearance_start), ("end", clearance_end)):
        if clearance is None:
            continue
        style = "dimension_pass" if clearance.ok else "dimension_fail"
        u_mm = 0.0 if label == "start" else l_mm
        shapes.append(SketchText(
            u_mm, half_h_mm + 20.0,
            # #62: was "A7 clearance (start): achieved 41.9 mm,
            # required 14.0 mm (PASS)" -- 62 characters anchored at the
            # support, i.e. at the canvas edge, so its tail was cut off.
            # Both numbers and the verdict survive; the prose does not.
            "A7 {}: {:.1f} / {:.1f} mm ({})".format(
                label, clearance.achieved_mm, clearance.required_mm,
                "PASS" if clearance.ok else "FAIL",
            ),
            style,
        ))

    return shapes


# --- 3: the 135-degree hook detail (schematic bend arc) ----------------------


def hook_detail_shapes(bend_leg_mm, hook_angle_deg, cu_mm=0.0, cv_mm=0.0, scale=1.0):
    """A small standalone drawing of the stirrup hook (docs/ui/sketch-
    notation.svg's bubble): the 135-degree angle and the leg LENGTH are
    exact (from ``rft.core.plan.EndPlan``-adjacent bend geometry / the
    hook type's own read-back angle, A45); the FILLET the real bend
    traces is schematic (A48/A49) -- the bar type's own bend radius owns
    it, and this module never attempts to draw it to scale.

    ``bend_leg_mm`` is the exact leg length to draw (mm, before the
    caller's own overall scale is applied elsewhere); ``hook_angle_deg``
    is the exact angle to label -- ``rft.revit.bar_types.hook_angle_deg``'s
    read-back value, or the required 135 when it could not be read (A45).
    """
    leg_mm = bend_leg_mm * scale
    p0 = (cu_mm - leg_mm, cv_mm + leg_mm)
    p1 = (cu_mm - leg_mm, cv_mm - leg_mm)
    p2 = (cu_mm + leg_mm, cv_mm - leg_mm)
    shapes = [
        SketchLine(p0[0], p0[1], p1[0], p1[1], "stirrup"),
        SketchLine(p1[0], p1[1], p2[0], p2[1], "stirrup"),
        # The bend itself -- SCHEMATIC (A48/A49): a straight stand-in for
        # the fillet the bar type's own bend radius actually traces.
        SketchLine(p1[0], p1[1], p1[0] + leg_mm * 0.35, p1[1] + leg_mm * 0.35, "schematic"),
        SketchText(cu_mm, cv_mm - leg_mm - 16.0,
                   # #62: was 52 characters explaining WHY the fillet
                   # is schematic. The explanation moved to the caption;
                   # the marker stays on the drawing, because #49
                   # requires it there. Angle and leg length are the
                   # exact numbers, and exact numbers are what a label
                   # is for.
                   "{:.1f} deg hook, leg {:.1f} mm (bend SCHEMATIC)".format(
                       hook_angle_deg, bend_leg_mm),
                   "schematic"),
    ]
    return shapes
