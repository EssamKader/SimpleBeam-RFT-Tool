# -*- coding: utf-8 -*-
"""S6 -- crack / skin reinforcement for deep beams (rev 2 section 5;
A22-A26 as amended by A42; residual question R2). See
specs/beam-rft-detailing.md S6 and GitHub issue #19.

Pipeline established by S1's tracer bullet, reused here: pick beam ->
validate host -> read geometry -> compute crack-bar layout + embedment ->
place -> commit transaction -> report.

SCOPE, per this ticket's brief:
- Only fires when h > 700 mm (section 5, strict >). h <= 700 mm reports
  "not triggered" and places nothing -- not an error.
- Crack bars run the FULL SPAN, embedding straight into the support with
  NO HOOK (A23) -- section 2's anchorage machinery (the LD split, section
  2.3's cap/clamp/mandatory-hook rule) is never applied here. A supported
  end's embedment is `support_width - support_cover` (R2); an unsupported
  end runs straight to `beam end - cover`, mirroring section 2.5/A12,
  reported EXPLICITLY as an unsupported end (see
  `rft.core.crack_bars.crack_bar_end_result`).
- Diameter comes from an explicit `ROLE_CRACK` `RebarBarType` selection
  (A42, superseding A22's original free-text `Ø_crack` input -- see this
  ticket's brief, which corrects the ticket's own out-of-date acceptance
  criterion).
- Crack bars are EXEMPT from section 6.2 spacing validation (A25) -- no
  such validation is run here, by design; see
  `rft.core.crack_bars.spacing_validation_exemption_note`.
- Top/bottom main bar types and the stirrup type are selected here too,
  even though this pushbutton places neither -- their diameters and the
  stirrup diameter feed section 4's layer-offset formula (A26: H_avail is
  measured to the INNERMOST main bar layer), exactly as "Place Main
  Bars.pushbutton" selects the stirrup type for the same reason without
  placing it.
"""

from pyrevit import DB, forms, revit, script
from pyrevit.forms import Button, FlexForm, Label, TextBox

from rft.core.crack_bars import (
    DEFAULT_S_MAX_MM,
    available_height_mm,
    crack_bar_end_result,
    crack_bar_u_positions_mm,
    crack_layer_plan,
    crack_layer_v_positions_mm,
    crack_reinforcement_triggered,
    spacing_validation_exemption_note,
)
from rft.core.grades import (
    ROLE_BOTTOM_MAIN,
    ROLE_CRACK,
    ROLE_STIRRUP,
    ROLE_TOP_MAIN,
    bar_type_for_role,
    missing_bar_type_selection_message,
    role_grade_report_line,
    role_picker_label,
    stirrup_grade_conflict_message,
)
from rft.core.guards import free_end_guard_message
from rft.core.layout import layer_offset_mm
from rft.revit.bar_types import bar_type_diameter_mm, list_bar_types
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
from rft.revit.guards import continuous_run_guard
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

# Same THREE-cover situation "Place Main Bars.pushbutton" documents, plus a
# FOURTH here: the SUPPORTING element's own cover (rev 2 section 2.4, A8),
# used for the crack bar's embedment (R2) -- distinct again from all three
# beam-side covers below. See that pushbutton's module-level comment for
# the shared SHAPE UNVERIFIED caveat on RebarFaceType/RebarHostData this
# constant carries.
SUPPORT_SIDE_FACE_TYPE = DB.Structure.RebarFaceType.Other
BEAM_SIDE_FACE_TYPE = DB.Structure.RebarFaceType.Other
BEAM_END_FACE_TYPE = DB.Structure.RebarFaceType.Other


