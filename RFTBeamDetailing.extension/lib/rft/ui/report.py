# -*- coding: utf-8 -*-
"""The Review tab's report text (rev 2 section 8.2, A37), as pure
functions over values already computed.

WHY THIS IS ITS OWN MODULE. This is ~400 lines of the most detailed prose
the tool produces -- every layer offset, every achieved spacing, every
anchorage `a` and `b`, every warning -- and it lived inside ``script.py``,
which imports ``pyrevit`` and therefore cannot be imported under CPython
at all. Not one line of it could be executed by a test. The window's
report was the largest piece of untested code in the project, and it is
the piece the engineer actually reads before committing steel to a model.

Nothing here touches the Revit API or WPF. Element names, measured
diameters and the beam/support geometry arrive as plain values in
``ReportInputs`` and a geometry dict; the raw text of each input field
arrives as a string and is parsed HERE, by ``rft.ui.inputs``, so that
every "Cannot compute ...: <reason>" line keeps the parser's own wording
rather than a paraphrase of it.

The report is a FORMATTER. It states what the plan says and adds no
detailing arithmetic of its own -- the same rule A48 applies to the
sketch renderer, for the same reason: a second computation of a number
that becomes steel is free to disagree with the first (#56).

Wording is carried across verbatim from the three pushbuttons that placed
real reinforcement in a live session (v0.1.0), via the single window that
replaced them. Python 2/3 compatible: IronPython 2.7 is the runtime that
loads this in production.
"""

from collections import namedtuple

from rft.core.anchorage import (
    development_length,
    free_end_configuration_warning,
    top_bottom_clearance_warning,
)
from rft.core.crack_bars import (
    available_height_mm,
    crack_bar_end_result,
    crack_bar_u_positions_mm,
    crack_layer_plan,
    crack_layer_v_positions_mm,
    spacing_validation_exemption_note,
)
from rft.core.grades import (
    ROLE_BOTTOM_MAIN,
    ROLE_CRACK,
    ROLE_STIRRUP,
    ROLE_TOP_MAIN,
    role_grade_report_line,
)
from rft.core.layout import (
    MAX_LAYERS,
    layer_offset_mm,
    spacer_diameter_warning,
)
from rft.core.spacing import governing_min_spacing_mm, validate_face_spacing
from rft.core.stirrups import (
    ZONE_LAYOUT_FLAGS,
    centreline_leg_dimensions_mm,
    stirrup_count_and_spacing,
    stirrup_zones_mm,
    zone_array_length_mm,
)
from rft.core import plan as core_plan
from rft.ui import inputs as ui_inputs

# Everything the report reads that is NOT geometry: the four bar-type
# names and the hook name (``None`` where a role is unpicked -- which is
# how every "is it selected" branch below reads), their measured
# diameters, the hook angle as read back (``None`` when it could not be
# verified, A45), and the RAW TEXT of every input field.
#
# Raw text rather than parsed numbers, deliberately. The report's job
# includes saying which input it could not use and why, in the parser's
# own words; handing it pre-parsed values would either lose those
# messages or duplicate them.
ReportInputs = namedtuple("ReportInputs", [
    "top_bar_type_name", "btm_bar_type_name",
    "stirrup_bar_type_name", "crack_bar_type_name",
    "hook_type_name", "hook_angle_deg",
    "top_dia_mm", "btm_dia_mm", "stirrup_dia_mm", "crack_dia_mm",
    "top_count_text", "btm_count_text",
    "top_layers_text", "btm_layers_text",
    "top_option_label", "btm_option_label",
    "spacer_dia_text", "d_agg_text", "min_spacing_override_text",
    "ld_top_mult_text", "ld_btm_mult_text",
    "dense_spacing_text", "normal_spacing_text", "closure_type_label",
    "crack_s_max_text",
])


