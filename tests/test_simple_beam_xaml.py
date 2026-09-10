# -*- coding: utf-8 -*-
"""#47 (U3) -- guards against an ``x:Name`` typo between
``SimpleBeamWindow.xaml`` and ``script.py``, which pyRevit's ``WPFWindow``
would surface only as an ``AttributeError`` on a live host (``script.py``
itself cannot be imported here -- it imports ``pyrevit``, which is not
installed under plain CPython; see ``tests/fake_revit_api.py``'s header).

This does not execute the window. It parses both files as TEXT/XML and
cross-checks names, which is the one thing that CAN be checked without a
Revit host and would have caught the exact defect this ticket's brief
warns about.
"""

import io
import os
import re
import xml.etree.ElementTree as ET

PUSHBUTTON_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "SimpleBeamRFT.extension",
    "RFT-Tools.tab",
    "Beams.panel",
    "Simple Beam.pushbutton",
)
XAML_PATH = os.path.join(PUSHBUTTON_DIR, "SimpleBeamWindow.xaml")
SCRIPT_PATH = os.path.join(PUSHBUTTON_DIR, "script.py")

X_NAME = "{http://schemas.microsoft.com/winfx/2006/xaml}Name"

# Attribute names script.py reads/writes as ``self.<name>`` that are
# NOT ``x:Name`` WPF elements -- ordinary Python state, or attributes of
# ``self.selection``/other non-window objects that the same "self."
# regex cannot distinguish from the window's own attributes.
NON_XAML_SELF_ATTRS = {
    "beam", "host_data", "geometry_mm", "selection",
    "_bar_type_options_by_role", "_hook_type_options",
    # BeamMaterialsSelection's own attributes (a DIFFERENT "self" -- its
    # __init__, not SimpleBeamWindow's).
    "top_main_bar_type", "bottom_main_bar_type", "stirrup_bar_type",
    "crack_bar_type", "stirrup_hook_type", "stirrup_hook_angle_deg",
    # #48 (U4) -- ordinary Python state, not an x:Name control.
    "beam_covers_mm",
    # The two caches. ``_diameter_cache_mm`` is DOCUMENT-scoped (a bar
    # type's diameter has nothing to do with the picked beam) and so is
    # deliberately absent from BEAM_SCOPED_ATTRS below;
    # ``_support_detection`` is beam-scoped and appears in both lists.
    "_diameter_cache_mm", "_support_detection",
    # #57 -- the dispatch guard, plus one INHERITED WPF member:
    # Window.Dispatcher is a real attribute of the base class, not an
    # x:Name control, so it belongs here for the same reason ordinary
    # Python state does. It is currently named only inside a docstring --
    # this check reads source text, not live attributes, which is the
    # trade for being able to run it at all without a Revit host.
    "_api_call_in_flight", "Dispatcher",
    # INHERITED WPFWindow members. ``_script_method_names()`` only finds
    # methods DEFINED in this file, so anything the base class provides
    # has to be named here: Dispatcher above is a property, set_icon is a
    # method (pyRevit's own helper for the title-bar icon). Both are real
    # attributes and neither is an x:Name control.
    "set_icon",
    # #49 (U5) -- FrameworkElement.FindResource, a real inherited WPF/.NET
    # method (SimpleBeamWindow -> forms.WPFWindow -> Window ->
    # FrameworkElement) used by the sketch renderer to look up a brush by
    # its x:Key name. Not an x:Name control itself.
    "FindResource",
    # #54 (U10) -- Window.Closing, the inherited WPF event the window
    # subscribes to so this project's inputs are remembered on the way
    # out. An event on the base class, not an x:Name control.
    "Closing",
}

# This exclusion list is a maintenance cost, and deliberately so: a new
# plain attribute on either class fails this test until it is listed here.
# It failed exactly that way when the review added
# ``stirrup_hook_angle_deg``, which is the right direction to be wrong in
# -- a list that defaulted to "assume it is ordinary state" would have let
# a genuinely mistyped control name through in silence.


def _script_method_names():
    text = io.open(SCRIPT_PATH, encoding="utf-8").read()
    return set(re.findall(r"def\s+(\w+)\(self", text))

# x:Name elements that exist for a later ticket (#50/#56) and are not yet
# referenced by this ticket's script.py -- named here explicitly so the
# reverse check stays meaningful instead of being disabled outright.
# "Review" is entirely #50's (U6) scope, so it is not walked at all below
# (see ``OWNED_TAB_HEADER_SUBSTRINGS``).
#
# #48 (U4) is INPUT COLLECTION ONLY -- it does not validate, derive or
# place anything, so several Main bars/Stirrups fields are genuinely
# write-only from this ticket's script.py: the engineer types into them,
# and #50 (Review's derivation/report) or #56 (the placement port) is what
# reads them back. Listing them here says so explicitly, rather than
# wiring a placeholder read that would do nothing.
NOT_YET_REFERENCED = {
    # Trimmed by #60: every field #48 added is now read by #50's
    # derivation/report or #56's placer, so the only genuinely
    # unreferenced control left is the TabControl itself. A stale
    # exclusion is a hole in this check, not a harmless leftover --
    # two entries here named controls that had been RENAMED away, so
    # the reverse check was excusing names that no longer existed.
    # (top/bottom_face_option_tb were also listed here and named
    # controls RENAMED to *_combo in rc3 -- they existed in neither
    # file any more, which is precisely the kind of dead exclusion
    # that quietly widens the hole this check is meant to close.)
    "tabs",
}

