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

import os

from pyrevit import EXEC_PARAMS, forms, revit, script

from rft.core.anchorage import (
    DEFAULT_LD_BTM_MULTIPLIER,
    DEFAULT_LD_TOP_MULTIPLIER,
    development_length,
    placed_clearance_mm,
)
from rft.core.crack_bars import (
    DEFAULT_S_MAX_MM,
    available_height_mm,
    crack_bar_end_result,
    crack_reinforcement_triggered,
)
from rft.core.guards import stirrup_type3_guard_message
from rft.core.layout import (
    MAX_LAYERS,
    layer_offset_mm,
    spacer_length_mm,
)
from rft.core.spacing import governing_min_spacing_mm, validate_layer_spacing
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
from rft.core import plan as core_plan
from rft.revit.geometry import (
    beam_axis_direction,
    beam_endpoints,
    beam_section_axes,
    beam_section_centre_offsets,
    beam_section_dimensions_mm,
    end_support_face_point,
    find_supporting_element,
    point_at_cc_offset,
    span_length_mm,
    start_support_face_point,
    support_width_along_axis_mm,
)
from rft.revit.guards import continuous_run_guard
from rft.revit.host import (
    HostValidationError,
    read_beam_face_covers_mm,
    read_support_side_cover_mm,
    validate_rebar_host,
)
from rft.revit.placement import (
    bar_point_at_uv,
    bend_plane_normal,
    build_main_bar_curves,
    main_bar_end_geometry,
    place_anchored_bar,
    run_in_transaction,
)
from rft.revit.stirrups import (
    apply_maximum_spacing_layout,
    build_stirrup_curves,
    place_stirrup,
)
from rft.revit.units import internal_to_mm, mm_to_internal
from rft.ui import derivation as ui_derivation
from rft.ui import inputs as ui_inputs
from rft.ui import report as ui_report
from rft.ui import sketch as ui_sketch
from rft.ui.sketch_layout import (
    LabelBox,
    estimate_text_size_px,
    place_labels,
)
from rft.ui.sketch_palette import brush_key_for_style

# #49 (U5) -- the renderer's ONLY WPF imports for the live sketch. These
# are plain WPF/CLR types (Line/Ellipse/Polygon/TextBlock/Points), not the
# Revit API -- constructing them needs no API context, exactly like every
# other direct control write already in this file (self.h_avail_tb.Text =
# ..., etc., per docs/research/ui-wpf-hosting.md's "direct reads + one
# explicit redraw" recommendation). Wrapped: if this import ever fails on
# a live host (a pyRevit engine that has not loaded PresentationFramework
# for some reason), the whole window must still open -- the sketch is a
# verification surface, not a load-bearing part of placement.
try:
    from System.Windows import Point
    from System.Windows.Media import PointCollection
    from System.Windows.Controls import Canvas as WpfCanvas
    from System.Windows.Controls import TextBlock as WpfTextBlock
    from System.Windows.Shapes import Ellipse as WpfEllipse
    from System.Windows.Shapes import Line as WpfLine
    from System.Windows.Shapes import Polygon as WpfPolygon
    _WPF_SHAPES_AVAILABLE = True
except Exception:
    _WPF_SHAPES_AVAILABLE = False

# SHAPE UNVERIFIED (CONTEXT.md's fake-shape rule, applied here because this
# code cannot be exercised at all without a Revit host, not only faked):
# ``FrameworkElement.FindResource`` is a real WPF/.NET method and
# ``System.Windows.Controls.Canvas.SetLeft``/``SetTop`` are real static
# attached-property setters, per the .NET Framework documentation -- but
# NEITHER has been called from inside a pyRevit-hosted ``WPFWindow`` in
# this project before now. docs/research/ui-wpf-hosting.md confirms
# ``Canvas``/``Line``/``Ellipse``/``Polygon``/``TextBlock`` construction
# and pyRevit's own resource injection into ``WPFWindow``, but not
# ``FindResource`` specifically, nor ``PointCollection`` construction from
# IronPython 2.7. This whole rendering path is UNVERIFIED until it is
# shown on a live host (see this ticket's report).

# #62 -- the sketch's own two presentation constants.
#
# MIN_BAR_RADIUS_PX: a bar's position is exact, its drawn size is a
# symbol. Without a floor, a 16 mm bar on a 900 mm section is ~2 px.
# SKETCH_FONT_SIZE_PX must match rft.ui.sketch_layout's own default, since
# that module estimates a label's width from it.
MIN_BAR_RADIUS_PX = 3.0
SKETCH_FONT_SIZE_PX = 11.0

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

# What Place additionally requires, ON TOP of what the Review derivation
# (#50) has already established as requested.
#
# #48 pinned this list to "top main, bottom main, stirrup, always". Once
# #50 made Place's ENABLED state follow the derivation, that became a
# contradiction the engineer could see: request stirrups only, Review says
# "Stirrups: will be placed", Place lights up -- and then refuses, naming
# top and bottom main bars it was never asked to place.
#
# The rule now follows what each section actually consumes, read from the
# three verified pushbuttons rather than assumed:
#
#   - The STIRRUP BAR TYPE is needed by EVERY section, not just stirrups.
#     Main bars need its diameter for the layer offsets (section 4.1) and
#     crack bars for their horizontal positions (crack_bar_u_positions_mm).
#     So it is required whenever anything at all is placed.
#   - The STIRRUP HOOK TYPE is needed ONLY by stirrups. "Place Main Bars"
#     uses no RebarHookType at all -- a main bar's bent end is geometry
#     (section 2.5), not a hook type -- and neither does "Place Crack
#     Bars".
#   - Each face's own main-bar type, and the crack bar type, are implied by
#     the derivation itself: a face is not REQUESTED without its type.
#
# A42's no-fallback rule is unchanged. Nothing here defaults to a "first
# found" type; this only stops Place demanding a selection for
# reinforcement nobody asked to place.


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


def _support_detection(support_start, support_end, start_pt, end_pt, axis,
                       support_width_start_mm, support_width_end_mm,
                       support_cover_start_mm, support_cover_end_mm):
    """The ONE place the support-detection dict's shape is written.

    Two callers need it: ``_detect_supports_uncached``, which scans for
    the supports itself, and ``_pick_beam_in_context``, which has already
    scanned and only needs the result cached so the live sketch can read
    plain numbers off the UI thread (#49). Before this existed the second
    caller spelled out all twelve keys again. It agreed exactly with the
    first -- which is how the duplicated ZONE_LAYOUT_FLAGS agreed too,
    for three releases, while the report and the placer described
    different stirrup sets.

    The derived fields are derived HERE rather than passed in, for the
    same reason: ``is_supported_*`` is "a support was found" and ``l_mm``
    is the centre-to-centre span, which exists only when both ends are
    supported. Two callers deriving those separately is two chances to
    derive them differently.
    """
    is_supported_start = support_start is not None
    is_supported_end = support_end is not None
    l_mm = None
    if is_supported_start and is_supported_end:
        l_mm = span_length_mm(support_start, support_end, internal_to_mm)
    return {
        # The support ELEMENTS, not just their measurements: placement
        # needs them for the support-face reference points and for the
        # stirrup zones' centre-to-centre datum, from the same detection
        # pass the report uses, so the two cannot disagree about which
        # element supports which end (#56).
        "support_start": support_start,
        "support_end": support_end,
        "start_pt": start_pt,
        "end_pt": end_pt,
        "axis": axis,
        "is_supported_start": is_supported_start,
        "is_supported_end": is_supported_end,
        "support_width_start_mm": support_width_start_mm,
        "support_width_end_mm": support_width_end_mm,
        "support_cover_start_mm": support_cover_start_mm,
        "support_cover_end_mm": support_cover_end_mm,
        "l_mm": l_mm,
    }


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