def derivation_lines(review):
    """The header block: what is requested, and why not, per section
    (issue #50's derivation, rev 2 section 8 / A47 / A50).
    """
    lines = [
        "Derivation (rev 2 section 8, A47/A50):",
        "- " + review.top_main.reason,
        "- " + review.bottom_main.reason,
        "- " + review.stirrups.reason,
        "- " + review.crack_bars.reason,
    ]
    if not review.any_requested:
        lines.append("- **Nothing is requested. Place is disabled.**")
    return lines


def format_end_result(a_mm, b_mm):
    """Ported verbatim (wording) from "Place Main Bars.pushbutton"."""
    if b_mm is None:
        return "achieved={:.1f} mm (no hook, unsupported)".format(a_mm)
    return "a={:.1f} mm, b={:.1f} mm".format(a_mm, b_mm)

def main_bars_lines(inputs, review, geometry):
    """Main bars section of the report (rev 2 section 2, 4, 4.1, 6.1,
    6.2-6.4) -- wording ported from "Place Main Bars.pushbutton" where
    it applies to only ONE requested face rather than always both.
    """
    lines = ["", "Main bars (rev 2 section 2, 4, 4.1, 6.1, 6.2-6.4):"]

    stirrup_bar_type = inputs.stirrup_bar_type_name
    if stirrup_bar_type is None:
        lines.append(
            "- Cannot compute main bar layout: no stirrup RebarBarType "
            "selected on Beam & Materials. It positions every main bar "
            "via section 4's layer offsets and section 6.1's corner-bar "
            "inset, even when this run does not also place stirrups."
        )
        return lines
    dia_stirrup_mm = inputs.stirrup_dia_mm
    lines.append(
        "- " + role_grade_report_line(ROLE_STIRRUP, inputs.stirrup_bar_type_name)
        + " (positions the main bars; placed only if stirrups are also requested)"
    )

    try:
        spacer_dia_mm = ui_inputs.parse_positive_float(inputs.spacer_dia_text, "O_spacer")
        d_agg_mm = ui_inputs.parse_optional_positive_float(inputs.d_agg_text, "D_agg")
        min_spacing_override_mm = ui_inputs.parse_optional_positive_float(
            inputs.min_spacing_override_text, "min-spacing override"
        )
        ld_top_mult = ui_inputs.parse_positive_float(inputs.ld_top_mult_text, "LD_top multiplier")
        ld_btm_mult = ui_inputs.parse_positive_float(inputs.ld_btm_mult_text, "LD_btm multiplier")
    except ValueError as ex:
        lines.append("- Cannot compute main bar layout: {}".format(ex))
        return lines

    top_dia_mm = inputs.top_dia_mm
    btm_dia_mm = inputs.btm_dia_mm

    faces = (
        ("Top", ROLE_TOP_MAIN, review.top_main, inputs.top_bar_type_name, top_dia_mm,
         btm_dia_mm, inputs.top_count_text, inputs.top_layers_text,
         inputs.top_option_label, ld_top_mult, True),
        ("Bottom", ROLE_BOTTOM_MAIN, review.bottom_main, inputs.btm_bar_type_name, btm_dia_mm,
         top_dia_mm, inputs.btm_count_text, inputs.btm_layers_text,
         inputs.btm_option_label, ld_btm_mult, False),
    )
    for (face_label, role, face_derivation, bar_type_name, dia_own_mm, dia_other_mm,
         count_text, layers_text, option_label, ld_mult, is_top) in faces:
        if not face_derivation.requested:
            lines.append("- {} face: not requested.".format(face_label))
            continue
        lines.append(
            "- " + role_grade_report_line(role, bar_type_name)
        )
        lines += _one_main_face_lines(
            face_label, dia_own_mm, dia_other_mm, count_text, layers_text, option_label,
            ld_mult, is_top, dia_stirrup_mm, spacer_dia_mm, d_agg_mm,
            min_spacing_override_mm, geometry,
        )

    if review.top_main.requested and review.bottom_main.requested:
        clearance_warning = top_bottom_clearance_warning(top_dia_mm, btm_dia_mm)
        lines.append(
            "- Top/bottom centreline clearance (section 2.2, A7): achieved "
            "= O_BTM = {:.1f} mm, required = (O_TOP+O_BTM)/2 = {:.1f} mm.".format(
                btm_dia_mm, 0.5 * (top_dia_mm + btm_dia_mm)
            )
        )
        if clearance_warning:
            lines.append("- **A7 clearance warning:** {}".format(clearance_warning))
    return lines