# The tab headers owned by #47 (U3), #48 (U4) and #50 (U6) -- matched by
# substring since ElementTree has no attribute-value XPath matching.
# "Review" is INCLUDED as of #50 (U6): it is no longer a placeholder, so a
# control added there and never referenced by script.py is exactly the
# dead-XAML/typo risk this reverse check exists to catch on every other
# owned tab.
OWNED_TAB_HEADER_SUBSTRINGS = ("Beam", "Main bars", "Stirrups", "Crack bars", "Review")


def _xaml_names():
    tree = ET.parse(XAML_PATH)
    return {el.get(X_NAME) for el in tree.iter() if el.get(X_NAME) is not None}


def _beam_materials_tab_names():
    """x:Name elements inside the "Beam & Materials" TabItem only -- the
    tab #47 (U3) owns. Found by locating the TabItem whose Header contains
    "Beam" (ElementTree does not expose attribute-value XPath matching by
    substring), then walking its subtree.
    """
    tree = ET.parse(XAML_PATH)
    ns = "{http://schemas.microsoft.com/winfx/2006/xaml/presentation}"
    for tab_item in tree.iter(ns + "TabItem"):
        header = tab_item.get("Header") or ""
        if "Beam" in header:
            return {el.get(X_NAME) for el in tab_item.iter() if el.get(X_NAME) is not None}
    raise AssertionError("no TabItem with 'Beam' in its Header was found")


def _owned_tabs_names():
    """x:Name elements inside every TabItem #47/#48/#50 own -- Beam &
    Materials, Main bars, Stirrups, Crack bars and Review (issue #48, U4
    extended the reverse check's scope from just Beam & Materials to the
    first three of those; issue #50, U6 extends it again to Review, which
    is no longer a placeholder).
    """
    tree = ET.parse(XAML_PATH)
    ns = "{http://schemas.microsoft.com/winfx/2006/xaml/presentation}"
    names = set()
    matched_headers = []
    for tab_item in tree.iter(ns + "TabItem"):
        header = tab_item.get("Header") or ""
        if any(substring in header for substring in OWNED_TAB_HEADER_SUBSTRINGS):
            matched_headers.append(header)
            names |= {el.get(X_NAME) for el in tab_item.iter() if el.get(X_NAME) is not None}
    assert len(matched_headers) == len(OWNED_TAB_HEADER_SUBSTRINGS), (
        "expected one TabItem per owned header substring %r, matched %r"
        % (OWNED_TAB_HEADER_SUBSTRINGS, matched_headers)
    )
    return names


def _script_self_attr_references():
    text = io.open(SCRIPT_PATH, encoding="utf-8").read()
    return set(re.findall(r"self\.([A-Za-z_][A-Za-z0-9_]*)", text))


def _script_quoted_identifiers():
    """Some controls (the four bar-type role rows) are reached via
    ``getattr(self, combo_name)`` with ``combo_name`` a STRING LITERAL in
    ``BAR_TYPE_ROLE_ROWS``, not a literal ``self.<name>`` -- those names
    would otherwise be invisible to a check based on ``self.`` text alone.
    """
    text = io.open(SCRIPT_PATH, encoding="utf-8").read()
    return set(re.findall(r"[\"\']([A-Za-z_][A-Za-z0-9_]*)[\"\']", text))


def test_xaml_parses():
    ET.parse(XAML_PATH)  # raises ParseError on malformed XML


def test_every_self_attr_the_script_treats_as_a_xaml_control_exists():
    """Forward direction: every ``self.<name>`` the script references, other
    than ordinary Python state, must have a matching ``x:Name`` in the
    XAML -- otherwise it is an ``AttributeError`` waiting for a live host.
    """
    xaml_names = _xaml_names()
    excluded = NON_XAML_SELF_ATTRS | _script_method_names()
    referenced = _script_self_attr_references() - excluded
    missing = sorted(referenced - xaml_names)
    assert not missing, (
        "script.py references self.<name> for these names, which have no "
        "matching x:Name in SimpleBeamWindow.xaml (AttributeError on a "
        "live host): %s" % missing
    )


def test_every_beam_materials_control_is_referenced_by_the_script():
    """Reverse direction, scoped to the "Beam & Materials" tab -- the tab
    #47 (U3) owns. A named control this ticket added that the script
    never reads or writes would be dead XAML, and a typo on the SCRIPT
    side (referencing a name that is subtly different from the one in the
    tab) would otherwise hide behind the forward check finding no exact
    match to complain about only if the wrong name happened to collide
    with something else.
    """
    referenced = _script_self_attr_references() | _script_quoted_identifiers()
    beam_materials_names = _beam_materials_tab_names() - NOT_YET_REFERENCED
    unreferenced = sorted(beam_materials_names - referenced)
    assert not unreferenced, (
        "these x:Name elements on the Beam & Materials tab are never "
        "referenced by script.py: %s" % unreferenced
    )


