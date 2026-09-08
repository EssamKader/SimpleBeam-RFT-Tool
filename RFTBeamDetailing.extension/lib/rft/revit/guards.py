"""Revit-side detection for the S9 out-of-scope configuration guards.

Detection only -- the policy (collinear-vs-transverse threshold, refuse-vs-
warn choice, message text) lives entirely in `rft.core.guards`, which this
module calls into. Kept as its own module rather than folded into
`rft.revit.geometry`: `geometry.py` is generic geometry reads used by every
story (S1-S8); this module is guard-specific policy wiring used only by S9,
and keeping it separate means a future change to guard behaviour never
touches the geometry-reading functions every other story depends on.

Rev 2 section 2.4/section 9 item 2 (A39): a beam framing into a girder is a
valid single span, not a continuous run -- the discriminator is ANGULAR
(collinear vs. transverse), not categorical (the neighbour is found via the
SAME `OST_StructuralFraming` category regardless of which way it turns out
to be classified).
"""

import math

from Autodesk.Revit.DB import BuiltInCategory, FilteredElementCollector

from rft.core.guards import (
    classify_neighbour_axis,
    continuous_run_guard_message,
    is_on_same_axis_line,
)

from .geometry import DEFAULT_SUPPORT_SEARCH_RADIUS_MM, beam_axis_direction, beam_endpoints
from .units import internal_to_mm


def neighbour_axis_dot_product(beam, neighbour):
    """Dot product of the BEAM's own normalised axis direction and the
    NEIGHBOUR's own normalised axis direction, each read from ITS OWN
    `Location.Curve` via `beam_axis_direction` -- never the beam's axis
    reused twice, and never a datum other than each element's own location
    curve (the recurring "wrong reference" bug class this project has hit
    three times already: cover face, centroid vs. location curve, pre-cap
    vs. as-built).

    SHAPE UNVERIFIED: assumes a neighbouring `OST_StructuralFraming`
    element (a beam or girder) exposes `Location.Curve` the same way the
    beam being detailed does. `beam_axis_direction`/`beam_endpoints`
    already carry this assumption for the beam itself (see
    `rft/revit/geometry.py`); this is the first place it is relied on for
    a SECOND, independently-picked framing element, and that has not been
    confirmed against a live host either.
    """
    return beam_axis_direction(beam).DotProduct(beam_axis_direction(neighbour))


def neighbour_lateral_offset_mm(beam, neighbour, point):
    """Perpendicular distance (mm) from the BEAM's own axis LINE to the
    neighbour endpoint nearest ``point`` (the beam end being checked).

    Direction alone does not make a neighbour collinear -- a parallel beam
    a few hundred millimetres away scores abs(dot) = 1 and is a perfectly
    valid separate member (issue #22 review). This measures the other half
    of "collinear": whether the neighbour is on the same LINE, not merely
    pointing the same way.

    Measured from the beam's own start point along its own axis direction,
    both read from the beam's own location curve -- never the neighbour's
    frame, and never a bounding-box centre.
    """
    axis = beam_axis_direction(beam)
    origin = beam_endpoints(beam)[0]

    nearest = None
    nearest_distance = None
    for candidate in beam_endpoints(neighbour):
        delta = candidate - point
        distance = math.sqrt(delta.DotProduct(delta))
        if nearest_distance is None or distance < nearest_distance:
            nearest, nearest_distance = candidate, distance

    to_endpoint = nearest - origin
    along = axis.DotProduct(to_endpoint)
    perpendicular = to_endpoint - axis.Multiply(along)
    return internal_to_mm(math.sqrt(perpendicular.DotProduct(perpendicular)))


def find_continuous_run_neighbour(doc, beam, point, to_internal_units,
                                    exclude_element_id=None,
                                    search_radius_mm=DEFAULT_SUPPORT_SEARCH_RADIUS_MM):
    """Any `OST_StructuralFraming` element near ``point`` (a beam end) whose
    own axis is COLLINEAR with ``beam``'s (rev 2 section 2.4/section 9 item
    2, A39). Returns the first such neighbour, or ``None``.

    Deliberately a SEPARATE search from `rft.revit.geometry.
    find_supporting_element`, not a re-use of whichever single support that
    function selects for anchorage width: a beam end can have BOTH a column
    (the nearest bounding-box centre, and so the element
    `find_supporting_element` returns) AND a collinear neighbouring beam at
    the very same end -- two collinear beams meeting at a shared column is
    still a continuous run. Gating this check on `find_supporting_element`'s
    winner would silently miss that case whenever the column wins the
    proximity contest, which is exactly the dangerous configuration this
    guard exists to catch.

    Only `OST_StructuralFraming` is searched (never columns or walls): a
    column's `Location.Point` and a wall's `Location.Curve` both carry no
    meaningful "does this run collinear with the beam" question the way a
    beam or girder's own long axis does.
    """
    radius = to_internal_units(search_radius_mm)
    collector = (
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_StructuralFraming)
        .WhereElementIsNotElementType()
    )
    for element in collector:
        if exclude_element_id is not None and element.Id == exclude_element_id:
            continue
        bbox = element.get_BoundingBox(None)
        if bbox is None:
            continue
        if not (bbox.Min.X - radius <= point.X <= bbox.Max.X + radius and
                bbox.Min.Y - radius <= point.Y <= bbox.Max.Y + radius):
            continue
        classification = classify_neighbour_axis(neighbour_axis_dot_product(beam, element))
        if not classification.is_continuous:
            continue
        # Same direction is only half of collinear -- it must also be on the
        # same line, or a parallel neighbour is refused as a continuous run
        # (issue #22 review).
        if not is_on_same_axis_line(neighbour_lateral_offset_mm(beam, element, point)):
            continue
        return element
    return None


def continuous_run_guard(doc, beam, point, to_internal_units, end_label,
                          exclude_element_id=None,
                          search_radius_mm=DEFAULT_SUPPORT_SEARCH_RADIUS_MM):
    """Run the continuous-run guard at one beam end. Returns a
    ``rft.core.guards.GuardMessage`` (refusal) if this end has a collinear
    neighbouring beam, else ``None``. Callers must run this BEFORE any
    placement work, and must call it once per end (independently) -- an end
    span of a continuous run has a collinear neighbour at only ONE end.
    """
    neighbour = find_continuous_run_neighbour(
        doc, beam, point, to_internal_units, exclude_element_id, search_radius_mm
    )
    if neighbour is None:
        return None
    classification = classify_neighbour_axis(neighbour_axis_dot_product(beam, neighbour))
    return continuous_run_guard_message(end_label, classification.angle_from_collinear_deg)
