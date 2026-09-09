"""Role -> steel grade assignment (rev 2 section 1.1, A34) and the
explicit-selection policy S7/A42 requires (issues #20, #27).

Pure Python: no Revit imports. `RebarBarType`/`RebarHookType` objects
themselves are resolved in the adapter layer (``rft.revit.bar_types``) from
an EXPLICIT selection made in the pushbutton's own UI -- never inferred
from the document by name-matching or a "first available" fallback. This
module owns the POLICY those adapters and pushbuttons call into: which
grade each bar role uses, the label each role's picker must carry, the
messages emitted when a required selection is missing, the 180-degree
stirrup-hook check (issue #25), and the stirrup/high-tensile grade-conflict
guard A42 requires -- mirroring how ``rft.core.guards`` owns policy for the
S9 out-of-scope guards.

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
HOOK_ANGLE_SPEC_SECTION = "rev 2 section 7.3 (A33)"
GRADE_CONFLICT_SPEC_SECTION = "rev 2 section 1.1 (A34/A42)"

HOOK_ANGLE_REQUIRED_DEG = 180.0

# This ticket's own design choice, not a spec value -- same pattern as
# CONTINUOUS_RUN_ANGLE_THRESHOLD_DEG in rft.core.guards. A hook angle
# round-tripped through a radians-valued Revit parameter can carry a
# fraction of a degree of float noise; 1 degree comfortably absorbs that
# while still catching a genuinely different hook (e.g. 90 or 135 deg).
HOOK_ANGLE_TOLERANCE_DEG = 1.0


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
    selection (rev 2 section 7.3, A33; issue #25). Same no-fallback rule
    as the bar-type selections above -- closes the "falls back to the
    first RebarHookType in the document" defect issue #25 named.
    """
    condition = "no RebarHookType selected for the stirrup hook"
    message = (
        "No RebarHookType selected for the stirrup hook. Rev 2 section 7.3 "
        "(A33) fixes the hook at 180 degrees semicircular -- falling back "
        "to the first RebarHookType in the document risks silently placing "
        "a non-compliant angle (issue #25). A missing selection is a "
        "blocking validation error."
    )
    return GuardMessage(condition=condition, spec_section=HOOK_ANGLE_SPEC_SECTION, message=message)


def hook_angle_guard_message(angle_deg, hook_type_name=""):
    """Blocking ``GuardMessage`` when a READ-BACK hook angle is not 180
    degrees within ``HOOK_ANGLE_TOLERANCE_DEG`` (rev 2 section 7.3, A33;
    issue #25). Returns ``None`` when the angle holds.

    Callers must NOT call this when the angle could not be read back at
    all -- see ``rft.revit.bar_types.hook_angle_deg``'s docstring. An
    unreadable angle is reported to the engineer as UNVERIFIED, not
    silently treated as a pass; this function only judges an angle that
    was actually obtained.
    """
    if abs(angle_deg - HOOK_ANGLE_REQUIRED_DEG) <= HOOK_ANGLE_TOLERANCE_DEG:
        return None
    named = " '{}'".format(hook_type_name) if hook_type_name else ""
    condition = "stirrup hook type{} angle = {:.1f} deg, not 180 deg".format(named, angle_deg)
    message = (
        "Stirrup hook type{} reads back an angle of {:.1f} degrees, not "
        "the 180-degree semicircular hook rev 2 section 7.3 (A33) "
        "requires. Select a 180-degree RebarHookType before placing "
        "stirrups (issue #25).".format(named, angle_deg)
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
