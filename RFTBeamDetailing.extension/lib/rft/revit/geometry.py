# -*- coding: utf-8 -*-
"""Reads beam and support geometry from the model. No detailing math here --
only Revit reads, converted to mm at the return boundary via the caller-
supplied ``from_internal_units``/``to_internal_units`` (``rft.revit.units``).

Rev 2 section 1 (b, h, L / A6), section 2.4 (support width / A9).

UNVERIFIED AGAINST A LIVE HOST: docs/research/revit-api-strategy.md does not
cover support detection at all (it scopes unit boundary, rebar creation,
bend radius, host prerequisites, rebar sets and transactions -- not "how do
I find the column at a beam's end"). The approach below -- bounding-box
proximity in plan to the beam's end point -- is this ticket's own design
choice, not a settled research finding, and is untested against a real
model. See docs/verification/s1-tracer-bullet.md.
"""

from Autodesk.Revit.DB import (
    BuiltInCategory,
    FilteredElementCollector,
    GeometryInstance,
    Options,
    Wall,
    XYZ,
)

from .host import HostValidationError

DEFAULT_SUPPORT_SEARCH_RADIUS_MM = 300.0

# rev 2 section 2.4, A9: any structural support -- column, wall or girder.
# A girder is itself Structural Framing, the SAME category the beam being
# detailed belongs to -- callers must pass `exclude_element_id` to avoid a
# beam finding itself.
SUPPORT_CATEGORIES = (
    BuiltInCategory.OST_StructuralColumns,
    BuiltInCategory.OST_Walls,
    BuiltInCategory.OST_StructuralFraming,
)


def beam_endpoints(beam):
    """(start, end) XYZ points of the beam's location curve, internal units."""
    curve = beam.Location.Curve
    return curve.GetEndPoint(0), curve.GetEndPoint(1)


def beam_axis_direction(beam):
    start, end = beam_endpoints(beam)
    return (end - start).Normalize()


def _horizontal_bbox_corners(bbox):
    return [
        XYZ(bbox.Min.X, bbox.Min.Y, 0),
        XYZ(bbox.Max.X, bbox.Min.Y, 0),
        XYZ(bbox.Min.X, bbox.Max.Y, 0),
        XYZ(bbox.Max.X, bbox.Max.Y, 0),
    ]


def beam_section_axes(beam):
    """(u_dir, v_dir): the cross-section's own width and height unit
    vectors -- u horizontal and perpendicular to the beam axis, v vertical.

    The single definition of the section frame, so every caller that maps
    ``rft.core``'s centroid-local (u, v) millimetre coordinates into the
    model uses the same one. Horizontal beams only, per rev 2 scope
    (A6/§1).
    """
    axis = beam_axis_direction(beam)
    return XYZ(-axis.Y, axis.X, 0).Normalize(), XYZ.BasisZ


def beam_section_dimensions_mm(beam, from_internal_units):
    """(b, h) in mm: b is the section's extent perpendicular to the beam's
    own axis (plan width), h is the vertical (Z) extent. Read from the
    bounding box rather than a family parameter so it does not depend on a
    specific family's parameter naming -- rectangular sections only, per
    rev 2 scope (A6/§1).

    Measured against the beam's own LOCAL bounding box (rotation-aware,
    issue #18 review finding #2), because `get_BoundingBox(None)` is
    world-axis-aligned: projecting that onto the perpendicular direction
    returns b + L for a beam at 45 deg -- a 250 mm wide, 6000 mm long beam
    measures 6250 mm. Falls back to the world AABB only when no
    `GeometryInstance` is available, which is correct only for a beam
    parallel to a project axis.
    """
    u_dir, _v_dir = beam_section_axes(beam)

    local_bbox, transform = _rotation_aware_local_bbox(beam)
    if local_bbox is not None and transform is not None:
        b_internal = _local_extent_along(local_bbox, transform, u_dir)
        h_internal = local_bbox.Max.Z - local_bbox.Min.Z
        return from_internal_units(b_internal), from_internal_units(h_internal)

    bbox = beam.get_BoundingBox(None)
    if bbox is None:
        raise HostValidationError(
            "Beam {} has no bounding box geometry.".format(beam.Id),
            element_id=beam.Id,
        )
    corners = _horizontal_bbox_corners(bbox)
    proj = [u_dir.DotProduct(c) for c in corners]
    b_internal = max(proj) - min(proj)
    h_internal = bbox.Max.Z - bbox.Min.Z
    return from_internal_units(b_internal), from_internal_units(h_internal)


