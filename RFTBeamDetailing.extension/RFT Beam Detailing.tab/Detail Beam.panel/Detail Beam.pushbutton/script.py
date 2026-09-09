# -*- coding: utf-8 -*-
"""U2 (issue #46) -- the single "Detail Beam" shell: one WPFWindow, five
tabs, one beam-pick flow, one Transaction. The eventual replacement for
"Place Main Bars", "Place Stirrups" and "Place Crack Bars" (A46, A47).

NOTHING IS DELETED BY THIS TICKET. This button is ADDED ALONGSIDE those
three, which stay until the single window has been verified on a live host
-- deletion is #55 (U11), on the project owner's instruction. The ribbon
carries both meanwhile, deliberately: those three are the only VERIFIED
tool (v0.1.0 placed real reinforcement with them on a 0 and a 45 degree
beam), so while the Place button below is still a stub the tool as a whole
is never broken. They do not conflict at runtime -- separate pushbutton
folders, loaded independently by pyRevit, sharing lib/rft read-only.

Keeping them also buys a check that deleting early would have thrown away:
detail the same beam both ways and compare, which is a direct test that this
rework changed the INTERFACE and not the DETAILING. That comparison is an
acceptance criterion on #55.

SCOPE (this ticket only): the window, the tab set, the beam-pick control and
the transaction boundary. Tab CONTENTS -- bar-type pickers, spacing inputs,
the live sketch, the Review-tab derivation and report -- are #47 (U3), #48
(U4) and #50 (U6). The Place button on the Review tab is a LOUD stub: it
opens the one Transaction A46 requires, calls into a placement function that
is not implemented yet, and lets that failure roll the transaction back and
report itself -- naming the tickets that will fill it in. A button that
looks finished and places nothing would be worse than one that says so.

A35 -- the dialog opens FIRST, then the beam is picked: this script shows
the window before anything Revit-specific happens, and every geometry/
support field on "Beam & Materials" is disabled until a beam is picked.
Re-picking repopulates them and re-runs support detection from scratch.

Ordering preserved from today's pushbuttons, load-bearing per this ticket's
brief: continuous-run refusal (A41) -> support detection -> no-support-at-
both-ends refusal -> cover reads -- all of it BEFORE any placement work, and
all of it running again on every re-pick.

#47 (U3) ADDS to the above, on the SAME "Beam & Materials" tab: the four
per-face covers now shown separately (top/bottom/start end/end end, never
concatenated, never formatting a supported end's None cover numerically --
the rc5 crash); one RebarBarType picker per bar role (top main, bottom
main, stirrup, crack) plus the stirrup RebarHookType, each populated by
``bar_types.bar_type_options``/``hook_type_options`` and labelled with the
measured diameter and A34's required grade (``role_picker_label``); the
hook picker filtered to the Stirrup/Tie family and re-checked after
picking (A45); and L/b/h made to actually mean something once edited --
parsed and validated at Place, naming the offending field.

STRUCTURAL, not guarded (this ticket's last acceptance criterion): the
window holds exactly ONE attribute per role (``self.selection``, a
``BeamMaterialsSelection``), written only by each picker's own
``SelectionChanged`` handler. There is no second bar-type/hook-type
collector call anywhere below, and no "fall back to the first one found"
branch -- an unpicked role reads back as unpicked and Place refuses,
naming it. U4/U6 (not yet built) read this same attribute; they cannot
introduce the A46 stirrup-diameter mismatch because there is only one
place a stirrup ``RebarBarType`` can come from.
"""

from pyrevit import forms, revit, script

from rft.core.anchorage import DEFAULT_LD_BTM_MULTIPLIER, DEFAULT_LD_TOP_MULTIPLIER
from rft.core.crack_bars import (
    DEFAULT_S_MAX_MM,
    available_height_mm,
    crack_reinforcement_triggered,
)
from rft.core.guards import stirrup_type3_guard_message
from rft.core.layout import MAX_LAYERS, layer_offset_mm
from rft.core.grades import (
    ROLE_BOTTOM_MAIN,
    ROLE_CRACK,
    ROLE_STIRRUP,
    ROLE_TOP_MAIN,
    hook_angle_guard_message,
    hook_style_guard_message,
    missing_bar_type_selection_message,
    missing_hook_type_selection_message,
    no_usable_hook_type_message,
    role_picker_label,
    unreadable_hook_style_message,
)
from rft.revit.bar_types import (
    bar_type_diameter_mm,
    bar_type_options,
    element_name,
    hook_angle_deg,
    hook_style,
    hook_type_options,
    list_stirrup_hook_types,
)
from rft.revit.geometry import (
    beam_axis_direction,
    beam_endpoints,
    beam_section_axes,
    beam_section_dimensions_mm,
    find_supporting_element,
    support_width_along_axis_mm,
)
from rft.revit.guards import continuous_run_guard
from rft.revit.host import (
    HostValidationError,
    read_beam_face_covers_mm,
    read_support_side_cover_mm,
    validate_rebar_host,
)
from rft.revit.placement import run_in_transaction
from rft.revit.units import internal_to_mm, mm_to_internal
from rft.ui import inputs as ui_inputs

