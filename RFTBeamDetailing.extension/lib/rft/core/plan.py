# -*- coding: utf-8 -*-
"""What will be placed, as numbers, before anything touches Revit.

Composition only. Every value here comes from an existing ``rft.core``
function; this module adds no detailing arithmetic of its own and is the
place where the numbers are assembled ONCE.

Why it exists (issue #56). The Review report (#50) and the placement code
both need the same quantities -- layer offsets, bar positions, anchorage
`a`/`b` per end, stirrup zones and counts, the crack-bar plan. Computing
them twice, in a formatter and again in a placer, is how a report and the
bars it describes drift apart: both would keep calling the correct core
functions, and would still be able to disagree about which inputs they
were called with. The report formats a plan; the placer executes the same
plan object. They cannot disagree because there is only one.

This is the same rule A48 applies to the sketch renderer and A46 applies
to the stirrup diameter, in the one place where being wrong is not a
cosmetic problem: these numbers become steel.

No Revit import. Diameters, covers and support geometry arrive as plain
numbers, read by the caller.
"""

from collections import namedtuple

from rft.core.anchorage import (
    bottom_bar_anchorage,
    development_length,
    top_bar_anchorage,
    unsupported_end_anchorage,
)
from rft.core.crack_bars import (
    available_height_mm,
    crack_bar_u_positions_mm,
    crack_layer_plan,
    crack_layer_v_positions_mm,
)
from rft.core.layout import (
    corner_bar_u_positions_mm,
    layer_offset_mm,
    main_layer_v_positions_mm,
)
from rft.core.stirrups import (
    ZONE_LAYOUT_FLAGS,
    centreline_leg_dimensions_mm,
    stirrup_count_and_spacing,
    stirrup_curve_endpoints_mm,
    stirrup_zones_mm,
    zone_array_length_mm,
)

# One layer of one face: where its bars sit in the section.
LayerPlan = namedtuple("LayerPlan", "layer_n offset_mm v_mm u_positions_mm")

# One end of one face: the anchorage the bar terminates with.
#
# ``a_mm`` is the straight length at a supported end and the ACHIEVED
# length at an unsupported one -- two different quantities that the
# verified pushbutton also carries in one field, and reports differently
# (`_format_end_result`). ``b_mm`` is None whenever there is no hook.
# ``refused_reason`` is set when `a` cannot be computed at all, in which
# case every other field is None.
EndPlan = namedtuple("EndPlan", "a_mm b_mm warning refused_reason")

FacePlan = namedtuple("FacePlan", "is_top layers start_end end_end")

ZonePlan = namedtuple(
    "ZonePlan",
    "name zone max_spacing_mm include_first include_last "
    "array_length_mm count spacing_mm",
)

# ``width_mm``/``height_mm`` are the CENTRELINE rectangle the endpoints
# were derived from. Carried on the plan rather than left as a local,
# because the report states them (240 x 840 on the verification beam,
# where the OUTER rectangle is 260 x 860) and the report must state what
# the plan holds, not recompute it.
StirrupPlan = namedtuple(
    "StirrupPlan", "endpoints_mm width_mm height_mm zones total_count")

# ``n_gaps`` and the two offsets are inputs and intermediates rather
# than positions, and are carried for the same reason as the stirrup
# rectangle above: the report prints all three (section 5.2's gap count,
# and the innermost layer offset per face that H_avail is measured
# between), and a report that recomputes them can disagree with the bars.
CrackPlan = namedtuple(
    "CrackPlan",
    "h_avail_mm n_gaps n_layers spacing_mm v_positions_mm u_positions_mm "
    "offset_top_mm offset_btm_mm",
)


def face_layer_plans(is_top, h_mm, b_mm, cover_face_mm, cover_side_mm,
                     stirrup_dia_mm, bar_dia_mm, spacer_dia_mm,
                     bar_count, layer_count):
    """Every layer of one face: its offset from the face (§4.1), its `v`
    in the section frame (§4), and the `u` of each bar in it (§6.1).

    The +h/2 - offset / -h/2 + offset mirror stays in
    ``main_layer_v_positions_mm`` rather than being repeated here -- the
    sketch, the report and the placer all need the same convention, and
    two copies of it is how a drawing and the bars it depicts drift apart
    (A48, #44).
    """
    plans = []
    offsets_mm = [
        layer_offset_mm(cover_face_mm, stirrup_dia_mm, bar_dia_mm, spacer_dia_mm, n)
        for n in range(1, layer_count + 1)
    ]
    v_positions_mm = main_layer_v_positions_mm(h_mm, offsets_mm, is_top)
    for n, (offset_mm, v_mm) in enumerate(zip(offsets_mm, v_positions_mm), start=1):
        plans.append(LayerPlan(
            layer_n=n,
            offset_mm=offset_mm,
            v_mm=v_mm,
            u_positions_mm=corner_bar_u_positions_mm(
                b_mm, cover_side_mm, stirrup_dia_mm, bar_dia_mm, bar_count
            ),
        ))
    return plans


