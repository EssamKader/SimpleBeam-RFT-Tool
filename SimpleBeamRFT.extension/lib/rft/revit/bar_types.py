# -*- coding: utf-8 -*-
"""Adapter layer for ``RebarBarType``/``RebarHookType`` enumeration and
read-back (S7, issue #20; hook-angle and hook-style read-back, issue #25/
A45; A42 per-role selection and grade-conflict guard, issue #27).

Rev 2 section 1.1 (A34, A42): one ``RebarBarType`` is chosen per bar ROLE
by the engineer via an EXPLICIT dropdown/list selection -- never inferred
from the document by name-matching or a "first available" fallback. That
selection UI lives in each pushbutton's own script.py (mirroring where
``ask_inputs`` already lives); this module only enumerates the document's
available types for that picker, and reads back the properties this
project needs: a bar type's own diameter (the single source of truth for
every downstream mm computation, A42), and -- rev 2 section 7.3, A45 --
a stirrup hook type's own angle AND its own ``REBAR_HOOK_STYLE`` family,
the two-part guard issue #25/#31's live-host probe found is required
(``list_stirrup_hook_types`` also filters the picker to the matching
family as a convenience, not a guarantee).

SHAPE UNVERIFIED (partially closed by issue #25/#31's live-host probe --
see each function's docstring for what is now VERIFIED LIVE vs still
unconfirmed) -- see tests/fake_revit_api.py's header for the running list.
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
    """All ``RebarHookType`` elements in the document, unfiltered -- no
    longer used by any pushbutton's picker directly (see
    ``list_stirrup_hook_types``), kept as the general enumeration primitive
    other callers may still want.
    """
    return list(FilteredElementCollector(document).OfClass(RebarHookType))


def list_stirrup_hook_types(document):
    """``RebarHookType`` elements filtered to the Stirrup/Tie family
    (``REBAR_HOOK_STYLE == 1``) rev 2 section 7.3 (A45) requires for
    stirrups -- issue #25/#31's live-host probe found every stock
    Standard-family hook (every stock 180-degree hook among them) is
    rejected outright by ``RebarStyle.StirrupTie`` with an opaque
    ``InternalException``, so offering one in the stirrup picker is a UI
    that invites that failure.

    A hook whose style cannot be read back at all is EXCLUDED here too --
    it is not offered as if it might work. This filter is a convenience,
    not a guarantee: the caller must still re-check the SELECTED hook's
    style and angle after the picker returns (``rft.core.grades.
    hook_style_guard_message`` / ``hook_angle_guard_message`` /
    ``unreadable_hook_style_message``), since the read here and the read
    after selection are two separate calls that could disagree, and since
    filtering can legitimately leave nothing to pick from at all (rft.core.
    grades.no_usable_hook_type_message`` names that case).
    """
    return [hook_type for hook_type in list_hook_types(document) if hook_style(hook_type) == 1]


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

    VERIFIED LIVE (issue #25/#31, Revit 2024, ``RevitAPI 24.3.40.0``):
    ``hook_type.get_Parameter(BuiltInParameter.REBAR_HOOK_ANGLE)
    .AsDouble()`` returns RADIANS, exactly as this function's read-back and
    ``math.degrees`` conversion already assumed -- confirmed against real
    hook types reading back pi for a 180-degree hook. This function still
    returns ``None`` on any failure to read the parameter rather than
    guessing an angle -- that behaviour is unchanged and stays load-bearing
    (a project may still contain a hook type this call cannot read for
    other reasons) -- so callers can tell "read back and checked" apart
    from "could not be verified" -- ``rft.core.grades.
    hook_angle_guard_message`` must not be called at all for the ``None``
    case (see its own docstring).
    """
    try:
        from Autodesk.Revit.DB import BuiltInParameter

        param = hook_type.get_Parameter(BuiltInParameter.REBAR_HOOK_ANGLE)
        if param is None:
            return None
        return math.degrees(param.AsDouble())
    except (AttributeError, TypeError):
        return None


