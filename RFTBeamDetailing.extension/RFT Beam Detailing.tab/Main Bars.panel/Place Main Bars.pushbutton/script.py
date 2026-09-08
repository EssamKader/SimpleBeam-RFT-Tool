# -*- coding: utf-8 -*-
"""S3 -- cross-section bar layout (§4, §4.1, §6.1, §6.3), extended by S2
(§2) -- full end anchorage for both top and bottom bars, any support type,
independent per end. See specs/beam-rft-detailing.md S2/S3 and GitHub
issues #15/#16.

Pipeline established by S1's tracer bullet, reused here: pick beam ->
validate host -> read geometry -> compute layout + anchorage -> place ->
commit transaction -> report. Minimal FlexForm only (S1's style) -- the
rich cross-field-validated WPF form is S8's scope (#21).

ISSUE #15 (S2) CLOSES THE "NOT PLACED (see #15)" HOLE THIS SCRIPT LEFT:
top-face bars are now placed, bending DOWNWARD, using the same layer-
offset/corner-bar layout S3 already computed for them. Each beam end is
handled INDEPENDENTLY: a detected support (column, wall or girder) gets
the bent anchorage (§2.1-§2.3); no detected support gets a straight run
with no hook (§2.5, A12, R3 resolved) and a warning. The two ends of one
bar can therefore differ.

SCOPE BOUNDARIES (see this ticket's report for the full rationale):
- Spacer bars: only ``spacer_length_mm`` is computed and reported. Rev 2
  section 6.3 gives a length and no longitudinal spacing rule, so no
  spacer bar is placed -- guessing one is prohibited by CONTEXT.md.
- Steel-grade (RebarBarType) resolution follows S1/S5's by-name-with-
  fallback pattern; grade logic itself is S7 (#20).
- "Place Bottom Bar.pushbutton" (S1) and "Place Stirrups.pushbutton" (S5)
  keep their original both-ends-supported assumption; only THIS pushbutton
  (already S3's, the one #15's ticket named) gets S2's full unsupported-
  end/any-support-type treatment for main bars, per this ticket's explicit
  scope ("close that hole here rather than adding a fourth pushbutton").
"""

from pyrevit import DB, forms, revit, script
from pyrevit.forms import Button, FlexForm, Label, TextBox

from rft.core.anchorage import (
    DEFAULT_LD_BTM_MULTIPLIER,
    DEFAULT_LD_TOP_MULTIPLIER,
    bottom_bar_anchorage,
    development_length,
    free_end_configuration_warning,
    top_bar_anchorage,
    placed_clearance_warning,
    top_bottom_clearance_warning,
    unsupported_end_anchorage,
    unsupported_end_straight_run_mm,
)
from rft.core.layout import (
    MAX_LAYERS,
    corner_bar_u_positions_mm,
    layer_offset_mm,
    spacer_diameter_warning,
    spacer_length_mm,
)
from rft.revit.geometry import (
    beam_axis_direction,
    beam_endpoints,
    beam_section_axes,
    beam_section_centre_offsets,
    beam_section_dimensions_mm,
    end_support_face_point,
    find_supporting_element,
    start_support_face_point,
    support_width_along_axis_mm,
)
from rft.revit.host import HostValidationError, read_face_cover_mm, read_support_cover_mm, validate_rebar_host
from rft.revit.placement import (
    bar_point_at_uv,
    bend_plane_normal,
    build_main_bar_curves,
    main_bar_end_geometry,
    place_anchored_bar,
    run_in_transaction,
)
from rft.revit.units import internal_to_mm, mm_to_internal

output = script.get_output()
doc = revit.doc