def _one_main_face_lines(face_label, dia_own_mm, dia_other_mm, count_text,
                         layers_text, option_label, ld_mult, is_top, dia_stirrup_mm,
                         spacer_dia_mm, d_agg_mm, min_spacing_override_mm, geometry):
    lines = []
    try:
        count = ui_inputs.parse_optional_positive_int(count_text, "{} bar count per layer".format(face_label))
        layers = ui_inputs.parse_optional_positive_int(
            layers_text, "Number of {} layers".format(face_label.lower()), max_value=MAX_LAYERS
        )
    except ValueError as ex:
        lines.append("  - Cannot compute {} face layout: {}".format(face_label.lower(), ex))
        return lines
    if count is None or layers is None:
        lines.append("  - Cannot compute {} face layout: missing count/layers.".format(face_label.lower()))
        return lines

    option = ui_inputs.face_option_from_label(option_label)
    if option is None:
        lines.append("  - Cannot compute {} face layout: no section 6.3 option selected.".format(face_label.lower()))
        return lines

    governing_min_mm = governing_min_spacing_mm(dia_own_mm, d_agg_mm, min_spacing_override_mm)
    spacing_report = validate_face_spacing(
        "{} face".format(face_label), option, [count] * layers, geometry["b_mm"],
        geometry["cover_side_mm"], dia_stirrup_mm, dia_own_mm, governing_min_mm,
    )
    lines.append("  - section 6.2 governing min_spacing = {:.1f} mm".format(governing_min_mm))
    for r in spacing_report.layer_results:
        lines.append(
            "  - section 6.3/6.4 layer {}: {} bars, achieved clear spacing = {}".format(
                r.layer_index, r.bar_count,
                "{:.1f} mm ({})".format(r.achieved_clear_mm, "PASS" if r.passes else "FAIL")
                if r.achieved_clear_mm is not None
                else "n/a (single bar, no horizontal spacing question)",
            )
        )
    for g in spacing_report.guard_messages:
        lines.append("  - **REFUSED (section 6.2-6.4):** {}".format(g.message))

    # #56: the SAME plan objects the placer executes. The report used
    # to recompute these three quantities itself, from the same core
    # functions -- correct, and still able to drift, because two call
    # sites can be given different arguments and neither would notice.
    # Now there is one computation and the report is its formatter.
    cover_mm = geometry["cover_top_mm"] if is_top else geometry["cover_btm_mm"]
    try:
        layer_plans = core_plan.face_layer_plans(
            is_top, geometry["h_mm"], geometry["b_mm"], cover_mm,
            geometry["cover_side_mm"], dia_stirrup_mm, dia_own_mm,
            spacer_dia_mm, count, layers,
        )
    except ValueError as ex:
        lines.append("  - Cannot compute {} face layout: {}".format(
            face_label.lower(), ex))
        return lines

    for layer in layer_plans:
        lines.append("  - layer {}: offset_{} = {:.1f} mm, v = {:.1f} mm".format(
            layer.layer_n, layer.layer_n, layer.offset_mm, layer.v_mm))
    lines.append(
        "  - corner-bar u positions ({} bars): {}".format(
            count,
            ", ".join("{:.1f}".format(u) for u in layer_plans[0].u_positions_mm),
        )
    )

    if layers > 1:
        r1_min_mm = governing_min_spacing_mm(dia_own_mm, d_agg_mm)
        spacer_warning = spacer_diameter_warning(spacer_dia_mm, r1_min_mm)
        if spacer_warning:
            lines.append("  - **R1 warning:** {}".format(spacer_warning))

    # A51: dia_other_mm comes from the SELECTED opposite bar type,
    # placed or not -- so this only refuses when NOTHING is selected
    # there, which is the half of A51 that A42 governs. The old wording
    # here said "because the bottom face is not requested", which was
    # the pre-A51 rule and is no longer what the code does.
    ld_mm = development_length(dia_own_mm, ld_mult)
    try:
        start_plan = core_plan.end_plan(
            geometry["is_supported_start"], is_top,
            geometry["support_width_start_mm"], geometry["support_cover_start_mm"],
            dia_own_mm, dia_other_mm, ld_mm, geometry["cover_end_start_mm"],
            "{} face, start end".format(face_label),
        )
        end_plan_ = core_plan.end_plan(
            geometry["is_supported_end"], is_top,
            geometry["support_width_end_mm"], geometry["support_cover_end_mm"],
            dia_own_mm, dia_other_mm, ld_mm, geometry["cover_end_end_mm"],
            "{} face, end end".format(face_label),
        )
    except ValueError as ex:
        lines.append("  - Cannot compute end anchorage: {}".format(ex))
        return lines

    refusals = [
        p.refused_reason for p in (start_plan, end_plan_) if p.refused_reason
    ]
    if refusals:
        for reason in refusals:
            lines.append("  - **REFUSED (A51):** {}".format(reason))
        return lines

    lines.append(
        "  - LD = {:.0f} x {:.1f} = {:.1f} mm -> start: {}; end: {}".format(
            ld_mult, dia_own_mm, ld_mm,
            format_end_result(start_plan.a_mm, start_plan.b_mm),
            format_end_result(end_plan_.a_mm, end_plan_.b_mm),
        )
    )
    for w in (start_plan.warning, end_plan_.warning):
        if w:
            lines.append("  - **WARNING:** {}".format(w))
    if not geometry["is_supported_start"]:
        lines.append("  - **WARNING:** Start end: {}".format(free_end_configuration_warning()))
    if not geometry["is_supported_end"]:
        lines.append("  - **WARNING:** End end: {}".format(free_end_configuration_warning()))

    # NOT DONE HERE: "Place Main Bars.pushbutton"'s as-built A7 cross-check
    # (``placed_clearance_warning``) compares the TOP and BOTTOM bar's
    # placed `a` at the SAME end, which this per-face loop -- one face at
    # a time, by construction (#50's independent-face derivation) -- does
    # not hold both of at once. Left unreported here rather than computed
    # from a placeholder value for the other face; see this ticket's
    # closing report for this gap.
    return lines


