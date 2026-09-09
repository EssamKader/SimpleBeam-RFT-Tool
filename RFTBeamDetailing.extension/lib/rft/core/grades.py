# -*- coding: utf-8 -*-
"""Role -> steel grade assignment (rev 2 section 1.1, A34) and the
explicit-selection policy S7/A42 requires (issues #20, #27).

Pure Python: no Revit imports. `RebarBarType`/`RebarHookType` objects
themselves are resolved in the adapter layer (``rft.revit.bar_types``) from
an EXPLICIT selection made in the pushbutton's own UI -- never inferred
from the document by name-matching or a "first available" fallback. This
module owns the POLICY those adapters and pushbuttons call into: which
grade each bar role uses, the label each role's picker must carry, the
messages emitted when a required selection is missing, the two-part
stirrup-hook guard -- REBAR_HOOK_STYLE must be Stirrup/Tie (1) and the
angle must be 135 degrees (rev 2 section 7.3, A45, supersedes A33; issue
#25) -- and the stirrup/high-tensile grade-conflict guard A42 requires --
mirroring how ``rft.core.guards`` owns policy for the S9 out-of-scope
guards.

Rev 2 section 1.1 (A34, A42), section 2.1 (A10), section 7.3 (A33).

**A42 supersedes A35** (ticket #27): A35 specified exactly two
``RebarBarType`` selections, one per GRADE. In Revit a ``RebarBarType`` IS a
diameter, so two selections cannot express a Ø12 top bar and a Ø16 bottom
bar in the same beam -- the normal case. A42 moves to one selection per bar
ROLE instead. Grade stops being a selection axis: inferring a
``RebarBarType``'s grade from the type itself is exactly what A35's note
already ruled out (a `RebarBarType` carries a diameter, not a grade), so
A34's assignment is now the LABEL each role's picker carries and a line in
the report -- the engineer's selection is the assertion, not something this
module can verify. The bar diameter itself is no longer typed anywhere; it
comes from the selected type via ``rft.revit.bar_types.bar_type_diameter_mm``.
"""

from .guards import GuardMessage

GRADE_MILD = "mild St 24/35 (fy 240 MPa, plain round)"
GRADE_HIGH_TENSILE = "high tensile St 36/52 (fy 360 MPa, deformed)"

ROLE_STIRRUP = "stirrups"
ROLE_TOP_MAIN = "top main bars"
ROLE_BOTTOM_MAIN = "bottom main bars"
ROLE_CRACK = "crack/skin bars"
ROLE_SPACER = "spacer bars"

# rev 2 section 1.1, A34 -- applied LITERALLY, as data, not as scattered
# per-pushbutton conditionals. THE SPACER ROW IS DELIBERATE: mild steel is
# common for spacer bars in practice, so a future reader will assume this
# is a mistake and "correct" it back to mild. It is not a mistake -- A34's
# assignment table lists spacer bars under high tensile, decided by ticket
# #13 and confirmed by the project owner when this ticket (S7, issue #20)
# was scoped. Do not change this mapping without a new decision ticket
# that explicitly overrides A34. Spacer bars are not placed (rev 2 §6.3,
# no picker exists for this role -- see A42/#27), but the row stays for
# when that lands.
ROLE_GRADE = {
    ROLE_STIRRUP: GRADE_MILD,
    ROLE_TOP_MAIN: GRADE_HIGH_TENSILE,
    ROLE_BOTTOM_MAIN: GRADE_HIGH_TENSILE,
    ROLE_CRACK: GRADE_HIGH_TENSILE,
    ROLE_SPACER: GRADE_HIGH_TENSILE,
}

# Human-readable names for pickers and reports. Kept separate from the
# internal ``ROLE_*`` string constants so the picker/report wording can be
# tidied without touching the dict keys used throughout the codebase.
ROLE_LABEL = {
    ROLE_STIRRUP: "Stirrups",
    ROLE_TOP_MAIN: "Top main bars",
    ROLE_BOTTOM_MAIN: "Bottom main bars",
    ROLE_CRACK: "Crack/skin bars",
    ROLE_SPACER: "Spacer bars",
}

GRADE_ASSIGNMENT_SPEC_SECTION = "rev 2 section 1.1 (A34)"
BAR_TYPE_SELECTION_SPEC_SECTION = "rev 2 section 1.1 (A42, supersedes A35)"
# A45 (ticket #31/#25) supersedes A33: the required angle moved from 180 deg
# to 135 deg after a live-host probe found every stock Stirrup/Tie-family
# hook ships at 90/135 deg, and every 180 deg hook ships as Standard family,
# which RebarStyle.StirrupTie rejects outright. The angle guard's spec
# section now cites A45, not A33.
HOOK_ANGLE_SPEC_SECTION = "rev 2 section 7.3 (A45, supersedes A33)"
# Same live probe (A45): the family constraint is separate from the angle
# and is cited under the same amendment, since A45 is what documents both
# halves of the guard together.
HOOK_STYLE_SPEC_SECTION = "rev 2 section 7.3 (A45)"
GRADE_CONFLICT_SPEC_SECTION = "rev 2 section 1.1 (A34/A42)"