output = script.get_output()
doc = revit.doc

# #47 (U3) -- one (role, selection-attribute, ComboBox x:Name, label
# TextBlock x:Name) row per bar-type role the Beam & Materials tab owns.
# Driving the picker wiring from this single tuple, rather than one
# hand-written block per role, is what makes "one attribute per role,
# populated only from the picker" (this ticket's structural requirement)
# hold for all four roles instead of being re-typed four times with a
# chance to diverge.
BAR_TYPE_ROLE_ROWS = (
    (ROLE_TOP_MAIN, "top_main_bar_type", "top_main_bar_combo", "top_main_bar_label_tb"),
    (ROLE_BOTTOM_MAIN, "bottom_main_bar_type", "bottom_main_bar_combo", "bottom_main_bar_label_tb"),
    (ROLE_STIRRUP, "stirrup_bar_type", "stirrup_bar_combo", "stirrup_bar_label_tb"),
    (ROLE_CRACK, "crack_bar_type", "crack_bar_combo", "crack_bar_label_tb"),
)

# Roles Place refuses on if unset. Crack bars are deliberately EXCLUDED:
# whether a crack bar type is REQUIRED depends on h > 700 (rev 2 section
# 5), a derivation that belongs to the Review tab (#50, U6) and does not
# exist yet -- forcing a crack-bar selection here for every beam, including
# one with h <= 700, would be this ticket inventing U6's rule early.
REQUIRED_BAR_TYPE_ROLES_FOR_PLACE = (
    (ROLE_TOP_MAIN, "top_main_bar_type"),
    (ROLE_BOTTOM_MAIN, "bottom_main_bar_type"),
    (ROLE_STIRRUP, "stirrup_bar_type"),
)


class BeamMaterialsSelection(object):
    """The single source of truth for "one RebarBarType per role, plus the
    stirrup RebarHookType" (this ticket's last acceptance criterion).

    Exactly one attribute per role, populated ONLY by the matching
    ComboBox's ``SelectionChanged`` handler below -- there is no second
    ``bar_type_options``/``list_stirrup_hook_types`` call anywhere else in
    this window, and no "if unset, use the first one found" branch
    anywhere (A42). U4's tabs and the eventual ``_do_place`` read these
    same attributes directly, so the stirrup type positioning the main
    bars (§4, §6.1) and the stirrup type placed as stirrups cannot be two
    different elements -- the A46 mismatch this ticket must make
    structurally impossible, not guarded.
    """

    def __init__(self):
        self.top_main_bar_type = None
        self.bottom_main_bar_type = None
        self.stirrup_bar_type = None
        self.crack_bar_type = None
        self.stirrup_hook_type = None
        # The hook's own angle as read back, or None when it could not be
        # read at all -- carried here so #50's report can state plainly
        # whether A45's 135 degrees was VERIFIED or merely assumed,
        # instead of the report having to re-read the parameter and
        # possibly disagree with what the picker checked.
        self.stirrup_hook_angle_deg = None


def _end_support(document, point, axis, beam_id):
    """Detect the support at one beam end (rev 2 section 2.4, A9). A free/
    cantilever end returns (None, None) -- the unsupported path (section
    2.5). Identical helper to every pre-#46 pushbutton's own copy.
    """
    support = find_supporting_element(document, point, mm_to_internal, exclude_element_id=beam_id)
    if support is None:
        return None, None
    width_mm = support_width_along_axis_mm(support, axis, internal_to_mm)
    return support, width_mm


def _format_cover_mm(value_mm):
    """Never format ``None`` numerically -- the exact rc5 crash this
    project already hit once (``"{:.1f}".format(None)``). ``None`` here
    means "no exposed face to read", which is the normal case at a
    SUPPORTED end (rev 2 section 10 / issue #30) -- not a missing value.
    """
    if value_mm is None:
        return "n/a (supported)"
    return "{:.1f} mm".format(value_mm)


def _format_support(is_supported, width_mm, cover_mm):
    if not is_supported:
        return "none detected (free/cantilever end -- rev 2 section 2.5, A14)"
    return "detected, width = {:.1f} mm, support cover = {}".format(
        width_mm, _format_cover_mm(cover_mm)
    )


