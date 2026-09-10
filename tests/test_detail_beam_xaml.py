# -*- coding: utf-8 -*-
"""#47 (U3) -- guards against an ``x:Name`` typo between
``DetailBeamWindow.xaml`` and ``script.py``, which pyRevit's ``WPFWindow``
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
    "RFTBeamDetailing.extension",
    "RFT Beam Detailing.tab",
    "Detail Beam.panel",
    "Detail Beam.pushbutton",
)
XAML_PATH = os.path.join(PUSHBUTTON_DIR, "DetailBeamWindow.xaml")
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
    # __init__, not DetailBeamWindow's).
    "top_main_bar_type", "bottom_main_bar_type", "stirrup_bar_type",
    "crack_bar_type", "stirrup_hook_type", "stirrup_hook_angle_deg",
    # #48 (U4) -- ordinary Python state, not an x:Name control.
    "beam_covers_mm",
    # #57 -- the dispatch guard, plus one INHERITED WPF member:
    # Window.Dispatcher is a real attribute of the base class, not an
    # x:Name control, so it belongs here for the same reason ordinary
    # Python state does. It is currently named only inside a docstring --
    # this check reads source text, not live attributes, which is the
    # trade for being able to run it at all without a Revit host.
    "_api_call_in_flight", "Dispatcher",
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
        "matching x:Name in DetailBeamWindow.xaml (AttributeError on a "
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
BEAM_SCOPED_ATTRS = ("beam", "host_data", "beam_covers_mm", "geometry_mm")


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
    start = text.index("    def __init__(self):", text.index("class DetailBeamWindow"))
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
    required = {
        "_report_one_main_face": ("face_layer_plans", "end_plan"),
        "_build_placement_plans": ("face_plan", "stirrup_plan", "crack_plan"),
    }
    for method, calls in required.items():
        body = _method_body(method)
        for call in calls:
            assert "core_plan.{}(".format(call) in body, (
                "%s must obtain its dimensions from rft.core.plan.%s, not "
                "compute them itself -- otherwise the Review report and the "
                "placed steel can disagree (#56)." % (method, call)
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