def beam_section_centre_offsets(beam, station_point):
    """(du, dv), internal units: the offset from ``station_point`` -- any
    point on the beam's LOCATION CURVE -- to the section centroid,
    resolved in the section's own (u, v) axes (``beam_section_axes``).

    A beam's location curve is NOT its section centroid. Revit's structural
    framing justification parameters (z-Direction Justification defaults to
    **Top** for beams, plus y-Direction Justification and the offset
    values) shift the solid relative to the placement line. So any shape
    built centred on the location curve -- a stirrup rectangle, or any bar
    coordinate arriving from ``rft.core`` in centroid-local (u, v) mm --
    lands off the beam: by h/2, i.e. 300 mm on a 600 mm deep beam, in the
    default top-justified case (issue #18 review finding #1).

    Derived from the SAME bounding box ``beam_section_dimensions_mm`` reads
    b and h from, so the centroid can never disagree with the section
    dimensions it is paired with, and rotation-aware by the same path.

    UNVERIFIED AGAINST A LIVE HOST: a bounding box can be enlarged by
    joined or attached geometry, in which case its centre is not the
    section centroid. Reading the justification parameters directly would
    be exact, but assumes a parameter set that cannot be confirmed here --
    see docs/verification/s1-tracer-bullet.md.
    """
    u_dir, _v_dir = beam_section_axes(beam)

    local_bbox, transform = _rotation_aware_local_bbox(beam)
    if local_bbox is not None and transform is not None:
        centre = transform.OfPoint(
            XYZ(
                (local_bbox.Min.X + local_bbox.Max.X) / 2.0,
                (local_bbox.Min.Y + local_bbox.Max.Y) / 2.0,
                (local_bbox.Min.Z + local_bbox.Max.Z) / 2.0,
            )
        )
    else:
        bbox = beam.get_BoundingBox(None)
        if bbox is None:
            raise HostValidationError(
                "Beam {} has no bounding box geometry.".format(beam.Id),
                element_id=beam.Id,
            )
        centre = XYZ(
            (bbox.Min.X + bbox.Max.X) / 2.0,
            (bbox.Min.Y + bbox.Max.Y) / 2.0,
            (bbox.Min.Z + bbox.Max.Z) / 2.0,
        )

    # u_dir is horizontal, so a vertical difference cannot leak into du;
    # v_dir is BasisZ, so dv is the plain Z difference. The along-axis
    # component of `centre` is deliberately unused -- the station point
    # already fixes the position along the span.
    du = u_dir.DotProduct(centre - station_point)
    dv = centre.Z - station_point.Z
    return du, dv


