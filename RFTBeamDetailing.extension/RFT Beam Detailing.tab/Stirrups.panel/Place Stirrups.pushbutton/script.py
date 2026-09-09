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

from rft.core.grades import (
    ROLE_STIRRUP,
    bar_type_for_role,
    hook_angle_guard_message,
    missing_bar_type_selection_message,
    missing_hook_type_selection_message,
    role_grade_report_line,
    role_picker_label,
)
from rft.core.guards import no_support_detected_message, stirrup_type3_guard_message
from rft.core.stirrups import (
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
    support_width_along_axis_mm,
    find_supporting_element,
    point_at_cc_offset,
    span_length_mm,
)
from rft.revit.bar_types import (
    bar_type_diameter_mm,
    hook_angle_deg,
    list_bar_types,
    list_hook_types,
)
from rft.revit.guards import continuous_run_guard
from rft.revit.host import HostValidationError, validate_rebar_host
from rft.revit.placement import bend_plane_normal, run_in_transaction
from rft.revit.stirrups import apply_maximum_spacing_layout, build_stirrup_curves, place_stirrup
from rft.revit.units import internal_to_mm, mm_to_internal

output = script.get_output()
doc = revit.doc


def select_bar_type_for_role(document, role):
    """Explicit per-role selection of a ``RebarBarType`` (rev 2 section
    1.1, A42, ticket #27; supersedes A35/S7's issue #20 model) -- NO
    fallback to "the first one found". Returns None if the document has
    no RebarBarType at all, or if the engineer cancels the picker. The
    picker's title carries A34's required grade for this role
    (``role_picker_label``), since grade can no longer be checked
    mechanically from the type itself.

    SHAPE UNVERIFIED -- see "Place Bottom Bar.pushbutton"'s identical
    docstring for ``pyrevit.forms.SelectFromList.show``'s unconfirmed
    signature.
    """
    bar_types = list_bar_types(document)
    if not bar_types:
        return None
    return forms.SelectFromList.show(
        bar_types,
        multiselect=False,
        name_attr="Name",
        title="Select RebarBarType -- {}".format(role_picker_label(role)),
        button_name="Select",
    )


def select_hook_type(document):
    """Explicit selection of the 180-degree RebarHookType used for
    stirrups (rev 2 section 7.3, A33; issue #25) -- NO fallback to "the
    first one found". Returns None if the document has no RebarHookType at
    all, or if the engineer cancels the picker.

    Whether the picked type's angle is ACTUALLY 180 degrees is checked
    separately, after selection, in ``main`` -- via ``hook_angle_deg``,
    which may itself come back unable to confirm the angle at all (issue
    #25's second open question). This function only removes the
    name-matching fallback; it does not and cannot validate the angle.

    SHAPE UNVERIFIED -- see "Place Bottom Bar.pushbutton"'s identical
    docstring for ``pyrevit.forms.SelectFromList.show``'s unconfirmed
    signature.
    """
    hook_types = list_hook_types(document)
    if not hook_types:
        return None
    return forms.SelectFromList.show(
        hook_types,
        multiselect=False,
        name_attr="Name",
        title="Select 180-degree RebarHookType (stirrups)",
        button_name="Select",
    )


