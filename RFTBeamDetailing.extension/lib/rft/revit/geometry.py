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
    XYZ,
)

from .host import HostValidationError

DEFAULT_SUPPORT_SEARCH_RADIUS_MM = 300.0


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


def find_supporting_column(doc, point, to_internal_units,
                            search_radius_mm=DEFAULT_SUPPORT_SEARCH_RADIUS_MM):
    """Nearest structural column whose (plan) bounding box, expanded by
    ``search_radius_mm``, contains ``point``. Returns None if none found --
    callers must treat that as "no support detected" (S1 assumes one always
    exists; S2 handles the absence).
    """
    radius = to_internal_units(search_radius_mm)
    collector = (
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_StructuralColumns)
        .WhereElementIsNotElementType()
    )
    best, best_dist = None, None
    for column in collector:
        bbox = column.get_BoundingBox(None)
        if bbox is None:
            continue
        if not (bbox.Min.X - radius <= point.X <= bbox.Max.X + radius and
                bbox.Min.Y - radius <= point.Y <= bbox.Max.Y + radius):
            continue
        cx = (bbox.Min.X + bbox.Max.X) / 2.0
        cy = (bbox.Min.Y + bbox.Max.Y) / 2.0
        dist = ((cx - point.X) ** 2 + (cy - point.Y) ** 2) ** 0.5
        if best_dist is None or dist < best_dist:
            best, best_dist = column, dist
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

    Used for supports (``column_width_along_axis_mm``) and, since issue
    #18's review, for the BEAM itself: `b` and the section centroid have
    exactly the same rotation problem, and a 250x6000 beam at 45 deg
    otherwise measures b = 6250 mm (= b + L).

    UNVERIFIED AGAINST A LIVE HOST: whether `FamilyInstance.get_Geometry()`
    reliably yields a `GeometryInstance` wrapping symbol-space geometry for
    a structural column or beam (vs. already-transformed `Solid`s, which
    some families/`Options` combinations return directly) has not been
    confirmed without a real model. Scope limit per issue #14 review: this
    is fixed only well enough for columns and single rectangular beams;
    general support-type detection is issue #15 (S2).
    """
    options = Options()
    for geom_obj in element.get_Geometry(options):
        if isinstance(geom_obj, GeometryInstance):
            local_bbox = geom_obj.GetBoundingBox()
            if local_bbox is not None:
                return local_bbox, geom_obj.Transform
    return None, None


def column_width_along_axis_mm(column, axis_direction, from_internal_units):
    """Support width (rev 2 section 2.4): how far into the column, along
    the beam axis, a straight bar can travel.

    Preferentially measured against the column's own local bounding box
    (rotation-aware, issue #14 review finding #5) by expressing
    `axis_direction` in the column's local frame via its instance
    transform, then projecting the LOCAL (un-rotated) bbox corners --
    this is exact for a rotated rectangular column since a rectangle's
    projection onto any direction is symmetric about its centre regardless
    of in-plan rotation. Falls back to the world-axis-aligned bounding box
    only if no `GeometryInstance` can be found, which is only correct when
    the column happens to be unrotated relative to the world axes.
    """
    local_bbox, transform = _rotation_aware_local_bbox(column)
    if local_bbox is not None and transform is not None:
        return from_internal_units(_local_extent_along(local_bbox, transform, axis_direction))

    bbox = column.get_BoundingBox(None)
    if bbox is None:
        raise HostValidationError(
            "Column {} has no bounding box geometry.".format(column.Id),
            element_id=column.Id,
        )
    axis_xy = XYZ(axis_direction.X, axis_direction.Y, 0).Normalize()
    corners = _horizontal_bbox_corners(bbox)
    proj = [axis_xy.DotProduct(c) for c in corners]
    return from_internal_units(max(proj) - min(proj))


def start_support_face_point(column, beam_start_point, axis_direction, support_width_internal):
    """The point (internal units) where the beam-start support's near face
    -- the face the bar's straight leg passes through -- crosses the beam
    axis line.

    Derived from the column's own location point and its (rotation-aware)
    support width, not assumed to be the beam's `LocationCurve` endpoint
    (issue #14 review finding #2): `span_length_mm` derives `L` from the
    two columns' location points (centre-to-centre), which implies the
    beam curve typically runs column-centre to column-centre rather than
    face to face -- so `beam_start_point` itself may sit past the column's
    centre, not at its near face. A rectangular column's footprint is
    centrally symmetric, so its projection onto `axis_direction` is
    symmetric about the projected centre regardless of rotation, making
    "centre + half width" a valid face datum even under finding #5's fix.
    """
    center = column.Location.Point
    t_center = axis_direction.DotProduct(center - beam_start_point)
    t_face = t_center + support_width_internal / 2.0
    return beam_start_point + axis_direction.Multiply(t_face)


def end_support_face_point(column, beam_start_point, axis_direction, support_width_internal):
    """The point (internal units) where the beam-end support's near face
    crosses the beam axis line. Same derivation as
    `start_support_face_point`, mirrored: the near face is on the
    `-axis_direction` side of the column's centre (see that function's
    docstring for the full rationale).
    """
    center = column.Location.Point
    t_center = axis_direction.DotProduct(center - beam_start_point)
    t_face = t_center - support_width_internal / 2.0
    return beam_start_point + axis_direction.Multiply(t_face)


def point_at_cc_offset(beam_start_point, axis_direction, reference_column, offset_mm, to_internal_units):
    """A point on the beam axis line at ``offset_mm`` (mm) from
    ``reference_column``'s own centre, along ``axis_direction``.

    This is the same centre-referenced c/c datum ``span_length_mm`` and
    ``rft.core.stirrups.stirrup_zones_mm`` use (0 == the reference column's
    own centre, rev 2 section 3.1) -- so a zone's ``start``/``end`` value
    (mm) can be turned directly into a 3D point without re-deriving the
    datum. Same centre-projection technique as
    ``start_support_face_point``/``end_support_face_point``.
    """
    center = reference_column.Location.Point
    t_center = axis_direction.DotProduct(center - beam_start_point)
    t_target = t_center + to_internal_units(offset_mm)
    return beam_start_point + axis_direction.Multiply(t_target)


def span_length_mm(column_a, column_b, from_internal_units):
    """L = centreline-to-centreline distance between supports (rev 2
    section 1, A6), taken between the two columns' location points.
    """
    pa = column_a.Location.Point
    pb = column_b.Location.Point
    dist = ((pa.X - pb.X) ** 2 + (pa.Y - pb.Y) ** 2) ** 0.5
    return from_internal_units(dist)