def hook_style(hook_type):
    """The selected ``RebarHookType``'s own ``REBAR_HOOK_STYLE``, as an
    int (0 = Standard, 1 = Stirrup/Tie), or ``None`` if it cannot be read
    back at all. Mirrors ``hook_angle_deg``'s contract exactly (issue #25,
    A45).

    VERIFIED LIVE (issue #25/#31, Revit 2024, ``RevitAPI 24.3.40.0``): the
    live probe confirmed that ``BuiltInParameter.REBAR_HOOK_STYLE``
    distinguishes Standard (0, every stock 180-degree hook in the library)
    from Stirrup/Tie (1, every stock 90/135-degree hook), and that
    ``RebarStyle.StirrupTie`` rejects a Standard-family hook with an opaque
    ``InternalException`` regardless of its angle.

    The exact call below was then re-probed on its own terms across 48
    hook types in the live model: ``get_Parameter(BuiltInParameter.
    REBAR_HOOK_STYLE)`` returns a parameter with ``StorageType.Integer``
    and ``AsInteger()`` yields 0 or 1 for every one of them. Nothing about
    this function's read-back is assumed any more.

    The ``None``-on-unreadable path is kept anyway and stays load-bearing:
    a project may still hold a hook type this call cannot read for other
    reasons, and a caller must then degrade to a REFUSAL (see
    ``rft.core.grades.unreadable_hook_style_message``), never a silent
    pass -- since a wrong family throws that opaque exception, an
    unreadable style must never be treated as "probably fine".

    NAMES LIE ABOUT FAMILY, which is the whole reason this reads a
    parameter instead of matching on ``Name``. The live model contains a
    hook type called ``Stirrup/Tie - 45`` whose ``REBAR_HOOK_STYLE`` is
    **0 (Standard)** -- selecting it for a stirrup by name would produce
    exactly the opaque ``InternalException`` this guard exists to prevent.
    """
    try:
        from Autodesk.Revit.DB import BuiltInParameter

        param = hook_type.get_Parameter(BuiltInParameter.REBAR_HOOK_STYLE)
        if param is None:
            return None
        return param.AsInteger()
    except (AttributeError, TypeError):
        return None


def element_name(element):
    """An ``ElementType``'s name, read from ``SYMBOL_NAME_PARAM``.

    VERIFIED LIVE (Revit 2024, ``RevitAPI 24.3.40.0``): returns a
    ``StorageType.String`` parameter holding exactly what ``Element.Name``
    returns in C# -- ``'10M'``, ``'Stirrup/Tie - 135 deg.'`` -- for both
    ``RebarBarType`` and ``RebarHookType``.

    WHY NOT ``element.Name``: it raises ``AttributeError: 'RebarBarType'
    object has no attribute 'Name'`` under pyRevit's IronPython 2.7 engine.
    ``Name``'s declaring type is ``Autodesk.Revit.DB.ElementType``, which
    **hides** (C# ``new``) ``Element.Name``, and IronPython's binder does
    not expose a property shadowed that way. Confirmed live: the property's
    ``DeclaringType.FullName`` is ``Autodesk.Revit.DB.ElementType`` for
    both classes, and C# reads it happily -- so this is a language-binding
    failure, not a missing member. It killed the picker in v0.1.0-rc3 the
    moment pyRevit's ``TemplateListItem.name`` did ``getattr(item, 'Name')``
    on our behalf, which is why no ``name_attr`` is passed any more.

    Returns a bracketed placeholder rather than raising if the parameter is
    missing or blank: a nameless type must still be visible in the picker,
    where the engineer can see something is wrong, instead of taking down
    the whole dialog.
    """
    from Autodesk.Revit.DB import BuiltInParameter

    param = element.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
    if param is not None:
        value = param.AsString()
        if value:
            return value
    return "<unnamed, id {}>".format(element.Id)


def bar_type_options(document, from_internal_units):
    """``(label, bar_type)`` pairs for the per-role picker, sorted by
    diameter -- ascending and numeric, not by name.

    The label carries the type's ACTUAL diameter in mm, because a bar
    type's name routinely disagrees with it and A42 makes the type's own
    diameter the single source of truth for every downstream computation.
    Measured live in the verification model: ``10M`` is **9.50 mm**,
    ``16M`` is **15.90 mm**, ``25M`` is **25.40 mm** -- Imperial #3/#5/#8
    bars carrying metric-looking names. An engineer picking ``16M`` for a
    "diameter 16 bar" gets 15.9 mm through every formula, correctly, and
    the label is the only place that can be seen before committing.

    Sorting by name would also order ``10M`` before ``9M``; sorting by
    diameter puts the list in the order a bar schedule is read.
    """
    rows = []
    for bar_type in list_bar_types(document):
        diameter_mm = bar_type_diameter_mm(bar_type, from_internal_units)
        rows.append(
            (
                "{}  --  {:.1f} mm".format(element_name(bar_type), diameter_mm),
                bar_type,
                diameter_mm,
            )
        )
    rows.sort(key=lambda row: row[2])
    return [(label, bar_type) for label, bar_type, _diameter in rows]


def hook_type_options(hook_types):
    """``(label, hook_type)`` pairs for the stirrup hook picker.

    The label carries the angle read back from the type rather than its
    name, for the reason ``hook_style``'s docstring records: names lie.
    The live model holds ``Stirrup/Tie - 45`` at ``REBAR_HOOK_STYLE == 0``,
    and ``Standard - 135 deg.`` at the required angle in the wrong family.
    An unreadable angle is LABELLED as unreadable rather than omitted or
    guessed -- ``hook_types`` is already family-filtered, so a hook
    reaching here with no readable angle is something the engineer should
    see, and selecting it is still refused after the fact by
    ``hook_angle_guard_message``'s caller.
    """
    options = []
    for hook_type in hook_types:
        angle_deg = hook_angle_deg(hook_type)
        if angle_deg is None:
            label = "{}  --  angle UNREADABLE".format(element_name(hook_type))
        else:
            label = "{}  --  {:.0f} deg".format(element_name(hook_type), angle_deg)
        options.append((label, hook_type))
    return options