def test_every_owned_tab_control_is_referenced_by_the_script():
    """Reverse direction, extended (issue #48, U4) from just "Beam &
    Materials" to all FOUR tabs this project owns so far: Beam &
    Materials, Main bars, Stirrups and Crack bars. "Review" stays out of
    scope -- it is a genuine #50 (U6) placeholder. A typo'd ``x:Name`` on
    any of these three new tabs is an ``AttributeError`` on a live host
    and nothing else in this suite would see it.
    """
    referenced = _script_self_attr_references() | _script_quoted_identifiers()
    owned_names = _owned_tabs_names() - NOT_YET_REFERENCED
    unreferenced = sorted(owned_names - referenced)
    assert not unreferenced, (
        "these x:Name elements on a tab #47/#48 own are never referenced "
        "by script.py: %s" % unreferenced
    )


def test_x_name_values_are_unique():
    tree = ET.parse(XAML_PATH)
    names = [el.get(X_NAME) for el in tree.iter() if el.get(X_NAME) is not None]
    duplicates = sorted(set(n for n in names if names.count(n) > 1))
    assert not duplicates, "duplicate x:Name values: %s" % duplicates


# --- beam-scoped state must be cleared on every pick ----------------------

# Attributes holding data about THE PICKED BEAM. Each must be cleared in
# _reset_beam_state, which runs on every pick and every refused pick --
# otherwise the previous beam's value survives into the next beam with
# nothing to indicate it. Document-scoped state (the bar-type selections)
# is deliberately NOT here: those outlive a re-pick on purpose.
BEAM_SCOPED_ATTRS = (
    "beam", "host_data", "beam_covers_mm", "geometry_mm",
    # The cached support detection: the previous beam's supports would
    # report and place against the wrong span, plausibly and silently.
    "_support_detection",
)


def _reset_beam_state_body():
    """The source of _reset_beam_state, up to the next method definition."""
    text = io.open(SCRIPT_PATH, encoding="utf-8").read()
    start = text.index("    def _reset_beam_state(self")
    end = text.index("\n    def ", start + 1)
    return text[start:end]


def test_every_beam_scoped_attribute_is_cleared_on_pick():
    """Regression guard, added after this exact defect shipped once.

    #47's review found that self.geometry_mm survived a re-pick and
    declared it fixed. The edit anchored on "self.beam = None /
    self.host_data = None" -- two lines that appear in BOTH __init__ and
    _reset_beam_state -- and matched __init__ first, so it added a
    duplicate assignment there and left _reset_beam_state untouched. The
    suite was green, the review comment said "fixed", and the defect was
    still present. Nothing in a green test run contradicted it, because
    nothing was looking.
    """
    body = _reset_beam_state_body()
    missing = [
        attr for attr in BEAM_SCOPED_ATTRS
        if "self.{} = None".format(attr) not in body
    ]
    assert not missing, (
        "these beam-scoped attributes are not cleared in "
        "_reset_beam_state, so the previous beam's value survives a "
        "re-pick: %s" % missing
    )


def test_beam_scoped_attributes_are_not_double_assigned_in_init():
    """The duplicate that the same botched edit left behind in __init__.

    Harmless in itself -- assigning None twice does nothing -- but it is
    the fingerprint of an edit that landed in the wrong method, so it is
    worth failing on rather than tidying away silently.
    """
    text = io.open(SCRIPT_PATH, encoding="utf-8").read()
    start = text.index("    def __init__(self):", text.index("class SimpleBeamWindow"))
    end = text.index("\n    # ", start)
    init_body = text[start:end]
    duplicated = [
        attr for attr in BEAM_SCOPED_ATTRS
        if init_body.count("self.{} = None".format(attr)) > 1
    ]
    assert not duplicated, (
        "assigned twice in __init__, which is what an edit misapplied to "
        "__init__ instead of _reset_beam_state looks like: %s" % duplicated
    )


# --- the window must stay modeless, and handlers must not touch Revit -----

# Revit API calls that fail with InvalidOperationException when made from
# a modeless window's own event handler, i.e. outside an API context.
# They are legal ONLY inside a function dispatched through
# revit.events.execute_in_revit_context.
API_CALLS_NEEDING_CONTEXT = ("revit.pick_element", "run_in_transaction")


REPORT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "RFT.lib", "rft", "ui", "report.py",
)


def _report_module_source():
    return io.open(REPORT_PATH, encoding="utf-8").read()


def _code_only(body):
    """A method's source with comments stripped.

    A guard that greps for a call is satisfied by a COMMENT mentioning
    that call -- which is not a hypothetical: the mutation written to
    prove the guard below replaced the real call with
    ``boxes  # place_labels(...)``, and the guard passed. The prover
    reported it MISSED, which is the only reason it was noticed.

    Crude on purpose: it does not parse strings, so a "#" inside a string
    literal would truncate that line. That is acceptable for the "is this
    call present in the code" question, and erring toward seeing LESS
    code makes the guards stricter, never laxer.
    """
    return "\n".join(
        line.split("#", 1)[0] for line in body.splitlines()
    )


def _method_body(name):
    text = io.open(SCRIPT_PATH, encoding="utf-8").read()
    start = text.index("    def {}(self".format(name))
    end = text.index("\n    def ", start + 1)
    return text[start:end]