def stirrups_lines(inputs, geometry):
    """Stirrups section (rev 2 section 3, 7) -- wording ported from
    "Place Stirrups.pushbutton".
    """
    lines = ["", "Stirrups (rev 2 section 3, 7):"]
    stirrup_bar_type = inputs.stirrup_bar_type_name
    if stirrup_bar_type is None:
        lines.append("- Cannot compute stirrup geometry: no stirrup RebarBarType selected.")
        return lines
    dia_stirrup_mm = inputs.stirrup_dia_mm
    lines.append("- " + role_grade_report_line(ROLE_STIRRUP, inputs.stirrup_bar_type_name))

    hook_type_name = inputs.hook_type_name or "<none>"
    if inputs.hook_angle_deg is None:
        lines.append(
            "- **Hook type used: '{}'.** Its angle could NOT be read back and "
            "verified against the required 135 degrees (rev 2 section 7.3, "
            "A45). Confirm the 135-degree angle manually before relying on "
            "this beam's stirrups.".format(hook_type_name)
        )
    else:
        lines.append(
            "- Hook type used: '{}', angle read back and verified = {:.1f} "
            "degrees, required 135 (rev 2 section 7.3, A45).".format(
                hook_type_name, inputs.hook_angle_deg
            )
        )

    # Stirrups have no cover field of their own on this tab (#48 collects
    # dense/normal spacing and closure type only) -- the stirrup rectangle
    # uses the beam's own SIDE cover, exactly as every other horizontal
    # cross-section dimension in this report does.
    cover_mm = geometry["cover_side_mm"]

    try:
        dense_mm = ui_inputs.parse_positive_float(inputs.dense_spacing_text, "Dense spacing")
        normal_mm = ui_inputs.parse_positive_float(inputs.normal_spacing_text, "Normal spacing")
    except ValueError as ex:
        lines.append("- Cannot compute stirrup distribution: {}".format(ex))
        return lines
    closure_type = ui_inputs.closure_type_from_label(inputs.closure_type_label)
    if closure_type is None:
        lines.append("- Cannot compute stirrup distribution: no closure type selected.")
        return lines

    width_mm, height_mm = centreline_leg_dimensions_mm(
        geometry["b_mm"], geometry["h_mm"], cover_mm, dia_stirrup_mm
    )
    lines.append(
        "- CENTRELINE rectangle = {:.1f} x {:.1f} mm (b={:.1f}, h={:.1f}, "
        "Cover={:.1f}, O_stirrup={:.1f}), closure type = {}".format(
            width_mm, height_mm, geometry["b_mm"], geometry["h_mm"], cover_mm,
            dia_stirrup_mm, closure_type,
        )
    )

    if geometry["l_mm"] is None:
        lines.append(
            "- Cannot compute the 3-zone stirrup distribution: rev 2 section "
            "3.1's zones need BOTH ends supported (a span centreline length), "
            "and at least one end here is unsupported."
        )
        return lines

    face_a_offset_mm = geometry["support_width_start_mm"] / 2.0
    face_b_offset_mm = geometry["support_width_end_mm"] / 2.0
    try:
        zones = stirrup_zones_mm(geometry["l_mm"], face_a_offset_mm, face_b_offset_mm)
    except ValueError as ex:
        lines.append("- Cannot compute stirrup zones: {}".format(ex))
        return lines

    lines.append("- L (c/c) = {:.1f} mm".format(geometry["l_mm"]))
    zone_specs = [
        ("zone1", zones.zone1, dense_mm, ZONE_LAYOUT_FLAGS["zone1"]),
        ("zone2", zones.zone2, normal_mm, ZONE_LAYOUT_FLAGS["zone2"]),
        ("zone3", zones.zone3, dense_mm, ZONE_LAYOUT_FLAGS["zone3"]),
    ]
    beam_total = 0
    for name, zone, max_spacing_mm, (include_first, include_last) in zone_specs:
        array_length_mm = zone_array_length_mm(zone)
        try:
            result = stirrup_count_and_spacing(array_length_mm, max_spacing_mm, include_first, include_last)
        except ValueError as ex:
            lines.append("- {}: {}".format(name, ex))
            continue
        beam_total += result.count
        lines.append(
            "- {}: [{:.1f}, {:.1f}] mm, array length = {:.1f} mm, achieved "
            "spacing = {:.1f} mm (max {:.1f} mm), count = {}".format(
                name, zone.start, zone.end, array_length_mm, result.spacing_mm,
                max_spacing_mm, result.count,
            )
        )
    lines.append("- **Beam total stirrup count = {}**".format(beam_total))
    return lines