HOOK_ANGLE_REQUIRED_DEG = 135.0

# This ticket's own design choice, not a spec value -- same pattern as
# CONTINUOUS_RUN_ANGLE_THRESHOLD_DEG in rft.core.guards. A hook angle
# round-tripped through a radians-valued Revit parameter can carry a
# fraction of a degree of float noise; 1 degree comfortably absorbs that
# while still catching a genuinely different hook (e.g. 90 or 180 deg).
HOOK_ANGLE_TOLERANCE_DEG = 1.0

# BuiltInParameter.REBAR_HOOK_STYLE's two values, confirmed live against
# Revit 2024 / RevitAPI 24.3.40.0 (issue #25/#31 probe): every stock 180 deg
# hook is Standard family; every stock Stirrup/Tie hook ships at 90 or
# 135 deg. RebarStyle.StirrupTie accepts only Stirrup/Tie-family hooks and
# throws an opaque `InternalException: "An internal error has occurred."`
# on a Standard-family one, regardless of that hook's own angle.
HOOK_STYLE_STANDARD = 0
HOOK_STYLE_STIRRUP_TIE = 1


def grade_for_role(role):
    """The steel grade rev 2 section 1.1 (A34) assigns to ``role``.

    Raises ``KeyError`` for an unrecognised role -- there is no default
    grade to fall back to.
    """
    return ROLE_GRADE[role]


def role_picker_label(role):
    """The label A42 requires each role's ``RebarBarType`` picker to carry
    -- built from ``ROLE_GRADE`` so it can never drift from the mapping,
    e.g. "Bottom main bars -- high tensile St 36/52 (fy 360 MPa,
    deformed)". Puts A34's requirement in front of the engineer at the
    moment of choosing, since the grade can no longer be checked
    afterwards from the selected type itself.
    """
    return "{} -- {}".format(ROLE_LABEL[role], ROLE_GRADE[role])


def role_grade_report_line(role, bar_type_name):
    """Report line (A42): which bar type was used for ``role`` AND the
    grade A34 requires for it, so a wrong pick is visible after the fact
    even though it could not be blocked mechanically.
    """
    return "{}: RebarBarType '{}' used (A34 requires {})".format(
        ROLE_LABEL[role], bar_type_name, ROLE_GRADE[role]
    )


def bar_type_for_role(role, selected_bar_type):
    """The already EXPLICITLY-selected ``RebarBarType`` object for
    ``role`` (rev 2 section 1.1, A42) -- never inferred from naming, never
    a fallback to "the first available type" in the document.

    Raises ``ValueError`` if no selection was supplied, so a bar can never
    be placed with a defaulted or guessed type. Callers should normally
    catch a missing selection earlier via
    ``missing_bar_type_selection_message`` and refuse before reaching this
    call -- this is the last-resort guard, not the primary one.
    """
    if selected_bar_type is None:
        raise ValueError(
            "No RebarBarType selected for role '{}' -- rev 2 section 1.1 "
            "(A42) requires an explicit selection for every role actually "
            "placed; a missing selection is a blocking error, never a "
            "defaulted or guessed bar type.".format(role)
        )
    return selected_bar_type


def missing_bar_type_selection_message(role):
    """Blocking ``GuardMessage`` (rev 2 section 1.1, A42) for a missing
    explicit ``RebarBarType`` selection for ``role``.
    """
    condition = "no RebarBarType selected for role '{}'".format(role)
    message = (
        "No RebarBarType selected for {}. Rev 2 section 1.1 (A42) requires "
        "explicit selection from the document's available RebarBarTypes, "
        "labelled with the grade A34 requires for this role -- never "
        "inferred from naming conventions, which silently picks the wrong "
        "grade whenever an office's naming is non-standard. A missing "
        "selection is a blocking validation error; no bar may be placed "
        "with a defaulted or guessed bar type.".format(role_picker_label(role))
    )
    return GuardMessage(condition=condition, spec_section=BAR_TYPE_SELECTION_SPEC_SECTION, message=message)


