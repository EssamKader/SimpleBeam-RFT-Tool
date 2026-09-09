# -*- coding: utf-8 -*-
"""S1 tracer bullet -- place one anchored bottom main bar end-to-end.

Deliberately the thinnest possible vertical slice: one bar, one face, both
anchored ends. Establishes the pipeline every later story inherits: pick
beam -> validate host -> read geometry -> compute anchorage -> place bar ->
commit transaction -> report. See specs/beam-rft-detailing.md S1 and
GitHub issue #14.

Corrected per issue #14 review: the bar is placed as a 3-segment curve list
anchored at BOTH ends -- bend leg `b` at end A (up), one continuous
straight run spanning the beam plus `a` into each support, bend leg `b` at
end B (up) -- not a 2-segment stub at one end. The ticket's original
"2-segment" wording described one end only and contradicted its own
both-ends acceptance criteria.
"""

from pyrevit import DB, forms, revit, script
from pyrevit.forms import Button, FlexForm, Label, TextBox

from rft.core.anchorage import DEFAULT_LD_BTM_MULTIPLIER, bottom_bar_anchorage, development_length
from rft.core.grades import (
    ROLE_BOTTOM_MAIN,
    bar_type_for_role,
    missing_bar_type_selection_message,
    role_grade_report_line,
    role_picker_label,
)
from rft.core.guards import no_support_detected_message
from rft.revit.bar_types import bar_type_diameter_mm, list_bar_types
from rft.revit.geometry import (
    beam_axis_direction,
    beam_endpoints,
    beam_section_dimensions_mm,
    support_width_along_axis_mm,
    end_support_face_point,
    find_supporting_element,
    span_length_mm,
    start_support_face_point,
)
from rft.revit.guards import continuous_run_guard
from rft.revit.host import HostValidationError, read_support_cover_mm, validate_rebar_host
from rft.revit.placement import bend_plane_normal, build_bottom_bar_curves, place_anchored_bar, run_in_transaction
from rft.revit.units import internal_to_mm, mm_to_internal

output = script.get_output()
doc = revit.doc

# UNVERIFIED AGAINST A LIVE HOST -- issue #14 review finding #4: `Bottom`
# (the column's BASE face) was definitely wrong for a bar entering the
# column horizontally, which is governed by a SIDE face cover instead.
# `Other` is the best-documented candidate: RebarHostData exposes distinct
# `Exterior`/`Interior` cover only for walls (per-face parameters
# CLEAR_COVER_EXTERIOR/CLEAR_COVER_INTERIOR); "most hosts" -- which
# includes columns -- instead expose CLEAR_COVER_TOP/CLEAR_COVER_BOTTOM/
# CLEAR_COVER_OTHER, where `Other` covers every side face lumped together
# (a column has no single "exterior" side the way a wall does). This
# remains unconfirmed without a live host -- see
# docs/verification/s1-tracer-bullet.md and rft/revit/host.py's module
# docstring, which flags a deeper concern: research now suggests the real
# `RebarHostData` API may be `GetExposedFaces()` / `GetCoverType(Reference)`
# rather than a `RebarFaceType`-keyed `GetFaces`/`GetCoverType` pair at all.
SUPPORT_SIDE_FACE_TYPE = DB.Structure.RebarFaceType.Other