def crack_bars_lines(inputs, geometry):
    """Crack/skin bars section (rev 2 section 5) -- wording ported
    from "Place Crack Bars.pushbutton". Only ever reached when #50's
    derivation already confirmed both faces are detailed (A50), so
    H_avail is never computed from an assumed layer count here.
    """
    lines = ["", "Crack/skin bars (rev 2 section 5):"]
    dia_crack_mm = inputs.crack_dia_mm
    lines.append("- " + role_grade_report_line(ROLE_CRACK, inputs.crack_bar_type_name))

    stirrup_bar_type = inputs.stirrup_bar_type_name
    if stirrup_bar_type is None:
        lines.append("- Cannot compute crack-bar layout: no stirrup RebarBarType selected.")
        return lines
    dia_stirrup_mm = inputs.stirrup_dia_mm

    top_dia_mm = inputs.top_dia_mm
    btm_dia_mm = inputs.btm_dia_mm

    try:
        spacer_dia_mm = ui_inputs.parse_positive_float(inputs.spacer_dia_text, "O_spacer")
        s_max_mm = ui_inputs.parse_positive_float(inputs.crack_s_max_text, "s_max")
    except ValueError as ex:
        lines.append("- Cannot compute crack-bar layout: {}".format(ex))
        return lines

    layers_top = ui_inputs.parse_optional_positive_int(inputs.top_layers_text, "Number of top layers", max_value=MAX_LAYERS)
    layers_btm = ui_inputs.parse_optional_positive_int(inputs.btm_layers_text, "Number of bottom layers", max_value=MAX_LAYERS)

    offset_top_mm = layer_offset_mm(geometry["cover_top_mm"], dia_stirrup_mm, top_dia_mm, spacer_dia_mm, layers_top)
    offset_btm_mm = layer_offset_mm(geometry["cover_btm_mm"], dia_stirrup_mm, btm_dia_mm, spacer_dia_mm, layers_btm)
    h_avail_mm = available_height_mm(geometry["h_mm"], offset_top_mm, offset_btm_mm)
    lines.append(
        "- offset_top (innermost, layer {}) = {:.1f} mm, offset_btm (innermost, "
        "layer {}) = {:.1f} mm (A26)".format(layers_top, offset_top_mm, layers_btm, offset_btm_mm)
    )
    lines.append("- H_avail = {:.1f} mm (section 5.1)".format(h_avail_mm))

    try:
        plan = crack_layer_plan(h_avail_mm, s_max_mm)
    except ValueError as ex:
        lines.append("- Cannot compute crack-bar layer plan: {}".format(ex))
        return lines
    lines.append(
        "- n_gaps = {}, n_crack_layers = {}, actual_spacing = {:.1f} mm "
        "(max s_max = {:.1f} mm, section 5.2)".format(
            plan.n_gaps, plan.n_crack_layers, plan.actual_spacing_mm, s_max_mm
        )
    )
    lines.append("- " + spacing_validation_exemption_note())

    if plan.n_crack_layers == 0:
        lines.append(
            "- **n_crack_layers = 0**: H_avail <= s_max, a legitimate outcome "
            "(section 5.2) -- no crack/skin bars would be placed."
        )
        return lines

    v_positions_mm = crack_layer_v_positions_mm(
        geometry["h_mm"], offset_btm_mm, plan.n_crack_layers, plan.actual_spacing_mm
    )
    u_left_mm, u_right_mm = crack_bar_u_positions_mm(
        geometry["b_mm"], geometry["cover_side_mm"], dia_stirrup_mm, dia_crack_mm
    )
    lines.append(
        "- u positions (A24): left = {:.1f} mm, right = {:.1f} mm; v positions: {}".format(
            u_left_mm, u_right_mm, ", ".join("{:.1f}".format(v) for v in v_positions_mm)
        )
    )

    result_start = crack_bar_end_result(
        geometry["is_supported_start"],
        support_width_mm=geometry["support_width_start_mm"],
        support_cover_mm=geometry["support_cover_start_mm"],
        beam_end_cover_mm=geometry["cover_end_start_mm"],
    )
    result_end = crack_bar_end_result(
        geometry["is_supported_end"],
        support_width_mm=geometry["support_width_end_mm"],
        support_cover_mm=geometry["support_cover_end_mm"],
        beam_end_cover_mm=geometry["cover_end_end_mm"],
    )
    for label, result in (("Start end", result_start), ("End end", result_end)):
        if result.is_supported:
            lines.append(
                "- {}: supported, embedment = {:.1f} mm, straight, no hook "
                "(A23, R2)".format(label, result.embedment_mm)
            )
        else:
            lines.append(
                "- {}: **UNSUPPORTED** -- straight run terminating {:.1f} mm "
                "short of the beam's own end (R2, mirroring section 2.5/A12)".format(
                    label, result.terminates_short_of_end_mm
                )
            )
            lines.append(
                "- **WARNING ({}):** {}".format(label, free_end_configuration_warning())
            )

    lines.append("- **Total crack/skin bar count = {}** (2 per layer x {} layers)".format(
        plan.n_crack_layers * 2, plan.n_crack_layers
    ))
    return lines
