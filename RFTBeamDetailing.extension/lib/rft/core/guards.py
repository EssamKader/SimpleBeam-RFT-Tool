"""Out-of-scope configuration guards (S9): continuous-run detection, the
cantilever/free-end warning, and the stirrup type 3 rejection.

Pure Python: no Revit imports. This module owns the POLICY every guard
enforces -- classification thresholds and message text, each carrying its
triggering condition and rev 2 spec section so no call site can emit a bare
failure. It does not detect anything itself: `rft.revit.guards` does the
Revit-side reads (a beam's/neighbour's own axis, a beam end's support) and
calls into this module to interpret and phrase the result.

Rev 2 section 9 item 2 (A39, multi-span deferred), section 2.4 (a beam
framing into a girder is still a single span), section 2.5 (A14, cantilever/
free ends), section 7.2 (A31, stirrup type 3 parked).
"""

import math
from collections import namedtuple

from .anchorage import free_end_configuration_warning
from .stirrups import TYPE3_PARKED_MESSAGE

GuardMessage = namedtuple("GuardMessage", ["condition", "spec_section", "message"])

CONTINUOUS_RUN_SPEC_SECTION = "rev 2 section 9 item 2 (A39)"
FREE_END_SPEC_SECTION = "rev 2 section 2.5 (A14)"
STIRRUP_TYPE3_SPEC_SECTION = "rev 2 section 7.2 (A31), residual question R6"
NO_SUPPORT_SPEC_SECTION = "rev 2 section 2.4/2.5 (A9, A12, A14)"

# Angle, in degrees, at or ABOVE which a neighbouring structural-framing
# element's own axis is treated as COLLINEAR with the beam being detailed
# (a continuous run) rather than TRANSVERSE (a girder support, rev 2 section
# 2.4 -- a valid single span). Rev 2 gives NO angular tolerance for this --
# this constant is THIS TICKET'S OWN DESIGN CHOICE, not a spec rule, exactly
# like `DEFAULT_SUPPORT_SEARCH_RADIUS_MM` in `rft.revit.geometry`.
#
# Chosen at 45 degrees, the natural midpoint between "clearly collinear"
# (0 deg from collinear) and "clearly transverse" (90 deg from collinear).
# An angle of EXACTLY 45 degrees is resolved toward CONTINUOUS, not
# transverse (see `classify_neighbour_axis`'s `>=` comparison): this guard
# exists specifically to prevent the dangerous failure mode -- a continuous
# beam silently detailed as simply supported, missing the hogging steel it
# needs over the shared support -- so an ambiguous angle is deliberately
# biased toward the refusal, not the permissive path. The cost of a
# false-positive refusal (the engineer re-checks and confirms it really is
# a girder) is far lower than a false-negative pass-through.
CONTINUOUS_RUN_ANGLE_THRESHOLD_DEG = 45.0
CONTINUOUS_RUN_AXIS_DOT_TOLERANCE = math.cos(math.radians(CONTINUOUS_RUN_ANGLE_THRESHOLD_DEG))

# Maximum perpendicular distance, in millimetres, between the beam's own
# axis LINE and a neighbouring framing element, for that neighbour to count
# as lying on the SAME line rather than merely running the same way.
#
# Collinear means same direction AND same line. Testing direction alone
# (issue #22 review) refuses a beam that merely has a PARALLEL neighbour
# nearby -- twin beams a couple of hundred millimetres apart, an edge beam
# alongside a floor beam -- since the search is a bounding-box proximity
# test around the beam end and a parallel neighbour scores abs(dot) = 1.
# Those are valid single spans, and refusing them with the message "this
# beam is part of a continuous run" would be both wrong and confusing.
#
# Rev 2 gives NO tolerance for this either -- 50 mm is THIS TICKET'S OWN
# DESIGN CHOICE, like the angular threshold above: loose enough to absorb
# real modelling slop where a continuation is meant to be on-axis, far
# tighter than any plausible spacing between two deliberately separate
# parallel members.
CONTINUOUS_RUN_LATERAL_TOLERANCE_MM = 50.0


def is_on_same_axis_line(lateral_offset_mm):
    """Whether a neighbour's measured perpendicular offset from the beam's
    own axis line is small enough to be the SAME line (a continuation)
    rather than a separate parallel member.

    ``lateral_offset_mm`` comes from
    `rft.revit.guards.neighbour_lateral_offset_mm`; this function only
    applies the policy tolerance so it stays Revit-free.
    """
    return abs(lateral_offset_mm) <= CONTINUOUS_RUN_LATERAL_TOLERANCE_MM


NeighbourAxisClassification = namedtuple(
    "NeighbourAxisClassification",
    ["is_continuous", "axis_dot_abs", "angle_from_collinear_deg"],
)