def missing_hook_type_selection_message():
    """Blocking ``GuardMessage`` for a missing explicit ``RebarHookType``
    selection (rev 2 section 7.3, A45; issue #25). Same no-fallback rule
    as the bar-type selections above -- closes the "falls back to the
    first RebarHookType in the document" defect issue #25 named.

    This fires when the engineer cancels the picker (or the document has
    no ``RebarHookType`` at all). It is distinct from
    ``no_usable_hook_type_message``, which fires when the picker's
    candidate LIST is itself empty after filtering to the required family
    -- a different, more actionable situation (see that function).
    """
    condition = "no RebarHookType selected for the stirrup hook"
    message = (
        "No RebarHookType selected for the stirrup hook. Rev 2 section 7.3 "
        "(A45) requires a Stirrup/Tie-family hook (REBAR_HOOK_STYLE = 1) at "
        "135 degrees +/- 1 degree -- falling back to the first RebarHookType "
        "in the document risks silently placing a non-compliant or "
        "incompatible hook (issue #25). A missing selection is a blocking "
        "validation error."
    )
    return GuardMessage(condition=condition, spec_section=HOOK_ANGLE_SPEC_SECTION, message=message)


def no_usable_hook_type_message():
    """Blocking ``GuardMessage`` (rev 2 section 7.3, A45; issue #25) when
    filtering the document's ``RebarHookType``s to the Stirrup/Tie family
    (``REBAR_HOOK_STYLE == 1``) A45 requires leaves NOTHING to pick from --
    a project containing only Standard-family hooks, for instance, has no
    valid stirrup hook at all.

    This names the fix -- create or duplicate a Stirrup/Tie-family hook at
    135 degrees -- rather than falling back to "the first hook found",
    which is exactly the defect issue #25/S7 (#20) already removed. An
    empty candidate list must refuse, never silently offer an
    unfilterable/unusable hook.
    """
    condition = "no Stirrup/Tie-family (REBAR_HOOK_STYLE = 1) RebarHookType exists in the document"
    message = (
        "No Stirrup/Tie-family RebarHookType (REBAR_HOOK_STYLE = 1) exists "
        "in this project. Rev 2 section 7.3 (A45) requires stirrups to use "
        "a Stirrup/Tie-family hook at 135 degrees +/- 1 degree -- a "
        "Standard-family hook throws an opaque Revit "
        "'InternalException: An internal error has occurred' regardless of "
        "its angle, so there is no usable fallback. Create or duplicate a "
        "Stirrup/Tie-family RebarHookType set to 135 degrees in this "
        "project, then retry (issue #25, A45)."
    )
    return GuardMessage(condition=condition, spec_section=HOOK_STYLE_SPEC_SECTION, message=message)


def hook_style_guard_message(style, hook_type_name=""):
    """Blocking ``GuardMessage`` when a READ-BACK hook style is not
    ``HOOK_STYLE_STIRRUP_TIE`` (1) (rev 2 section 7.3, A45; issue #25/#31
    live-host probe). Returns ``None`` when the style holds.

    Kept SEPARATE from ``hook_angle_guard_message`` on purpose -- both are
    required, but a combined message would misdiagnose the common failure
    mode: a Standard-family hook set to exactly 135 degrees passes the
    angle check and is still rejected by ``RebarStyle.StirrupTie`` with an
    opaque ``InternalException: "An internal error has occurred."`` A
    single combined message would tell that engineer their ANGLE is wrong,
    which it is not -- the constraint is the family. This message says
    which family was selected, which family is required, and states
    explicitly that a correct angle does not save a wrong family.

    Callers must NOT call this when the style could not be read back at
    all -- an unreadable style is its own refusal
    (``unreadable_hook_style_message``), not a pass-through to this
    function, since a wrong family throws that opaque exception and there
    is nothing safe to "proceed hopefully" toward.
    """
    if style == HOOK_STYLE_STIRRUP_TIE:
        return None
    style_name = "Standard" if style == HOOK_STYLE_STANDARD else "an unrecognised family ({})".format(style)
    named = " '{}'".format(hook_type_name) if hook_type_name else ""
    condition = "stirrup hook type{} REBAR_HOOK_STYLE = {} ({}), not 1 (Stirrup/Tie)".format(
        named, style, style_name
    )
    message = (
        "Stirrup hook type{} is {} (REBAR_HOOK_STYLE = {}), not the "
        "required Stirrup/Tie family (REBAR_HOOK_STYLE = 1). Rev 2 section "
        "7.3 (A45) requires a Stirrup/Tie-family hook for stirrups: "
        "RebarStyle.StirrupTie rejects a Standard-family hook with an "
        "opaque Revit 'InternalException: An internal error has occurred', "
        "REGARDLESS of that hook's angle -- this hook's angle being correct "
        "(or even exactly 135 degrees) does not save it. Select a "
        "Stirrup/Tie-family RebarHookType before placing stirrups "
        "(issue #25, A45).".format(named, style_name, style)
    )
    return GuardMessage(condition=condition, spec_section=HOOK_STYLE_SPEC_SECTION, message=message)