def ask_inputs():
    components = [
        Label("Cover (mm):"),
        TextBox("cover", Text="25"),
        Label("Dense spacing, supports (mm, maximum):"),
        TextBox("dense_spacing", Text="150"),
        Label("Normal spacing, midspan (mm, maximum):"),
        TextBox("normal_spacing", Text="200"),
        Label("Closure type (1, 2 or 4 -- 3 is parked):"),
        TextBox("closure_type", Text="1"),
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
    dense_spacing_mm = float(values["dense_spacing"])
    normal_spacing_mm = float(values["normal_spacing"])
    closure_type = int(values["closure_type"])

    # --- A42 (ticket #27, supersedes A35/S7): one explicit per-role
    # RebarBarType selection, no fallback ---------------------------------
    stirrup_bar_type_selected = select_bar_type_for_role(doc, ROLE_STIRRUP)
    if stirrup_bar_type_selected is None:
        forms.alert(
            missing_bar_type_selection_message(ROLE_STIRRUP).message,
            title="RebarBarType selection required",
        )
        script.exit()
    bar_type = bar_type_for_role(ROLE_STIRRUP, stirrup_bar_type_selected)

    hook_type = select_hook_type(doc)
    if hook_type is None:
        forms.alert(missing_hook_type_selection_message().message, title="RebarHookType selection required")
        script.exit()

    # --- A42: the stirrup diameter comes FROM the selected type -- there
    # is no free-text Ø_stirrup to reconcile it against any more.
    dia_stirrup_mm = bar_type_diameter_mm(bar_type, internal_to_mm)

    stirrup_bar_type_id = getattr(bar_type, "Id", None)
    stirrup_bar_type_name = getattr(bar_type, "Name", "")

    # No mechanical grade-conflict guard here: this run holds only the mild
    # stirrup selection, with no high-tensile selection to compare it
    # against. The guard lives in "Place Main Bars", which holds all three
    # selections at once. Reading the beam's already-placed rebar to
    # compare across runs was tried and removed (issue #27 review): it
    # rested on an unconfirmed `Rebar.GetHostId()` and failed OPEN, so it
    # would have looked like a guard while protecting nothing.

    # --- issue #25: read back the selected hook's own angle where
    # possible and BLOCK if it is not 180 degrees. If it cannot be read
    # back at all, this does NOT block -- it is reported as UNVERIFIED in
    # the output below (issue #25 stays open for a live-host session
    # rather than being falsely closed by an assumption).
    hook_type_name = getattr(hook_type, "Name", None)
    hook_angle_deg_value = hook_angle_deg(hook_type)
    hook_angle_unverified = hook_angle_deg_value is None
    if not hook_angle_unverified:
        hook_angle_violation = hook_angle_guard_message(hook_angle_deg_value, hook_type_name=hook_type_name or "")
        if hook_angle_violation:
            forms.alert(hook_angle_violation.message, title="Stirrup hook angle is not 180 degrees")
            script.exit()

    b_mm, h_mm = beam_section_dimensions_mm(beam, internal_to_mm)
    start_pt, end_pt = beam_endpoints(beam)
    axis = beam_axis_direction(beam)

    # --- S9 guard, run BEFORE any placement work (rev 2 section 9 item 2,
    # A39) -- see "Place Bottom Bar.pushbutton" for the same wiring and its
    # rationale.
    continuous_guards = [
        g for g in (
            continuous_run_guard(doc, beam, start_pt, mm_to_internal, "Start end", exclude_element_id=beam.Id),
            continuous_run_guard(doc, beam, end_pt, mm_to_internal, "End end", exclude_element_id=beam.Id),
        ) if g is not None
    ]
    if continuous_guards:
        forms.alert(
            "\n\n".join(g.message for g in continuous_guards),
            title="Continuous run detected -- refused",
        )
        script.exit()

    col_start = find_supporting_element(doc, start_pt, mm_to_internal, exclude_element_id=beam.Id)
    col_end = find_supporting_element(doc, end_pt, mm_to_internal, exclude_element_id=beam.Id)
    if col_start is None or col_end is None:
        missing = [
            no_support_detected_message(label)
            for label, found in (("Start end", col_start), ("End end", col_end))
            if found is None
        ]
        forms.alert(
            "\n\n".join(g.message for g in missing),
            title="Unsupported configuration",
        )
        script.exit()

    l_mm = span_length_mm(col_start, col_end, internal_to_mm)
    support_width_start_mm = support_width_along_axis_mm(col_start, axis, internal_to_mm)
    support_width_end_mm = support_width_along_axis_mm(col_end, axis, internal_to_mm)
    face_a_offset_mm = support_width_start_mm / 2.0
    face_b_offset_mm = support_width_end_mm / 2.0

    try:
        zones = stirrup_zones_mm(l_mm, face_a_offset_mm, face_b_offset_mm)
    except ValueError as ex:
        forms.alert(str(ex), title="Degenerate zone")
        script.exit()

    # --- S9 guard (rev 2 section 7.2, A31): stirrup type 3 is rejected
    # outright, before any zone/leg-geometry computation runs.
    if closure_type == 3:
        forms.alert(stirrup_type3_guard_message().message, title="Stirrup type 3 is parked")
        script.exit()

    try:
        width_mm, height_mm = centreline_leg_dimensions_mm(b_mm, h_mm, cover_mm, dia_stirrup_mm)
        endpoints_mm = stirrup_curve_endpoints_mm(closure_type, width_mm, height_mm)
    except ValueError as ex:
        forms.alert(str(ex), title="Invalid stirrup geometry")
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
    output.print_md("- " + role_grade_report_line(ROLE_STIRRUP, stirrup_bar_type_name))
    output.print_md(
        "- CENTRELINE rectangle = {:.1f} x {:.1f} mm (b={:.1f}, h={:.1f}, "
        "Cover={:.1f}, O_stirrup={:.1f})".format(width_mm, height_mm, b_mm, h_mm, cover_mm, dia_stirrup_mm)
    )
    output.print_md("- L (c/c) = {:.1f} mm, closure type = {}".format(l_mm, closure_type))

    # --- issue #25: exactly which hook type was used, and whether its
    # angle could be verified, always printed regardless of the outcome.
    if hook_angle_unverified:
        output.print_md(
            "- **Hook type used: '{}'.** Its angle could NOT be read back "
            "and verified against the required 180 degrees (rev 2 section "
            "7.3, A33) -- see issue #25, still open. Confirm the 180-degree "
            "angle manually before relying on this beam's stirrups.".format(
                hook_type_name or "<unnamed>"
            )
        )
    else:
        output.print_md(
            "- Hook type used: '{}', angle read back and verified = {:.1f} "
            "degrees (rev 2 section 7.3, A33).".format(hook_type_name or "<unnamed>", hook_angle_deg_value)
        )

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