# UNVERIFIED AGAINST A LIVE HOST -- same open question S1 carries (rft/
# revit/host.py module docstring): whether RebarFaceType is even the real
# RebarHostData face-lookup shape. THREE conceptually distinct covers are
# read in this script, per this ticket's instructions -- kept as three
# separate constants even though the API-shape uncertainty currently maps
# all three to the same enum member, so a future fix to any one of them
# does not silently change the other two:
#
# 1. SUPPORT_SIDE_FACE_TYPE -- the SUPPORTING element's own cover (rev 2
#    section 2.4, A8), read off the support (column/wall/girder), used in
#    a_t / a_btm. NOT the beam's own cover.
# 2. BEAM_SIDE_FACE_TYPE -- the BEAM's own side-face cover (rev 2 sections
#    4, 6, 7), used for every HORIZONTAL cross-section dimension (corner
#    bar inset, spacer length). NOT a top/bottom face cover, NOT the
#    support's cover.
# 3. BEAM_END_FACE_TYPE -- the BEAM's own cover at its CUT END (rev 2
#    section 2.5, R3 resolved: "beam end - cover"), used ONLY for the
#    unsupported-end straight run. A THIRD thing again: neither the
#    support's cover nor the beam's side cover. Whether ``RebarHostData``
#    exposes a face specifically for a framing element's cut end (as
#    opposed to a side/top/bottom face) is UNCLEAR and not confirmed by
#    either docs/research/revit-api-strategy.md or rft/revit/host.py's own
#    module docstring -- flagged here rather than silently reusing another
#    constant's value without comment.
SUPPORT_SIDE_FACE_TYPE = DB.Structure.RebarFaceType.Other
BEAM_SIDE_FACE_TYPE = DB.Structure.RebarFaceType.Other
BEAM_END_FACE_TYPE = DB.Structure.RebarFaceType.Other


def resolve_bar_type(document, requested_name):
    """A single provisional RebarBarType (grade selection is S7, #20).
    Matches S1/S5's by-name-with-fallback pattern.
    """
    bar_types = list(
        DB.FilteredElementCollector(document).OfClass(DB.Structure.RebarBarType)
    )
    if not bar_types:
        raise HostValidationError("No RebarBarType exists in this document.")
    if requested_name:
        for bt in bar_types:
            if bt.Name == requested_name:
                return bt
        output.print_md(
            "*No RebarBarType named '{}' found -- falling back to '{}'.*".format(
                requested_name, bar_types[0].Name
            )
        )
    return bar_types[0]


def ask_inputs():
    components = [
        Label("Stirrup diameter O_stirrup (mm):"),
        TextBox("dia_stirrup", Text="10"),
        Label("Top bar diameter O_TOP (mm):"),
        TextBox("dia_top", Text="12"),
        Label("Bottom bar diameter O_BTM (mm):"),
        TextBox("dia_btm", Text="16"),
        Label("Spacer diameter O_spacer (mm, clear gap between layers):"),
        TextBox("dia_spacer", Text="16"),
        Label("Max aggregate size D_agg (mm) -- required, no default (rev 2 §8.1 ships it blank):"),
        TextBox("d_agg", Text=""),
        Label("Top bar count per layer:"),
        TextBox("count_top", Text="3"),
        Label("Bottom bar count per layer:"),
        TextBox("count_btm", Text="3"),
        Label("Number of top layers (1-{}):".format(MAX_LAYERS)),
        TextBox("layers_top", Text="1"),
        Label("Number of bottom layers (1-{}):".format(MAX_LAYERS)),
        TextBox("layers_btm", Text="1"),
        Label("LD_top multiplier (x diameter, default {}, assumes St 36/52):".format(
            int(DEFAULT_LD_TOP_MULTIPLIER)
        )),
        TextBox("ld_top_mult", Text=str(int(DEFAULT_LD_TOP_MULTIPLIER))),
        Label("LD_btm multiplier (x diameter, default {}, assumes St 36/52):".format(
            int(DEFAULT_LD_BTM_MULTIPLIER)
        )),
        TextBox("ld_btm_mult", Text=str(int(DEFAULT_LD_BTM_MULTIPLIER))),
        Label("RebarBarType name (blank = first available):"),
        TextBox("bar_type_name", Text=""),
        Button("Place main bars (top + bottom)"),
    ]
    form = FlexForm("S2/S3 - Main bar layout and end anchorage", components)
    form.show()
    if not form.values:
        script.exit()
    return form.values


def _format_end_result(a_mm, b_mm):
    """`a=..., b=...` when supported (bent), or `achieved=... mm (no hook,
    unsupported)` when not -- ``a_mm`` holds the achieved-length value in
    the unsupported case, which is not the same quantity as the formula
    `a`, so it is labelled differently rather than reused under the same
    name.
    """
    if b_mm is None:
        return "achieved={:.1f} mm (no hook, unsupported)".format(a_mm)
    return "a={:.1f} mm, b={:.1f} mm".format(a_mm, b_mm)