def unreadable_hook_style_message(hook_type_name=""):
    """Blocking ``GuardMessage`` (rev 2 section 7.3, A45; issue #25) when a
    stirrup hook type's ``REBAR_HOOK_STYLE`` could not be read back at all
    (``rft.revit.bar_types.hook_style`` returned ``None``).

    Unlike an unreadable ANGLE -- which degrades to an honest UNVERIFIED
    report line and does not block, since a wrong angle alone does not
    crash Revit -- an unreadable STYLE must REFUSE. A wrong family throws
    Revit's opaque ``InternalException: "An internal error has occurred."``
    on the actual ``Rebar.CreateFromCurves`` call, so proceeding "hopefully"
    on an unconfirmed family risks exactly that opaque failure instead of
    an actionable refusal now.
    """
    named = " '{}'".format(hook_type_name) if hook_type_name else ""
    condition = "stirrup hook type{} REBAR_HOOK_STYLE could not be read back".format(named)
    message = (
        "Stirrup hook type{}'s REBAR_HOOK_STYLE could not be read back. Rev "
        "2 section 7.3 (A45) requires a Stirrup/Tie-family hook "
        "(REBAR_HOOK_STYLE = 1) for stirrups, and a Standard-family hook "
        "throws an opaque Revit 'InternalException: An internal error has "
        "occurred' regardless of its angle -- so this refuses rather than "
        "proceeding on an unconfirmed family. Select a different hook type, "
        "or confirm this one's family in Revit before retrying "
        "(issue #25, A45).".format(named)
    )
    return GuardMessage(condition=condition, spec_section=HOOK_STYLE_SPEC_SECTION, message=message)


def hook_angle_guard_message(angle_deg, hook_type_name=""):
    """Blocking ``GuardMessage`` when a READ-BACK hook angle is not 135
    degrees within ``HOOK_ANGLE_TOLERANCE_DEG`` (rev 2 section 7.3, A45,
    supersedes A33; issue #25). Returns ``None`` when the angle holds.

    Callers must NOT call this when the angle could not be read back at
    all -- see ``rft.revit.bar_types.hook_angle_deg``'s docstring. An
    unreadable angle is reported to the engineer as UNVERIFIED, not
    silently treated as a pass; this function only judges an angle that
    was actually obtained.

    Kept SEPARATE from ``hook_style_guard_message`` on purpose -- see that
    function's docstring for why a combined check would misdiagnose the
    Standard-family-at-135-degrees case.
    """
    if abs(angle_deg - HOOK_ANGLE_REQUIRED_DEG) <= HOOK_ANGLE_TOLERANCE_DEG:
        return None
    named = " '{}'".format(hook_type_name) if hook_type_name else ""
    condition = "stirrup hook type{} angle = {:.1f} deg, not 135 deg".format(named, angle_deg)
    message = (
        "Stirrup hook type{} reads back an angle of {:.1f} degrees, not "
        "the 135-degree hook rev 2 section 7.3 (A45) requires. Select a "
        "135-degree Stirrup/Tie RebarHookType before placing stirrups "
        "(issue #25).".format(named, angle_deg)
    )
    return GuardMessage(condition=condition, spec_section=HOOK_ANGLE_SPEC_SECTION, message=message)


def stirrup_grade_conflict_message(stirrup_type_id, stirrup_type_name,
                                    other_type_id, other_type_name, other_role):
    """Blocking ``GuardMessage`` (A42, ticket #27) when the ``RebarBarType``
    selected/used for stirrups is the SAME element as a type selected/used
    for a high-tensile role. One element cannot carry both grades (A34),
    so -- unlike grade itself -- this is mechanically checkable: it never
    relies on inferring a grade from the type, only on comparing two
    already-known selections by ELEMENT ID.

    Returns ``None`` when the ids differ (or either id is ``None``, i.e.
    nothing to compare yet). Compares by id, never by name -- two types
    can share a display name in a badly-kept office template.
    """
    if stirrup_type_id is None or other_type_id is None:
        return None
    if stirrup_type_id != other_type_id:
        return None
    condition = "stirrup RebarBarType '{}' is the same element as the {} RebarBarType".format(
        stirrup_type_name, other_role
    )
    message = (
        "The RebarBarType selected for stirrups ('{}') is the SAME element "
        "as the RebarBarType used for {} ('{}'). Rev 2 section 1.1 (A34) "
        "assigns stirrups mild St 24/35 and {} high tensile St 36/52 -- one "
        "RebarBarType element cannot be both grades, so this is a blocking "
        "error, not a matter of judgement.".format(
            stirrup_type_name, other_role, other_type_name, other_role
        )
    )
    return GuardMessage(condition=condition, spec_section=GRADE_CONFLICT_SPEC_SECTION, message=message)