def classify_neighbour_axis(axis_dot_product):
    """Classify a neighbouring structural-framing element's axis relative to
    the beam being detailed (rev 2 section 2.4/section 9 item 2).

    ``axis_dot_product`` is the dot product of the BEAM's own normalised
    axis direction and the NEIGHBOUR's own normalised axis direction --
    both unit vectors read from each element's own location curve (see
    `rft.revit.guards.neighbour_axis_dot_product`). This function takes the
    already-computed scalar so it stays Revit-free and independently
    testable; it does not know or care where the dot product came from.

    abs(dot) near 1 (parallel OR anti-parallel -- a beam continuing past a
    support points the "same way" only if traversed consistently start to
    end, so BOTH signs must count as collinear) means COLLINEAR ->
    CONTINUOUS RUN. abs(dot) near 0 means PERPENDICULAR -> TRANSVERSE
    GIRDER SUPPORT, a valid single-span configuration.
    """
    axis_dot_abs = min(abs(axis_dot_product), 1.0)
    angle_from_collinear_deg = math.degrees(math.acos(axis_dot_abs))
    is_continuous = axis_dot_abs >= CONTINUOUS_RUN_AXIS_DOT_TOLERANCE
    return NeighbourAxisClassification(
        is_continuous=is_continuous,
        axis_dot_abs=axis_dot_abs,
        angle_from_collinear_deg=angle_from_collinear_deg,
    )


def continuous_run_guard_message(end_label, angle_from_collinear_deg):
    """REFUSAL message (rev 2 section 9 item 2, A39) for a beam end where a
    collinear neighbouring beam was detected -- a continuous run, not a
    single span, regardless of whether a column or wall is ALSO present at
    that end (the dangerous case this guard exists for: two collinear
    beams meeting at a shared column is still a continuous beam needing
    hogging steel over that support).

    A39 explicitly permits either "warn on" or "refuse" a continuous run.
    REFUSE is chosen here -- this ticket's own policy choice under that
    explicit latitude, not a spec mandate -- because this story's whole
    rationale is never handing the engineer plausible-looking detailing for
    a configuration the tool did not model, and because stirrup type 3
    (the other v1-scope gap) is already REJECTED outright rather than
    merely warned. Reverting this one call to a warning is a one-line
    change if the project owner prefers that instead.
    """
    condition = "{}: collinear neighbouring beam detected -- continuous run, not a single span".format(
        end_label
    )
    message = (
        "{}: REFUSED -- this beam is part of a CONTINUOUS RUN, not a "
        "single span ({}). A neighbouring structural-framing element's own "
        "axis is collinear with this beam's -- same direction, {:.1f} "
        "degrees from exactly collinear, AND on the same axis line within "
        "{:.0f} mm (both tolerances are this ticket's own design choices, "
        "not spec rules). "
        "Multi-span behaviour remains out of scope for v1 -- detailing "
        "this beam as simply supported would omit the hogging "
        "reinforcement a continuous beam needs over this support, even "
        "though a column or wall may also be present at this end. To "
        "proceed: reclassify or remove the neighbouring element, or wait "
        "for multi-span support.".format(
            end_label, CONTINUOUS_RUN_SPEC_SECTION, angle_from_collinear_deg,
            CONTINUOUS_RUN_LATERAL_TOLERANCE_MM,
        )
    )
    return GuardMessage(condition=condition, spec_section=CONTINUOUS_RUN_SPEC_SECTION, message=message)


def free_end_guard_message(end_label):
    """WARNING (rev 2 section 2.5, A14) for a cantilever/free beam end --
    reuses `rft.core.anchorage.free_end_configuration_warning` rather than
    reimplementing its text; only adds the end label and the
    condition/spec-section fields this ticket's guard-result shape
    requires.
    """
    condition = "{}: no support detected -- cantilever/free end".format(end_label)
    message = "{}: {}".format(end_label, free_end_configuration_warning())
    return GuardMessage(condition=condition, spec_section=FREE_END_SPEC_SECTION, message=message)


def stirrup_type3_guard_message():
    """REJECTION (rev 2 section 7.2, A31) for stirrup closure type 3 --
    reuses `rft.core.stirrups.TYPE3_PARKED_MESSAGE` rather than
    reimplementing its text.
    """
    return GuardMessage(
        condition="stirrup closure type 3 requested -- parked, inner loop undefined",
        spec_section=STIRRUP_TYPE3_SPEC_SECTION,
        message=TYPE3_PARKED_MESSAGE,
    )


def no_support_detected_message(end_label):
    """REFUSAL for a beam end with NO detectable support at all (neither a
    column, wall nor girder), used by pushbuttons that do not implement the
    unsupported-end anchorage path (rev 2 section 2.5/A12's straight-run,
    no-hook case) and so cannot proceed at all -- distinct from
    `free_end_guard_message`, which WARNS and proceeds where that path IS
    implemented.
    """
    condition = "{}: no support (column, wall or girder) detected at all".format(end_label)
    message = (
        "{}: no supporting element (column, wall or girder) detected ({}). "
        "This pushbutton does not implement the unsupported-end, no-hook "
        "anchorage path -- a straight bar to beam end - cover requires the "
        "full end-anchorage treatment (rev 2 section 2.5, A12/R3), which "
        "only 'Place Main Bars.pushbutton' carries. Either a support must "
        "be detected here, or this beam must be detailed with that "
        "pushbutton instead.".format(end_label, NO_SUPPORT_SPEC_SECTION)
    )
    return GuardMessage(condition=condition, spec_section=NO_SUPPORT_SPEC_SECTION, message=message)
