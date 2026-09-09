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
    "tabs", "status_tb",
    "top_bar_count_tb", "bottom_bar_count_tb",
    "top_face_option_tb", "bottom_face_option_tb",
    "d_agg_tb", "min_spacing_override_tb",
    "dense_spacing_tb", "normal_spacing_tb",
}

# The tab headers owned by #47 (U3) and #48 (U4) -- matched by substring
# since ElementTree has no attribute-value XPath matching. "Review" is
# deliberately excluded: it is #50's (U6) scope and stays a placeholder,
# so a control added there would not yet be read by this script.py either.
OWNED_TAB_HEADER_SUBSTRINGS = ("Beam", "Main bars", "Stirrups", "Crack bars")


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
    """x:Name elements inside every TabItem #47/#48 own -- Beam &
    Materials, Main bars, Stirrups and Crack bars (issue #48, U4: the
    reverse check's scope extends from just Beam & Materials to these
    three new tabs). "Review" (#50, U6) is excluded on purpose -- it is
    still a genuine placeholder, not this ticket's scope.
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
    modal_calls = re.findall(r"\.ShowDialog\s*\(|show_dialog\s*\(", text)
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