def _parse_positive_float(text, field_label):
    """L/b/h are read from the model but editable (A35) -- the engineer's
    edit wins over the model read. Parsed only here, at Place, so an
    invalid edit is caught with a message naming the offending field
    rather than surfacing later as a cryptic core-function ValueError.
    """
    stripped = (text or "").strip()
    try:
        value = float(stripped)
    except ValueError:
        raise ValueError("{} must be a number -- got '{}'.".format(field_label, stripped))
    if value <= 0:
        raise ValueError("{} must be positive -- got {}.".format(field_label, value))
    return value


class DetailBeamWindow(forms.WPFWindow):
    """The five-tab shell (issue #46). "Beam & Materials" (#47) and the
    Main bars/Stirrups/Crack bars tabs (#48, this ticket) collect inputs;
    Review's derivation and report (#50) and placement itself (#56) are
    not built yet -- this ticket places nothing, per its own scope."""

    def __init__(self):
        # Bare filename: WPFWindow._determine_xaml resolves it against
        # EXEC_PARAMS.command_path, the folder this script sits in --
        # confirmed by the #42 spike, not re-derived here.
        forms.WPFWindow.__init__(self, "DetailBeamWindow.xaml")

        self.beam = None
        self.host_data = None
        self.geometry_mm = None
        # #48 -- the beam's own top/bottom cover, kept as NUMBERS (not just
        # formatted into a TextBlock) so H_avail (rev 2 section 5.1, A26)
        # can be computed live without a second read of the model. Cleared
        # with the rest of the beam-scoped state.
        self.beam_covers_mm = None
        # #47 (U3) -- the one attribute per role this window owns; see
        # ``BeamMaterialsSelection``'s docstring. Populated only by the
        # ComboBox handlers wired below, never re-derived elsewhere.
        self.selection = BeamMaterialsSelection()
        self._bar_type_options_by_role = {}
        self._hook_type_options = []

        self.pick_btn.Click += self.on_pick_click
        self.place_btn.Click += self.on_place_click

        # Bar/hook types are DOCUMENT-scoped, not beam-scoped (a
        # RebarBarType does not belong to any one beam), so the pickers
        # are populated once here rather than re-queried on every pick --
        # doing so on every pick would be the exact second-collector-call
        # this ticket's structural requirement forbids.
        self._populate_material_pickers()

        # #48 (U4) -- defaults for Main bars/Stirrups/Crack bars are set
        # HERE, from the imported core constants, rather than trusted to
        # whatever literal happens to sit in the XAML -- so the shipped
        # default provably traces to ``rft.core`` and cannot drift from it
        # (A36; this ticket's instruction that defaults come from the core
        # constants, never retyped literals).
        self._populate_reinforcement_tab_defaults()

        # h is editable (#47, A35) and the crack tab's enabled state must
        # track it live (this ticket's brief), not only at pick time.
        self.h_tb.TextChanged += self._on_h_or_layout_changed
        self.top_layers_tb.TextChanged += self._on_h_or_layout_changed
        self.bottom_layers_tb.TextChanged += self._on_h_or_layout_changed
        self.spacer_dia_tb.TextChanged += self._on_h_or_layout_changed

        self._reset_beam_state(message="No beam picked yet.")

    # ------------------------------------------------------- bar/hook types
    def _populate_material_pickers(self):
        """Fills each role's ComboBox from ``bar_types.bar_type_options``/
        ``hook_type_options`` -- the measured-diameter labelling A42/#27
        already produces -- and wires each to the ONE attribute on
        ``self.selection`` it owns. No default selection is set
        (``SelectedIndex = -1``): A42 forbids a fallback to "first found",
        so an unpicked role must read back as unpicked, not as index 0.
        """
        # ONE collector pass, shared by all four roles. Calling
        # bar_type_options once per role ran the same document-wide query
        # four times -- and made this module's own claim of a single
        # bar-type lookup false, which is the claim the ticket's
        # structural requirement rests on.
        options = bar_type_options(doc, internal_to_mm)
        for role, attr_name, combo_name, label_name in BAR_TYPE_ROLE_ROWS:
            getattr(self, label_name).Text = role_picker_label(role)
            self._bar_type_options_by_role[role] = options
            combo = getattr(self, combo_name)
            # Label strings only, never the raw (label, bar_type) tuples --
            # binding tuples straight to ItemsSource renders the Python
            # repr in the dropdown. The element is recovered afterwards by
            # looking the chosen label back up in ``options``.
            combo.ItemsSource = [label for label, _bar_type in options]
            combo.SelectedIndex = -1
            combo.SelectionChanged += (
                lambda sender, args, role=role, attr_name=attr_name:
                self._on_bar_type_selected(sender, role, attr_name)
            )

        stirrup_hook_candidates = list_stirrup_hook_types(doc)
        self._hook_type_options = hook_type_options(stirrup_hook_candidates)
        self.stirrup_hook_combo.ItemsSource = [
            label for label, _hook_type in self._hook_type_options
        ]
        self.stirrup_hook_combo.SelectedIndex = -1
        self.stirrup_hook_combo.SelectionChanged += self._on_hook_type_selected
        if not stirrup_hook_candidates:
            self.stirrup_hook_status_tb.Text = no_usable_hook_type_message().message

    def _on_bar_type_selected(self, sender, role, attr_name):
        label = sender.SelectedItem
        if label is None:
            setattr(self.selection, attr_name, None)
        else:
            options = self._bar_type_options_by_role[role]
            # dict(options) recovers the element the label was built from --
            # the same pattern the three pre-#46 pushbuttons already use for
            # ``forms.SelectFromList``, applied to a ComboBox instead.
            setattr(self.selection, attr_name, dict(options)[label])
        # #48 -- H_avail (rev 2 section 5.1, A26) needs the top/bottom main
        # bar diameters AND the stirrup diameter, all of which live only on
        # ``self.selection``, so every role's picker re-triggers the same
        # refresh rather than only the two main-bar roles.
        self._refresh_h_avail()

    def _on_hook_type_selected(self, sender, args):
        """Rev 2 section 7.3 (A45): the selection is re-checked AFTER
        picking, not trusted on the strength of ``list_stirrup_hook_types``
        having pre-filtered the candidate list -- that filter is a
        convenience, not a guarantee (its own docstring says so). A
        rejected pick is reverted (``SelectedIndex = -1``) so
        ``self.selection.stirrup_hook_type`` never holds a hook that
        failed either half of the two-part guard.
        """
        label = sender.SelectedItem
        if label is None:
            self.selection.stirrup_hook_type = None
            self.selection.stirrup_hook_angle_deg = None
            return
        hook_type = dict(self._hook_type_options)[label]
        hook_type_name = element_name(hook_type)

        style = hook_style(hook_type)
        if style is None:
            forms.alert(
                unreadable_hook_style_message(hook_type_name).message,
                title="Stirrup hook family could not be verified",
            )
            sender.SelectedIndex = -1
            self.selection.stirrup_hook_type = None
            return
        style_violation = hook_style_guard_message(style, hook_type_name=hook_type_name)
        if style_violation:
            forms.alert(style_violation.message, title="Stirrup hook family is not Stirrup/Tie")
            sender.SelectedIndex = -1
            self.selection.stirrup_hook_type = None
            return

        angle_deg = hook_angle_deg(hook_type)
        if angle_deg is None:
            # An unreadable ANGLE does NOT block -- the verified "Place
            # Stirrups" button does not block on it either, because the
            # FAMILY check above is the half that actually prevents
            # Revit's opaque InternalException. But it must be SAID. That
            # button prints an explicit UNVERIFIED line telling the
            # engineer to confirm the 135 degrees by hand, and issue #25
            # is still open precisely because no live host has read this
            # parameter back yet. Accepting the hook in silence would
            # drop the one piece of information the engineer can act on.
            self.stirrup_hook_status_tb.Text = (
                "Hook '{}' accepted, but its angle is UNVERIFIED: the "
                "angle could not be read back and checked against the "
                "required 135 degrees (rev 2 section 7.3, A45). The "
                "Stirrup/Tie family WAS verified. Confirm the 135-degree "
                "angle manually before relying on this beam's "
                "stirrups.".format(hook_type_name)
            )
        else:
            angle_violation = hook_angle_guard_message(angle_deg, hook_type_name=hook_type_name)
            if angle_violation:
                forms.alert(angle_violation.message, title="Stirrup hook angle is not 135 degrees")
                sender.SelectedIndex = -1
                self.selection.stirrup_hook_type = None
                return
            # Nothing wrong to report, so this red status line goes quiet.
            # The POSITIVE confirmation ("angle read back = 135.0") is the
            # report's job, as it is in the verified pushbutton today --
            # #50 (U6) prints it from stirrup_hook_angle_deg below.
            self.stirrup_hook_status_tb.Text = ""

        self.selection.stirrup_hook_angle_deg = angle_deg
        self.selection.stirrup_hook_type = hook_type

    # --------------------------------------------------- U4 reinforcement tabs
    def _populate_reinforcement_tab_defaults(self):
        """Main bars/Stirrups/Crack bars tab defaults (issue #48, U4), set
        from the imported ``rft.core`` constants rather than left to
        whatever literal the XAML happens to carry -- ``DEFAULT_LD_TOP_
        MULTIPLIER``/``DEFAULT_LD_BTM_MULTIPLIER`` (``rft.core.anchorage``),
        ``DEFAULT_S_MAX_MM`` (``rft.core.crack_bars``) and ``MAX_LAYERS``
        (``rft.core.layout``). Bar counts and layer counts are NOT touched
        here -- they ship blank (A44) and this method must never fill them.
        """
        self.ld_top_mult_tb.Text = "{:.0f}".format(DEFAULT_LD_TOP_MULTIPLIER)
        self.ld_btm_mult_tb.Text = "{:.0f}".format(DEFAULT_LD_BTM_MULTIPLIER)
        self.ld_top_label_tb.Text = (
            "Top bar development length multiplier (LD_top, default {:.0f})".format(
                DEFAULT_LD_TOP_MULTIPLIER
            )
        )
        self.ld_btm_label_tb.Text = (
            "Bottom bar development length multiplier (LD_btm, default {:.0f})".format(
                DEFAULT_LD_BTM_MULTIPLIER
            )
        )
        self.top_layers_label_tb.Text = "Number of top layers (1-{})".format(MAX_LAYERS)
        self.bottom_layers_label_tb.Text = "Number of bottom layers (1-{})".format(MAX_LAYERS)

        self.crack_s_max_tb.Text = "{:.0f}".format(DEFAULT_S_MAX_MM)
        self.crack_s_max_label_tb.Text = (
            "Max spacing between crack-bar layers, s_max (mm, default {:.0f})".format(
                DEFAULT_S_MAX_MM
            )
        )

        # #48 (U4) constraint 4: the ComboBox offers ONLY 1, 2, 4 -- type 3
        # is never an item to select, not merely refused after typing (A31,
        # R6). Default selection is stirrup type 1 (A36).
        self.closure_type_combo.ItemsSource = [
            str(n) for n in ui_inputs.ALLOWED_CLOSURE_TYPES
        ]
        self.closure_type_combo.SelectedIndex = 0
        # rft.core.guards.stirrup_type3_guard_message()'s OWN text, quoted
        # verbatim (this ticket's constraint 4) so the note on this tab
        # cannot drift from the guard it describes.
        self.closure_type3_note_tb.Text = stirrup_type3_guard_message().message

        self.crack_bars_tab.IsEnabled = False
        self.h_avail_tb.Text = ui_inputs.no_beam_picked_h_avail_message()

    def _on_h_or_layout_changed(self, sender, args):
        """Re-evaluates the crack tab's enabled state and H_avail on every
        edit of `h` or of the main-bar layer counts/spacer diameter (this
        ticket's brief: `h` is editable, #47/A35, and the crack tab's
        enabled state must track it live, not only at pick time).

        A half-typed or empty `h` must never crash the window: unparseable
        text returns ``None`` from ``ui_inputs.try_parse_float`` and this
        handler leaves the crack tab's CURRENT enabled state untouched --
        it does not force it to disabled.
        """
        h_mm = ui_inputs.try_parse_float(self.h_tb.Text)
        if h_mm is not None:
            self.crack_bars_tab.IsEnabled = crack_reinforcement_triggered(h_mm)
        self._refresh_h_avail()

    def _refresh_h_avail(self):
        """H_avail (rev 2 section 5.1, A26), DISPLAYED, never entered (this
        ticket's constraint 3) -- measured to the INNERMOST main-bar layer,
        read from the Main bars tab and ``self.selection``'s bar types
        rather than re-asked. Shows a sentence naming what is missing
        instead of a number or a formatted ``None`` (this ticket's brief;
        the exact gap this ticket closes in v0.1.0's "Place Crack Bars").

        No detailing arithmetic lives in ``rft.ui.inputs`` -- it only
        reports which input is missing; the actual offsets and H_avail
        itself are computed here, by calling ``rft.core.layout.
        layer_offset_mm`` / ``rft.core.crack_bars.available_height_mm``
        directly, per A48 (the renderer/adapter owns no detailing
        arithmetic of its own).
        """
        if self.beam is None or self.beam_covers_mm is None:
            self.h_avail_tb.Text = ui_inputs.no_beam_picked_h_avail_message()
            return

        h_mm = ui_inputs.try_parse_float(self.h_tb.Text)
        top_bar_dia_mm = (
            bar_type_diameter_mm(self.selection.top_main_bar_type, internal_to_mm)
            if self.selection.top_main_bar_type is not None else None
        )
        btm_bar_dia_mm = (
            bar_type_diameter_mm(self.selection.bottom_main_bar_type, internal_to_mm)
            if self.selection.bottom_main_bar_type is not None else None
        )
        stirrup_dia_mm = (
            bar_type_diameter_mm(self.selection.stirrup_bar_type, internal_to_mm)
            if self.selection.stirrup_bar_type is not None else None
        )
        try:
            layers_top = ui_inputs.parse_optional_positive_int(
                self.top_layers_tb.Text, "Number of top layers", max_value=MAX_LAYERS
            )
            layers_btm = ui_inputs.parse_optional_positive_int(
                self.bottom_layers_tb.Text, "Number of bottom layers", max_value=MAX_LAYERS
            )
        except ValueError:
            # An in-progress/invalid layer-count edit is reported the same
            # way as a MISSING one -- H_avail cannot be computed from it
            # either way, and this handler must never raise (it runs on
            # every keystroke).
            layers_top = None
            layers_btm = None

        missing = ui_inputs.missing_h_avail_inputs(
            h_mm, top_bar_dia_mm, btm_bar_dia_mm, stirrup_dia_mm, layers_top, layers_btm
        )
        if missing:
            self.h_avail_tb.Text = ui_inputs.h_avail_missing_message(missing)
            return

        try:
            spacer_dia_mm = ui_inputs.parse_positive_float(
                self.spacer_dia_tb.Text, "O_spacer"
            )
        except ValueError:
            self.h_avail_tb.Text = ui_inputs.h_avail_missing_message(
                ["a valid spacer diameter (O_spacer)"]
            )
            return

        offset_top_mm = layer_offset_mm(
            self.beam_covers_mm.top_mm, stirrup_dia_mm, top_bar_dia_mm, spacer_dia_mm, layers_top
        )
        offset_btm_mm = layer_offset_mm(
            self.beam_covers_mm.bottom_mm, stirrup_dia_mm, btm_bar_dia_mm, spacer_dia_mm, layers_btm
        )
        h_avail_mm = available_height_mm(h_mm, offset_top_mm, offset_btm_mm)
        self.h_avail_tb.Text = "H_avail = {:.1f} mm (rev 2 section 5.1, A26).".format(
            h_avail_mm
        )

    # ------------------------------------------------------------ picking
    def _reset_beam_state(self, message):
        """A35: every geometry/support field is disabled until a beam is
        picked, and a failed/refused pick must leave the window in exactly
        this same disabled state -- never a half-populated one.

        Bar/hook type selections are DELIBERATELY left untouched here: they
        are document-scoped (A42), not beam-scoped, so re-picking a beam
        (or refusing one) has no bearing on which stirrup diameter the
        engineer already chose -- clearing it on every pick would make the
        engineer re-select bar types per beam for no reason a spec section
        gives.
        """
        self.beam = None
        self.host_data = None
        self.beam_covers_mm = None
        # Beam-scoped, so cleared here with everything else. Written only
        # at Place today, so nothing reads a stale value YET -- but #49's
        # live sketch and #50's report both read the geometry, and leaving
        # the previous beam's L/b/h here would hand them the WRONG beam's
        # dimensions with nothing to indicate it.
        #
        # This line is the actual fix that #47's review claimed to have
        # made. That edit anchored on "self.beam = None / self.host_data =
        # None", which appears in BOTH this method and __init__, and it
        # matched __init__ first -- leaving a duplicate assignment there
        # and this method untouched. An anchor that is not unique is not
        # an anchor.
        self.geometry_mm = None
        self.beam_status_tb.Text = message
        self.warnings_tb.Text = ""
        self.l_tb.Text = ""
        self.b_tb.Text = ""
        self.h_tb.Text = ""
        self.cover_top_tb.Text = ""
        self.cover_bottom_tb.Text = ""
        self.cover_side_tb.Text = ""
        self.cover_start_end_tb.Text = ""
        self.cover_end_end_tb.Text = ""
        self.start_support_tb.Text = ""
        self.end_support_tb.Text = ""
        # #48 -- an explicit reset (no beam picked, or a refused pick)
        # forces the crack tab closed and H_avail back to "no beam picked"
        # rather than leaving whatever state the previous beam left behind.
        # This is deliberately NOT the same code path as
        # ``_on_h_or_layout_changed``'s "leave current state unchanged on
        # an unparseable edit" -- that rule is for an in-progress keystroke,
        # not for a beam being un-picked outright.
        self.crack_bars_tab.IsEnabled = False
        self.h_avail_tb.Text = ui_inputs.no_beam_picked_h_avail_message()

    def on_pick_click(self, sender, args):
        # Re-picking must repopulate everything and re-run support
        # detection from scratch (A35) -- so the state is reset FIRST,
        # regardless of how far the previous pick got.
        self._reset_beam_state(message="No beam picked yet.")

        beam = revit.pick_element(message="Select a beam (structural framing) to detail.")
        if beam is None:
            return

        try:
            host_data = validate_rebar_host(beam)
        except HostValidationError as ex:
            forms.alert(str(ex), title="Host validation failed")
            return

        start_pt, end_pt = beam_endpoints(beam)
        axis = beam_axis_direction(beam)
        u_dir, v_dir = beam_section_axes(beam)
        b_mm, h_mm = beam_section_dimensions_mm(beam, internal_to_mm)
        # Placeholder L for THIS shell only: the physical location-curve
        # endpoint distance. Rev 2's own L (A6) is support-centre-to-
        # support-centre (`rft.revit.geometry.span_length_mm`), which needs
        # both supports resolved -- not always true here, since one end may
        # be unsupported. #47 (Beam & Materials) owns the real pre-fill
        # rule for this field; this value is only for the shell to have
        # something honest to show and re-populate on every pick.
        l_mm = internal_to_mm(start_pt.DistanceTo(end_pt))

        # --- A41, run BEFORE support detection: a collinear neighbouring
        # beam at either end makes this a continuous run, not a single
        # span, and REFUSES outright rather than being merely warned.
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
            return

        # --- support detection, per end, any support type (rev 2 section
        # 2.4/A9) -- run AFTER the continuous-run refusal, BEFORE the
        # no-support refusal and the cover reads, exactly as today's
        # pushbuttons order it.
        support_start, support_width_start_mm = _end_support(doc, start_pt, axis, beam.Id)
        support_end, support_width_end_mm = _end_support(doc, end_pt, axis, beam.Id)
        is_supported_start = support_start is not None
        is_supported_end = support_end is not None

        if not is_supported_start and not is_supported_end:
            forms.alert(
                "No support (column, wall or girder) detected at EITHER end "
                "(rev 2 section 2.4/2.5, A9/A12/A14). This tool details a "
                "single-span, simply-supported beam -- a beam with no "
                "support at all is not a span and is refused outright "
                "rather than silently detailed (this project's own "
                "judgement call, not a rev 2 rule).",
                title="No support detected",
            )
            return

        warning_lines = []
        if not is_supported_start:
            warning_lines.append("Start end: no support detected -- free/cantilever end (A14), warned not refused.")
        if not is_supported_end:
            warning_lines.append("End end: no support detected -- free/cantilever end (A14), warned not refused.")

        # --- cover reads, LAST, only after both refusals above have had
        # their chance to fire (issue #30/#46 ordering): END covers are
        # only requested at whichever end is actually unsupported, since a
        # supported end exposes no end face to read at all.
        try:
            beam_covers = read_beam_face_covers_mm(
                beam, host_data, u_dir, v_dir, axis, internal_to_mm, element_id=beam.Id,
                need_end_start=not is_supported_start, need_end_end=not is_supported_end,
            )
        except HostValidationError as ex:
            forms.alert(str(ex), title="Cover read-back failed")
            return

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
            return

        # --- everything above succeeded: populate and enable the fields.
        self.beam = beam
        self.host_data = host_data
        # #48 -- set BEFORE ``h_tb.Text`` below, whose ``TextChanged`` fires
        # ``_on_h_or_layout_changed`` -> ``_refresh_h_avail`` immediately:
        # H_avail needs ``self.beam_covers_mm`` already set to compute
        # anything rather than fall back to "no beam picked".
        self.beam_covers_mm = beam_covers
        self.beam_status_tb.Text = "Picked beam id {}.".format(beam.Id)
        self.warnings_tb.Text = "\n".join(warning_lines)
        self.l_tb.Text = "{:.1f}".format(l_mm)
        self.b_tb.Text = "{:.1f}".format(b_mm)
        self.h_tb.Text = "{:.1f}".format(h_mm)
        # Four covers, each face SEPARATELY (this ticket's explicit
        # requirement) -- never concatenated into one TextBlock, and never
        # formatted through the same numeric path for the two end covers,
        # which are None on a supported end (the rc5 crash).
        self.cover_top_tb.Text = "Top: {:.1f} mm".format(beam_covers.top_mm)
        self.cover_bottom_tb.Text = "Bottom: {:.1f} mm".format(beam_covers.bottom_mm)
        self.cover_side_tb.Text = "Side: {:.1f} mm".format(beam_covers.side_mm)
        self.cover_start_end_tb.Text = "Start end: {}".format(
            _format_cover_mm(beam_covers.end_start_mm)
        )
        self.cover_end_end_tb.Text = "End end: {}".format(
            _format_cover_mm(beam_covers.end_end_mm)
        )
        self.start_support_tb.Text = "Start end: " + _format_support(
            is_supported_start, support_width_start_mm, support_cover_start_mm
        )
        self.end_support_tb.Text = "End end: " + _format_support(
            is_supported_end, support_width_end_mm, support_cover_end_mm
        )
        self.geometry_panel.IsEnabled = True

    # ------------------------------------------------------------- place
    def _do_place(self):
        """THE PLACEMENT CALL SITE IS A LOUD STUB, NOT A SILENT NO-OP.

        Main bars, stirrups and crack bars are placed by #47 (Beam &
        Materials -- bar-type/hook selection), #48 (the three
        reinforcement tabs' own inputs) and #50 (Review's derivation rule
        and report), none of which exist yet. Raising here -- inside the
        one Transaction ``run_in_transaction`` already wraps -- is
        deliberate: it proves the rollback path works on a real exception
        before there is anything real to roll back, and it refuses to let
        the engineer believe Place did something it did not.
        """
        raise NotImplementedError(
            "Place is not implemented yet, and nothing has been placed.\n\n"
            "USE THE EXISTING BUTTONS MEANWHILE: \"Place Main Bars\", "
            "\"Place Stirrups\" and \"Place Crack Bars\" are still on the "
            "ribbon and still work -- they are the verified tool (v0.1.0). "
            "They stay until this window has replaced them in practice "
            "(#55).\n\n"
            "This window's placement is built by #56, which ports the "
            "three verified buttons' placement paths into this one "
            "transaction. Its inputs come from #48 (Main bars/Stirrups/"
            "Crack bars tabs) and #50 (Review tab's derivation and "
            "report). This ticket (#46) built only the window, the tabs, "
            "the beam-pick flow and the transaction boundary."
        )

    def _missing_bar_type_and_hook_messages(self):
        """The A42 no-fallback check, read from the ONE attribute per role
        ``self.selection`` owns -- never a second lookup into the
        document. Returns the list of ``GuardMessage``s for whichever
        roles are still unpicked, naming each one.
        """
        missing = []
        for role, attr_name in REQUIRED_BAR_TYPE_ROLES_FOR_PLACE:
            if getattr(self.selection, attr_name) is None:
                missing.append(missing_bar_type_selection_message(role))
        if self.selection.stirrup_hook_type is None:
            missing.append(missing_hook_type_selection_message())
        return missing

    def on_place_click(self, sender, args):
        if self.beam is None:
            forms.alert(
                "Pick a beam on the Beam & Materials tab before pressing "
                "Place (A35).",
                title="No beam picked",
            )
            return

        # L/b/h are editable (A35) -- the engineer's edit wins over the
        # model read. Parsed here, at Place, naming the offending field
        # rather than letting a bad edit reach a core function as a
        # confusing ValueError.
        try:
            l_mm = _parse_positive_float(self.l_tb.Text, "L")
            b_mm = _parse_positive_float(self.b_tb.Text, "b")
            h_mm = _parse_positive_float(self.h_tb.Text, "h")
        except ValueError as ex:
            forms.alert(str(ex), title="Invalid geometry input")
            return
        self.geometry_mm = (l_mm, b_mm, h_mm)

        # This ticket's structural requirement: Place refuses by name,
        # from the SAME attribute the pickers set -- no second collector
        # call, no defaulting to "first found" (A42).
        missing = self._missing_bar_type_and_hook_messages()
        if missing:
            forms.alert(
                "\n\n".join(m.message for m in missing),
                title="Bar type / hook selection required",
            )
            return

        try:
            run_in_transaction(doc, "RFT Detail Beam", self._do_place)
        except NotImplementedError as ex:
            # The expected path today: the stub refused, the transaction
            # rolled back, nothing was placed.
            message = str(ex)
            self.place_result_tb.Text = message
            forms.alert(message, title="Not implemented yet")
            return
        except Exception as ex:
            # A GENUINE failure, distinguished from the stub deliberately.
            # Titling every exception "Not implemented" would, the moment
            # #47/#48/#50 land, report a real Revit error -- an
            # InternalException from a rejected hook family, say -- as an
            # unfinished feature, and send whoever reads it looking in
            # entirely the wrong place. The transaction has rolled back
            # either way, so the model is unchanged; only the diagnosis
            # differs, and the diagnosis is the whole value of the message.
            message = "Placement FAILED and was rolled back -- {}: {}".format(
                type(ex).__name__, ex
            )
            self.place_result_tb.Text = message
            forms.alert(message, title="Placement failed -- rolled back")
            return
        # Unreachable until #47/#48/#50 land -- self._do_place always
        # raises today, so this line has never executed and must not
        # claim success it cannot back up.
        self.place_result_tb.Text = "Placed successfully."


def main():
    window = DetailBeamWindow()
    window.ShowDialog()


if __name__ == "__main__":
    main()
