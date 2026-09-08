# -*- coding: utf-8 -*-
"""S3 -- cross-section bar layout: layer offsets, corner-bar distribution,
spacer length, R1 vertical-spacing warning. See specs/beam-rft-detailing.md
S3 and GitHub issue #16.

Pipeline established by S1's tracer bullet, reused here: pick beam ->
validate host -> read geometry -> compute (this time §4/§4.1/§6.1 layout)
-> place -> commit transaction -> report. Minimal FlexForm only (S1's
style) -- the rich cross-field-validated WPF form is S8's scope (#21).

SCOPE BOUNDARIES (see this ticket's report for the full rationale):
- Top-face bars are computed and reported, never placed. Top-bar
  anchorage is S2 (#15); inventing it here is out of scope.
- Spacer bars: only ``spacer_length_mm`` is computed and reported. Rev 2
  section 6.3 gives a length and no longitudinal spacing rule, so no
  spacer bar is placed -- guessing one is prohibited by CONTEXT.md.
- Steel-grade (RebarBarType) resolution follows S1/S5's by-name-with-
  fallback pattern; grade logic itself is S7 (#20).
"""

from pyrevit import DB, forms, revit, script
from pyrevit.forms import Button, FlexForm, Label, TextBox

from rft.core.anchorage import DEFAULT_LD_BTM_MULTIPLIER, bottom_bar_anchorage, development_length
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
    column_width_along_axis_mm,
    end_support_face_point,
    find_supporting_column,
    start_support_face_point,
)
from rft.revit.host import HostValidationError, read_face_cover_mm, read_support_cover_mm, validate_rebar_host
from rft.revit.placement import (
    bar_face_points_at_uv,
    bend_plane_normal,
    build_bottom_bar_curves,
    place_anchored_bar,
    run_in_transaction,
)
from rft.revit.units import internal_to_mm, mm_to_internal

output = script.get_output()
doc = revit.doc

# UNVERIFIED AGAINST A LIVE HOST -- same open question S1 carries for the
# bottom face (rft/revit/host.py module docstring): whether RebarFaceType
# is even the real RebarHostData face-lookup shape. Reused unchanged here,
# now also for the TOP face, purely for reporting.
SUPPORT_SIDE_FACE_TYPE = DB.Structure.RebarFaceType.Other