def select_bar_type_for_role(document, role):
    """Explicit per-role selection of a ``RebarBarType`` (rev 2 section
    1.1, A42; S7/#20, superseded by #27) -- NO fallback to "the first one
    found". Returns None if the document has no RebarBarType at all, or if
    the engineer cancels the picker. The picker's title carries A34's
    required grade for this role (``role_picker_label``), since grade can
    no longer be checked mechanically from the type itself.

    SHAPE UNVERIFIED -- ``pyrevit.forms.SelectFromList.show(items,
    multiselect=False, name_attr=..., title=..., button_name=...)`` is the
    standard pyRevit dropdown/list-picker component; its exact signature
    could not be confirmed against documentation in this environment (no
    pyRevit installation here). This call itself has never executed --
    see docs/verification/s7-grades.md.
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
        Label("LD_btm multiplier (x diameter, default {}, assumes St 36/52):".format(
            int(DEFAULT_LD_BTM_MULTIPLIER)
        )),
        TextBox("ld_mult", Text=str(int(DEFAULT_LD_BTM_MULTIPLIER))),
        Button("Place bar"),
    ]
    form = FlexForm("S1 - Place bottom bar", components)
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
    ld_mult = float(values["ld_mult"]) if values["ld_mult"] else DEFAULT_LD_BTM_MULTIPLIER

    # --- A42 (ticket #27, supersedes A35/S7): one explicit per-role
    # RebarBarType selection, no fallback -----------------------------
    bottom_bar_type = select_bar_type_for_role(doc, ROLE_BOTTOM_MAIN)
    if bottom_bar_type is None:
        forms.alert(
            missing_bar_type_selection_message(ROLE_BOTTOM_MAIN).message,
            title="RebarBarType selection required",
        )
        script.exit()
    bar_type = bar_type_for_role(ROLE_BOTTOM_MAIN, bottom_bar_type)

    # --- A42: the bottom bar's diameter comes FROM the selected type --
    # there is no free-text Ø_BTM to reconcile it against any more.
    dia_btm_mm = bar_type_diameter_mm(bar_type, internal_to_mm)

    # --- A42 (ticket #27) mechanical grade-conflict guard: the selected
    # type must not be the SAME element as a stirrup type already placed
    # on this beam (a prior "Place Stirrups" run) -- one element cannot be
    # both grades. Compared by element id, never by name.
    bottom_bar_type_id = getattr(bar_type, "Id", None)
    bottom_bar_type_name = getattr(bar_type, "Name", "")
    # No mechanical grade-conflict guard here: this tracer pushbutton holds
    # only the bottom-bar selection, with no stirrup selection to compare
    # it against. The guard lives in "Place Main Bars", which holds all
    # three selections at once (issue #27 review).

    b_mm, h_mm = beam_section_dimensions_mm(beam, internal_to_mm)
    start_pt, end_pt = beam_endpoints(beam)
    axis = beam_axis_direction(beam)

    # --- S9 guard, run BEFORE any placement work (rev 2 section 9 item 2,
    # A39): a collinear neighbouring beam at either end makes this a
    # continuous run, not a single span, regardless of whether a column is
    # ALSO present there. REFUSED, not warned -- see
    # rft.core.guards.continuous_run_guard_message for the policy rationale.
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

    try:
        cover_start_mm = read_support_cover_mm(col_start, SUPPORT_SIDE_FACE_TYPE, doc, internal_to_mm)
        cover_end_mm = read_support_cover_mm(col_end, SUPPORT_SIDE_FACE_TYPE, doc, internal_to_mm)
    except HostValidationError as ex:
        forms.alert(str(ex), title="Cover read-back failed")
        script.exit()

    ld_btm_mm = development_length(dia_btm_mm, ld_mult)
    try:
        anchorage_start = bottom_bar_anchorage(support_width_start_mm, cover_start_mm, ld_btm_mm)
        anchorage_end = bottom_bar_anchorage(support_width_end_mm, cover_end_mm, ld_btm_mm)
    except ValueError as ex:
        forms.alert(str(ex), title="Invalid anchorage input")
        script.exit()

    output.print_md("### S1 tracer bullet -- computed anchorage (rev 2 §2.2/§2.3)")
    output.print_md("- " + role_grade_report_line(ROLE_BOTTOM_MAIN, bottom_bar_type_name))
    output.print_md("- b = {:.1f} mm, h = {:.1f} mm, L (c/c) = {:.1f} mm".format(b_mm, h_mm, l_mm))
    output.print_md("- LD_btm = {} x {:.1f} = {:.1f} mm".format(ld_mult, dia_btm_mm, ld_btm_mm))
    output.print_md(
        "- Start end: support width = {:.1f} mm, cover = {:.1f} mm -> "
        "a = {:.1f} mm, b = {:.1f} mm".format(
            support_width_start_mm, cover_start_mm, anchorage_start.a, anchorage_start.b
        )
    )
    output.print_md(
        "- End end:   support width = {:.1f} mm, cover = {:.1f} mm -> "
        "a = {:.1f} mm, b = {:.1f} mm".format(
            support_width_end_mm, cover_end_mm, anchorage_end.a, anchorage_end.b
        )
    )
    output.print_md("*Placing the bar anchored at both ends (bend up -> straight run -> bend up).*")

    bend_direction = DB.XYZ.BasisZ  # bottom bar bends upward, rev 2 §2.2

    def do_place():
        a_start_internal = mm_to_internal(anchorage_start.a)
        b_start_internal = mm_to_internal(anchorage_start.b)
        a_end_internal = mm_to_internal(anchorage_end.a)
        b_end_internal = mm_to_internal(anchorage_end.b)

        # Support faces, not the beam curve's endpoints -- finding #2:
        # span_length_mm's c/c derivation implies the curve typically runs
        # column-centre to column-centre, not face to face.
        face_start = start_support_face_point(
            col_start, start_pt, axis, mm_to_internal(support_width_start_mm)
        )
        face_end = end_support_face_point(
            col_end, start_pt, axis, mm_to_internal(support_width_end_mm)
        )

        curves = build_bottom_bar_curves(
            face_start, face_end, axis, bend_direction,
            a_start_internal, b_start_internal, a_end_internal, b_end_internal,
        )
        norm = bend_plane_normal(axis, bend_direction)
        return place_anchored_bar(doc, beam, bar_type, curves, norm)

    try:
        run_in_transaction(doc, "RFT S1 - place bottom bar", do_place)
    except Exception as ex:
        forms.alert(
            "Placement failed and was rolled back: {}".format(ex),
            title="Error",
        )
        script.exit()

    output.print_md("**Bar placed successfully.**")


if __name__ == "__main__":
    main()