def test_the_window_is_never_shown_modally():
    """ShowDialog() disables every other top-level window in the process,
    Revit's main window included, so Selection.PickObject can never
    receive a click in the viewport.

    This shipped in v0.2.0-rc1 and made "Pick beam..." do nothing at all
    until the window was closed outright -- the first live test of the
    single window found it immediately (#57). The suite was fully green
    at the time: nothing here modelled how the window is SHOWN.
    """
    text = io.open(SCRIPT_PATH, encoding="utf-8").read()
    # Matches the CALL (``x.ShowDialog(`` / ``show_dialog(``), not the
    # bare word -- the comment in script.py explaining why the modal call
    # is wrong necessarily contains the word itself, and a guard that
    # cannot coexist with its own explanation is a guard that gets
    # deleted.
    modal_calls = re.findall(r"\.ShowDialog\s*\(|\bshow_dialog\s*\(", text)
    assert not modal_calls, (
        "the Detail Beam window must be shown modeless (forms.WPFWindow."
        "show(), modal=False by default). ShowDialog() disables Revit's "
        "main window, so no pick can ever complete (#57)."
    )
    assert "window.show()" in text


def test_click_handlers_do_no_revit_work_directly():
    """The WPF click handlers run OUTSIDE Revit's API context. Anything
    touching the API has to go through execute_in_revit_context, so the
    handlers themselves must only dispatch.
    """
    for handler in ("on_pick_click", "on_place_click"):
        body = _method_body(handler)
        offenders = [call for call in API_CALLS_NEEDING_CONTEXT if call in body]
        assert not offenders, (
            "%s calls the Revit API directly. From a modeless window that "
            "raises InvalidOperationException -- dispatch it through "
            "_dispatch_to_revit_context instead (#57): %s"
            % (handler, offenders)
        )


def test_dispatched_work_cannot_fail_silently():
    """pyRevit's ExternalEvent handler swallows exceptions into its log
    (_GenericExternalEventHandler.Execute), so an error inside dispatched
    work would reach the engineer as nothing happening at all. The
    wrapper must catch and surface it.
    """
    body = _method_body("_run_in_revit_context")
    assert "except Exception" in body, (
        "_run_in_revit_context must catch everything: pyRevit's "
        "ExternalEvent handler logs and discards exceptions, which would "
        "make a real failure invisible (#57)."
    )
    assert "forms.alert" in body and "status_tb" in body, (
        "a caught failure must be shown in the window, not only stored."
    )


# --- a modeless window needs a persistent engine --------------------------

BUNDLE_PATH = os.path.join(PUSHBUTTON_DIR, "bundle.yaml")


def test_modeless_window_declares_a_persistent_engine():
    """#59. The window is modeless, so its handlers run AFTER script.py
    has returned. Without ``engine: persistent: true`` pyRevit tears the
    IronPython engine down at that moment: the window survives as a CLR
    object and a click handler can still write a TextBlock, but the
    ExternalEvent carrying every Revit API call is raised into a dead
    engine and never delivers.

    The live symptom was "Pick beam -- waiting for Revit..." forever, with
    no error anywhere, because the failure is UPSTREAM of the wrapper that
    reports failures. Nothing in the suite could see it: the setting lives
    in bundle.yaml, and until now no test read that file at all.

    Coupled deliberately to the modeless check: these two must change
    together or the button silently stops working.
    """
    import yaml

    bundle = yaml.safe_load(io.open(BUNDLE_PATH, encoding="utf-8").read())
    engine = bundle.get("engine") or {}
    assert engine.get("persistent") is True, (
        "bundle.yaml must declare engine.persistent: true -- the Detail "
        "Beam window is modeless and its Revit API calls are delivered by "
        "an ExternalEvent after the script returns (#59)."
    )


# --- Place must not be enabled and then refuse ----------------------------


def test_place_preflight_consults_the_same_derivation_that_enables_it():
    """#50 made Place's ENABLED state follow the Review derivation, while
    the pre-flight guard still demanded top main, bottom main and stirrup
    bar types unconditionally (#48's rule).

    The two disagreed in a way the engineer could see: request stirrups
    only, Review says "Stirrups: will be placed", Place lights up -- and
    then refuses, naming main bars nobody asked to place. A button that
    invites a click and then rejects it is worse than one that stays
    greyed out, because it makes the engineer doubt the tool rather than
    their input.

    The guard must therefore be scoped by the SAME derivation object that
    sets IsEnabled, so the two cannot drift apart again.
    """
    body = _method_body("_missing_bar_type_and_hook_messages")
    assert "review." in body, (
        "_missing_bar_type_and_hook_messages must be scoped by the Review "
        "derivation that enables the Place button, or the two can "
        "disagree and Place will refuse a click it invited."
    )
    assert "any_requested" in body, (
        "it must return nothing when nothing is requested -- that case is "
        "already handled by disabling the button."
    )