# The BEAM's own side face. Every HORIZONTAL dimension in this story is
# governed by it, not by the top/bottom cover: the corner bar's inset from
# a side face (§6.1) and the spacer bar's length across the section (§6.3).
# Using a face cover for those gives two different answers to a question
# the spec asks once, and misplaces every corner bar whenever the side
# cover differs from the top or bottom cover (issue #16 review).
BEAM_SIDE_FACE_TYPE = DB.Structure.RebarFaceType.Other


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
        Label("LD_btm multiplier (x diameter, default {}, assumes St 36/52):".format(
            int(DEFAULT_LD_BTM_MULTIPLIER)
        )),
        TextBox("ld_mult", Text=str(int(DEFAULT_LD_BTM_MULTIPLIER))),
        Label("RebarBarType name (blank = first available):"),
        TextBox("bar_type_name", Text=""),
        Button("Place bottom bars"),
    ]
    form = FlexForm("S3 - Main bar cross-section layout", components)
    form.show()
    if not form.values:
        script.exit()
    return form.values


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
    ld_mult = float(values["ld_mult"]) if values["ld_mult"] else DEFAULT_LD_BTM_MULTIPLIER
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
    except HostValidationError as ex:
        forms.alert(str(ex), title="Cover read-back failed")
        script.exit()

    b_mm, h_mm = beam_section_dimensions_mm(beam, internal_to_mm)
    start_pt, end_pt = beam_endpoints(beam)
    axis = beam_axis_direction(beam)
    u_dir, v_dir = beam_section_axes(beam)

    col_start = find_supporting_column(doc, start_pt, mm_to_internal)
    col_end = find_supporting_column(doc, end_pt, mm_to_internal)
    if col_start is None or col_end is None:
        forms.alert(
            "No supporting column detected at one or both ends. This tool "
            "assumes a column at both ends (S1 scope carried into S3).",
            title="Unsupported configuration",
        )
        script.exit()

    support_width_start_mm = column_width_along_axis_mm(col_start, axis, internal_to_mm)
    support_width_end_mm = column_width_along_axis_mm(col_end, axis, internal_to_mm)

    try:
        support_cover_start_mm = read_support_cover_mm(col_start, SUPPORT_SIDE_FACE_TYPE, doc, internal_to_mm)
        support_cover_end_mm = read_support_cover_mm(col_end, SUPPORT_SIDE_FACE_TYPE, doc, internal_to_mm)
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
    # ONE value per beam: it spans the section horizontally, so the SIDE
    # cover governs it, not either face cover (issue #16 review).
    spacer_length_section_mm = spacer_length_mm(b_mm, cover_side_mm, dia_stirrup_mm)

    # --- R1 (resolved, non-blocking): only meaningful with >1 stacked layer --
    warning_top = spacer_diameter_warning(dia_spacer_mm, dia_top_mm, d_agg_mm) if layers_top > 1 else None
    warning_btm = spacer_diameter_warning(dia_spacer_mm, dia_btm_mm, d_agg_mm) if layers_btm > 1 else None

    output.print_md("### S3 -- computed cross-section bar layout (rev 2 §4, §4.1, §6.1, §6.3)")
    output.print_md(
        "- b = {:.1f} mm, h = {:.1f} mm, cover_top = {:.1f} mm, cover_btm = {:.1f} mm, "
        "cover_side = {:.1f} mm, O_stirrup = {:.1f} mm".format(
            b_mm, h_mm, cover_top_mm, cover_btm_mm, cover_side_mm, dia_stirrup_mm
        )
    )
    output.print_md(
        "- spacer_length (§6.3, one horizontal dimension per section) = "
        "{:.1f} mm".format(spacer_length_section_mm)
    )
    output.print_md("#### Top face (O_TOP = {:.1f} mm) -- REPORTED ONLY, NOT PLACED (see #15)".format(dia_top_mm))
    for n, offset_mm in enumerate(top_layer_offsets_mm, start=1):
        output.print_md("- layer {}: offset_{} = {:.1f} mm".format(n, n, offset_mm))
    output.print_md("- corner-bar u positions ({} bars): {}".format(
        count_top, ", ".join("{:.1f}".format(u) for u in top_u_positions_mm)
    ))
    if warning_top:
        output.print_md("- **R1 warning (top):** {}".format(warning_top))

    output.print_md("#### Bottom face (O_BTM = {:.1f} mm) -- PLACED".format(dia_btm_mm))
    for n, offset_mm in enumerate(btm_layer_offsets_mm, start=1):
        output.print_md("- layer {}: offset_{} = {:.1f} mm".format(n, n, offset_mm))
    output.print_md("- corner-bar u positions ({} bars): {}".format(
        count_btm, ", ".join("{:.1f}".format(u) for u in btm_u_positions_mm)
    ))
    if warning_btm:
        output.print_md("- **R1 warning (bottom):** {}".format(warning_btm))

    total_bar_count = layers_top * count_top + layers_btm * count_btm
    output.print_md("- **Total bar count (both faces) = {}** ({} top, computed only; {} bottom, placed)".format(
        total_bar_count, layers_top * count_top, layers_btm * count_btm
    ))

    # --- bottom-face anchorage (S1 machinery, one diameter per face, A20) --
    ld_btm_mm = development_length(dia_btm_mm, ld_mult)
    try:
        anchorage_start = bottom_bar_anchorage(support_width_start_mm, support_cover_start_mm, ld_btm_mm)
        anchorage_end = bottom_bar_anchorage(support_width_end_mm, support_cover_end_mm, ld_btm_mm)
    except ValueError as ex:
        forms.alert(str(ex), title="Invalid anchorage input")
        script.exit()

    output.print_md(
        "- LD_btm = {} x {:.1f} = {:.1f} mm -> start: a={:.1f}, b={:.1f} mm; "
        "end: a={:.1f}, b={:.1f} mm".format(
            ld_mult, dia_btm_mm, ld_btm_mm,
            anchorage_start.a, anchorage_start.b, anchorage_end.a, anchorage_end.b,
        )
    )
    output.print_md(
        "*Placing {} bottom bar(s) per layer x {} layer(s) = {} bottom bars, "
        "each anchored at both ends per S1's machinery.*".format(
            count_btm, layers_btm, layers_btm * count_btm
        )
    )

    du_internal, dv_internal = beam_section_centre_offsets(beam, start_pt)

    def do_place():
        a_start_internal = mm_to_internal(anchorage_start.a)
        b_start_internal = mm_to_internal(anchorage_start.b)
        a_end_internal = mm_to_internal(anchorage_end.a)
        b_end_internal = mm_to_internal(anchorage_end.b)

        face_start = start_support_face_point(
            col_start, start_pt, axis, mm_to_internal(support_width_start_mm)
        )
        face_end = end_support_face_point(
            col_end, start_pt, axis, mm_to_internal(support_width_end_mm)
        )
        bend_direction = v_dir  # bottom bar bends upward, rev 2 §2.2
        norm = bend_plane_normal(axis, bend_direction)

        placed = []
        for layer_v_mm in btm_layer_offsets_mm:
            # Bottom layer offsets are measured UP from the bottom face, so
            # the layer's v coordinate (centred on the section centroid) is
            # negative: h/2 above the centroid is the top face, so the
            # bottom face is -h/2, and the layer sits `layer_v_mm` above it.
            v_mm = -(h_mm / 2.0) + layer_v_mm
            for u_mm in btm_u_positions_mm:
                bar_face_start, bar_face_end = bar_face_points_at_uv(
                    face_start, face_end, u_dir, v_dir,
                    du_internal, dv_internal, u_mm, v_mm, mm_to_internal,
                )

                curves = build_bottom_bar_curves(
                    bar_face_start, bar_face_end, axis, bend_direction,
                    a_start_internal, b_start_internal, a_end_internal, b_end_internal,
                )
                placed.append(place_anchored_bar(doc, beam, bar_type, curves, norm))
        return placed

    try:
        run_in_transaction(doc, "RFT S3 - place main bars (bottom face)", do_place)
    except Exception as ex:
        forms.alert(
            "Placement failed and was rolled back: {}".format(ex),
            title="Error",
        )
        script.exit()

    output.print_md("**Bottom-face bars placed successfully.**")


if __name__ == "__main__":
    main()