def select_bar_type_for_role(document, role):
    """Explicit per-role selection of a ``RebarBarType`` (rev 2 section
    1.1, A42) -- NO fallback to "the first one found". Identical to every
    other pushbutton's helper of the same name; see "Place Bottom
    Bar.pushbutton" for the full docstring, including the
    SHAPE UNVERIFIED note on ``pyrevit.forms.SelectFromList.show``.
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


def ask_inputs():
    components = [
        Label("Spacer diameter O_spacer (mm, clear gap between main bar layers, A19):"),
        TextBox("dia_spacer", Text="16"),
        Label("Number of top main bar layers (1-5, for H_avail's innermost offset, A26):"),
        TextBox("layers_top", Text="1"),
        Label("Number of bottom main bar layers (1-5, for H_avail's innermost offset, A26):"),
        TextBox("layers_btm", Text="1"),
        Label("Max spacing between crack-bar layers, s_max (mm, section 5.2, A36 default {:.0f}):".format(
            DEFAULT_S_MAX_MM
        )),
        TextBox("s_max", Text=str(int(DEFAULT_S_MAX_MM))),
        Button("Place crack/skin bars"),
    ]
    form = FlexForm("S6 - Place crack/skin bars", components)
    form.show()
    if not form.values:
        script.exit()
    return form.values


def _end_support(doc, point, axis, beam_id):
    """Detect the support at one beam end (rev 2 section 2.4, A9). Same
    helper as "Place Main Bars.pushbutton" -- a free/cantilever end
    returns (None, None), the unsupported path (section 2.5/A14).
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
    dia_spacer_mm = float(values["dia_spacer"]) if values["dia_spacer"] else 16.0
    layers_top = int(values["layers_top"])
    layers_btm = int(values["layers_btm"])
    s_max_mm = float(values["s_max"])

    # --- A42: one explicit RebarBarType selection per role, no fallback --
    crack_bar_type_selected = select_bar_type_for_role(doc, ROLE_CRACK)
    if crack_bar_type_selected is None:
        forms.alert(missing_bar_type_selection_message(ROLE_CRACK).message, title="RebarBarType selection required")
        script.exit()
    crack_bar_type = bar_type_for_role(ROLE_CRACK, crack_bar_type_selected)

    # Top/bottom main bar types and the stirrup type are selected here too,
    # even though NONE of the three is placed by this pushbutton -- their
    # diameters feed section 4's layer-offset formula, which A26 requires
    # for H_avail (measured to the INNERMOST main bar layer). Typing these
    # diameters instead would reintroduce the two-sources-of-truth defect
    # A42 exists to remove (issue #27 review) -- the same reasoning "Place
    # Main Bars.pushbutton" already applies to its own stirrup selection.
    top_bar_type_selected = select_bar_type_for_role(doc, ROLE_TOP_MAIN)
    if top_bar_type_selected is None:
        forms.alert(missing_bar_type_selection_message(ROLE_TOP_MAIN).message, title="RebarBarType selection required")
        script.exit()
    top_bar_type = bar_type_for_role(ROLE_TOP_MAIN, top_bar_type_selected)

    btm_bar_type_selected = select_bar_type_for_role(doc, ROLE_BOTTOM_MAIN)
    if btm_bar_type_selected is None:
        forms.alert(missing_bar_type_selection_message(ROLE_BOTTOM_MAIN).message, title="RebarBarType selection required")
        script.exit()
    btm_bar_type = bar_type_for_role(ROLE_BOTTOM_MAIN, btm_bar_type_selected)

    stirrup_bar_type_selected = select_bar_type_for_role(doc, ROLE_STIRRUP)
    if stirrup_bar_type_selected is None:
        forms.alert(missing_bar_type_selection_message(ROLE_STIRRUP).message, title="RebarBarType selection required")
        script.exit()
    stirrup_bar_type = bar_type_for_role(ROLE_STIRRUP, stirrup_bar_type_selected)

    dia_crack_mm = bar_type_diameter_mm(crack_bar_type, internal_to_mm)
    dia_top_mm = bar_type_diameter_mm(top_bar_type, internal_to_mm)
    dia_btm_mm = bar_type_diameter_mm(btm_bar_type, internal_to_mm)
    dia_stirrup_mm = bar_type_diameter_mm(stirrup_bar_type, internal_to_mm)

    crack_bar_type_name = getattr(crack_bar_type, "Name", "")
    top_bar_type_name = getattr(top_bar_type, "Name", "")
    btm_bar_type_name = getattr(btm_bar_type, "Name", "")
    stirrup_bar_type_name = getattr(stirrup_bar_type, "Name", "")

    # --- A42 mechanical grade-conflict guard: this run holds the mild
    # stirrup selection AND three high-tensile selections (crack, top,
    # bottom) at once -- one RebarBarType element cannot be both grades.
    conflicts = [
        c for c in (
            stirrup_grade_conflict_message(
                getattr(stirrup_bar_type, "Id", None), stirrup_bar_type_name,
                getattr(crack_bar_type, "Id", None), crack_bar_type_name, ROLE_CRACK,
            ),
            stirrup_grade_conflict_message(
                getattr(stirrup_bar_type, "Id", None), stirrup_bar_type_name,
                getattr(top_bar_type, "Id", None), top_bar_type_name, ROLE_TOP_MAIN,
            ),
            stirrup_grade_conflict_message(
                getattr(stirrup_bar_type, "Id", None), stirrup_bar_type_name,
                getattr(btm_bar_type, "Id", None), btm_bar_type_name, ROLE_BOTTOM_MAIN,
            ),
        ) if c is not None
    ]
    if conflicts:
        forms.alert("\n\n".join(c.message for c in conflicts), title="Stirrup/main bar grade conflict")
        script.exit()

    # --- THREE beam-side covers, read once each, never substituted for one
    # another (issue #16/S3 review; see "Place Main Bars.pushbutton"'s
    # module comment for the full rationale):
    #   cover_top/cover_btm -> H_avail (a VERTICAL quantity, section 5.1)
    #   cover_side          -> A24's horizontal crack-bar inset
    #   cover_end           -> the beam's own end-face cover, unsupported
    #                          ends only (R2, mirroring section 2.5/A12)
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

    # --- S9 guard, run BEFORE any placement work (rev 2 section 9 item 2,
    # A39) -- see "Place Bottom Bar.pushbutton" for the same wiring and its
    # rationale (REFUSED, not warned).
    continuous_guards = [
        g for g in (
            continuous_run_guard(doc, beam, start_pt, mm_to_internal, "Start end", exclude_element_id=beam.Id),
            continuous_run_guard(doc, beam, end_pt, mm_to_internal, "End end", exclude_element_id=beam.Id),
        ) if g is not None
    ]
    if continuous_guards:
        forms.alert("\n\n".join(g.message for g in continuous_guards), title="Continuous run detected -- refused")
        script.exit()

    # --- section 5 trigger: h from the SAME rotation-aware bounding-box
    # read every other pushbutton uses -- never from a typed input, so
    # there is exactly one source of truth for h.
    output.print_md("### S6 -- crack/skin reinforcement (rev 2 section 5)")
    output.print_md("- b = {:.1f} mm, h = {:.1f} mm".format(b_mm, h_mm))
    if not crack_reinforcement_triggered(h_mm):
        output.print_md(
            "- **Section 5 does NOT fire**: h = {:.1f} mm <= {:.0f} mm. "
            "n_crack_layers = 0. No crack/skin bars are placed.".format(h_mm, 700.0)
        )
        script.exit()

    # --- A26: H_avail measured to the INNERMOST main bar layer, i.e. the
    # LAST layer (layers_top / layers_btm), not layer 1.
    try:
        offset_top_innermost_mm = layer_offset_mm(
            cover_top_mm, dia_stirrup_mm, dia_top_mm, dia_spacer_mm, layers_top
        )
        offset_btm_innermost_mm = layer_offset_mm(
            cover_btm_mm, dia_stirrup_mm, dia_btm_mm, dia_spacer_mm, layers_btm
        )
    except ValueError as ex:
        forms.alert(str(ex), title="Invalid layer count")
        script.exit()

    h_avail_mm = available_height_mm(h_mm, offset_top_innermost_mm, offset_btm_innermost_mm)

    try:
        plan = crack_layer_plan(h_avail_mm, s_max_mm)
    except ValueError as ex:
        forms.alert(str(ex), title="Invalid crack-bar layer plan")
        script.exit()

    v_positions_mm = crack_layer_v_positions_mm(
        h_mm, offset_btm_innermost_mm, plan.n_crack_layers, plan.actual_spacing_mm
    )
    u_left_mm, u_right_mm = crack_bar_u_positions_mm(b_mm, cover_side_mm, dia_stirrup_mm, dia_crack_mm)

    output.print_md("- " + role_grade_report_line(ROLE_CRACK, crack_bar_type_name))
    output.print_md(
        "- " + role_grade_report_line(ROLE_TOP_MAIN, top_bar_type_name)
        + " (feeds H_avail only; no top bar is placed by this pushbutton)"
    )
    output.print_md(
        "- " + role_grade_report_line(ROLE_BOTTOM_MAIN, btm_bar_type_name)
        + " (feeds H_avail only; no bottom bar is placed by this pushbutton)"
    )
    output.print_md(
        "- " + role_grade_report_line(ROLE_STIRRUP, stirrup_bar_type_name)
        + " (positions the crack bars horizontally; no stirrup is placed by this pushbutton)"
    )
    output.print_md(
        "- cover_top = {:.1f} mm, cover_btm = {:.1f} mm, cover_side = {:.1f} mm, "
        "cover_end = {:.1f} mm".format(cover_top_mm, cover_btm_mm, cover_side_mm, cover_end_mm)
    )
    output.print_md(
        "- offset_top (innermost, layer {}) = {:.1f} mm, offset_btm (innermost, layer {}) "
        "= {:.1f} mm (A26)".format(layers_top, offset_top_innermost_mm, layers_btm, offset_btm_innermost_mm)
    )
    output.print_md("- H_avail = {:.1f} mm (section 5.1)".format(h_avail_mm))
    output.print_md(
        "- n_gaps = {}, n_crack_layers = {}, actual_spacing = {:.1f} mm "
        "(max s_max = {:.1f} mm, section 5.2)".format(
            plan.n_gaps, plan.n_crack_layers, plan.actual_spacing_mm, s_max_mm
        )
    )
    output.print_md(
        "- u positions (A24): left = {:.1f} mm, right = {:.1f} mm".format(u_left_mm, u_right_mm)
    )
    output.print_md("- " + spacing_validation_exemption_note())

    if plan.n_crack_layers == 0:
        output.print_md(
            "- **n_crack_layers = 0**: H_avail <= s_max, a legitimate outcome "
            "(section 5.2) -- no crack/skin bars are placed."
        )
        script.exit()

    # --- rev 2 section 2.4/2.5 (A9/A12/A14): support detection, per end.
    support_start, support_width_start_mm = _end_support(doc, start_pt, axis, beam.Id)
    support_end, support_width_end_mm = _end_support(doc, end_pt, axis, beam.Id)
    is_supported_start = support_start is not None
    is_supported_end = support_end is not None

    if not is_supported_start and not is_supported_end:
        forms.alert(
            "No support (column, wall or girder) detected at EITHER end "
            "(rev 2 section 2.4/2.5, A9/A12/A14). This tool details a "
            "single-span, simply-supported beam -- a beam with no support "
            "at all is not a span and is refused outright rather than "
            "silently detailed (this specific hard-stop is this project's "
            "own judgement call, not a rev 2 rule; A14's own requirement is "
            "only to WARN at a free end, which is what happens below when "
            "just ONE end is unsupported).",
            title="No support detected",
        )
        script.exit()

    # A14 requires a WARNING at a free end, not merely a geometric report
    # line. This pushbutton DOES implement the unsupported-end path (R2's
    # straight run), so the right guard is `free_end_guard_message` (warn
    # and proceed), never `no_support_detected_message` (refuse, for
    # pushbuttons that do not implement that path). Without this, an
    # engineer detailing a cantilever is told the geometry but never told
    # the configuration is out of scope for v1.
    free_end_warnings = [
        g for g in (
            None if is_supported_start else free_end_guard_message("Start end"),
            None if is_supported_end else free_end_guard_message("End end"),
        ) if g is not None
    ]

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

    result_start = crack_bar_end_result(
        is_supported_start,
        support_width_mm=support_width_start_mm,
        support_cover_mm=support_cover_start_mm,
        beam_end_cover_mm=cover_end_mm,
    )
    result_end = crack_bar_end_result(
        is_supported_end,
        support_width_mm=support_width_end_mm,
        support_cover_mm=support_cover_end_mm,
        beam_end_cover_mm=cover_end_mm,
    )

    def _format_end(label, result):
        if result.is_supported:
            output.print_md(
                "- {}: supported, embedment = {:.1f} mm, straight, no hook "
                "(A23, R2)".format(label, result.embedment_mm)
            )
        else:
            output.print_md(
                "- {}: **UNSUPPORTED** -- no support width to embed into. "
                "Straight run terminating {:.1f} mm short of the beam's own "
                "end (R2, mirroring section 2.5/A12 -- this ticket's "
                "interpretation of R2, not a rule section 5 itself "
                "states).".format(label, result.terminates_short_of_end_mm)
            )

    _format_end("Start end", result_start)
    _format_end("End end", result_end)

    for g in free_end_warnings:
        output.print_md("- **WARNING ({}):** {}".format(g.spec_section, g.message))

    total_bar_count = plan.n_crack_layers * 2
    output.print_md("- **Total crack/skin bar count = {}** (2 per layer x {} layers)".format(
        total_bar_count, plan.n_crack_layers
    ))

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

    a_start_internal = (
        mm_to_internal(result_start.embedment_mm) if is_supported_start else cover_end_internal
    )
    a_end_internal = (
        mm_to_internal(result_end.embedment_mm) if is_supported_end else cover_end_internal
    )

    def do_place():
        placed = []
        for v_mm in v_positions_mm:
            for u_mm in (u_left_mm, u_right_mm):
                bar_ref_start = bar_point_at_uv(
                    ref_start, u_dir, v_dir, du_internal, dv_internal, u_mm, v_mm, mm_to_internal
                )
                bar_ref_end = bar_point_at_uv(
                    ref_end, u_dir, v_dir, du_internal, dv_internal, u_mm, v_mm, mm_to_internal
                )
                # A23: no hook -- b_internal is always None, so
                # main_bar_end_geometry returns a straight corner point at
                # both ends regardless of support, and build_main_bar_curves
                # below emits a single straight segment, never a bend.
                corner_start, bend_start = main_bar_end_geometry(
                    is_supported_start, bar_ref_start, axis, True, a_start_internal, None
                )
                corner_end, bend_end = main_bar_end_geometry(
                    is_supported_end, bar_ref_end, axis, False, a_end_internal, None
                )
                curves = build_main_bar_curves(corner_start, corner_end, v_dir, bend_start, bend_end)
                norm = bend_plane_normal(axis, v_dir)
                placed.append(place_anchored_bar(doc, beam, crack_bar_type, curves, norm))
        return placed

    try:
        run_in_transaction(doc, "RFT S6 - place crack/skin bars", do_place)
    except Exception as ex:
        forms.alert("Placement failed and was rolled back: {}".format(ex), title="Error")
        script.exit()

    output.print_md("**Crack/skin bars placed successfully.**")


if __name__ == "__main__":
    main()
