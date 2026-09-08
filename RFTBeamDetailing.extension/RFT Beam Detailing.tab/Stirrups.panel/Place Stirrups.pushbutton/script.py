# -*- coding: utf-8 -*-
"""S5 -- place a full 3-zone stirrup cage on a single-span beam.

Pipeline established by S1's tracer bullet, reused here: pick beam ->
validate host -> read geometry -> compute (this time stirrup leg geometry
and 3-zone distribution) -> place -> commit transaction -> report. See
specs/beam-rft-detailing.md S5 and GitHub issue #18.

Minimal FlexForm only (S1's style) -- the rich cross-field-validated WPF
form is S8's scope (issue #21), not this ticket's.
"""

from pyrevit import DB, forms, revit, script
from pyrevit.forms import Button, FlexForm, Label, TextBox

from rft.core.stirrups import (
    TYPE3_PARKED_MESSAGE,
    ZONE_LAYOUT_FLAGS,
    centreline_leg_dimensions_mm,
    stirrup_count_and_spacing,
    stirrup_curve_endpoints_mm,
    stirrup_zones_mm,
    zone_array_length_mm,
)
from rft.revit.geometry import (
    beam_axis_direction,
    beam_endpoints,
    beam_section_axes,
    beam_section_centre_offsets,
    beam_section_dimensions_mm,
    column_width_along_axis_mm,
    find_supporting_column,
    point_at_cc_offset,
    span_length_mm,
)
from rft.revit.host import HostValidationError, validate_rebar_host
from rft.revit.placement import bend_plane_normal, run_in_transaction
from rft.revit.stirrups import apply_maximum_spacing_layout, build_stirrup_curves, place_stirrup
from rft.revit.units import internal_to_mm, mm_to_internal

output = script.get_output()
doc = revit.doc


