"""Role -> steel grade assignment (rev 2 section 1.1, A34) and the
explicit-selection / diameter-consistency policy S7 requires (issue #20).

Pure Python: no Revit imports. `RebarBarType`/`RebarHookType` objects
themselves are resolved in the adapter layer (``rft.revit.bar_types``) from
an EXPLICIT selection made in the pushbutton's own UI -- never inferred
from the document by name-matching or a "first available" fallback. This
module owns the POLICY those adapters and pushbuttons call into: which
grade each bar role uses, the messages emitted when a required selection
is missing, the 180-degree stirrup-hook check (issue #25), and the
diameter cross-check this ticket's own "trap" names -- mirroring how
``rft.core.guards`` owns policy for the S9 out-of-scope guards.

Rev 2 section 1.1 (A34, A35), section 2.1 (A10), section 7.3 (A33).
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
# that explicitly overrides A34.
ROLE_GRADE = {
    ROLE_STIRRUP: GRADE_MILD,
    ROLE_TOP_MAIN: GRADE_HIGH_TENSILE,
    ROLE_BOTTOM_MAIN: GRADE_HIGH_TENSILE,
    ROLE_CRACK: GRADE_HIGH_TENSILE,
    ROLE_SPACER: GRADE_HIGH_TENSILE,
}

GRADE_ASSIGNMENT_SPEC_SECTION = "rev 2 section 1.1 (A34)"
BAR_TYPE_SELECTION_SPEC_SECTION = "rev 2 section 1.1 (A35)"
HOOK_ANGLE_SPEC_SECTION = "rev 2 section 7.3 (A33)"
DIAMETER_CONSISTENCY_SPEC_SECTION = "rev 2 section 1.1 (A34/A35), this ticket's diameter-consistency check"

HOOK_ANGLE_REQUIRED_DEG = 180.0

# This ticket's own design choice, not a spec value -- same pattern as
# CONTINUOUS_RUN_ANGLE_THRESHOLD_DEG in rft.core.guards. A hook angle
# round-tripped through a radians-valued Revit parameter can carry a
# fraction of a degree of float noise; 1 degree comfortably absorbs that
# while still catching a genuinely different hook (e.g. 90 or 135 deg).
HOOK_ANGLE_TOLERANCE_DEG = 1.0

# This ticket's own design choice, not a spec value. Loose enough to
# absorb a fraction-of-a-mm unit round-trip artifact between internal feet
# and mm; tight enough that a genuinely different bar size (e.g. a typed
# 16 against a selected 20 mm RebarBarType) is always caught.
DIAMETER_TOLERANCE_MM = 0.5


def grade_for_role(role):
    """The steel grade rev 2 section 1.1 (A34) assigns to ``role``.

    Raises ``KeyError`` for an unrecognised role -- there is no default
    grade to fall back to.
    """
    return ROLE_GRADE[role]


def bar_type_for_role(role, mild_bar_type, high_tensile_bar_type):
    """The already EXPLICITLY-selected ``RebarBarType`` object for ``role``
    (rev 2 section 1.1, A34/A35) -- never inferred from naming, never a
    fallback to "the first available type" in the document.

    Raises ``ValueError`` if the grade this role needs was not supplied
    (a missing explicit selection reaching this far), so a bar can never
    be placed with a defaulted or guessed type. Callers should normally
    catch a missing selection earlier via
    ``missing_bar_type_selection_message`` and refuse before reaching this
    call -- this is the last-resort guard, not the primary one.
    """
    grade = grade_for_role(role)
    bar_type = mild_bar_type if grade == GRADE_MILD else high_tensile_bar_type
    if bar_type is None:
        raise ValueError(
            "No RebarBarType selected for grade '{}' (role: '{}') -- rev 2 "
            "section 1.1 (A34/A35) requires an explicit selection for "
            "every grade actually used; a missing selection is a blocking "
            "error, never a defaulted or guessed bar type.".format(grade, role)
        )
    return bar_type


def missing_bar_type_selection_message(grade_label):
    """Blocking ``GuardMessage`` (rev 2 section 1.1, A35) for a missing
    explicit ``RebarBarType`` selection -- shared text for both the mild
    and the high-tensile slot so both call sites refuse identically.
    """
    condition = "no RebarBarType selected for the {} slot".format(grade_label)
    message = (
        "No {} RebarBarType selected. Rev 2 section 1.1 (A35) requires "
        "explicit selection from the document's available RebarBarTypes "
        "-- never inferred from naming conventions, which silently picks "
        "the wrong grade whenever an office's naming is non-standard. A "
        "missing selection is a blocking validation error; no bar may be "
        "placed with a defaulted or guessed bar type.".format(grade_label)
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


def diameter_consistency_message(role_label, typed_diameter_mm, bar_type_diameter_mm):
    """Blocking ``GuardMessage`` when a free-text diameter input disagrees
    with the diameter actually carried by the explicitly-selected
    ``RebarBarType`` (this ticket's named trap). Returns ``None`` within
    ``DIAMETER_TOLERANCE_MM``.

    The typed diameter stays the single value the pure-core math (`LD`,
    layer offsets, the stirrup rectangle) already takes in mm -- this does
    not replace that input, it refuses to proceed when the two numbers
    disagree, so those computations can never silently run against a
    diameter that is not the one actually being placed.
    """
    if abs(typed_diameter_mm - bar_type_diameter_mm) <= DIAMETER_TOLERANCE_MM:
        return None
    condition = "{}: typed diameter {:.1f} mm != selected RebarBarType diameter {:.1f} mm".format(
        role_label, typed_diameter_mm, bar_type_diameter_mm
    )
    message = (
        "{}: the typed diameter ({:.1f} mm) does not match the diameter "
        "carried by the selected RebarBarType ({:.1f} mm). Left "
        "unresolved, LD, layer offsets and/or the stirrup rectangle would "
        "be computed against the WRONG diameter with nothing in the model "
        "showing it. Fix either the typed value or the bar type "
        "selection.".format(role_label, typed_diameter_mm, bar_type_diameter_mm)
    )
    return GuardMessage(condition=condition, spec_section=DIAMETER_CONSISTENCY_SPEC_SECTION, message=message)
