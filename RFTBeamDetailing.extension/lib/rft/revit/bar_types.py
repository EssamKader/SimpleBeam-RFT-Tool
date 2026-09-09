"""Adapter layer for ``RebarBarType``/``RebarHookType`` enumeration and
read-back (S7, issue #20; hook-angle read-back, issue #25; A42 per-role
selection and grade-conflict guard, issue #27).

Rev 2 section 1.1 (A34, A42): one ``RebarBarType`` is chosen per bar ROLE
by the engineer via an EXPLICIT dropdown/list selection -- never inferred
from the document by name-matching or a "first available" fallback. That
selection UI lives in each pushbutton's own script.py (mirroring where
``ask_inputs`` already lives); this module only enumerates the document's
available types for that picker, and reads back the properties this
ticket needs: a bar type's own diameter (now the single source of truth
for every downstream mm computation, A42), a hook type's own angle (issue
#25), and -- for the A42 stirrup/high-tensile grade-conflict guard -- the
``RebarBarType``s already used by Rebar previously placed on a given host.

SHAPE UNVERIFIED -- nothing here has been confirmed against a live Revit
host. See each function's docstring and tests/fake_revit_api.py's header
for the running list.
"""

import math

from Autodesk.Revit.DB import FilteredElementCollector
from Autodesk.Revit.DB.Structure import Rebar, RebarBarType, RebarHookType, RebarStyle


def list_bar_types(document):
    """All ``RebarBarType`` elements in the document, for the explicit
    per-role dropdown selection (rev 2 section 1.1, A42) -- no filtering,
    no inference: the engineer picks from the full list.
    """
    return list(FilteredElementCollector(document).OfClass(RebarBarType))


def list_hook_types(document):
    """All ``RebarHookType`` elements in the document, for the explicit
    dropdown selection (rev 2 section 7.3, A33; issue #25).
    """
    return list(FilteredElementCollector(document).OfClass(RebarHookType))


def bar_type_diameter_mm(bar_type, from_internal_units):
    """The selected ``RebarBarType``'s own diameter, in mm -- since A42,
    this is the SINGLE SOURCE OF TRUTH for the bar diameter used
    everywhere downstream (`LD`, layer offsets, the stirrup rectangle, the
    §2.2/A7 clearance): there is no longer a separate typed diameter input
    to reconcile it against.

    SHAPE UNVERIFIED: assumes ``RebarBarType.BarNominalDiameter`` (the
    catalog/nominal diameter) is a read-only property in internal units.
    Published Revit API documentation for ``RebarBarType`` also lists
    ``BarModelDiameter`` (the diameter used for modelling/clash geometry,
    which can differ slightly from the nominal catalog size) as a
    plausible alternative property; which of the two is the intended one
    has not been confirmed against a live host. If ``BarNominalDiameter``
    turns out to be wrong, swap it for ``BarModelDiameter`` here -- no
    caller of this function needs to change either way.
    """
    return from_internal_units(bar_type.BarNominalDiameter)


def hook_angle_deg(hook_type):
    """The selected ``RebarHookType``'s own hook angle, in degrees, or
    ``None`` if it cannot be read back at all (issue #25).

    SHAPE UNVERIFIED: the presumed read-back is
    ``hook_type.get_Parameter(BuiltInParameter.REBAR_HOOK_ANGLE)
    .AsDouble()``, returning RADIANS (per issue #25's own note), converted
    to degrees here. Whether this parameter exists on ``RebarHookType`` at
    all, and whether it is even the right member for the catalog hook's
    own fixed angle (as opposed to some per-instance override), is
    unconfirmed without a live host. This function returns ``None`` on any
    failure to read it rather than guessing an angle, so callers can tell
    "read back and checked" apart from "could not be verified" --
    ``rft.core.grades.hook_angle_guard_message`` must not be called at all
    for the ``None`` case (see its own docstring).
    """
    try:
        from Autodesk.Revit.DB import BuiltInParameter

        param = hook_type.get_Parameter(BuiltInParameter.REBAR_HOOK_ANGLE)
        if param is None:
            return None
        return math.degrees(param.AsDouble())
    except (AttributeError, TypeError):
        return None