def resolve_bar_type(document, requested_name):
    """The mild St 24/35 RebarBarType by name (rev 2 §7.3, §1.1). Matches
    S1's ``resolve_bar_type`` pattern -- first available if unset/not found.
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


def resolve_hook_type(document, requested_name):
    """The 180 deg semicircular RebarHookType by name (rev 2 §7.3, A33).
    Same fallback pattern as ``resolve_bar_type``.
    """
    hook_types = list(
        DB.FilteredElementCollector(document).OfClass(DB.Structure.RebarHookType)
    )
    if not hook_types:
        raise HostValidationError("No RebarHookType exists in this document.")
    if requested_name:
        for ht in hook_types:
            if ht.Name == requested_name:
                return ht
        output.print_md(
            "*No RebarHookType named '{}' found -- falling back to '{}'.*".format(
                requested_name, hook_types[0].Name
            )
        )
    return hook_types[0]


def ask_inputs():
    components = [
        Label("Cover (mm):"),
        TextBox("cover", Text="25"),
        Label("Stirrup diameter O_stirrup (mm):"),
        TextBox("dia_stirrup", Text="10"),
        Label("Dense spacing, supports (mm, maximum):"),
        TextBox("dense_spacing", Text="150"),
        Label("Normal spacing, midspan (mm, maximum):"),
        TextBox("normal_spacing", Text="200"),
        Label("Closure type (1, 2 or 4 -- 3 is parked):"),
        TextBox("closure_type", Text="1"),
        Label("RebarBarType name, mild St 24/35 (blank = first available):"),
        TextBox("bar_type_name", Text=""),
        Label("RebarHookType name, 180 deg (blank = first available):"),
        TextBox("hook_type_name", Text=""),
        Button("Place stirrups"),
    ]
    form = FlexForm("S5 - Place stirrups", components)
    form.show()
    if not form.values:
        script.exit()
    return form.values


def main():
    beam = revit.pick_element(message="Select a beam (structural framing) to detail.")
    if beam is None:
        script.exit()

    try:
        validate_rebar_host(beam)
    except HostValidationError as ex:
        forms.alert(str(ex), title="Host validation failed")
        script.exit()

    values = ask_inputs()
    cover_mm = float(values["cover"])
    dia_stirrup_mm = float(values["dia_stirrup"])
    dense_spacing_mm = float(values["dense_spacing"])
    normal_spacing_mm = float(values["normal_spacing"])
    closure_type = int(values["closure_type"])
    bar_type = resolve_bar_type(doc, values.get("bar_type_name"))
    hook_type = resolve_hook_type(doc, values.get("hook_type_name"))

    b_mm, h_mm = beam_section_dimensions_mm(beam, internal_to_mm)
    start_pt, end_pt = beam_endpoints(beam)
    axis = beam_axis_direction(beam)

    col_start = find_supporting_column(doc, start_pt, mm_to_internal)
    col_end = find_supporting_column(doc, end_pt, mm_to_internal)
    if col_start is None or col_end is None:
        forms.alert(
            "No supporting column detected at one or both ends. This tool "
            "assumes a column at both ends (S1 scope carried into S5).",
            title="Unsupported configuration",
        )
        script.exit()

    l_mm = span_length_mm(col_start, col_end, internal_to_mm)
    support_width_start_mm = column_width_along_axis_mm(col_start, axis, internal_to_mm)
    support_width_end_mm = column_width_along_axis_mm(col_end, axis, internal_to_mm)
    face_a_offset_mm = support_width_start_mm / 2.0
    face_b_offset_mm = support_width_end_mm / 2.0

    try:
        zones = stirrup_zones_mm(l_mm, face_a_offset_mm, face_b_offset_mm)
    except ValueError as ex:
        forms.alert(str(ex), title="Degenerate zone")
        script.exit()

    try:
        width_mm, height_mm = centreline_leg_dimensions_mm(b_mm, h_mm, cover_mm, dia_stirrup_mm)
        endpoints_mm = stirrup_curve_endpoints_mm(closure_type, width_mm, height_mm)
    except ValueError as ex:
        title = "Stirrup type 3 is parked" if closure_type == 3 else "Invalid stirrup geometry"
        forms.alert(str(ex), title=title)
        script.exit()

    zone_specs = [
        ("zone1", zones.zone1, dense_spacing_mm, ZONE_LAYOUT_FLAGS["zone1"]),
        ("zone2", zones.zone2, normal_spacing_mm, ZONE_LAYOUT_FLAGS["zone2"]),
        ("zone3", zones.zone3, dense_spacing_mm, ZONE_LAYOUT_FLAGS["zone3"]),
    ]

    zone_results = {}
    for name, zone, max_spacing_mm, (include_first, include_last) in zone_specs:
        array_length_mm = zone_array_length_mm(zone)
        try:
            zone_results[name] = stirrup_count_and_spacing(
                array_length_mm, max_spacing_mm, include_first, include_last
            )
        except ValueError as ex:
            forms.alert(str(ex), title="Degenerate zone")
            script.exit()

    output.print_md("### S5 -- computed stirrup geometry and distribution (rev 2 §3, §7)")
    output.print_md(
        "- CENTRELINE rectangle = {:.1f} x {:.1f} mm (b={:.1f}, h={:.1f}, "
        "Cover={:.1f}, O_stirrup={:.1f})".format(width_mm, height_mm, b_mm, h_mm, cover_mm, dia_stirrup_mm)
    )
    output.print_md("- L (c/c) = {:.1f} mm, closure type = {}".format(l_mm, closure_type))

    beam_total = 0
    u_dir, v_dir = beam_section_axes(beam)
    norm = bend_plane_normal(u_dir, v_dir)

    # The core returns corners about the section CENTROID, but a station
    # point sits on the beam's LOCATION CURVE -- with Revit's default
    # top-justified structural framing those differ by h/2, which would
    # build the whole cage outside the beam (issue #18 review finding #1).
    du_internal, dv_internal = beam_section_centre_offsets(beam, start_pt)
    output.print_md(
        "- Section centroid offset from the beam's location curve: "
        "du = {:.1f} mm, dv = {:.1f} mm".format(
            internal_to_mm(du_internal), internal_to_mm(dv_internal)
        )
    )

    for name, zone, max_spacing_mm, (include_first, include_last) in zone_specs:
        result = zone_results[name]
        array_length_mm = zone_array_length_mm(zone)
        beam_total += result.count
        output.print_md(
            "- {}: [{:.1f}, {:.1f}] mm, array length = {:.1f} mm, "
            "achieved spacing = {:.1f} mm (max {:.1f} mm), count = {}".format(
                name, zone.start, zone.end, array_length_mm, result.spacing_mm, max_spacing_mm, result.count
            )
        )
    output.print_md("- **Beam total stirrup count = {}**".format(beam_total))

    def do_place():
        placed = []
        for name, zone, max_spacing_mm, (include_first, include_last) in zone_specs:
            array_length_mm = zone_array_length_mm(zone)
            station_internal = point_at_cc_offset(
                start_pt, axis, col_start, zone.start, mm_to_internal
            )
            origin_internal = (
                station_internal
                + u_dir.Multiply(du_internal)
                + v_dir.Multiply(dv_internal)
            )
            curves = build_stirrup_curves(origin_internal, u_dir, v_dir, endpoints_mm, mm_to_internal)
            rebar = place_stirrup(doc, beam, bar_type, hook_type, curves, norm)
            apply_maximum_spacing_layout(
                rebar,
                mm_to_internal(max_spacing_mm),
                mm_to_internal(array_length_mm),
                include_first,
                include_last,
            )
            placed.append(rebar)
        return placed

    try:
        run_in_transaction(doc, "RFT S5 - place stirrups", do_place)
    except Exception as ex:
        forms.alert(
            "Placement failed and was rolled back: {}".format(ex),
            title="Error",
        )
        script.exit()

    output.print_md("**Stirrups placed successfully.**")


if __name__ == "__main__":
    main()