class SimpleBeamWindow(forms.WPFWindow):
    """The five-tab shell (issue #46). "Beam & Materials" (#47) and the
    Main bars/Stirrups/Crack bars tabs (#48, this ticket) collect inputs;
    Review's derivation and report (#50) and placement itself (#56) are
    not built yet -- this ticket places nothing, per its own scope."""

    def __init__(self):
        # Bare filename: WPFWindow._determine_xaml resolves it against
        # EXEC_PARAMS.command_path, the folder this script sits in --
        # confirmed by the #42 spike, not re-derived here.
        forms.WPFWindow.__init__(self, "SimpleBeamWindow.xaml")

        self.beam = None
        self.host_data = None
        self.geometry_mm = None
        # Support detection for the picked beam -- see ``_detect_supports``.
        # BEAM-scoped, so it is cleared on every pick along with the rest.
        self._support_detection = None
        # #48 -- the beam's own top/bottom cover, kept as NUMBERS (not just
        # formatted into a TextBlock) so H_avail (rev 2 section 5.1, A26)
        # can be computed live without a second read of the model. Cleared
        # with the rest of the beam-scoped state.
        self.beam_covers_mm = None
        # #47 (U3) -- the one attribute per role this window owns; see
        # ``BeamMaterialsSelection``'s docstring. Populated only by the
        # ComboBox handlers wired below, never re-derived elsewhere.
        self.selection = BeamMaterialsSelection()
        # #57 -- one dispatch at a time; see _dispatch_to_revit_context.
        self._api_call_in_flight = False
        self._bar_type_options_by_role = {}
        self._hook_type_options = []
        # Measured bar diameters, keyed by RebarBarType id -- see
        # ``_diameter_mm``. DOCUMENT-scoped like the picker options above,
        # not beam-scoped: a bar type's diameter has nothing to do with
        # which beam is picked, so this is deliberately NOT cleared by
        # ``_reset_beam_state``.
        self._diameter_cache_mm = {}

        # The window's TITLE-BAR icon, which is a different property from
        # the ribbon button's artwork: pyRevit reads icon.png for the
        # button when it builds the ribbon, but a WPFWindow keeps WPF's
        # default until told otherwise. Same file, so the two cannot drift.
        #
        # WRAPPED, deliberately: bitmap_from_file raises on a bad path, and
        # a missing decoration must never stop the tool opening. The window
        # is the product; the icon is not.
        try:
            self.set_icon(os.path.join(EXEC_PARAMS.command_path, "icon.png"))
        except Exception:
            pass

        self.pick_btn.Click += self.on_pick_click
        self.place_btn.Click += self.on_place_click
        self.build_report_btn.Click += self.on_build_report_click

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

        # #50 (U6) -- the derivation rule needs only the bar counts beyond
        # what #48 already tracks live: main bar counts per face. Nothing
        # here touches the Revit API (a bar count is parsed text, a bar/
        # hook type is "is this None or not"), so this stays on the UI
        # thread, unlike the report itself (see on_build_report_click).
        self.top_bar_count_tb.TextChanged += self._refresh_review_derivation
        self.bottom_bar_count_tb.TextChanged += self._refresh_review_derivation

        # #49 (U5) -- the live sketch redraws on every field that feeds
        # rft.ui.sketch's inputs (A48: it draws only what rft.core already
        # computed, so every one of THOSE fields must trigger a redraw, or
        # the drawing goes stale the moment the engineer edits one).
        # Wired directly, like _refresh_h_avail/_refresh_review_derivation
        # above -- no Revit API call happens between here and the Canvas
        # being repainted, so this needs no dispatch (#57).
        for tb_name in (
            "top_bar_count_tb", "bottom_bar_count_tb",
            "top_layers_tb", "bottom_layers_tb",
            "spacer_dia_tb", "d_agg_tb", "min_spacing_override_tb",
            "ld_top_mult_tb", "ld_btm_mult_tb",
            "dense_spacing_tb", "normal_spacing_tb", "crack_s_max_tb",
            "l_tb", "b_tb", "h_tb",
        ):
            getattr(self, tb_name).TextChanged += self._redraw_sketches
        self.top_face_option_combo.SelectionChanged += self._redraw_sketches
        self.bottom_face_option_combo.SelectionChanged += self._redraw_sketches
        self.closure_type_combo.SelectionChanged += self._redraw_sketches
        for canvas_name in (
            "main_bars_sketch_canvas", "stirrups_sketch_canvas",
            "crack_bars_sketch_canvas",
        ):
            getattr(self, canvas_name).SizeChanged += self._redraw_sketches

        self._reset_beam_state(message="No beam picked yet.")
        # Sets the initial "nothing requested -- Place disabled" state
        # (this ticket's brief) -- without this call Place would open
        # enabled until the first keystroke or pick touched a wired field.
        self._refresh_review_derivation()
        # #49 (U5) -- draws the "nothing picked yet" empty canvases rather
        # than leaving whatever WPF's own default (blank) Canvas looks
        # like before the first keystroke or pick touches a wired field.
        self._redraw_sketches()

    # ------------------------------------------------------- bar/hook types
    def _diameter_mm(self, bar_type):
        """One ``RebarBarType``'s MEASURED diameter, read from the model
        once per type and remembered. ``None`` in, ``None`` out -- an
        unpicked role has no diameter, and every caller here already has
        to handle that (A42 forbids inventing one).

        ``bar_type_diameter_mm`` is a Revit parameter read, and
        ``_refresh_h_avail`` made three of them on EVERY KEYSTROKE in
        `h`, in either layer count, and in the spacer field -- on the UI
        thread, while the engineer is typing. A bar type's diameter cannot
        change while this window is open (the type would have to be
        edited in the document, and a pyRevit reload picks that up), so
        one read per type is the same number without the traffic.

        Keyed by the element id as a STRING, not by the element: two
        wrappers for the same type are separate Python objects, and
        ``ElementId.IntegerValue`` is deprecated in the Revit versions
        this tool targets. A key that failed to match would only ever
        cause a re-read, never a wrong number.
        """
        if bar_type is None:
            return None
        key = str(bar_type.Id)
        if key not in self._diameter_cache_mm:
            self._diameter_cache_mm[key] = bar_type_diameter_mm(
                bar_type, internal_to_mm
            )
        return self._diameter_cache_mm[key]

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
        # #50 (U6) -- every role's picker can flip a section's requested
        # state (a main-bar face on its own type, crack bars on ITS type
        # plus both faces' types, A50).
        self._refresh_review_derivation()
        # #49 (U5) -- a bar type's diameter feeds every layer offset and
        # bar radius the sketch draws.
        self._redraw_sketches()

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
            self._refresh_review_derivation()
            self._redraw_sketches()
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
            self._refresh_review_derivation()
            self._redraw_sketches()
            return
        style_violation = hook_style_guard_message(style, hook_type_name=hook_type_name)
        if style_violation:
            forms.alert(style_violation.message, title="Stirrup hook family is not Stirrup/Tie")
            sender.SelectedIndex = -1
            self.selection.stirrup_hook_type = None
            self._refresh_review_derivation()
            self._redraw_sketches()
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
                self._refresh_review_derivation()
                self._redraw_sketches()
                return
            # Nothing wrong to report, so this red status line goes quiet.
            # The POSITIVE confirmation ("angle read back = 135.0") is the
            # report's job, as it is in the verified pushbutton today --
            # #50 (U6) prints it from stirrup_hook_angle_deg below.
            self.stirrup_hook_status_tb.Text = ""

        self.selection.stirrup_hook_angle_deg = angle_deg
        self.selection.stirrup_hook_type = hook_type
        # #50 (U6) -- the hook is stirrup-exclusive, so only this handler
        # (never the main-bar-type handlers) can flip the stirrups section's
        # requested state.
        self._refresh_review_derivation()
        self._redraw_sketches()

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
        #
        # #58: the items now SAY what each type is. Types 1 and 2 are the
        # same closed loop and differ only in which top corner the hooks
        # meet at, which no engineer can be expected to infer from "1" and
        # "2" -- the project owner asked precisely this on first sight of
        # the tool.
        self.closure_type_combo.ItemsSource = [
            label for _value, label in ui_inputs.CLOSURE_TYPE_CHOICES
        ]
        self.closure_type_combo.SelectedIndex = 0

        # #58: section 6.3's per-face option, likewise named rather than
        # numbered. v0.1.0's pushbutton said "1=single wide row,
        # 2=stacked"; the single window shipped "(1/2, section 6.3)" and
        # lost the meaning. Restored, and as a closed choice so an invalid
        # option cannot be typed at all.
        face_option_labels = [
            label for _value, label in ui_inputs.FACE_OPTION_CHOICES
        ]
        for combo in (self.top_face_option_combo, self.bottom_face_option_combo):
            combo.ItemsSource = face_option_labels
            combo.SelectedIndex = 0
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
        # #50 (U6) -- h and the layer counts all feed the crack-bars
        # derivation (A50), so the Review tab must track the same edits
        # H_avail already does.
        self._refresh_review_derivation()

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
        top_bar_dia_mm = self._diameter_mm(self.selection.top_main_bar_type)
        btm_bar_dia_mm = self._diameter_mm(self.selection.bottom_main_bar_type)
        stirrup_dia_mm = self._diameter_mm(self.selection.stirrup_bar_type)
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

    # --------------------------------------------------------- U6 Review tab
    #
    # Two halves, deliberately split by whether they touch the Revit API
    # (this ticket's own constraint):
    #
    # 1. THE DERIVATION (``rft.ui.derivation``) is pure logic over values
    #    already held -- a bar/hook type is only ever tested "is this None",
    #    never read for a property -- so it stays on the UI thread and
    #    recomputes live on every relevant edit, exactly like #48's H_avail.
    # 2. THE FULL REPORT (section 8.2, A37) reads bar type NAMES and
    #    DIAMETERS off already-selected elements, and re-detects supports --
    #    all genuine Revit API calls -- so it is built only inside
    #    ``_dispatch_to_revit_context``, behind its own "Build full report"
    #    button, never on a keystroke.

    def _try_parse_optional_int(self, text, field_label):
        """Tolerant wrapper for the derivation/report refresh handlers,
        which run on every keystroke and must never raise: an in-progress
        or invalid count/layer edit degrades to ``None`` -- "not entered
        yet" -- exactly like ``_refresh_h_avail`` already treats it.
        """
        try:
            return ui_inputs.parse_optional_positive_int(
                text, field_label, max_value=MAX_LAYERS
            )
        except ValueError:
            return None

    def _compute_review_derivation(self):
        """The whole Review-tab derivation (issue #50, U6), read from
        ``self.selection`` (the one attribute per role) and the tab
        TextBoxes -- no second collector call, no Revit read.
        """
        top_bar_count = self._try_parse_optional_int(
            self.top_bar_count_tb.Text, "Top bar count per layer"
        )
        bottom_bar_count = self._try_parse_optional_int(
            self.bottom_bar_count_tb.Text, "Bottom bar count per layer"
        )
        layers_top = self._try_parse_optional_int(
            self.top_layers_tb.Text, "Number of top layers"
        )
        layers_btm = self._try_parse_optional_int(
            self.bottom_layers_tb.Text, "Number of bottom layers"
        )
        h_mm = ui_inputs.try_parse_float(self.h_tb.Text)
        return ui_derivation.compute_review_derivation(
            top_bar_type_selected=self.selection.top_main_bar_type,
            top_bar_count=top_bar_count,
            bottom_bar_type_selected=self.selection.bottom_main_bar_type,
            bottom_bar_count=bottom_bar_count,
            hook_type_selected=self.selection.stirrup_hook_type,
            crack_bar_type_selected=self.selection.crack_bar_type,
            h_mm=h_mm,
            layers_top=layers_top,
            layers_btm=layers_btm,
        )

    def _refresh_review_derivation(self, sender=None, args=None):
        """Recomputes the derivation and updates the Review tab AND the
        Place button's enabled state (this ticket's brief: "Place is
        disabled when nothing is requested, and says so"). Wired as both a
        plain method call and a WPF event handler (hence the optional
        ``sender``/``args``), exactly like ``_on_h_or_layout_changed``.
        """
        review = self._compute_review_derivation()
        lines = [
            review.top_main.reason,
            review.bottom_main.reason,
            review.stirrups.reason,
            review.crack_bars.reason,
        ]
        if not review.any_requested:
            lines.append(
                "Nothing is requested yet -- Place is disabled (rev 2 "
                "section 8, this ticket's derivation rule)."
            )
        self.review_derivation_tb.Text = "\n".join(lines)
        self.place_btn.IsEnabled = review.any_requested

    # --------------------------------------------------------- U5 sketch
    #
    # #49. Every dimension drawn here is sourced from rft.core (A48) --
    # this file composes and positions; it derives nothing. Touches NO
    # Revit API: every value read below is either a plain number already
    # stored on self (from a prior pick, or the CACHED support detection
    # -- see the assignment inside _pick_beam_in_context) or a TextBox's
    # raw text, parsed by rft.ui.inputs. Nothing here needs
    # execute_in_revit_context (#57), exactly like _refresh_h_avail.
    #
    # NEVER RAISES OUT: a half-typed or empty field must leave the
    # previous drawing (or a blank canvas) on screen rather than kill the
    # window (this ticket's acceptance criterion) -- each canvas is
    # rebuilt inside its own try/except so one tab's bad input cannot
    # blank another tab's drawing.

    def _clear_canvas(self, canvas):
        try:
            canvas.Children.Clear()
        except Exception:
            pass

    def _redraw_sketches(self, sender=None, args=None):
        if not _WPF_SHAPES_AVAILABLE:
            return
        try:
            self._redraw_section_canvas(self.main_bars_sketch_canvas, want_crack=False)
        except Exception:
            self._clear_canvas(self.main_bars_sketch_canvas)
        try:
            self._redraw_section_canvas(self.crack_bars_sketch_canvas, want_crack=True)
        except Exception:
            self._clear_canvas(self.crack_bars_sketch_canvas)
        try:
            self._redraw_elevation_canvas(self.stirrups_sketch_canvas)
        except Exception:
            self._clear_canvas(self.stirrups_sketch_canvas)

    def _sketch_common_inputs(self):
        """b/h/covers/stirrup diameter, or ``None`` when any is missing or
        unparseable -- the shared minimum every sketch view needs.
        """
        if self.beam is None or self.beam_covers_mm is None:
            return None
        b_mm = ui_inputs.try_parse_float(self.b_tb.Text)
        h_mm = ui_inputs.try_parse_float(self.h_tb.Text)
        stirrup_dia_mm = self._diameter_mm(self.selection.stirrup_bar_type)
        if b_mm is None or h_mm is None or stirrup_dia_mm is None:
            return None
        return {
            "b_mm": b_mm, "h_mm": h_mm,
            "cover_top_mm": self.beam_covers_mm.top_mm,
            "cover_btm_mm": self.beam_covers_mm.bottom_mm,
            "cover_side_mm": self.beam_covers_mm.side_mm,
            "stirrup_dia_mm": stirrup_dia_mm,
        }

    def _sketch_face_data(self, is_top, common):
        """One face's (bar_dia_mm, layers, spacing_results), or
        (None, [], None) when the face is not usably detailed yet.

        ``layers`` is a list of ``rft.core.plan.LayerPlan`` --
        ``core_plan.face_layer_plans``, the SAME function
        ``_build_placement_plans`` and ``rft.ui.report`` call, so the
        sketch cannot draw a bar position that disagrees with either.
        """
        bar_type = (
            self.selection.top_main_bar_type if is_top
            else self.selection.bottom_main_bar_type
        )
        bar_dia_mm = self._diameter_mm(bar_type)
        count = self._try_parse_optional_int(
            (self.top_bar_count_tb if is_top else self.bottom_bar_count_tb).Text,
            "bar count per layer",
        )
        layer_count = self._try_parse_optional_int(
            (self.top_layers_tb if is_top else self.bottom_layers_tb).Text,
            "layer count",
        )
        if bar_dia_mm is None or count is None or layer_count is None or count < 2:
            return None, [], None
        try:
            spacer_dia_mm = ui_inputs.parse_positive_float(self.spacer_dia_tb.Text, "O_spacer")
        except ValueError:
            return None, [], None
        cover_face_mm = common["cover_top_mm"] if is_top else common["cover_btm_mm"]
        try:
            layers = core_plan.face_layer_plans(
                is_top, common["h_mm"], common["b_mm"], cover_face_mm,
                common["cover_side_mm"], common["stirrup_dia_mm"], bar_dia_mm,
                spacer_dia_mm, count, layer_count,
            )
        except ValueError:
            return None, [], None
        d_agg_mm = ui_inputs.try_parse_float(self.d_agg_tb.Text)
        override_mm = ui_inputs.try_parse_float(self.min_spacing_override_tb.Text)
        governing_min_mm = governing_min_spacing_mm(bar_dia_mm, d_agg_mm, override_mm)
        spacing_results = [
            validate_layer_spacing(
                layer.layer_n, count, common["b_mm"], common["cover_side_mm"],
                common["stirrup_dia_mm"], bar_dia_mm, governing_min_mm,
            )
            for layer in layers
        ]
        return bar_dia_mm, layers, spacing_results

    def _sketch_crack_plan(self, common):
        """An ``rft.core.plan.CrackPlan``, or ``None`` when crack bars are
        not triggered/detailed yet (A50) -- same trigger and same
        innermost-layer-offset function ``_build_placement_plans`` uses.
        """
        if not crack_reinforcement_triggered(common["h_mm"]):
            return None
        top_dia_mm = self._diameter_mm(self.selection.top_main_bar_type)
        btm_dia_mm = self._diameter_mm(self.selection.bottom_main_bar_type)
        crack_dia_mm = self._diameter_mm(self.selection.crack_bar_type)
        layers_top = self._try_parse_optional_int(self.top_layers_tb.Text, "top layers")
        layers_btm = self._try_parse_optional_int(self.bottom_layers_tb.Text, "bottom layers")
        if None in (top_dia_mm, btm_dia_mm, crack_dia_mm, layers_top, layers_btm):
            return None
        try:
            spacer_dia_mm = ui_inputs.parse_positive_float(self.spacer_dia_tb.Text, "O_spacer")
            s_max_mm = ui_inputs.parse_positive_float(self.crack_s_max_tb.Text, "s_max")
        except ValueError:
            return None
        offset_top_mm = core_plan.innermost_layer_offset_mm(
            common["cover_top_mm"], common["stirrup_dia_mm"], top_dia_mm,
            spacer_dia_mm, layers_top,
        )
        offset_btm_mm = core_plan.innermost_layer_offset_mm(
            common["cover_btm_mm"], common["stirrup_dia_mm"], btm_dia_mm,
            spacer_dia_mm, layers_btm,
        )
        try:
            return core_plan.crack_plan(
                common["h_mm"], common["b_mm"], common["cover_side_mm"],
                common["stirrup_dia_mm"], crack_dia_mm,
                offset_top_mm, offset_btm_mm, s_max_mm,
            )
        except ValueError:
            return None

    def _redraw_section_canvas(self, canvas, want_crack):
        common = self._sketch_common_inputs()
        if common is None:
            self._clear_canvas(canvas)
            return
        top_dia_mm, top_layers, top_spacing = self._sketch_face_data(True, common)
        bottom_dia_mm, bottom_layers, bottom_spacing = self._sketch_face_data(False, common)
        spacer_len_mm = None
        if (len(top_layers) >= 2) or (len(bottom_layers) >= 2):
            spacer_len_mm = spacer_length_mm(
                common["b_mm"], common["cover_side_mm"], common["stirrup_dia_mm"]
            )
        crack_plan_obj = self._sketch_crack_plan(common) if want_crack else None
        crack_dia_mm = (
            self._diameter_mm(self.selection.crack_bar_type)
            if crack_plan_obj is not None else None
        )
        shapes = ui_sketch.section_shapes(
            common["b_mm"], common["h_mm"],
            common["cover_top_mm"], common["cover_btm_mm"], common["cover_side_mm"],
            common["cover_top_mm"], common["stirrup_dia_mm"],
            top_bar_dia_mm=top_dia_mm, top_layers=top_layers or None,
            top_spacing=top_spacing,
            bottom_bar_dia_mm=bottom_dia_mm, bottom_layers=bottom_layers or None,
            bottom_spacing=bottom_spacing,
            spacer_length_mm=spacer_len_mm,
            crack_dia_mm=crack_dia_mm, crack_plan=crack_plan_obj,
        )
        self._draw_shapes(canvas, shapes)

    def _sketch_end_plans(self, is_top, dia_own_mm, dia_other_mm, ld_text, ld_label,
                          detection, support_width_start_mm, support_width_end_mm):
        if dia_own_mm is None:
            return None, None
        try:
            ld_mult = ui_inputs.parse_positive_float(ld_text, ld_label)
        except ValueError:
            return None, None
        ld_mm = development_length(dia_own_mm, ld_mult)
        try:
            start = core_plan.end_plan(
                detection["is_supported_start"], is_top, support_width_start_mm,
                detection["support_cover_start_mm"], dia_own_mm, dia_other_mm,
                ld_mm, None, "start",
            )
            end = core_plan.end_plan(
                detection["is_supported_end"], is_top, support_width_end_mm,
                detection["support_cover_end_mm"], dia_own_mm, dia_other_mm,
                ld_mm, None, "end",
            )
        except Exception:
            return None, None
        return start, end

    def _redraw_elevation_canvas(self, canvas):
        common = self._sketch_common_inputs()
        # DELIBERATELY reads the CACHED detection only -- never
        # ``self._detect_supports()``, which calls the Revit API on its
        # first miss and would raise InvalidOperationException from this
        # UI-thread handler (#57). The cache is populated inside
        # ``_pick_beam_in_context``, which already runs in an API context.
        detection = self._support_detection
        if common is None or not detection or "error" in detection:
            self._clear_canvas(canvas)
            return
        l_mm = detection["l_mm"]
        support_width_start_mm = detection["support_width_start_mm"]
        support_width_end_mm = detection["support_width_end_mm"]
        if l_mm is None or support_width_start_mm is None or support_width_end_mm is None:
            self._clear_canvas(canvas)
            return

        stirrup_plan_obj = None
        try:
            closure_type = ui_inputs.closure_type_from_label(
                self.closure_type_combo.SelectedItem
            )
            dense_mm = ui_inputs.parse_positive_float(self.dense_spacing_tb.Text, "Dense spacing")
            normal_mm = ui_inputs.parse_positive_float(self.normal_spacing_tb.Text, "Normal spacing")
            if closure_type is not None:
                stirrup_plan_obj = core_plan.stirrup_plan(
                    l_mm, common["b_mm"], common["h_mm"], common["cover_top_mm"],
                    common["stirrup_dia_mm"], closure_type, dense_mm, normal_mm,
                    support_width_start_mm / 2.0, support_width_end_mm / 2.0,
                )
        except (ValueError, TypeError):
            stirrup_plan_obj = None

        top_dia_mm = self._diameter_mm(self.selection.top_main_bar_type)
        btm_dia_mm = self._diameter_mm(self.selection.bottom_main_bar_type)
        top_end_start, top_end_end = self._sketch_end_plans(
            True, top_dia_mm, btm_dia_mm, self.ld_top_mult_tb.Text,
            "LD_top multiplier", detection, support_width_start_mm, support_width_end_mm,
        )
        bottom_end_start, bottom_end_end = self._sketch_end_plans(
            False, btm_dia_mm, top_dia_mm, self.ld_btm_mult_tb.Text,
            "LD_btm multiplier", detection, support_width_start_mm, support_width_end_mm,
        )

        clearance_start = clearance_end = None
        for pair, attr in (
            ((top_end_start, bottom_end_start), "clearance_start"),
            ((top_end_end, bottom_end_end), "clearance_end"),
        ):
            top_end, bottom_end = pair
            if (top_end is not None and bottom_end is not None
                    and top_end.a_mm is not None and bottom_end.a_mm is not None):
                clearance = placed_clearance_mm(
                    bottom_end.a_mm, top_end.a_mm, top_dia_mm, btm_dia_mm
                )
                if attr == "clearance_start":
                    clearance_start = clearance
                else:
                    clearance_end = clearance

        crack_plan_obj = self._sketch_crack_plan(common)

        shapes = ui_sketch.elevation_shapes(
            l_mm, support_width_start_mm, support_width_end_mm, common["h_mm"],
            top_end_start=top_end_start, top_end_end=top_end_end,
            bottom_end_start=bottom_end_start, bottom_end_end=bottom_end_end,
            stirrup_plan=stirrup_plan_obj,
            clearance_start=clearance_start, clearance_end=clearance_end,
            crack_plan=crack_plan_obj,
        )
        self._draw_shapes(canvas, shapes)

    def _draw_shapes(self, canvas, shapes):
        """The ONE place mm becomes pixels (the coordinate transform A48
        allows the renderer to own) and shapes become WPF children. No
        detailing arithmetic: every u/v/r/text here is read verbatim off
        an ``rft.ui.sketch`` shape, never derived.

        ``translate(cx, cy) scale(s, -s)`` (this ticket's coordinate
        convention): origin at the section centroid, v positive UP.
        """
        canvas.Children.Clear()
        if not shapes:
            return
        us, vs = [], []
        for shape in shapes:
            if isinstance(shape, ui_sketch.SketchLine):
                us += [shape.u1, shape.u2]
                vs += [shape.v1, shape.v2]
            elif isinstance(shape, ui_sketch.SketchCircle):
                us += [shape.u - shape.r, shape.u + shape.r]
                vs += [shape.v - shape.r, shape.v + shape.r]
            elif isinstance(shape, ui_sketch.SketchText):
                us.append(shape.u)
                vs.append(shape.v)
            elif isinstance(shape, ui_sketch.SketchPolygon):
                for u, v in shape.points:
                    us.append(u)
                    vs.append(v)
        if not us or not vs:
            return

        margin_mm = 30.0
        min_u, max_u = min(us) - margin_mm, max(us) + margin_mm
        min_v, max_v = min(vs) - margin_mm, max(vs) + margin_mm

        width_px = canvas.ActualWidth if canvas.ActualWidth > 0 else 400.0
        height_px = canvas.ActualHeight if canvas.ActualHeight > 0 else 240.0
        span_u = max(max_u - min_u, 1.0)
        span_v = max(max_v - min_v, 1.0)
        scale = min(width_px / span_u, height_px / span_v)
        cx = width_px / 2.0 - (min_u + max_u) / 2.0 * scale
        cy = height_px / 2.0 + (min_v + max_v) / 2.0 * scale

        def to_px(u_mm, v_mm):
            return cx + u_mm * scale, cy - v_mm * scale

        text_shapes = []
        for shape in shapes:
            brush = self.FindResource(brush_key_for_style(shape.style))
            if isinstance(shape, ui_sketch.SketchLine):
                x1, y1 = to_px(shape.u1, shape.v1)
                x2, y2 = to_px(shape.u2, shape.v2)
                line = WpfLine()
                line.X1, line.Y1, line.X2, line.Y2 = x1, y1, x2, y2
                line.Stroke = brush
                line.StrokeThickness = 1.4
                canvas.Children.Add(line)
            elif isinstance(shape, ui_sketch.SketchCircle):
                x, y = to_px(shape.u, shape.v)
                # #62: a MINIMUM drawn radius. A 16 mm bar on a 900 mm
                # deep section fitted to this canvas is about 2 px across
                # -- correct to scale, and invisible. The bar's POSITION
                # stays exact (it is the plan's own u/v, untouched); only
                # the symbol drawn at that position gets a floor, exactly
                # as docs/ui/sketch-notation.svg draws bars as symbols
                # rather than to-scale circles.
                r_px = max(shape.r * scale, MIN_BAR_RADIUS_PX)
                ellipse = WpfEllipse()
                ellipse.Width = 2.0 * r_px
                ellipse.Height = 2.0 * r_px
                WpfCanvas.SetLeft(ellipse, x - r_px)
                WpfCanvas.SetTop(ellipse, y - r_px)
                ellipse.Fill = brush
                canvas.Children.Add(ellipse)
            elif isinstance(shape, ui_sketch.SketchPolygon):
                points = PointCollection()
                for u_mm, v_mm in shape.points:
                    x, y = to_px(u_mm, v_mm)
                    points.Add(Point(x, y))
                polygon = WpfPolygon()
                polygon.Points = points
                polygon.Stroke = brush
                polygon.StrokeThickness = 1.2
                canvas.Children.Add(polygon)
            elif isinstance(shape, ui_sketch.SketchText):
                # Collected, not drawn: every label's final position is
                # decided together, below, so none is clipped by the
                # canvas edge and none lands on another (#62).
                text_shapes.append(shape)

        # #62: labels last, and placed as a set.
        #
        # Drawn straight from the transform, a label anchored near a
        # support had its tail cut off by the canvas edge ("A7 clearanc"),
        # and two layers 0.1 mm apart drew their achieved spacing on top
        # of one another. Both are presentation, and both are fiddly
        # enough to need tests -- so the decision lives in
        # rft.ui.sketch_layout, which is importable, and this loop only
        # applies the answer.
        #
        # Order is priority: sketch.py emits its dimension labels before
        # its captions, so a dimension keeps the position it asked for and
        # a caption moves out of the way.
        boxes = []
        for shape in text_shapes:
            x, y = to_px(shape.u, shape.v)
            text_width_px, text_height_px = estimate_text_size_px(
                shape.text, SKETCH_FONT_SIZE_PX)
            # Centred on its anchor horizontally, which is how the
            # notation drawing dimensions a span, and lifted so the
            # anchor is the label's baseline rather than its top edge.
            boxes.append(LabelBox(
                x - text_width_px / 2.0, y - text_height_px,
                text_width_px, text_height_px,
            ))
        for shape, box in zip(text_shapes, place_labels(boxes, width_px, height_px)):
            text_block = WpfTextBlock()
            text_block.Text = shape.text
            text_block.FontSize = SKETCH_FONT_SIZE_PX
            text_block.Foreground = self.FindResource(
                brush_key_for_style(shape.style))
            WpfCanvas.SetLeft(text_block, box.x)
            WpfCanvas.SetTop(text_block, box.y)
            canvas.Children.Add(text_block)

    def on_build_report_click(self, sender, args):
        """WPF click handler. Does no Revit work itself (#57) -- the full
        report reads bar type names/diameters and re-detects supports,
        which are genuine Revit API calls, so building it is dispatched.
        """
        self._dispatch_to_revit_context(
            self._build_review_report_in_context, "Build report"
        )

    def _set_review_report(self, lines):
        """Writes the report to the Review tab AND to the pyRevit output
        window (A37: Review is where it is read, the output window is
        where it is kept -- scrollable, copyable, and it survives closing
        the dialog).
        """
        self.review_report_tb.Text = "\n".join(lines)
        output.print_md("### Detail Beam -- Review report (rev 2 section 8.2, A37)")
        for line in lines:
            output.print_md(line)

    def _build_review_report_in_context(self):
        """The full section 8.2/A37 report: derivation status for every
        section, then per-layer offsets/positions, governing/achieved
        spacing, anchorage a/b/LD per end, stirrup zones and counts, the
        crack-bar plan, the grade required per role against the bar type
        USED (``role_grade_report_line``), and every warning raised --
        for whichever sections the derivation above actually requested.

        Runs inside Revit's API context (dispatched) because bar type
        names/diameters and support re-detection are read here. THAT is
        this method's whole remaining job: read the model, then hand plain
        values to ``rft.ui.report``, which is pure and tested. The report
        text itself no longer lives in this file, where nothing could
        execute a line of it.
        """
        review = self._compute_review_derivation()
        lines = ui_report.derivation_lines(review)
        lines.append("")

        if self.beam is None:
            lines.append(
                "Pick a beam on the Beam & Materials tab to see the full "
                "section 8.2 report."
            )
            self._set_review_report(lines)
            return

        try:
            b_mm = _parse_positive_float(self.b_tb.Text, "b")
            h_mm = _parse_positive_float(self.h_tb.Text, "h")
        except ValueError as ex:
            lines.append("Geometry is not valid yet -- {}".format(ex))
            self._set_review_report(lines)
            return

        geometry = self._gather_report_geometry(b_mm, h_mm)
        if "error" in geometry:
            lines.append(geometry["error"])
            self._set_review_report(lines)
            return

        inputs = self._report_inputs()
        if review.top_main.requested or review.bottom_main.requested:
            lines += ui_report.main_bars_lines(inputs, review, geometry)
        if review.stirrups.requested:
            lines += ui_report.stirrups_lines(inputs, geometry)
        if review.crack_bars.requested:
            lines += ui_report.crack_bars_lines(inputs, geometry)

        self._set_review_report(lines)

    def _report_inputs(self):
        """Everything ``rft.ui.report`` needs that is not geometry, read
        off the model and the tabs ONCE and handed over as plain values.

        This is the whole Revit/WPF boundary of the report. Names and
        diameters are read here (both are API calls); the input fields are
        passed as RAW TEXT, because the report's job includes saying which
        input it could not use and why, in the parser's own words.
        """
        selection = self.selection

        def _name(bar_type):
            # ``None`` means unpicked, which is how every "is this role
            # selected" branch in the report reads. ``element_name`` on
            # None would raise instead.
            return element_name(bar_type) if bar_type is not None else None

        return ui_report.ReportInputs(
            top_bar_type_name=_name(selection.top_main_bar_type),
            btm_bar_type_name=_name(selection.bottom_main_bar_type),
            stirrup_bar_type_name=_name(selection.stirrup_bar_type),
            crack_bar_type_name=_name(selection.crack_bar_type),
            hook_type_name=_name(selection.stirrup_hook_type),
            hook_angle_deg=selection.stirrup_hook_angle_deg,
            top_dia_mm=self._diameter_mm(selection.top_main_bar_type),
            btm_dia_mm=self._diameter_mm(selection.bottom_main_bar_type),
            stirrup_dia_mm=self._diameter_mm(selection.stirrup_bar_type),
            crack_dia_mm=self._diameter_mm(selection.crack_bar_type),
            top_count_text=self.top_bar_count_tb.Text,
            btm_count_text=self.bottom_bar_count_tb.Text,
            top_layers_text=self.top_layers_tb.Text,
            btm_layers_text=self.bottom_layers_tb.Text,
            top_option_label=self.top_face_option_combo.SelectedItem,
            btm_option_label=self.bottom_face_option_combo.SelectedItem,
            spacer_dia_text=self.spacer_dia_tb.Text,
            d_agg_text=self.d_agg_tb.Text,
            min_spacing_override_text=self.min_spacing_override_tb.Text,
            ld_top_mult_text=self.ld_top_mult_tb.Text,
            ld_btm_mult_text=self.ld_btm_mult_tb.Text,
            dense_spacing_text=self.dense_spacing_tb.Text,
            normal_spacing_text=self.normal_spacing_tb.Text,
            closure_type_label=self.closure_type_combo.SelectedItem,
            crack_s_max_text=self.crack_s_max_tb.Text,
        )

    def _detect_supports(self):
        """Support detection for the picked beam: both ends' supporting
        element, width, cover and the span between them. Computed ONCE per
        pick and remembered.

        Every part of this is expensive and none of it depends on the
        inputs the engineer is editing. ``find_supporting_element`` is a
        document-wide filtered scan, run once per end, followed by a host
        validation and a cover read-back per support. It used to run again
        in full for every Review report and again for Place -- three or
        four identical scans per beam, and on a federated model that is
        the most expensive thing this tool does.

        Beam-scoped, and cleared by ``_reset_beam_state`` alongside
        ``self.beam`` itself, so a re-pick re-detects from scratch (A35's
        requirement that re-picking re-runs support detection).

        A failed read is cached too, deliberately: these failures are
        properties of the beam and its supports, not transient, so
        retrying on every keystroke would produce the same message at the
        cost of another scan. Re-picking clears it.
        """
        if self._support_detection is not None:
            return self._support_detection
        self._support_detection = self._detect_supports_uncached()
        return self._support_detection

    def _detect_supports_uncached(self):
        beam = self.beam
        try:
            start_pt, end_pt = beam_endpoints(beam)
            axis = beam_axis_direction(beam)
        except Exception as ex:
            return {"error": "Could not read beam geometry -- {}: {}".format(
                type(ex).__name__, ex)}

        support_start, support_width_start_mm = _end_support(doc, start_pt, axis, beam.Id)
        support_end, support_width_end_mm = _end_support(doc, end_pt, axis, beam.Id)
        is_supported_start = support_start is not None
        is_supported_end = support_end is not None

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
            return {"error": "Support cover read-back failed -- {}".format(ex)}

        return _support_detection(
            support_start, support_end, start_pt, end_pt, axis,
            support_width_start_mm, support_width_end_mm,
            support_cover_start_mm, support_cover_end_mm,
        )

    def _gather_report_geometry(self, b_mm, h_mm):
        """Beam/support geometry the report needs: the cached support
        detection above, plus the b/h the engineer may have edited and the
        beam's own covers (numbers already held on ``self``, not just the
        formatted TextBlock strings, which nothing can recompute from).

        Returns a dict with an ``"error"`` key on any failure, instead of
        raising, so one bad read degrades to a report line rather than
        losing the whole report.
        """
        detected = self._detect_supports()
        if "error" in detected:
            return detected

        geometry = dict(detected)
        geometry.update({
            "b_mm": b_mm, "h_mm": h_mm,
            "cover_top_mm": self.beam_covers_mm.top_mm,
            "cover_btm_mm": self.beam_covers_mm.bottom_mm,
            "cover_side_mm": self.beam_covers_mm.side_mm,
            "cover_end_start_mm": self.beam_covers_mm.end_start_mm,
            "cover_end_end_mm": self.beam_covers_mm.end_end_mm,
        })
        return geometry

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
        # The cached support detection is as beam-scoped as the beam:
        # keeping the previous beam's supports would report and place
        # against the wrong span, silently and plausibly, which is the
        # worst way for a cache to be wrong.
        self._support_detection = None
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
        # #49 (U5) -- a reset/refused pick must blank the sketches too, or
        # a stale drawing of the PREVIOUS beam would sit on screen with
        # nothing to indicate it belongs to a beam that is no longer
        # picked -- the same "beam-scoped state must not survive a
        # re-pick" rule this method exists to enforce for every other
        # field on this tab.
        self._redraw_sketches()

    # ------------------------------------------- Revit API context (#57)
    def _dispatch_to_revit_context(self, func, action_label):
        """Run ``func`` inside a real Revit API context.

        A MODELESS window's event handlers run OUTSIDE Revit's API
        context, where ``Selection.PickObject`` and ``Transaction`` both
        raise ``InvalidOperationException``. pyRevit's own modeless tool
        (``Measure.pushbutton``) solves this with
        ``revit.events.execute_in_revit_context``, which hands the call to
        an ``ExternalEvent`` and runs it when Revit is next idle. This is
        the precedent followed here rather than an inference.

        Two properties of that helper shape this method:

        1. It is ASYNCHRONOUS and returns nothing. Nothing can be handed
           back to the WPF click handler, so ``func`` must both do the
           work and update the window itself.
        2. Its handler SWALLOWS exceptions into pyRevit's log
           (``events.py``'s ``_GenericExternalEventHandler.Execute``). An
           error would reach the engineer as NOTHING HAPPENING AT ALL --
           the worst failure mode there is, and one this project has paid
           for repeatedly. So ``_run_in_revit_context`` below catches
           everything and puts it on screen.

        The single shared handler object is also why re-entry is refused:
        ``execute_in_revit_context`` overwrites one module-level
        ``_HANDLER.func``, so two dispatches in flight would clobber each
        other.
        """
        if self._api_call_in_flight:
            return
        self._api_call_in_flight = True
        self.status_tb.Text = "{} -- waiting for Revit...".format(action_label)
        revit.events.execute_in_revit_context(
            self._run_in_revit_context, func, action_label
        )

    def _run_in_revit_context(self, func, action_label):
        """The body actually executed by the ExternalEvent.

        Runs on Revit's UI thread -- the same thread that owns this window
        -- which is why it may touch the controls directly. If a live host
        ever proves otherwise, the symptom is an
        ``InvalidOperationException`` about the calling thread, and the
        fix is to wrap the UI writes in ``self.Dispatcher.Invoke``.
        """
        try:
            func()
            if self.status_tb.Text.endswith("waiting for Revit..."):
                self.status_tb.Text = "ready"
        except Exception as ex:
            # NEVER let this reach the ExternalEvent handler, which would
            # log it and show the engineer nothing at all.
            message = "{} failed -- {}: {}".format(
                action_label, type(ex).__name__, ex
            )
            self.status_tb.Text = message
            forms.alert(message, title="{} failed".format(action_label))
        finally:
            self._api_call_in_flight = False

    # ------------------------------------------------------------ picking
    def on_pick_click(self, sender, args):
        """WPF click handler. Does no Revit work itself (#57) -- it only
        asks for the pick to happen in an API context."""
        self._dispatch_to_revit_context(self._pick_beam_in_context, "Pick beam")

    def _pick_beam_in_context(self):
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
        # #49 (U5) -- the live sketch reads support/span data on the UI
        # thread, where a Revit API call would raise
        # InvalidOperationException (#57). This pick is already dispatched
        # and has just done the detection, so it fills the cache from what
        # it already computed and the redraw handler reads only plain
        # numbers.
        #
        # Built through the SAME constructor _detect_supports_uncached
        # returns, not a second dict literal. The review of #49 found one
        # here that listed all twelve keys again; it agreed exactly, which
        # is precisely how the duplicated ZONE_LAYOUT_FLAGS agreed right
        # up until it did not. One writer for one shape.
        self._support_detection = _support_detection(
            support_start, support_end, start_pt, end_pt, axis,
            support_width_start_mm, support_width_end_mm,
            support_cover_start_mm, support_cover_end_mm,
        )
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
        # #49 (U5) -- the fields above are what the sketch's own inputs
        # are read from; a successful pick is exactly the moment they
        # first exist.
        self._redraw_sketches()

    # ------------------------------------------------------------- place
    def _build_placement_plans(self, review, geometry):
        """Every number that is about to become steel, computed ONCE.

        The Review report formats these same plan objects (#50/#56), so
        the report cannot describe one beam while the model receives
        another. Returns (top_face, bottom_face, stirrups, crack), any of
        which is None when that section was not requested.
        """
        b_mm, h_mm = geometry["b_mm"], geometry["h_mm"]
        cover_side_mm = geometry["cover_side_mm"]
        stirrup_dia_mm = self._diameter_mm(self.selection.stirrup_bar_type)
        spacer_dia_mm = ui_inputs.parse_positive_float(
            self.spacer_dia_tb.Text, "O_spacer"
        )
        top_dia_mm = self._diameter_mm(self.selection.top_main_bar_type)
        btm_dia_mm = self._diameter_mm(self.selection.bottom_main_bar_type)

        # Parsed ONCE, here, rather than inside the per-face closure: the
        # crack plan needs the LAYER counts (and only those) for faces it
        # may not be placing, so they cannot be a detail private to a
        # face that is being placed.
        counts = {}
        layer_counts = {}
        for is_top in (True, False):
            label = "Top" if is_top else "Bottom"
            counts[is_top] = ui_inputs.parse_optional_positive_int(
                (self.top_bar_count_tb if is_top else self.bottom_bar_count_tb).Text,
                "{} bar count".format(label),
            )
            layer_counts[is_top] = ui_inputs.parse_optional_positive_int(
                (self.top_layers_tb if is_top else self.bottom_layers_tb).Text,
                "{} layer count".format(label), max_value=MAX_LAYERS,
            )

        def _face(is_top):
            # A51: the OPPOSITE face's diameter comes from its SELECTED
            # bar type whether or not that face is being placed. Passing
            # None here is what makes core_plan refuse the end by name
            # rather than invent a diameter (A42).
            dia_own = top_dia_mm if is_top else btm_dia_mm
            dia_other = btm_dia_mm if is_top else top_dia_mm
            return core_plan.face_plan(
                is_top, h_mm, b_mm,
                geometry["cover_top_mm"] if is_top else geometry["cover_btm_mm"],
                cover_side_mm,
                geometry["cover_end_start_mm"],
                stirrup_dia_mm, dia_own, dia_other, spacer_dia_mm,
                counts[is_top],
                layer_counts[is_top],
                ui_inputs.parse_positive_float(
                    (self.ld_top_mult_tb if is_top else self.ld_btm_mult_tb).Text,
                    "LD_{} multiplier".format("top" if is_top else "btm"),
                ),
                geometry["is_supported_start"], geometry["support_width_start_mm"],
                geometry["support_cover_start_mm"],
                geometry["is_supported_end"], geometry["support_width_end_mm"],
                geometry["support_cover_end_mm"],
            )

        top_face = _face(True) if review.top_main.requested else None
        bottom_face = _face(False) if review.bottom_main.requested else None

        stirrups = None
        if review.stirrups.requested:
            if geometry["l_mm"] is None:
                raise ValueError(
                    "Stirrups cannot be placed: rev 2 section 3.1's three "
                    "zones need a support-centre-to-support-centre span, "
                    "which needs BOTH ends supported. This beam has an "
                    "unsupported end."
                )
            stirrups = core_plan.stirrup_plan(
                geometry["l_mm"], b_mm, h_mm,
                geometry["cover_top_mm"], stirrup_dia_mm,
                ui_inputs.closure_type_from_label(
                    self.closure_type_combo.SelectedItem
                ),
                ui_inputs.parse_positive_float(
                    self.dense_spacing_tb.Text, "Dense spacing"
                ),
                ui_inputs.parse_positive_float(
                    self.normal_spacing_tb.Text, "Normal spacing"
                ),
                geometry["support_width_start_mm"] / 2.0,
                geometry["support_width_end_mm"] / 2.0,
            )

        crack = None
        if review.crack_bars.requested:
            # A26/A50: measured to the INNERMOST layer of each face.
            #
            # This asks core_plan for that ONE offset per face rather than
            # building a whole FacePlan and reading its last layer, which
            # is what it used to do -- twice over, for faces it had
            # already built above. That was not just duplicate work: a
            # FacePlan needs a per-layer BAR count, and A50 only requires
            # a face to be DETAILED (bar type + layer count). Detail both
            # faces, place only one, request crack bars, and the second
            # build raised a TypeError from inside the bar-position
            # arithmetic with the transaction already open. H_avail never
            # needed a bar count.
            if (top_dia_mm is None or btm_dia_mm is None
                    or layer_counts[True] is None or layer_counts[False] is None):
                raise ValueError(
                    "Crack bars cannot be placed: section 5.1's H_avail is "
                    "measured to the innermost main-bar layer of BOTH "
                    "faces, so each face needs a bar type AND a layer "
                    "count (A50). The Review tab names whichever is "
                    "still missing."
                )
            crack = core_plan.crack_plan(
                h_mm, b_mm, cover_side_mm, stirrup_dia_mm,
                self._diameter_mm(self.selection.crack_bar_type),
                core_plan.innermost_layer_offset_mm(
                    geometry["cover_top_mm"], stirrup_dia_mm, top_dia_mm,
                    spacer_dia_mm, layer_counts[True],
                ),
                core_plan.innermost_layer_offset_mm(
                    geometry["cover_btm_mm"], stirrup_dia_mm, btm_dia_mm,
                    spacer_dia_mm, layer_counts[False],
                ),
                ui_inputs.parse_positive_float(self.crack_s_max_tb.Text, "s_max"),
            )

        return top_face, bottom_face, stirrups, crack

    def _do_place(self):
        """Places every REQUESTED section, inside the one transaction that
        ``run_in_transaction`` has already opened (A46).

        All-or-nothing by construction: this raises rather than returning
        partial results, and the transaction rolls back, so a beam is
        never left half detailed. That includes A51's refusal -- a face
        whose anchorage cannot be computed stops the whole placement
        rather than being quietly skipped.

        Ported from the three pushbuttons that placed real reinforcement
        in a live session (v0.1.0). What changed is WHERE the numbers come
        from -- one plan, shared with the report -- not how any of them is
        computed.
        """
        review = self._compute_review_derivation()
        if not review.any_requested:
            raise ValueError(
                "Nothing is requested, so nothing was placed. Select a bar "
                "type and enter a bar count for a face, or select the "
                "stirrup hook, on the Beam & Materials and Main bars/"
                "Stirrups tabs."
            )

        geometry = self._gather_report_geometry(
            self.geometry_mm[1], self.geometry_mm[2]
        )
        if "error" in geometry:
            raise ValueError(geometry["error"])

        top_face, bottom_face, stirrups, crack = self._build_placement_plans(
            review, geometry
        )

        placed = []
        # Bottom before top, stirrups before crack bars: the order the
        # three verified buttons ran in when the engineer used them one
        # after another. Order does not affect geometry -- every bar's
        # position comes from the plan -- but keeping it makes the #55 A/B
        # comparison read the same way in the model tree.
        if bottom_face is not None:
            placed += self._place_main_face(
                geometry, bottom_face, self.selection.bottom_main_bar_type, False
            )
        if top_face is not None:
            placed += self._place_main_face(
                geometry, top_face, self.selection.top_main_bar_type, True
            )
        if stirrups is not None:
            placed += self._place_stirrups(geometry, stirrups)
        if crack is not None:
            placed += self._place_crack_bars(geometry, crack)

        return placed

    # ------------------------------------------------------- placement (#56)
    def _placement_reference_points(self, geometry):
        """Where each end's bars START: the support FACE when that end is
        supported, the beam's own physical end when it is not (section
        2.5). Ported from the verified pushbuttons, which both derive it
        this way.
        """
        if geometry["is_supported_start"]:
            ref_start = start_support_face_point(
                geometry["support_start"], geometry["start_pt"], geometry["axis"],
                mm_to_internal(geometry["support_width_start_mm"]),
            )
        else:
            ref_start = geometry["start_pt"]
        if geometry["is_supported_end"]:
            ref_end = end_support_face_point(
                geometry["support_end"], geometry["start_pt"], geometry["axis"],
                mm_to_internal(geometry["support_width_end_mm"]),
            )
        else:
            ref_end = geometry["end_pt"]
        return ref_start, ref_end

    def _place_main_face(self, geometry, face, bar_type, is_top):
        """One face's main bars, from a ``core_plan.FacePlan``.

        The plan holds every dimension; this method only turns numbers
        into points and calls the same helpers the verified "Place Main
        Bars" calls. Nothing is computed here -- if a number is missing it
        is added to the plan, never derived at this call site (A48's rule,
        applied to the placer rather than the renderer).
        """
        for end in (face.start_end, face.end_end):
            if end.refused_reason:
                # Refusing INSIDE the transaction is deliberate: it rolls
                # back whatever earlier sections placed, so the beam is
                # never left half detailed (A46).
                raise ValueError(end.refused_reason)

        axis = geometry["axis"]
        u_dir, v_dir = beam_section_axes(self.beam)
        bend_direction = v_dir.Negate() if is_top else v_dir
        du_internal, dv_internal = beam_section_centre_offsets(
            self.beam, geometry["start_pt"]
        )
        ref_start, ref_end = self._placement_reference_points(geometry)

        cover_end_start_mm = geometry["cover_end_start_mm"]
        cover_end_end_mm = geometry["cover_end_end_mm"]
        # mm_to_internal(None) raises inside UnitUtils -- converted only
        # where it is actually consumed, which is the unsupported branch.
        a_start_internal = (
            mm_to_internal(face.start_end.a_mm) if geometry["is_supported_start"]
            else mm_to_internal(cover_end_start_mm)
        )
        a_end_internal = (
            mm_to_internal(face.end_end.a_mm) if geometry["is_supported_end"]
            else mm_to_internal(cover_end_end_mm)
        )
        b_start_internal = (
            mm_to_internal(face.start_end.b_mm)
            if face.start_end.b_mm is not None else None
        )
        b_end_internal = (
            mm_to_internal(face.end_end.b_mm)
            if face.end_end.b_mm is not None else None
        )

        placed = []
        for layer in face.layers:
            for u_mm in layer.u_positions_mm:
                bar_ref_start = bar_point_at_uv(
                    ref_start, u_dir, v_dir, du_internal, dv_internal,
                    u_mm, layer.v_mm, mm_to_internal,
                )
                bar_ref_end = bar_point_at_uv(
                    ref_end, u_dir, v_dir, du_internal, dv_internal,
                    u_mm, layer.v_mm, mm_to_internal,
                )
                corner_start, bend_start = main_bar_end_geometry(
                    geometry["is_supported_start"], bar_ref_start, axis, True,
                    a_start_internal, b_start_internal,
                )
                corner_end, bend_end = main_bar_end_geometry(
                    geometry["is_supported_end"], bar_ref_end, axis, False,
                    a_end_internal, b_end_internal,
                )
                curves = build_main_bar_curves(
                    corner_start, corner_end, bend_direction, bend_start, bend_end
                )
                placed.append(place_anchored_bar(
                    doc, self.beam, bar_type, curves,
                    bend_plane_normal(axis, bend_direction),
                ))
        return placed

    def _place_stirrups(self, geometry, stirrups):
        """The three zones, from a ``core_plan.StirrupPlan``.

        Carries forward the finding that cost issue #18 a review round:
        the core returns corners about the section CENTROID, but a station
        point sits on the beam's LOCATION CURVE. With Revit's default
        top-justified structural framing those differ by h/2, and skipping
        the offset builds the entire cage outside the beam. It is applied
        per station, exactly as the verified button applies it.
        """
        u_dir, v_dir = beam_section_axes(self.beam)
        norm = bend_plane_normal(u_dir, v_dir)
        du_internal, dv_internal = beam_section_centre_offsets(
            self.beam, geometry["start_pt"]
        )
        placed = []
        for zone in stirrups.zones:
            station_internal = point_at_cc_offset(
                geometry["start_pt"], geometry["axis"], geometry["support_start"],
                zone.zone.start, mm_to_internal,
            )
            origin_internal = (
                station_internal
                + u_dir.Multiply(du_internal)
                + v_dir.Multiply(dv_internal)
            )
            curves = build_stirrup_curves(
                origin_internal, u_dir, v_dir, stirrups.endpoints_mm, mm_to_internal
            )
            rebar = place_stirrup(
                doc, self.beam, self.selection.stirrup_bar_type,
                self.selection.stirrup_hook_type, curves, norm,
            )
            apply_maximum_spacing_layout(
                rebar,
                mm_to_internal(zone.max_spacing_mm),
                mm_to_internal(zone.array_length_mm),
                zone.include_first,
                zone.include_last,
            )
            placed.append(rebar)
        return placed

    def _place_crack_bars(self, geometry, crack):
        """Crack/skin bars, from a ``core_plan.CrackPlan``.

        A23: no hook at either end, so ``b`` is always None and
        ``build_main_bar_curves`` emits a single straight segment. A
        supported end embeds; an unsupported one stops at beam-end minus
        cover.
        """
        axis = geometry["axis"]
        u_dir, v_dir = beam_section_axes(self.beam)
        du_internal, dv_internal = beam_section_centre_offsets(
            self.beam, geometry["start_pt"]
        )
        ref_start, ref_end = self._placement_reference_points(geometry)
        norm = bend_plane_normal(axis, v_dir)

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
        a_start_internal = mm_to_internal(
            result_start.embedment_mm if geometry["is_supported_start"]
            else geometry["cover_end_start_mm"]
        )
        a_end_internal = mm_to_internal(
            result_end.embedment_mm if geometry["is_supported_end"]
            else geometry["cover_end_end_mm"]
        )

        placed = []
        for v_mm in crack.v_positions_mm:
            for u_mm in crack.u_positions_mm:
                bar_ref_start = bar_point_at_uv(
                    ref_start, u_dir, v_dir, du_internal, dv_internal,
                    u_mm, v_mm, mm_to_internal,
                )
                bar_ref_end = bar_point_at_uv(
                    ref_end, u_dir, v_dir, du_internal, dv_internal,
                    u_mm, v_mm, mm_to_internal,
                )
                corner_start, bend_start = main_bar_end_geometry(
                    geometry["is_supported_start"], bar_ref_start, axis, True,
                    a_start_internal, None,
                )
                corner_end, bend_end = main_bar_end_geometry(
                    geometry["is_supported_end"], bar_ref_end, axis, False,
                    a_end_internal, None,
                )
                curves = build_main_bar_curves(
                    corner_start, corner_end, v_dir, bend_start, bend_end
                )
                placed.append(place_anchored_bar(
                    doc, self.beam, self.selection.crack_bar_type, curves, norm
                ))
        return placed

    def _missing_bar_type_and_hook_messages(self, review):
        """The A42 no-fallback check, scoped to what is actually REQUESTED.

        Read from the ONE attribute per role ``self.selection`` owns --
        never a second lookup into the document. Returns the
        ``GuardMessage``s for selections that the requested reinforcement
        genuinely needs and that are still unpicked, naming each one.

        Scoped deliberately: Place's enabled state follows #50's
        derivation, so a guard that demanded selections for sections
        nobody requested would enable the button and then refuse it --
        which is what shipped for exactly one review cycle.
        """
        missing = []
        if not review.any_requested:
            return missing

        # Needed by every section: main-bar layer offsets (4.1) and
        # crack-bar positions both take the stirrup's diameter.
        if self.selection.stirrup_bar_type is None:
            missing.append(missing_bar_type_selection_message(ROLE_STIRRUP))

        # Needed only by stirrups (A45). Main and crack bars use no
        # RebarHookType at all.
        if review.stirrups.requested and self.selection.stirrup_hook_type is None:
            missing.append(missing_hook_type_selection_message())

        return missing

    def on_place_click(self, sender, args):
        """WPF click handler. Input validation is pure Python and stays
        here; everything that touches Revit is dispatched (#57)."""
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
        missing = self._missing_bar_type_and_hook_messages(
            self._compute_review_derivation()
        )
        if missing:
            forms.alert(
                "\n\n".join(m.message for m in missing),
                title="Bar type / hook selection required",
            )
            return

        # A Transaction started from a modeless window's handler fails
        # exactly the way the pick did, so it goes through the same
        # dispatch (#57). #56's placement port inherits this.
        self._dispatch_to_revit_context(self._place_in_context, "Place")

    def _place_in_context(self):
        try:
            placed = run_in_transaction(doc, "RFT Detail Beam", self._do_place)
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
        # #56: reachable for the first time. It reports the COUNT rather
        # than the word "successfully" alone -- a number the engineer can
        # check against the Review report's own totals, and against what
        # the three verified buttons produce for the same beam, which is
        # the A/B comparison #55 turns on.
        count = len(placed) if placed is not None else 0
        message = "Placed {} rebar element{}.".format(
            count, "" if count == 1 else "s"
        )
        self.place_result_tb.Text = message
        self.status_tb.Text = message


# The window must outlive main(). A modeless window whose only reference is
# a local goes out of scope the moment the script returns; the same
# module-level-handle pattern is what pyRevit's own modeless Measure tool
# uses.
window = None


def main():
    global window
    window = SimpleBeamWindow()
    # MODELESS (issue #57). ShowDialog() disables every other top-level
    # window in the process -- Revit's main window included -- so
    # Selection.PickObject could never receive a click in the viewport and
    # "Pick beam..." did nothing until the window was closed outright.
    # forms.WPFWindow.show() defaults to modal=False and calls Show().
    window.show()


if __name__ == "__main__":
    main()
