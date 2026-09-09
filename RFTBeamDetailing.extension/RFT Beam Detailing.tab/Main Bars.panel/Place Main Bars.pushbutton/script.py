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
  spacer bar is placed -- guessing one is prohibited by CONTEXT.md. Ø_spacer
  stays a typed input (A19: it is the CLEAR VERTICAL GAP between layers,
  not a bar's own diameter, so it cannot be read off a RebarBarType).
- Steel-grade (RebarBarType) resolution is A42's explicit, no-fallback,
  ONE-SELECTION-PER-ROLE model (ticket #27, supersedes A35/S7's two-
  selections-per-grade model): a top main bar type AND a separate bottom
  main bar type, each picked from its own dropdown, so a Ø12 top bar and a
  Ø16 bottom bar (both A34 high tensile) can coexist in one beam. Each
  bar's diameter comes FROM its selected type -- there is no more free-text
  Ø_TOP/Ø_BTM to reconcile it against.
- "Place Bottom Bar.pushbutton" (S1) and "Place Stirrups.pushbutton" (S5)
  keep their original both-ends-supported assumption; only THIS pushbutton
  (already S3's, the one #15's ticket named) gets S2's full unsupported-
  end/any-support-type treatment for main bars, per this ticket's explicit
  scope ("close that hole here rather than adding a fourth pushbutton").
"""

from pyrevit import forms, revit, script
# FlexForm and its components live in rpw.ui.forms (RevitPythonWrapper, bundled
# with pyRevit), NOT in pyrevit.forms -- verified against pyRevit 6.1.0.26047,
# whose pyrevit.forms exposes SelectFromList/CommandSwitchWindow/alert/ask_for_*
# and nothing named Button. Importing these from pyrevit.forms raised
# ImportError on every button at load time.
from rpw.ui.forms import Button, FlexForm, Label, TextBox

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
from rft.core.grades import (
    ROLE_BOTTOM_MAIN,
    ROLE_STIRRUP,
    ROLE_TOP_MAIN,
    bar_type_for_role,
    missing_bar_type_selection_message,
    role_grade_report_line,
    role_picker_label,
    stirrup_grade_conflict_message,
)
from rft.core.layout import (
    MAX_LAYERS,
    corner_bar_u_positions_mm,
    layer_offset_mm,
    spacer_diameter_warning,
    spacer_length_mm,
)
from rft.core.spacing import (
    OPTION_SINGLE_ROW,
    OPTION_STACKED,
    governing_min_spacing_mm,
    validate_face_spacing,
)
from rft.revit.bar_types import (
    bar_type_diameter_mm,
    bar_type_options,
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
from rft.revit.guards import continuous_run_guard
from rft.revit.host import HostValidationError, read_beam_face_covers_mm, read_support_side_cover_mm, validate_rebar_host
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

# Cover reads (issue #30) go through `rft.revit.host.read_beam_face_covers_mm`
# / `read_support_side_cover_mm`, which classify each exposed face's own
# normal against the beam's frame rather than looking it up by the
# nonexistent `RebarFaceType` enum -- see that module's docstring. FOUR
# conceptually distinct covers still exist and must never be substituted for
# one another:
#
# 1. The SUPPORTING element's own cover (rev 2 section 2.4, A8), read off
#    the support (column/wall/girder), used in a_t / a_btm. NOT the beam's
#    own cover.
# 2. The BEAM's own TOP/BOTTOM face cover (rev 2 section 4), used for the
#    layer offsets. NOT the side cover, NOT the support's cover.
# 3. The BEAM's own SIDE-face cover (rev 2 sections 6, 7), used for every
#    HORIZONTAL cross-section dimension (corner-bar inset, spacer length).
# 4. The BEAM's own cover at its CUT END (rev 2 section 2.5, R3 resolved:
#    "beam end - cover"), used ONLY for the unsupported-end straight run --
#    only ever exposed as a face when that end has no support (issue #30).


def select_bar_type_for_role(document, role):
    """Explicit per-role selection of a ``RebarBarType`` (rev 2 section
    1.1, A42, ticket #27; supersedes A35/S7's issue #20 two-selections-
    per-grade model) -- NO fallback to "the first one found". Returns
    None if the document has no RebarBarType at all, or if the engineer
    cancels the picker.

    A SEPARATE selection for top and bottom main bars, even though both
    map to the SAME A34 grade (high tensile): a ``RebarBarType`` is a
    diameter in Revit, so a Ø12 top bar and a Ø16 bottom bar -- the
    default 12/16 mm case, and the normal case generally -- need two
    different type elements, not two grade slots. The picker's title
    carries A34's required grade for this role (``role_picker_label``),
    since grade can no longer be checked mechanically from the type
    itself.

    SHAPE UNVERIFIED -- see "Place Bottom Bar.pushbutton"'s identical
    docstring for ``pyrevit.forms.SelectFromList.show``'s unconfirmed
    signature.
    """
    options = bar_type_options(document, internal_to_mm)
    if not options:
        return None
    # No name_attr: pyRevit would getattr(item, "Name"), which raises
    # AttributeError under IronPython for an ElementType-hidden property
    # (see rft.revit.bar_types.element_name). Plain label strings are
    # passed instead and mapped back to the element afterwards.
    selected_label = forms.SelectFromList.show(
        [label for label, _element in options],
        multiselect=False,
        title="Select RebarBarType -- {}".format(role_picker_label(role)),
        button_name="Select",
    )
    if selected_label is None:
        return None
    return dict(options)[selected_label]


def ask_inputs():
    components = [
        Label("Spacer diameter O_spacer (mm, clear gap between layers):"),
        TextBox("dia_spacer", Text="16"),
        Label("Max aggregate size D_agg (mm, optional -- blank = §6.2's 50 mm fallback, A36):"),
        TextBox("d_agg", Text=""),
        Label("Top bar count per layer:"),
        TextBox("count_top", Text="3"),
        Label("Bottom bar count per layer:"),
        TextBox("count_btm", Text="3"),
        Label("Number of top layers (1-{}):".format(MAX_LAYERS)),
        TextBox("layers_top", Text="1"),
        Label("Number of bottom layers (1-{}):".format(MAX_LAYERS)),
        TextBox("layers_btm", Text="1"),
        Label("§6.3 top face option (1=single wide row, 2=stacked):"),
        TextBox("option_top", Text="1"),
        Label("§6.3 bottom face option (1=single wide row, 2=stacked):"),
        TextBox("option_btm", Text="1"),
        Label("§6.2 min-spacing override (mm, optional floor -- A29, blank = none):"),
        TextBox("min_spacing_override", Text=""),
        Label("LD_top multiplier (x diameter, default {}, assumes St 36/52):".format(
            int(DEFAULT_LD_TOP_MULTIPLIER)
        )),
        TextBox("ld_top_mult", Text=str(int(DEFAULT_LD_TOP_MULTIPLIER))),
        Label("LD_btm multiplier (x diameter, default {}, assumes St 36/52):".format(
            int(DEFAULT_LD_BTM_MULTIPLIER)
        )),
        TextBox("ld_btm_mult", Text=str(int(DEFAULT_LD_BTM_MULTIPLIER))),
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
    dia_spacer_mm = float(values["dia_spacer"]) if values["dia_spacer"] else 16.0

    # D_agg is OPTIONAL and ships blank (A36), precisely so section 6.2's
    # 50 mm fallback governs until an aggregate size is supplied. Refusing
    # a blank D_agg would make the tool unable to run in its OWN documented
    # default configuration, and would leave the fallback branch of
    # `governing_min_spacing_mm` unreachable from the UI (issue #17
    # review). `None` selects that branch; a number selects the formula.
    d_agg_mm = float(values["d_agg"]) if values["d_agg"] else None

    count_top = int(values["count_top"])
    count_btm = int(values["count_btm"])
    layers_top = int(values["layers_top"])
    layers_btm = int(values["layers_btm"])
    ld_top_mult = float(values["ld_top_mult"]) if values["ld_top_mult"] else DEFAULT_LD_TOP_MULTIPLIER
    ld_btm_mult = float(values["ld_btm_mult"]) if values["ld_btm_mult"] else DEFAULT_LD_BTM_MULTIPLIER
    option_top = int(values["option_top"]) if values["option_top"] else OPTION_SINGLE_ROW
    option_btm = int(values["option_btm"]) if values["option_btm"] else OPTION_SINGLE_ROW
    min_spacing_override_mm = (
        float(values["min_spacing_override"]) if values["min_spacing_override"] else None
    )

    # --- A42 (ticket #27, supersedes A35/S7): one explicit RebarBarType
    # selection PER ROLE, no fallback -- top and bottom main bars each get
    # their own picker (and so their own diameter) since a RebarBarType is
    # a diameter in Revit and the two roles' diameters commonly differ.
    top_bar_type_selected = select_bar_type_for_role(doc, ROLE_TOP_MAIN)
    if top_bar_type_selected is None:
        forms.alert(
            missing_bar_type_selection_message(ROLE_TOP_MAIN).message,
            title="RebarBarType selection required",
        )
        script.exit()
    top_bar_type = bar_type_for_role(ROLE_TOP_MAIN, top_bar_type_selected)

    btm_bar_type_selected = select_bar_type_for_role(doc, ROLE_BOTTOM_MAIN)
    if btm_bar_type_selected is None:
        forms.alert(
            missing_bar_type_selection_message(ROLE_BOTTOM_MAIN).message,
            title="RebarBarType selection required",
        )
        script.exit()
    btm_bar_type = bar_type_for_role(ROLE_BOTTOM_MAIN, btm_bar_type_selected)

    # The stirrup type is selected here even though this pushbutton places
    # NO stirrup: O_stirrup positions every main bar relative to the cage
    # (§4's layer offsets, §6.1's corner-bar inset, §6.3's spacer length).
    # Typing it instead would put the stirrup diameter back on two
    # independent sources of truth -- type 10 here, place 12 mm stirrups
    # from "Place Stirrups", and every main bar sits 2 mm off its true
    # cover with nothing in the model showing it (issue #27 review). A42's
    # whole point is that a diameter used in geometry comes from the type
    # that will be placed.
    stirrup_bar_type_selected = select_bar_type_for_role(doc, ROLE_STIRRUP)
    if stirrup_bar_type_selected is None:
        forms.alert(
            missing_bar_type_selection_message(ROLE_STIRRUP).message,
            title="RebarBarType selection required",
        )
        script.exit()
    stirrup_bar_type = bar_type_for_role(ROLE_STIRRUP, stirrup_bar_type_selected)

    # --- A42: each bar's diameter comes FROM its own selected type -- no
    # free-text Ø_TOP/Ø_BTM/Ø_stirrup left to reconcile it against.
    dia_top_mm = bar_type_diameter_mm(top_bar_type, internal_to_mm)
    dia_btm_mm = bar_type_diameter_mm(btm_bar_type, internal_to_mm)
    dia_stirrup_mm = bar_type_diameter_mm(stirrup_bar_type, internal_to_mm)

    top_bar_type_name = getattr(top_bar_type, "Name", "")
    btm_bar_type_name = getattr(btm_bar_type, "Name", "")
    stirrup_bar_type_name = getattr(stirrup_bar_type, "Name", "")

    # --- A42 (ticket #27) mechanical grade-conflict guard, run IN-RUN:
    # this pushbutton now holds the stirrup selection and both high-tensile
    # selections at once, so the comparison the guard needs is available
    # here directly -- one element cannot be both mild St 24/35 and high
    # tensile St 36/52. Compared by element id, never by name.
    conflicts = [
        c for c in (
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

    b_mm, h_mm = beam_section_dimensions_mm(beam, internal_to_mm)
    start_pt, end_pt = beam_endpoints(beam)
    axis = beam_axis_direction(beam)
    u_dir, v_dir = beam_section_axes(beam)

    # --- S9 guard, run BEFORE any placement work (rev 2 section 9 item 2,
    # A39): a collinear neighbouring beam at either end makes this a
    # continuous run, not a single span, regardless of whether a column or
    # girder is ALSO present at that end -- see
    # rft.core.guards.continuous_run_guard_message for the policy
    # rationale (REFUSED, not warned, under A39's explicit latitude).
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

    # --- rev 2 section 2.4/2.5 (A9/A12/A14): support detection, per end,
    # any support type -- a missing support takes the unsupported path,
    # never a hard stop, so top/bottom anchorage can be computed at both
    # ends independently below. Moved ahead of the cover reads (issue #30):
    # `cover_end` is only exposed as a face on an UNSUPPORTED end
    # (`GetExposedFaces()` returns no end face at all on a supported beam),
    # so whether it is even requested depends on knowing support status
    # first.
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

    warnings = []
    if not is_supported_start:
        warnings.append("Start end: " + free_end_configuration_warning())
    if not is_supported_end:
        warnings.append("End end: " + free_end_configuration_warning())

    # --- THREE-to-FOUR cover situation (issue #30, replacing the nonexistent
    # `RebarFaceType`): TOP/BOTTOM feed the layer offsets (section 4),
    # SIDE feeds every horizontal cross-section dimension (corner-bar
    # inset, section 6.1). END is only requested at an unsupported end
    # (section 2.5, A12, R3) -- requesting it where it does not exist would
    # be a refusal, so it must never be requested unconditionally. The
    # SUPPORTING element's own cover (section 2.4, A8) is a further,
    # separate read, off the support's own exposed faces, not the beam's.
    try:
        beam_covers = read_beam_face_covers_mm(
            beam, host_data, u_dir, v_dir, axis, internal_to_mm, element_id=beam.Id,
            need_end_start=not is_supported_start, need_end_end=not is_supported_end,
        )
    except HostValidationError as ex:
        forms.alert(str(ex), title="Cover read-back failed")
        script.exit()

    cover_top_mm = beam_covers.top_mm
    cover_btm_mm = beam_covers.bottom_mm
    cover_side_mm = beam_covers.side_mm
    # Only one of these is ever populated, at whichever end is unsupported;
    # the anchorage/report code below reads `cover_end_mm` unconditionally
    # for whichever end needs it, so pick whichever is not None (both may be
    # None if both ends are supported, in which case cover_end_mm is unused).
    cover_end_mm = (
        beam_covers.end_start_mm if beam_covers.end_start_mm is not None
        else beam_covers.end_end_mm
    )

    support_cover_start_mm = support_cover_end_mm = None
    try:
        if is_supported_start:
            support_start_host_data = validate_rebar_host(support_start)
            support_cover_start_mm = read_support_side_cover_mm(
                support_start, support_start_host_data, axis, True, internal_to_mm,
                element_id=support_start.Id,
            )
        if is_supported_end:
            support_end_host_data = validate_rebar_host(support_end)
            support_cover_end_mm = read_support_side_cover_mm(
                support_end, support_end_host_data, axis, False, internal_to_mm,
                element_id=support_end.Id,
            )
    except HostValidationError as ex:
        forms.alert(str(ex), title="Cover read-back failed")
        script.exit()

    # --- §6.2-6.4 spacing validation (A21, A27, A28, A29, A36, A43, A44),
    # run BEFORE any placement work -- this is a REFUSAL, so nothing may
    # reach a transaction if it fires (issue #17, S4). Deliberately AFTER
    # the continuous-run guard: that one rejects the beam's whole
    # configuration (A41), so reporting a section-level spacing problem
    # first would send the engineer to fix bar counts for a beam this
    # tool is going to refuse anyway (issue #17 review). The engineer's typed
    # bar count applies uniformly to every layer of a face (this pushbutton
    # has no per-layer count field, only one count per face), so every
    # layer of a face shares the same `layer_bar_counts` entry; each layer
    # is still validated independently by `validate_face_spacing` (A44).
    governing_min_top_mm = governing_min_spacing_mm(dia_top_mm, d_agg_mm, min_spacing_override_mm)
    governing_min_btm_mm = governing_min_spacing_mm(dia_btm_mm, d_agg_mm, min_spacing_override_mm)
    top_spacing_report = validate_face_spacing(
        "Top face", option_top, [count_top] * layers_top, b_mm, cover_side_mm,
        dia_stirrup_mm, dia_top_mm, governing_min_top_mm,
    )
    btm_spacing_report = validate_face_spacing(
        "Bottom face", option_btm, [count_btm] * layers_btm, b_mm, cover_side_mm,
        dia_stirrup_mm, dia_btm_mm, governing_min_btm_mm,
    )
    spacing_guard_messages = top_spacing_report.guard_messages + btm_spacing_report.guard_messages
    if spacing_guard_messages:
        forms.alert(
            "\n\n".join(g.message for g in spacing_guard_messages),
            title="Spacing violation -- refused (rev 2 section 6.2-6.4)",
        )
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
    # R1 compares O_spacer against section 6.2's minimum WITHOUT A29's
    # override applied: R1's own text names the formula, not the engineer's
    # raised floor, so a raised floor must not manufacture a warning.
    r1_min_top_mm = governing_min_spacing_mm(dia_top_mm, d_agg_mm)
    r1_min_btm_mm = governing_min_spacing_mm(dia_btm_mm, d_agg_mm)
    warning_top_spacer = spacer_diameter_warning(dia_spacer_mm, r1_min_top_mm) if layers_top > 1 else None
    warning_btm_spacer = spacer_diameter_warning(dia_spacer_mm, r1_min_btm_mm) if layers_btm > 1 else None

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
    output.print_md("- " + role_grade_report_line(ROLE_TOP_MAIN, top_bar_type_name))
    output.print_md("- " + role_grade_report_line(ROLE_BOTTOM_MAIN, btm_bar_type_name))
    output.print_md(
        "- " + role_grade_report_line(ROLE_STIRRUP, stirrup_bar_type_name)
        + " (positions the main bars; no stirrup is placed by this pushbutton)"
    )
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
    output.print_md("- §6.2 governing min_spacing (top) = {:.1f} mm".format(governing_min_top_mm))
    for r in top_spacing_report.layer_results:
        output.print_md(
            "- §6.3/§6.4 layer {}: {} bars, achieved clear spacing = {}".format(
                r.layer_index, r.bar_count,
                "{:.1f} mm (PASS)".format(r.achieved_clear_mm) if r.achieved_clear_mm is not None
                else "n/a (single bar, no horizontal spacing question)",
            )
        )
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
    output.print_md("- §6.2 governing min_spacing (bottom) = {:.1f} mm".format(governing_min_btm_mm))
    for r in btm_spacing_report.layer_results:
        output.print_md(
            "- §6.3/§6.4 layer {}: {} bars, achieved clear spacing = {}".format(
                r.layer_index, r.bar_count,
                "{:.1f} mm (PASS)".format(r.achieved_clear_mm) if r.achieved_clear_mm is not None
                else "n/a (single bar, no horizontal spacing question)",
            )
        )
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
                     a_start_mm, b_start_mm, a_end_mm, b_end_mm, face_bar_type):
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
                placed.append(place_anchored_bar(doc, beam, face_bar_type, curves, norm))
        return placed

    def do_place():
        placed = []
        placed += _place_face(
            btm_layer_offsets_mm, btm_u_positions_mm, v_dir, False,
            a_btm_start_mm, b_btm_start_mm, a_btm_end_mm, b_btm_end_mm, btm_bar_type,
        )
        placed += _place_face(
            top_layer_offsets_mm, top_u_positions_mm, v_dir.Negate(), True,
            a_top_start_mm, b_top_start_mm, a_top_end_mm, b_top_end_mm, top_bar_type,
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