def test_the_unconditional_required_roles_list_is_gone():
    """The constant the contradiction was built on. Kept as a named test
    so re-adding it has to be a deliberate act with a reason.
    """
    text = io.open(SCRIPT_PATH, encoding="utf-8").read()
    assert "REQUIRED_BAR_TYPE_ROLES_FOR_PLACE = (" not in text, (
        "this list demanded a bar type per role regardless of what was "
        "requested. What each section actually consumes is narrower: the "
        "stirrup BAR type is needed by every section (layer offsets, "
        "crack-bar positions), the stirrup HOOK only by stirrups."
    )


# --- the report and the placer must share one computation ----------------


def test_report_and_placement_both_use_the_shared_plan():
    """#56. The Review report describes what Place will build. If the two
    compute their numbers separately -- even from the same correct core
    functions -- they can be handed different arguments and neither would
    notice, and the report would describe a beam the model did not get.

    Both must go through rft.core.plan, which is where those numbers are
    computed once and tested (tests/test_core_plan.py).
    """
    # Named calls, not merely the substring "core_plan.": these two methods
    # each make SEVERAL plan calls, so checking that the module is
    # mentioned somewhere would still pass with one of them ripped out and
    # recomputed by hand. Mutation testing is what exposed that -- the
    # first version of this assertion survived exactly that change.
    required = (
        # (source text, what to search, required core_plan calls)
        (_method_body("_build_placement_plans"), "_build_placement_plans", (
            "face_plan", "stirrup_plan", "crack_plan",
            # The crack plan's two H_avail offsets. Before this call
            # existed the placer built a WHOLE FacePlan per face just to
            # read its last layer -- a second time for faces it had
            # already built -- and a FacePlan needs a per-layer bar
            # count, which a face that is detailed but not placed does
            # not have.
            "innermost_layer_offset_mm",
        )),
        # The report moved to rft/ui/report.py, which -- unlike script.py
        # -- can be imported and executed by tests
        # (tests/test_ui_report.py). This text check stays anyway: those
        # tests pin the report's OUTPUT, and identical output is exactly
        # what a hand-rolled second computation produces right up until
        # the day it does not.
        (_report_module_source(), "rft/ui/report.py", (
            "face_layer_plans", "end_plan",
            # The stirrup and crack sections recomputed their zones,
            # counts, spacings and every bar position for three releases.
            # This check could not see it: the PLACER's calls to
            # stirrup_plan and crack_plan satisfied the requirement on
            # their own, because the requirement was written per-CALL and
            # not per-CONSUMER. It is now stated for both consumers, which
            # is what "the report formats the plan" actually means.
            "stirrup_plan", "crack_plan", "innermost_layer_offset_mm",
        )),
    )
    # The missing calls are collected into a small list and THAT is
    # asserted on, rather than asserting `call in body` directly.
    #
    # pytest rewrites an assert to show its operands, and `body` here is a
    # whole module -- 500 lines of it. The direct form printed the entire
    # source on failure, which filled the pipe of the mutation prover
    # running this test and deadlocked it, leaving a mutated file in the
    # working tree. An assertion message is a diagnostic; it should be the
    # size of the fact it reports.
    missing = [
        (where, call)
        for body, where, calls in required
        for call in calls
        if "core_plan.{}(".format(call) not in body
    ]
    assert not missing, (
        "these consumers must obtain their dimensions from rft.core.plan, "
        "not compute them again -- otherwise the Review report and the "
        "placed steel can disagree (#56): %s"
        % ["%s is missing core_plan.%s()" % (w, c) for w, c in missing]
    )


def test_the_label_size_estimate_uses_the_font_the_labels_are_drawn_in():
    """#62. rft.ui.sketch_layout keeps labels inside the canvas by
    estimating each one's WIDTH from its length and the font size. If the
    renderer estimates at one size and draws at another, the estimate is
    wrong by that ratio and the clipping this fixed comes straight back --
    silently, since a too-small estimate simply lets the tail hang past
    the edge again.

    One constant, passed to the estimator AND set on the TextBlock.
    """
    body = _method_body("_draw_shapes")
    assert "estimate_text_size_px(" in body
    assert "SKETCH_FONT_SIZE_PX)" in body or "SKETCH_FONT_SIZE_PX," in body, (
        "the label width estimate must be given the same font size the "
        "labels are drawn in, not a literal"
    )
    assert "text_block.FontSize = SKETCH_FONT_SIZE_PX" in body, (
        "the TextBlock must be set from the same constant the estimate "
        "uses -- a literal here is how the two drift apart"
    )
    # And no second opinion about the size anywhere in that method.
    assert "FontSize = 1" not in body, (
        "a literal font size is set in _draw_shapes; use "
        "SKETCH_FONT_SIZE_PX so the estimate cannot disagree with the draw"
    )


def test_every_label_is_placed_through_the_tested_layout_module():
    """The clamping and de-collision are the fix for #62. They must not be
    re-implemented inline in the renderer, where nothing can execute them:
    that is the whole reason they were put in an importable module.
    """
    # Comments stripped: the first version of this check was satisfied by
    # a comment naming the call, which the prover caught by MISSING its
    # own mutation. A guard that a comment can satisfy is not a guard.
    body = _code_only(_method_body("_draw_shapes"))
    assert "place_labels(" in body, (
        "labels must be positioned by rft.ui.sketch_layout.place_labels, "
        "which has tests, not by arithmetic inlined here"
    )
    assert "LabelBox(" in body