def innermost_layer_offset_mm(cover_face_mm, stirrup_dia_mm, bar_dia_mm,
                              spacer_dia_mm, layer_count):
    """Where one face's INNERMOST main-bar layer sits (section 4.1) -- the
    only thing section 5.1's ``H_avail`` needs to know about that face.

    Note the innermost layer is layer number ``layer_count``, not layer 1:
    section 4.1 counts outwards from the concrete face, so the LAST layer
    is the one nearest the beam's centre. That fact was being re-stated at
    three call sites (the live H_avail readout, the report, the placer),
    each spelling it a slightly different way; it is stated here once.

    Why this exists separately from ``face_layer_plans``, which also
    reports it as ``layers[-1].offset_mm``: a full face plan needs the
    per-layer BAR COUNT, because it also computes every bar's ``u``.
    ``H_avail`` needs no bar count at all. A50 requires both faces to be
    DETAILED -- a bar type and a layer count each -- but a face can be
    detailed without being PLACED, and an unplaced face has no bar count
    (A42/#50 made the faces independent; #48 made a blank count mean
    blank rather than a default).

    So building a whole ``FacePlan`` just to read this one number was not
    merely wasteful. With a blank bar count it raised ``TypeError: '<' not
    supported between instances of 'NoneType' and 'int'`` from inside
    ``corner_bar_u_positions_mm``, with the transaction already open, for
    a combination the derivation had explicitly declared valid: both faces
    detailed, only one of them placed, crack bars requested.
    """
    return layer_offset_mm(
        cover_face_mm, stirrup_dia_mm, bar_dia_mm, spacer_dia_mm, layer_count
    )


def end_plan(is_supported, is_top, support_width_mm, support_cover_mm,
             dia_own_mm, dia_other_mm, ld_mm, cover_end_mm, end_label):
    """The anchorage at one end of one face.

    A51: the TOP bar's `a` needs the BOTTOM bar's diameter (§2.1). Since
    A42/#50 made the faces independent, that face may not be being placed
    -- but if the engineer has SELECTED a bottom bar type, its diameter is
    an explicit statement of bar size and is used, placed or not. With no
    opposite type selected at all there is no diameter and none is
    invented (A42): the end is REFUSED, by name, and the caller reports it
    rather than placing a bar whose anchorage it could not compute.
    """
    if is_supported:
        if is_top:
            if dia_other_mm is None:
                return EndPlan(None, None, None, (
                    "{}: cannot compute top-bar anchorage -- rev 2 section "
                    "2.1's a_t needs the BOTTOM bar's diameter, and no "
                    "bottom main bar type is selected (A51). Select one "
                    "and it will be used whether or not the bottom face "
                    "is placed."
                ).format(end_label))
            result = top_bar_anchorage(
                support_width_mm, support_cover_mm, dia_other_mm, ld_mm
            )
        else:
            result = bottom_bar_anchorage(support_width_mm, support_cover_mm, ld_mm)
        return EndPlan(result.a, result.b, None, None)

    result = unsupported_end_anchorage(
        0.0, ld_mm, terminates_short_of_end_mm=cover_end_mm
    )
    warning = "{}: {}".format(end_label, result.warning) if result.warning else None
    return EndPlan(result.achieved_length_mm, None, warning, None)


def face_plan(is_top, h_mm, b_mm, cover_face_mm, cover_side_mm, cover_end_mm,
              stirrup_dia_mm, bar_dia_mm, dia_other_mm, spacer_dia_mm,
              bar_count, layer_count, ld_multiplier,
              is_supported_start, support_width_start_mm, support_cover_start_mm,
              is_supported_end, support_width_end_mm, support_cover_end_mm):
    """One whole face: its layers and both its ends."""
    ld_mm = development_length(bar_dia_mm, ld_multiplier)
    return FacePlan(
        is_top=is_top,
        layers=face_layer_plans(
            is_top, h_mm, b_mm, cover_face_mm, cover_side_mm,
            stirrup_dia_mm, bar_dia_mm, spacer_dia_mm, bar_count, layer_count,
        ),
        start_end=end_plan(
            is_supported_start, is_top, support_width_start_mm,
            support_cover_start_mm, bar_dia_mm, dia_other_mm, ld_mm,
            cover_end_mm, "Start end",
        ),
        end_end=end_plan(
            is_supported_end, is_top, support_width_end_mm,
            support_cover_end_mm, bar_dia_mm, dia_other_mm, ld_mm,
            cover_end_mm, "End end",
        ),
    )


