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

StirrupPlan = namedtuple("StirrupPlan", "endpoints_mm zones total_count")

CrackPlan = namedtuple(
    "CrackPlan",
    "h_avail_mm n_layers spacing_mm v_positions_mm u_positions_mm",
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


# Which stirrup of a zone's array Revit itself lays out, per zone (§3.1).
# Shared by the report and the placer so a zone cannot be reported with
# one set of end flags and placed with another.
ZONE_LAYOUT_FLAGS = {
    "zone1": (True, True),
    "zone2": (False, True),
    "zone3": (False, True),
}


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
        n_layers=layers.n_crack_layers,
        spacing_mm=layers.actual_spacing_mm,
        v_positions_mm=crack_layer_v_positions_mm(
            h_mm, offset_btm_innermost_mm, layers.n_crack_layers,
            layers.actual_spacing_mm
        ),
        u_positions_mm=list(crack_bar_u_positions_mm(
            b_mm, cover_side_mm, stirrup_dia_mm, crack_dia_mm
        )),
    )