def test_the_support_detection_dict_has_exactly_one_writer():
    """#49's review finding, guarded.

    Two callers need the support-detection dict: the lazy detector that
    scans for the supports, and the pick handler that has already scanned
    and only needs the result cached so the live sketch can read plain
    numbers off the UI thread. #49 gave the second one its own dict
    literal, listing all twelve keys again.

    It agreed exactly with the first. So did rft.core.plan's private copy
    of ZONE_LAYOUT_FLAGS, for three releases, while the Review report and
    the placer described different stirrup sets -- identical steel,
    described wrongly, invisible because the totals matched.

    A second copy of a shape is not a shortcut; it is a second answer
    waiting to be given. This counts the writers.
    """
    text = io.open(SCRIPT_PATH, encoding="utf-8").read()
    writers = text.count('"support_width_start_mm":')
    assert writers == 1, (
        "the support-detection dict is built in %d places. Build it in "
        "_support_detection() and call that, so the shape and its derived "
        "fields (is_supported_*, l_mm) have one definition." % writers
    )
    assert "def _support_detection(" in text, (
        "this test no longer describes the code it guards: the shared "
        "constructor it was written about is gone."
    )


def test_the_placer_does_not_rebuild_a_face_plan_for_the_crack_offsets():
    """The other half of the same fix, and the half a "uses the plan
    module" check cannot see.

    ``core_plan.innermost_layer_offset_mm`` can be present and the old
    ``_face(True).layers[-1].offset_mm`` can still be sitting next to it.
    That expression is what crashed: a FacePlan needs a per-layer BAR
    count, A50 only requires a face to be DETAILED (bar type + layer
    count), so detailing both faces while placing only one raised a
    TypeError from inside the bar-position arithmetic -- with the
    transaction already open, for a combination the derivation had just
    declared valid.
    """
    body = _method_body("_build_placement_plans")
    assert "layers[-1]" not in body, (
        "_build_placement_plans reads a layer off a FacePlan again. The "
        "crack plan's H_avail offsets must come from "
        "core_plan.innermost_layer_offset_mm, which needs no bar count."
    )
    # SELF-GUARD: if _face() itself ever disappears this test would pass
    # for the wrong reason -- there would be no FacePlan to misread.
    assert "def _face(" in body, (
        "this test no longer describes the code it guards: the per-face "
        "closure it was written about is gone."
    )


def test_the_placement_stub_is_gone():
    """#56 removed it. A NotImplementedError left behind unreachable would
    be a claim the tool cannot place, which is no longer true.
    """
    text = io.open(SCRIPT_PATH, encoding="utf-8").read()
    assert "raise NotImplementedError" not in text


# --- attribute names on the derivation must exist -------------------------


def test_every_review_attribute_the_script_uses_exists():
    """The defect this test exists for reached a live host in v0.2.0-rc4.

    ``_do_place`` read ``review.crack`` while the namedtuple field is
    ``crack_bars``. Everything upstream worked -- the derivation was
    correct, the report printed, the transaction opened -- and placement
    died on an AttributeError at the last step, rolling back a beam the
    engineer had every reason to expect would be detailed.

    Nothing could catch it: ``script.py`` imports ``pyrevit`` and cannot
    be imported under CPython, so no test ever evaluates that attribute
    access. The names can still be compared as TEXT, which is the same
    trick the x:Name cross-check uses, and it is enough.
    """
    from rft.ui.derivation import ReviewDerivation

    text = io.open(SCRIPT_PATH, encoding="utf-8").read()
    used = set(re.findall(r"review\.([A-Za-z_][A-Za-z0-9_]*)", text))
    # SELF-GUARD, and it earned its place immediately: the first
    # version of this test carried a stray BACKSPACE byte in the
    # pattern: a regex word boundary written into the file as a
    # literal control character instead of two characters. It matched
    # nothing, so ``used`` was empty, so the set difference was empty,
    # so it PASSED -- against the very defect it was written for, and
    # its mutation test is the only reason that was noticed.
    #
    # A text-based check that finds nothing is indistinguishable from
    # one that finds nothing WRONG unless it says which it is.
    assert used, (
        "this test matched no review.<attr> access at all in script.py, "
        "so it proves nothing: either the pattern is broken or the "
        "code stopped using the derivation."
    )
    unknown = sorted(used - set(ReviewDerivation._fields))
    assert not unknown, (
        "script.py reads these attributes off a ReviewDerivation, which "
        "has no such field -- an AttributeError on a live host, after the "
        "transaction has already opened: %s (fields are %s)"
        % (unknown, list(ReviewDerivation._fields))
    )