# Which stirrup of a zone's array Revit itself lays out, per zone (§3.1),
# RE-EXPORTED from rft.core.stirrups rather than restated.
#
# It was restated here when this module was written, and the copy said
# something different: zone2 (False, True) and zone3 (False, True), where
# the original says zone2 (False, False) and zone3 (True, True). Both give
# each boundary exactly one owner, so both place bars at the same
# positions and both total 47 on the verification beam -- which is why
# nothing noticed. What differed was WHICH ZONE owns the bar at 2L/3, so
# the Review report (which imported the original) said "zone2: count = 9,
# zone3: count = 19" while Place built sets of 10 and 18.
#
# The original is the one with the reasoning attached (the R4
# de-duplication mitigation, issue #18 review finding #1), the one
# tests/test_stirrups.py pins, and the one rft.revit.stirrups documents
# against. A second copy of a constant is not a shortcut; it is a second
# answer waiting to be given.
ZONE_LAYOUT_FLAGS = ZONE_LAYOUT_FLAGS


def stirrup_plan(l_mm, b_mm, h_mm, cover_mm, stirrup_dia_mm, closure_type,
                 dense_spacing_mm, normal_spacing_mm,
                 face_a_offset_mm, face_b_offset_mm):
    """The three zones (§3.1) and the centreline loop (§7.1/A30).

    ``endpoints_mm`` is the CENTRELINE rectangle, which is what
    ``Rebar.CreateFromCurves`` receives -- not the outer rectangle the
    cover is measured to. ``outer_leg_dimensions_mm`` exists for the
    sketch; using it here would place every stirrup one full diameter too
    large.
    """
    width_mm, height_mm = centreline_leg_dimensions_mm(
        b_mm, h_mm, cover_mm, stirrup_dia_mm
    )
    zones = stirrup_zones_mm(l_mm, face_a_offset_mm, face_b_offset_mm)
    specs = (
        ("zone1", zones.zone1, dense_spacing_mm),
        ("zone2", zones.zone2, normal_spacing_mm),
        ("zone3", zones.zone3, dense_spacing_mm),
    )
    zone_plans = []
    total = 0
    for name, zone, max_spacing_mm in specs:
        include_first, include_last = ZONE_LAYOUT_FLAGS[name]
        array_length_mm = zone_array_length_mm(zone)
        result = stirrup_count_and_spacing(
            array_length_mm, max_spacing_mm, include_first, include_last
        )
        total += result.count
        zone_plans.append(ZonePlan(
            name=name, zone=zone, max_spacing_mm=max_spacing_mm,
            include_first=include_first, include_last=include_last,
            array_length_mm=array_length_mm,
            count=result.count, spacing_mm=result.spacing_mm,
        ))
    return StirrupPlan(
        endpoints_mm=stirrup_curve_endpoints_mm(closure_type, width_mm, height_mm),
        width_mm=width_mm,
        height_mm=height_mm,
        zones=zone_plans,
        total_count=total,
    )


def crack_plan(h_mm, b_mm, cover_side_mm, stirrup_dia_mm, crack_dia_mm,
               offset_top_innermost_mm, offset_btm_innermost_mm, s_max_mm):
    """Crack/skin bars (§5): how many layers, at what spacing, where.

    ``offset_*_innermost_mm`` are measured to the INNERMOST main-bar layer
    (A26) -- the caller passes the last layer's offset, not the first.
    """
    h_avail_mm = available_height_mm(
        h_mm, offset_top_innermost_mm, offset_btm_innermost_mm
    )
    layers = crack_layer_plan(h_avail_mm, s_max_mm)
    # ``n_crack_layers``, not ``n_gaps``: section 5.2 divides H_avail into
    # n gaps and puts a layer at each INTERIOR division, so there is one
    # fewer layer than gap. Reading the wrong field would place an extra
    # layer on top of a main-bar layer.
    return CrackPlan(
        h_avail_mm=h_avail_mm,
        n_gaps=layers.n_gaps,
        n_layers=layers.n_crack_layers,
        offset_top_mm=offset_top_innermost_mm,
        offset_btm_mm=offset_btm_innermost_mm,
        spacing_mm=layers.actual_spacing_mm,
        v_positions_mm=crack_layer_v_positions_mm(
            h_mm, offset_btm_innermost_mm, layers.n_crack_layers,
            layers.actual_spacing_mm
        ),
        u_positions_mm=list(crack_bar_u_positions_mm(
            b_mm, cover_side_mm, stirrup_dia_mm, crack_dia_mm
        )),
    )