def _end_support(doc, point, axis, beam_id):
    """Detect the support at one beam end (rev 2 section 2.4, A9) and
    return (support_or_None, width_mm_or_None). A free/cantilever end
    returns (None, None) -- the unsupported path, §2.5/A14.
    """
    support = find_supporting_element(doc, point, mm_to_internal, exclude_element_id=beam_id)
    if support is None:
        return None, None
    width_mm = support_width_along_axis_mm(support, axis, internal_to_mm)
    return support, width_mm


def main():
    beam = revit.pick_element(message="Select a beam (structural framing) to detail.")
    if beam is None:
        script.exit()

    try:
        host_data = validate_rebar_host(beam)
    except HostValidationError as ex:
        forms.alert(str(ex), title="Host validation failed")
        script.exit()

    values = ask_inputs()
    dia_stirrup_mm = float(values["dia_stirrup"])
    dia_top_mm = float(values["dia_top"])
    dia_btm_mm = float(values["dia_btm"])
    dia_spacer_mm = float(values["dia_spacer"]) if values["dia_spacer"] else 16.0

    if not values["d_agg"]:
        forms.alert(
            "Max aggregate size D_agg is required to evaluate the R1 "
            "spacer-diameter warning (rev 2 section 4.1, A21). Rev 2 gives "
            "no default for D_agg -- entering it is not optional here, "
            "unlike section 6.2's separate 50 mm horizontal-spacing "
            "fallback (which this pushbutton does not compute; that is "
            "S4, issue #17).",
            title="D_agg required",
        )
        script.exit()
    d_agg_mm = float(values["d_agg"])

    count_top = int(values["count_top"])
    count_btm = int(values["count_btm"])
    layers_top = int(values["layers_top"])
    layers_btm = int(values["layers_btm"])
    ld_top_mult = float(values["ld_top_mult"]) if values["ld_top_mult"] else DEFAULT_LD_TOP_MULTIPLIER
    ld_btm_mult = float(values["ld_btm_mult"]) if values["ld_btm_mult"] else DEFAULT_LD_BTM_MULTIPLIER
    bar_type = resolve_bar_type(doc, values.get("bar_type_name"))

    try:
        cover_top_mm = read_face_cover_mm(
            host_data, DB.Structure.RebarFaceType.Top, doc, internal_to_mm, element_id=beam.Id
        )
        cover_btm_mm = read_face_cover_mm(
            host_data, DB.Structure.RebarFaceType.Bottom, doc, internal_to_mm, element_id=beam.Id
        )
        cover_side_mm = read_face_cover_mm(
            host_data, BEAM_SIDE_FACE_TYPE, doc, internal_to_mm, element_id=beam.Id
        )
        cover_end_mm = read_face_cover_mm(
            host_data, BEAM_END_FACE_TYPE, doc, internal_to_mm, element_id=beam.Id
        )
    except HostValidationError as ex:
        forms.alert(str(ex), title="Cover read-back failed")
        script.exit()

    b_mm, h_mm = beam_section_dimensions_mm(beam, internal_to_mm)
    start_pt, end_pt = beam_endpoints(beam)
    axis = beam_axis_direction(beam)
    u_dir, v_dir = beam_section_axes(beam)

    # --- rev 2 section 2.4/2.5 (A9/A12/A14): support detection, per end,
    # any support type -- a missing support takes the unsupported path,
    # never a hard stop, so top/bottom anchorage can be computed at both
    # ends independently below.
    support_start, support_width_start_mm = _end_support(doc, start_pt, axis, beam.Id)
    support_end, support_width_end_mm = _end_support(doc, end_pt, axis, beam.Id)
    is_supported_start = support_start is not None
    is_supported_end = support_end is not None

    if not is_supported_start and not is_supported_end:
        forms.alert(
            "No support detected at EITHER end. This tool details a "
            "single-span, simply-supported beam (rev 2 scope) -- a beam "
            "with no support at all is not a span and is refused rather "
            "than silently detailed (this specific guard is this "
            "ticket's own judgement call, not a rev 2 rule -- see this "
            "ticket's report).",
            title="No support detected",
        )
        script.exit()

    warnings = []
    if not is_supported_start:
        warnings.append("Start end: " + free_end_configuration_warning())
    if not is_supported_end:
        warnings.append("End end: " + free_end_configuration_warning())

    support_cover_start_mm = support_cover_end_mm = None
    try:
        if is_supported_start:
            support_cover_start_mm = read_support_cover_mm(
                support_start, SUPPORT_SIDE_FACE_TYPE, doc, internal_to_mm
            )
        if is_supported_end:
            support_cover_end_mm = read_support_cover_mm(
                support_end, SUPPORT_SIDE_FACE_TYPE, doc, internal_to_mm
            )
    except HostValidationError as ex:
        forms.alert(str(ex), title="Cover read-back failed")
        script.exit()

    # --- §4/§4.1: per-layer offsets, both faces --------------------------
    try:
        top_layer_offsets_mm = [
            layer_offset_mm(cover_top_mm, dia_stirrup_mm, dia_top_mm, dia_spacer_mm, n)
            for n in range(1, layers_top + 1)
        ]
        btm_layer_offsets_mm = [
            layer_offset_mm(cover_btm_mm, dia_stirrup_mm, dia_btm_mm, dia_spacer_mm, n)
            for n in range(1, layers_btm + 1)
        ]
    except ValueError as ex:
        forms.alert(str(ex), title="Invalid layer count")
        script.exit()

    # --- §6.1: corner-bar horizontal distribution, both faces ------------
    try:
        top_u_positions_mm = corner_bar_u_positions_mm(
            b_mm, cover_side_mm, dia_stirrup_mm, dia_top_mm, count_top
        )
        btm_u_positions_mm = corner_bar_u_positions_mm(
            b_mm, cover_side_mm, dia_stirrup_mm, dia_btm_mm, count_btm
        )
    except ValueError as ex:
        forms.alert(str(ex), title="Invalid bar count")
        script.exit()

    # --- §6.3: spacer length (computed/reported only -- see module docstring).
    spacer_length_section_mm = spacer_length_mm(b_mm, cover_side_mm, dia_stirrup_mm)

    # --- R1 (resolved, non-blocking): only meaningful with >1 stacked layer --
    warning_top_spacer = spacer_diameter_warning(dia_spacer_mm, dia_top_mm, d_agg_mm) if layers_top > 1 else None
    warning_btm_spacer = spacer_diameter_warning(dia_spacer_mm, dia_btm_mm, d_agg_mm) if layers_btm > 1 else None

    # --- rev 2 section 2.2, A7: top/bottom centreline clearance (spec gap
    # when O_TOP > O_BTM -- see this ticket's report) --------------------
    warning_clearance = top_bottom_clearance_warning(dia_top_mm, dia_btm_mm)

    # --- rev 2 section 2.1-2.3, 2.5: end anchorage, BOTH faces, BOTH ends,
    # each end independent (issue #15, S2) -------------------------------
    ld_top_mm = development_length(dia_top_mm, ld_top_mult)
    ld_btm_mm = development_length(dia_btm_mm, ld_btm_mult)

    def end_anchorage(is_supported, support_width_mm, support_cover_mm, dia_own_mm,
                       ld_mm, is_top, end_label):
        if is_supported:
            if is_top:
                result = top_bar_anchorage(support_width_mm, support_cover_mm, dia_btm_mm, ld_mm)
            else:
                result = bottom_bar_anchorage(support_width_mm, support_cover_mm, ld_mm)
            return result.a, result.b, None
        # Unsupported: straight run to `beam end - cover` (R3, resolved).
        # The achieved EMBEDMENT is 0 -- there is no support to embed into.
        # The bar's termination `cover` short of the beam end is a separate
        # geometric fact, reported as such: reporting it AS the achieved
        # length would print a negative length (issue #15 review).
        result = unsupported_end_anchorage(0.0, ld_mm, terminates_short_of_end_mm=cover_end_mm)
        warning = "{}: {}".format(end_label, result.warning) if result.warning else None
        return result.achieved_length_mm, None, warning

    try:
        a_top_start_mm, b_top_start_mm, w1 = end_anchorage(
            is_supported_start, support_width_start_mm, support_cover_start_mm,
            dia_top_mm, ld_top_mm, True, "Start end (top)"
        )
        a_top_end_mm, b_top_end_mm, w2 = end_anchorage(
            is_supported_end, support_width_end_mm, support_cover_end_mm,
            dia_top_mm, ld_top_mm, True, "End end (top)"
        )
        a_btm_start_mm, b_btm_start_mm, w3 = end_anchorage(
            is_supported_start, support_width_start_mm, support_cover_start_mm,
            dia_btm_mm, ld_btm_mm, False, "Start end (bottom)"
        )
        a_btm_end_mm, b_btm_end_mm, w4 = end_anchorage(
            is_supported_end, support_width_end_mm, support_cover_end_mm,
            dia_btm_mm, ld_btm_mm, False, "End end (bottom)"
        )
    except ValueError as ex:
        forms.alert(str(ex), title="Invalid anchorage input")
        script.exit()

    for w in (w1, w2, w3, w4):
        if w:
            warnings.append(w)

    output.print_md("### S2/S3 -- computed cross-section layout and end anchorage (rev 2 §2, §4, §4.1, §6.1, §6.3)")
    output.print_md(
        "- b = {:.1f} mm, h = {:.1f} mm, cover_top = {:.1f} mm, cover_btm = {:.1f} mm, "
        "cover_side = {:.1f} mm, cover_end = {:.1f} mm, O_stirrup = {:.1f} mm".format(
            b_mm, h_mm, cover_top_mm, cover_btm_mm, cover_side_mm, cover_end_mm, dia_stirrup_mm
        )
    )
    output.print_md(
        "- spacer_length (§6.3, one horizontal dimension per section) = "
        "{:.1f} mm".format(spacer_length_section_mm)
    )
    output.print_md("- Start end support: {}".format(
        "detected, width = {:.1f} mm, cover = {:.1f} mm".format(support_width_start_mm, support_cover_start_mm)
        if is_supported_start else "NONE (unsupported/free end)"
    ))
    output.print_md("- End end support: {}".format(
        "detected, width = {:.1f} mm, cover = {:.1f} mm".format(support_width_end_mm, support_cover_end_mm)
        if is_supported_end else "NONE (unsupported/free end)"
    ))

    output.print_md("#### Top face (O_TOP = {:.1f} mm) -- PLACED (bends DOWNWARD)".format(dia_top_mm))
    for n, offset_mm in enumerate(top_layer_offsets_mm, start=1):
        output.print_md("- layer {}: offset_{} = {:.1f} mm".format(n, n, offset_mm))
    output.print_md("- corner-bar u positions ({} bars): {}".format(
        count_top, ", ".join("{:.1f}".format(u) for u in top_u_positions_mm)
    ))
    output.print_md(
        "- LD_top = {} x {:.1f} = {:.1f} mm -> start: {}; end: {}".format(
            ld_top_mult, dia_top_mm, ld_top_mm,
            _format_end_result(a_top_start_mm, b_top_start_mm),
            _format_end_result(a_top_end_mm, b_top_end_mm),
        )
    )
    if warning_top_spacer:
        output.print_md("- **R1 warning (top):** {}".format(warning_top_spacer))

    output.print_md("#### Bottom face (O_BTM = {:.1f} mm) -- PLACED (bends UPWARD)".format(dia_btm_mm))
    for n, offset_mm in enumerate(btm_layer_offsets_mm, start=1):
        output.print_md("- layer {}: offset_{} = {:.1f} mm".format(n, n, offset_mm))
    output.print_md("- corner-bar u positions ({} bars): {}".format(
        count_btm, ", ".join("{:.1f}".format(u) for u in btm_u_positions_mm)
    ))
    output.print_md(
        "- LD_btm = {} x {:.1f} = {:.1f} mm -> start: {}; end: {}".format(
            ld_btm_mult, dia_btm_mm, ld_btm_mm,
            _format_end_result(a_btm_start_mm, b_btm_start_mm),
            _format_end_result(a_btm_end_mm, b_btm_end_mm),
        )
    )
    if warning_btm_spacer:
        output.print_md("- **R1 warning (bottom):** {}".format(warning_btm_spacer))

    clearance_line = (
        "achieved = O_BTM = {:.1f} mm, required = (O_TOP+O_BTM)/2 = {:.1f} mm".format(
            dia_btm_mm, 0.5 * (dia_top_mm + dia_btm_mm)
        )
    )
    output.print_md("- Top/bottom centreline clearance (§2.2, A7): {}".format(clearance_line))
    if warning_clearance:
        output.print_md("- **A7 clearance warning:** {}".format(warning_clearance))

    # The same A7 check on the values ACTUALLY built: §2.3's cap can fire on
    # one bar and not the other at a wide support, which breaks the
    # formula-level invariant the check above tests (issue #15 review).
    # Only meaningful at an end that HAS an `a` -- an unsupported end has
    # no bend to clash.
    for end_label, is_supported, a_btm_end_mm_, a_top_end_mm_ in (
        ("Start end", is_supported_start, a_btm_start_mm, a_top_start_mm),
        ("End end", is_supported_end, a_btm_end_mm, a_top_end_mm),
    ):
        if not is_supported:
            continue
        placed_warning = placed_clearance_warning(
            a_btm_end_mm_, a_top_end_mm_, dia_top_mm, dia_btm_mm, end_label=end_label
        )
        if placed_warning:
            output.print_md("- **A7 as-built clearance warning:** {}".format(placed_warning))

    for w in warnings:
        output.print_md("- **WARNING:** {}".format(w))

    total_bar_count = layers_top * count_top + layers_btm * count_btm
    output.print_md("- **Total bar count (both faces) = {}** ({} top, {} bottom)".format(
        total_bar_count, layers_top * count_top, layers_btm * count_btm
    ))

    # --- face/end-point references, per end (support face if supported,
    # else the beam's own physical end point -- rev 2 section 2.5) ------
    if is_supported_start:
        ref_start = start_support_face_point(
            support_start, start_pt, axis, mm_to_internal(support_width_start_mm)
        )
    else:
        ref_start = start_pt
    if is_supported_end:
        ref_end = end_support_face_point(
            support_end, start_pt, axis, mm_to_internal(support_width_end_mm)
        )
    else:
        ref_end = end_pt

    cover_end_internal = mm_to_internal(cover_end_mm)
    du_internal, dv_internal = beam_section_centre_offsets(beam, start_pt)

    def _place_face(layer_offsets_mm, u_positions_mm, bend_direction, is_top,
                     a_start_mm, b_start_mm, a_end_mm, b_end_mm):
        placed = []
        a_start_internal = mm_to_internal(a_start_mm) if is_supported_start else cover_end_internal
        a_end_internal = mm_to_internal(a_end_mm) if is_supported_end else cover_end_internal
        b_start_internal = mm_to_internal(b_start_mm) if b_start_mm is not None else None
        b_end_internal = mm_to_internal(b_end_mm) if b_end_mm is not None else None

        for layer_offset_val_mm in layer_offsets_mm:
            if is_top:
                # Top-face layer offsets are measured DOWN from the top
                # face (§4): the top face sits at +h/2 above the section
                # centroid, so the layer's v coordinate is h/2 MINUS the
                # offset -- the mirror image of the bottom-face case below,
                # where the offset is ADDED to -h/2.
                v_mm = (h_mm / 2.0) - layer_offset_val_mm
            else:
                # Bottom layer offsets are measured UP from the bottom
                # face, so the layer's v coordinate (centred on the
                # section centroid) is -h/2 PLUS the offset.
                v_mm = -(h_mm / 2.0) + layer_offset_val_mm
            for u_mm in u_positions_mm:
                bar_ref_start = bar_point_at_uv(
                    ref_start, u_dir, v_dir, du_internal, dv_internal, u_mm, v_mm, mm_to_internal
                )
                bar_ref_end = bar_point_at_uv(
                    ref_end, u_dir, v_dir, du_internal, dv_internal, u_mm, v_mm, mm_to_internal
                )
                corner_start, bend_start = main_bar_end_geometry(
                    is_supported_start, bar_ref_start, axis, True, a_start_internal, b_start_internal
                )
                corner_end, bend_end = main_bar_end_geometry(
                    is_supported_end, bar_ref_end, axis, False, a_end_internal, b_end_internal
                )
                curves = build_main_bar_curves(corner_start, corner_end, bend_direction, bend_start, bend_end)
                norm = bend_plane_normal(axis, bend_direction)
                placed.append(place_anchored_bar(doc, beam, bar_type, curves, norm))
        return placed

    def do_place():
        placed = []
        placed += _place_face(
            btm_layer_offsets_mm, btm_u_positions_mm, v_dir, False,
            a_btm_start_mm, b_btm_start_mm, a_btm_end_mm, b_btm_end_mm,
        )
        placed += _place_face(
            top_layer_offsets_mm, top_u_positions_mm, v_dir.Negate(), True,
            a_top_start_mm, b_top_start_mm, a_top_end_mm, b_top_end_mm,
        )
        return placed

    try:
        run_in_transaction(doc, "RFT S2/S3 - place main bars (top + bottom)", do_place)
    except Exception as ex:
        forms.alert(
            "Placement failed and was rolled back: {}".format(ex),
            title="Error",
        )
        script.exit()

    output.print_md("**Top and bottom face bars placed successfully.**")


if __name__ == "__main__":
    main()