def test_no_xaml_comment_contains_a_double_hyphen():
    """A double hyphen is illegal inside an XML comment -- only the closing
    "-->" may contain one -- and it makes the whole file unparseable, so
    the window will not open at all.

    This is the THIRD time it has happened here: once while #48 was being
    implemented, once during rc3's label rework, once during #60's
    palette. Every time it came from writing a XAML comment in the same
    prose style as the Python comments right next to it, where "--" is
    ordinary punctuation. test_xaml_parses already catches it, but only as
    "not well-formed (invalid token): line 24, column 30", which says
    nothing about the cause. This says the cause.
    """
    text = io.open(XAML_PATH, encoding="utf-8").read()
    offenders = []
    for match in re.finditer(r"<!--(.*?)-->", text, flags=re.DOTALL):
        if re.search(r"-{2,}", match.group(1)):
            line = text[:match.start()].count("\n") + 1
            offenders.append(line)
    assert not offenders, (
        "XAML comment(s) starting at line(s) %s contain '--', which is "
        "illegal inside an XML comment and makes the file unparseable. "
        "Use a single hyphen in XAML comments; '--' is fine in the Python "
        "comments next door, which is exactly why this keeps happening."
        % offenders
    )


def test_the_window_element_itself_uses_no_static_resource():
    """The defect that broke v0.2.0-rc6 the moment the button was pressed.

    ``Background="{StaticResource SurfaceWhite}"`` was set on the <Window>
    element, whose own attributes are resolved BEFORE its
    ``Window.Resources`` block is populated -- so the name does not exist
    yet and WPF throws "Cannot find resource named 'SurfaceWhite'" at
    load. A forward reference, and ``StaticResource`` does not do forward
    references.

    The XML parsed perfectly, so ``test_xaml_parses`` was green: this is a
    WPF SEMANTIC error inside well-formed markup. Put window-level brushes
    on the root panel, which is a child and therefore parsed after the
    resources.
    """
    text = io.open(XAML_PATH, encoding="utf-8").read()
    window_tag = text[:text.index(">")]
    assert "StaticResource" not in window_tag, (
        "the <Window> element's own attributes cannot reference "
        "Window.Resources -- they are resolved before it exists. Move the "
        "brush onto the root Grid instead."
    )


def test_every_static_resource_reference_is_defined():
    """The same class of failure, generalised: any StaticResource whose
    key is never declared throws only when the window is constructed, on a
    live host, with a stack trace forty frames deep.
    """
    text = io.open(XAML_PATH, encoding="utf-8").read()
    used = set(re.findall(r"\{StaticResource\s+([A-Za-z0-9_]+)\s*\}", text))
    declared = set(re.findall(r'x:Key="([A-Za-z0-9_]+)"', text))
    assert used, "no StaticResource references found -- pattern broken?"
    missing = sorted(used - declared)
    assert not missing, (
        "these StaticResource keys are referenced but never declared with "
        "x:Key, which throws at window construction: %s" % missing
    )


def test_the_script_persists_only_what_the_persistence_module_allows():
    """#54 (U10). The rule that a restore cannot arm Place holds because
    four inputs are never stored -- and that holds only while the SCRIPT
    reads its field lists from rft.ui.persistence instead of naming
    fields itself.

    tests/test_ui_persistence.py proves the rule against the real
    derivation, but it can only see the lists. If the script were to add
    `data["text"]["top_bar_count_tb"] = ...` on its way past, the pure
    module would still look correct and the guarantee would be gone. So
    this reads the script.
    """
    from rft.ui import persistence as ui_persistence

    body = _code_only(_method_body("_store_project_inputs"))
    for name in ui_persistence.TEXT_FIELDS + ui_persistence.CHOICE_FIELDS:
        assert name not in body, (
            "%s is named directly in _store_project_inputs; the field "
            "lists belong to rft.ui.persistence, which is where the "
            "withheld four are enforced" % name
        )
    assert "ui_persistence.TEXT_FIELDS" in body
    assert "ui_persistence.CHOICE_FIELDS" in body
    assert "ui_persistence.to_store(" in body

    # And nothing anywhere in the script may store a withheld field.
    script_text = _code_only(io.open(SCRIPT_PATH, encoding="utf-8").read())
    store_region = script_text[script_text.index("def _store_project_inputs"):]
    store_region = store_region[:store_region.index("def _restore_project_inputs")]
    for field in ui_persistence.REQUEST_CONSTITUTING_FIELDS:
        assert field not in store_region, (
            "%s decides whether a section is REQUESTED and must never be "
            "persisted (U10): restoring values is not restoring intent" % field
        )


def test_settings_are_stored_per_project_and_never_globally():
    """U10: "Not per-user-global, which would carry one job's cover
    conventions into an unrelated job." pyRevit's this_project flag
    defaults to True, so the failure mode is a call that passes False --
    or one that relies on the default and is later "tidied".
    """
    script_text = _code_only(io.open(SCRIPT_PATH, encoding="utf-8").read())
    for call in ("script.store_data(", "script.load_data(", "script.data_exists("):
        assert call in script_text, "%s is not called at all" % call
    assert "this_project=False" not in script_text, (
        "settings must be per project, not per user"
    )
    # Stated explicitly at every call site rather than left to the default.
    assert script_text.count("this_project=True") == 3, (
        "each of store_data/load_data/data_exists must pass "
        "this_project=True explicitly -- the difference between per-project "
        "and per-user is too important to read as a default"
    )


