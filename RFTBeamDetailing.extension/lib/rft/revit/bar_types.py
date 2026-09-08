"""Adapter layer for ``RebarBarType``/``RebarHookType`` enumeration and
read-back (S7, issue #20; hook-angle read-back, issue #25).

Rev 2 section 1.1 (A34/A35): the mild and high-tensile ``RebarBarType``s
are chosen by the engineer via an EXPLICIT dropdown/list selection --
never inferred from the document by name-matching or a "first available"
fallback. That selection UI lives in each pushbutton's own script.py
(mirroring where ``ask_inputs`` already lives); this module only
enumerates the document's available types for that picker, and reads back
the two properties this ticket needs: a bar type's own diameter (the
diameter-consistency cross-check) and a hook type's own angle (issue #25).

SHAPE UNVERIFIED -- nothing here has been confirmed against a live Revit
host. See each function's docstring and tests/fake_revit_api.py's header
for the running list.
"""

import math

from Autodesk.Revit.DB import FilteredElementCollector
from Autodesk.Revit.DB.Structure import RebarBarType, RebarHookType


def list_bar_types(document):
    """All ``RebarBarType`` elements in the document, for the explicit
    dropdown selection (rev 2 section 1.1, A35) -- no filtering, no
    inference: the engineer picks from the full list.
    """
    return list(FilteredElementCollector(document).OfClass(RebarBarType))


def list_hook_types(document):
    """All ``RebarHookType`` elements in the document, for the explicit
    dropdown selection (rev 2 section 7.3, A33; issue #25).
    """
    return list(FilteredElementCollector(document).OfClass(RebarHookType))


def bar_type_diameter_mm(bar_type, from_internal_units):
    """The selected ``RebarBarType``'s own diameter, in mm -- used to
    cross-check against the free-text diameter inputs (this ticket's named
    trap: a typed diameter that disagrees with the selected type's real
    diameter would otherwise silently drive the wrong `LD`, layer offsets
    and stirrup rectangle).

    SHAPE UNVERIFIED: assumes ``RebarBarType.BarNominalDiameter`` (the
    catalog/nominal diameter -- matching what the spec's O_TOP / O_BTM /
    O_stirrup inputs mean) is a read-only property in internal units.
    Published Revit API documentation for ``RebarBarType`` also lists
    ``BarModelDiameter`` (the diameter used for modelling/clash geometry,
    which can differ slightly from the nominal catalog size) as a
    plausible alternative property; which of the two is the intended one
    for this cross-check has not been confirmed against a live host. If
    ``BarNominalDiameter`` turns out to be wrong, swap it for
    ``BarModelDiameter`` here -- the cross-check policy itself
    (``rft.core.grades.diameter_consistency_message``) does not change
    either way.
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
