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

# x:Name elements that exist for a later ticket (#48/#50) and are not yet
# referenced by this ticket's script.py -- named here explicitly so the
# reverse check stays meaningful instead of being disabled outright.
NOT_YET_REFERENCED = {"tabs", "status_tb"}


def _xaml_names():
    tree = ET.parse(XAML_PATH)
    return {el.get(X_NAME) for el in tree.iter() if el.get(X_NAME) is not None}


def _beam_materials_tab_names():
    """x:Name elements inside the "Beam & Materials" TabItem only -- the
    tab this ticket owns. Found by locating the TabItem whose Header
    contains "Beam" (ElementTree does not expose attribute-value XPath
    matching by substring), then walking its subtree.
    """
    tree = ET.parse(XAML_PATH)
    ns = "{http://schemas.microsoft.com/winfx/2006/xaml/presentation}"
    for tab_item in tree.iter(ns + "TabItem"):
        header = tab_item.get("Header") or ""
        if "Beam" in header:
            return {el.get(X_NAME) for el in tab_item.iter() if el.get(X_NAME) is not None}
    raise AssertionError("no TabItem with 'Beam' in its Header was found")


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
    this ticket owns. A named control this ticket added that the script
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


def test_x_name_values_are_unique():
    tree = ET.parse(XAML_PATH)
    names = [el.get(X_NAME) for el in tree.iter() if el.get(X_NAME) is not None]
    duplicates = sorted(set(n for n in names if names.count(n) > 1))
    assert not duplicates, "duplicate x:Name values: %s" % duplicates