def find_supporting_element(doc, point, to_internal_units, exclude_element_id=None,
                             search_radius_mm=DEFAULT_SUPPORT_SEARCH_RADIUS_MM):
    """Nearest structural support -- column, wall or girder -- whose (plan)
    bounding box, expanded by ``search_radius_mm``, contains ``point`` (rev
    2 section 2.4, A9). Returns None if none found -- callers must treat
    that as the unsupported/free-end path (rev 2 section 2.5, S2).

    ``exclude_element_id`` lets a caller exclude the beam being detailed
    itself: a girder search uses ``OST_StructuralFraming``, the SAME
    category the beam itself belongs to, so without this the beam could
    find itself as its own "support".

    Generalises S1's column-only ``find_supporting_column`` (renamed).
    Searched across all three support categories, nearest bounding-box
    centre wins across categories, same distance metric as before.
    """
    radius = to_internal_units(search_radius_mm)
    best, best_dist = None, None
    for category in SUPPORT_CATEGORIES:
        collector = (
            FilteredElementCollector(doc)
            .OfCategory(category)
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
            cx = (bbox.Min.X + bbox.Max.X) / 2.0
            cy = (bbox.Min.Y + bbox.Max.Y) / 2.0
            dist = ((cx - point.X) ** 2 + (cy - point.Y) ** 2) ** 0.5
            if best_dist is None or dist < best_dist:
                best, best_dist = element, dist
    return best


def _local_bbox_corners_xy(local_bbox):
    return [
        (local_bbox.Min.X, local_bbox.Min.Y),
        (local_bbox.Max.X, local_bbox.Min.Y),
        (local_bbox.Min.X, local_bbox.Max.Y),
        (local_bbox.Max.X, local_bbox.Max.Y),
    ]


def _local_extent_along(local_bbox, transform, world_direction):
    """Extent of a local (un-rotated) plan bounding box along a WORLD
    direction: express the direction in the element's local frame via its
    instance transform, then project the local corners. Exact for a
    rectangle at any in-plan rotation, since a rectangle's projection onto
    any direction is symmetric about its centre.
    """
    local_x = world_direction.DotProduct(transform.BasisX)
    local_y = world_direction.DotProduct(transform.BasisY)
    proj = [local_x * cx + local_y * cy for cx, cy in _local_bbox_corners_xy(local_bbox)]
    return max(proj) - min(proj)


def _rotation_aware_local_bbox(element):
    """The element's own local (un-rotated) bounding box and its instance
    transform to world space, extracted via its `GeometryInstance`
    (issue #14 review finding #5): `Element.get_BoundingBox(None)` is
    always WORLD-axis-aligned, so projecting it onto a direction that is
    not a project axis overstates a rotated element's footprint (a 600x600
    column at 45 deg measures ~849 mm that way). Returns
    (local_bbox, transform), or (None, None) if no `GeometryInstance` is
    found, in which case the caller falls back to the (rotation-unsafe)
    AABB.

    Used for supports (``support_width_along_axis_mm``, columns and
    girders -- walls take a separate ``Wall.Width`` path, no bounding box
    needed) and, since issue #18's review, for the BEAM itself: `b` and
    the section centroid have
    exactly the same rotation problem, and a 250x6000 beam at 45 deg
    otherwise measures b = 6250 mm (= b + L).

    UNVERIFIED AGAINST A LIVE HOST: whether `FamilyInstance.get_Geometry()`
    reliably yields a `GeometryInstance` wrapping symbol-space geometry for
    a structural column, girder or beam (vs. already-transformed `Solid`s,
    which some families/`Options` combinations return directly) has not
    been confirmed without a real model. Issue #15 (S2) reuses this
    unchanged for girders (same category shape as a column/beam, a
    `FamilyInstance`); it does NOT apply to walls, which take the separate
    `Wall.Width` path in `support_width_along_axis_mm` and never call this.
    """
    options = Options()
    for geom_obj in element.get_Geometry(options):
        if isinstance(geom_obj, GeometryInstance):
            local_bbox = geom_obj.GetBoundingBox()
            if local_bbox is not None:
                return local_bbox, geom_obj.Transform
    return None, None


def support_width_along_axis_mm(support, axis_direction, from_internal_units):
    """Support width (rev 2 section 2.4, A9): how far into the support,
    along the beam axis, a straight bar can travel. Generalises S1's
    column-only ``column_width_along_axis_mm`` (renamed) to any structural
    support -- column, wall or girder.

    WALL: support width = wall thickness (``Wall.Width``), regardless of
    the beam's incidence angle (R5, resolved). Deliberately conservative:
    understates embedment for an oblique beam, giving a shorter `a` and a
    longer bend `b` -- do not "improve" this into a swept-intersection
    length.

    SHAPE UNVERIFIED: ``Wall.Width`` -- assumed to be a read-only property
    returning the wall's total thickness in internal units (feet). Not
    confirmed against a live host; see tests/fake_revit_api.py header.

    COLUMN OR GIRDER: measured against the support's own local bounding
    box (rotation-aware, issue #14 review finding #5) by expressing
    `axis_direction` in the support's local frame via its instance
    transform, then projecting the LOCAL (un-rotated) bbox corners --
    this is exact for a rotated rectangular support since a rectangle's
    projection onto any direction is symmetric about its centre regardless
    of in-plan rotation. This is the SAME projection
    (``_local_extent_along``) used for columns, reused unchanged for a
    girder -- not a second projection. Falls back to the world-axis-aligned
    bounding box only if no `GeometryInstance` can be found, which is only
    correct when the support happens to be unrotated relative to the world
    axes.
    """
    if isinstance(support, Wall):
        return from_internal_units(support.Width)

    local_bbox, transform = _rotation_aware_local_bbox(support)
    if local_bbox is not None and transform is not None:
        return from_internal_units(_local_extent_along(local_bbox, transform, axis_direction))

    bbox = support.get_BoundingBox(None)
    if bbox is None:
        raise HostValidationError(
            "Support {} has no bounding box geometry.".format(support.Id),
            element_id=support.Id,
        )
    axis_xy = XYZ(axis_direction.X, axis_direction.Y, 0).Normalize()
    corners = _horizontal_bbox_corners(bbox)
    proj = [axis_xy.DotProduct(c) for c in corners]
    return from_internal_units(max(proj) - min(proj))


def support_reference_point(support):
    """The support's own reference point, used as the centre datum for
    face-point / c/c-span derivations (rev 2 section 2.4, A9).

    A column exposes ``Location.Point`` directly. A wall or girder's
    ``Location`` is typically a ``LocationCurve`` instead -- this falls
    back to that curve's midpoint, since callers only ever project this
    point onto the beam axis via ``DotProduct`` (the same "centre + half
    width" symmetric-footprint reasoning `start_support_face_point` already
    relies on for columns applies equally to a girder's or wall's own
    length datum).

    SHAPE UNVERIFIED / DESIGN CHOICE: whether a girder or wall instance
    exposes ``Location.Point`` or ``Location.Curve`` was not confirmed
    against a live host, and "curve midpoint as reference centre" is this
    ticket's own engineering choice, not a rev 2 rule -- flagged in this
    ticket's report.
    """
    location = support.Location
    point = getattr(location, "Point", None)
    if point is not None:
        return point
    curve = getattr(location, "Curve", None)
    if curve is not None:
        p0, p1 = curve.GetEndPoint(0), curve.GetEndPoint(1)
        return XYZ((p0.X + p1.X) / 2.0, (p0.Y + p1.Y) / 2.0, (p0.Z + p1.Z) / 2.0)
    raise HostValidationError(
        "Support {} has neither Location.Point nor Location.Curve; cannot "
        "derive its reference point (rev 2 section 2.4).".format(support.Id),
        element_id=support.Id,
    )


def start_support_face_point(support, beam_start_point, axis_direction, support_width_internal):
    """The point (internal units) where the beam-start support's near face
    -- the face the bar's straight leg passes through -- crosses the beam
    axis line.

    Derived from the support's own reference point (``support_reference_
    point``) and its (rotation-aware) support width, not assumed to be the
    beam's `LocationCurve` endpoint (issue #14 review finding #2):
    `span_length_mm` derives `L` from the two supports' reference points
    (centre-to-centre), which implies the beam curve typically runs
    support-centre to support-centre rather than face to face -- so
    `beam_start_point` itself may sit past the support's centre, not at its
    near face. A rectangular support's footprint is centrally symmetric,
    so its projection onto `axis_direction` is symmetric about the
    projected centre regardless of rotation, making "centre + half width"
    a valid face datum even under finding #5's fix.
    """
    center = support_reference_point(support)
    t_center = axis_direction.DotProduct(center - beam_start_point)
    t_face = t_center + support_width_internal / 2.0
    return beam_start_point + axis_direction.Multiply(t_face)


def end_support_face_point(support, beam_start_point, axis_direction, support_width_internal):
    """The point (internal units) where the beam-end support's near face
    crosses the beam axis line. Same derivation as
    `start_support_face_point`, mirrored: the near face is on the
    `-axis_direction` side of the support's reference point (see that
    function's docstring for the full rationale).
    """
    center = support_reference_point(support)
    t_center = axis_direction.DotProduct(center - beam_start_point)
    t_face = t_center - support_width_internal / 2.0
    return beam_start_point + axis_direction.Multiply(t_face)


def point_at_cc_offset(beam_start_point, axis_direction, reference_support, offset_mm, to_internal_units):
    """A point on the beam axis line at ``offset_mm`` (mm) from
    ``reference_support``'s own reference point, along ``axis_direction``.

    This is the same centre-referenced c/c datum ``span_length_mm`` and
    ``rft.core.stirrups.stirrup_zones_mm`` use (0 == the reference
    support's own reference point, rev 2 section 3.1) -- so a zone's
    ``start``/``end`` value (mm) can be turned directly into a 3D point
    without re-deriving the datum. Same centre-projection technique as
    ``start_support_face_point``/``end_support_face_point``.
    """
    center = support_reference_point(reference_support)
    t_center = axis_direction.DotProduct(center - beam_start_point)
    t_target = t_center + to_internal_units(offset_mm)
    return beam_start_point + axis_direction.Multiply(t_target)


def span_length_mm(support_a, support_b, from_internal_units):
    """L = centreline-to-centreline distance between supports (rev 2
    section 1, A6), taken between the two supports' reference points.
    """
    pa = support_reference_point(support_a)
    pb = support_reference_point(support_b)
    dist = ((pa.X - pb.X) ** 2 + (pa.Y - pb.Y) ** 2) ** 0.5
    return from_internal_units(dist)