def test_a_first_run_checks_before_loading_stored_data():
    """pyRevit's load_data opens the file directly and RAISES when nothing
    has been stored yet -- which is the normal first run on any project.
    The existence check is not optional, and the wrapper is not either.

    Checked with ast rather than by grepping for the call. The first
    version of this test looked for the substring "script.data_exists(",
    and the prover MISSED its own mutation: `if False and
    script.data_exists(...)` still contains that substring, so the check
    was bypassed and the test stayed green. Parsing is available here --
    ast.parse reads the file without importing it, which is the whole
    reason script.py cannot be tested any other way.
    """
    import ast

    tree = ast.parse(io.open(SCRIPT_PATH, encoding="utf-8").read())
    method = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_restore_project_inputs":
            method = node
    assert method is not None, "_restore_project_inputs is gone"

    def _calls(node):
        found = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func = child.func
                if isinstance(func, ast.Attribute):
                    found.add(func.attr)
        return found

    assert "load_data" in _calls(method), "nothing loads the stored data"

    # The load must be GATED by an existence check that can actually fire.
    gates = [
        node for node in ast.walk(method)
        if isinstance(node, ast.If) and "data_exists" in _calls(node.test)
    ]
    assert gates, (
        "load_data raises on a first run, which is every project's first "
        "run -- it must be gated by script.data_exists"
    )
    for gate in gates:
        # `if False and script.data_exists(...)` reads as a gate and is
        # not one. Any constant falsehood in the test disqualifies it.
        for child in ast.walk(gate.test):
            value = getattr(child, "value", None)
            assert not (isinstance(child, ast.Constant) and value in (False, 0, None)), (
                "the existence check is short-circuited by a constant, so "
                "it never runs: %s" % ast.dump(gate.test)[:120]
            )
        assert any(isinstance(n, ast.Return) for n in ast.walk(gate)), (
            "the existence check must RETURN when there is nothing stored, "
            "not fall through to the load"
        )

    body = _code_only(_method_body("_restore_project_inputs"))
    assert "except Exception:" in body, (
        "restoring runs while the window is opening -- a settings file is "
        "not worth failing to open the tool over"
    )


def test_place_preflight_checks_spacing_before_the_transaction_opens():
    """#61 -- the Review report's "REFUSED (section 6.2-6.4)" lines
    (A43/A44's sub-minimum achieved clear spacing, A36's option 1 with
    more than one layer) must actually stop Place, not just be printed.
    script.py cannot be imported (it imports pyrevit), so this parses it
    with ast rather than grepping for the call: a substring search would
    be satisfied by a comment, and would not notice `if False and ...`
    short-circuiting the gate -- both have bitten this repo before (see
    test_a_first_run_checks_before_loading_stored_data above).
    """
    import ast

    tree = ast.parse(io.open(SCRIPT_PATH, encoding="utf-8").read())
    method = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "on_place_click":
            method = node
    assert method is not None, "on_place_click is gone"

    def _calls(node):
        found = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func = child.func
                if isinstance(func, ast.Attribute):
                    found.add(func.attr)
                elif isinstance(func, ast.Name):
                    found.add(func.id)
        return found

    assert "_spacing_refusal_messages" in _calls(method), (
        "on_place_click never calls the section 6.2-6.4 preflight"
    )
    assert "_dispatch_to_revit_context" in _calls(method), (
        "_dispatch_to_revit_context is gone -- rewrite this guard against "
        "whatever now opens the transaction"
    )

    # The preflight must run BEFORE the transaction opens. Compared by
    # line number rather than assuming `ast.walk`'s traversal order lines
    # up with source order across nested blocks.
    spacing_call_linenos = [
        child.lineno for child in ast.walk(method)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == "_spacing_refusal_messages"
    ]
    dispatch_call_linenos = [
        child.lineno for child in ast.walk(method)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == "_dispatch_to_revit_context"
    ]
    assert spacing_call_linenos and dispatch_call_linenos
    assert max(spacing_call_linenos) < min(dispatch_call_linenos), (
        "the section 6.2-6.4 spacing preflight must run before "
        "_dispatch_to_revit_context, not after"
    )

    # The messages it returns must be GATED by an `if` that can actually
    # fire and RETURN -- not computed and dropped on the floor, and not
    # short-circuited by a constant the way one guard in this file was
    # (`if False and script.data_exists(...)`, above).
    assign = None
    for node in ast.walk(method):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Attribute) and func.attr == "_spacing_refusal_messages":
                assign = node
    assert assign is not None, (
        "nothing captures _spacing_refusal_messages's return value -- a "
        "call whose result is discarded refuses nothing"
    )
    assert len(assign.targets) == 1 and isinstance(assign.targets[0], ast.Name), (
        "the preflight's result must be bound to a single plain name"
    )
    target_name = assign.targets[0].id

    gates = [
        node for node in ast.walk(method)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name) and node.test.id == target_name
    ]
    assert gates, (
        "the preflight's messages are never checked with `if %s:` -- "
        "computed and never consulted is the same as never computed" % target_name
    )
    for gate in gates:
        for child in ast.walk(gate.test):
            value = getattr(child, "value", None)
            assert not (isinstance(child, ast.Constant) and value in (False, 0, None)), (
                "the spacing gate is short-circuited by a constant, so it "
                "never refuses: %s" % ast.dump(gate.test)[:120]
            )
        assert any(isinstance(n, ast.Return) for n in ast.walk(gate)), (
            "the spacing gate must RETURN on a refusal, not fall through "
            "to the transaction dispatch"
        )
