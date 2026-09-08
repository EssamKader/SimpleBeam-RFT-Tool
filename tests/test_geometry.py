"""Mock-object verification for `rft.revit.geometry`'s support-face and
rotation-aware width derivations (issue #14 review findings #2 and #5).

Not previously covered by the mock suite (docs/verification/s1-tracer-bullet.md
flagged column-detection/bounding-box math as an untested gap) -- these
functions are geometrically pure enough (given fake XYZ/transform/bbox
stand-ins) to exercise the real adapter logic here, same pattern as
test_mock_revit_adapter.py.
"""

import math

import pytest

from fake_revit_api import FakeFilteredElementCollector, FakeGeometryInstance, FakeWall, FakeXYZ

from rft.revit.geometry import (
    beam_section_centre_offsets,
    beam_section_dimensions_mm,
    end_support_face_point,
    find_supporting_element,
    point_at_cc_offset,
    start_support_face_point,
    support_reference_point,
    support_width_along_axis_mm,
)


class _LocalBBox(object):
    def __init__(self, min_xy, max_xy, min_z=0, max_z=0):
        self.Min = FakeXYZ(min_xy[0], min_xy[1], min_z)
        self.Max = FakeXYZ(max_xy[0], max_xy[1], max_z)


class _Transform(object):
    def __init__(self, basis_x, basis_y, basis_z=None, origin=None):
        self.BasisX = basis_x
        self.BasisY = basis_y
        self.BasisZ = basis_z or FakeXYZ(0, 0, 1)
        self.Origin = origin or FakeXYZ(0, 0, 0)

    def OfPoint(self, point):
        return (
            self.Origin
            + self.BasisX.Multiply(point.X)
            + self.BasisY.Multiply(point.Y)
            + self.BasisZ.Multiply(point.Z)
        )


class _Curve(object):
    def __init__(self, start, end):
        self._points = (start, end)

    def GetEndPoint(self, index):
        return self._points[index]


class _LocationCurve(object):
    def __init__(self, start, end):
        self.Curve = _Curve(start, end)


class _Beam(object):
    """Beam stand-in: a location curve (which fixes the axis, and therefore
    the section's u/v frame) plus optional local geometry and a world AABB.
    """

    def __init__(self, start, end, geometry_instances=None, world_bbox=None):
        self.Location = _LocationCurve(start, end)
        self.Id = 1234
        self._geometry_instances = geometry_instances or []
        self._world_bbox = world_bbox

    def get_Geometry(self, _options):
        return self._geometry_instances

    def get_BoundingBox(self, _view):
        return self._world_bbox


class _LocationPoint(object):
    def __init__(self, point):
        self.Point = point


class _Column(object):
    def __init__(self, location_point, geometry_instances=None):
        self.Location = _LocationPoint(location_point)
        self._geometry_instances = geometry_instances or []

    def get_Geometry(self, _options):
        return self._geometry_instances

    def get_BoundingBox(self, _view):
        return None


def test_start_support_face_point_is_half_width_toward_the_span():
    """Beam axis along world X; column centred 500 mm behind the beam
    start point (as it would be if the beam curve's endpoint sits at the
    column's centreline, finding #2). The near face is half the support
    width further along +axis_direction, toward the beam."""
    beam_start = FakeXYZ(0, 0, 0)
    axis = FakeXYZ(1, 0, 0)
    column_center = FakeXYZ(-500, 0, 0)
    column = _Column(location_point=column_center)

    face = start_support_face_point(column, beam_start, axis, support_width_internal=600)

    assert face.X == -500 + 300
    assert face.Y == 0


def test_end_support_face_point_is_half_width_toward_the_span():
    """Mirror of the start case: the beam-end support's near face is half
    the support width BACK toward the span (-axis_direction) from its
    centre."""
    beam_start = FakeXYZ(0, 0, 0)
    axis = FakeXYZ(1, 0, 0)
    column_center = FakeXYZ(6500, 0, 0)
    column = _Column(location_point=column_center)

    face = end_support_face_point(column, beam_start, axis, support_width_internal=600)

    assert face.X == 6500 - 300


def test_point_at_cc_offset_is_measured_from_the_reference_columns_centre():
    """issue #18 (S5): a zone's c/c-datum offset (mm) must land at the
    SAME point ``span_length_mm``/``stirrup_zones_mm`` treat as 0 -- the
    reference column's own centre, not the beam curve's endpoint (mirrors
    finding #2 from issue #14's review, reused here for zone origins)."""
    beam_start = FakeXYZ(0, 0, 0)
    axis = FakeXYZ(1, 0, 0)
    column_center = FakeXYZ(-500, 0, 0)
    column = _Column(location_point=column_center)

    def to_internal(mm):
        return mm  # identity: internal units == mm for this test

    point = point_at_cc_offset(beam_start, axis, column, offset_mm=2000.0, to_internal_units=to_internal)

    assert point.X == -500 + 2000.0
    assert point.Y == 0


def test_column_width_along_axis_uses_rotation_aware_local_bbox_when_available():
    """Issue #14 review finding #5: a 600x600 column rotated 45 degrees in
    plan, with a beam framing squarely into one of its faces (beam axis
    aligned with the column's own local X axis). The TRUE face-to-face
    width is 600 regardless of rotation; a world-axis-aligned bounding box
    would overstate it. The local-bbox-plus-transform path must recover
    the correct 600, not an inflated diagonal-ish value."""
    half = 300.0
    local_bbox = _LocalBBox((-half, -half), (half, half))

    angle = math.radians(45)
    basis_x = FakeXYZ(math.cos(angle), math.sin(angle), 0)
    basis_y = FakeXYZ(-math.sin(angle), math.cos(angle), 0)
    transform = _Transform(basis_x, basis_y)

    geometry_instance = FakeGeometryInstance(local_bbox=local_bbox, transform=transform)
    column = _Column(location_point=FakeXYZ(0, 0, 0), geometry_instances=[geometry_instance])

    # Beam axis aligned with the column's own (rotated) local X axis --
    # i.e. the beam frames squarely into a column face.
    axis_direction = basis_x

    width_mm = support_width_along_axis_mm(column, axis_direction, from_internal_units=lambda v: v)

    assert width_mm == pytest.approx(600.0)


def test_column_width_along_axis_falls_back_to_aabb_without_geometry_instance():
    """No `GeometryInstance` found (e.g. an unusual column geometry) falls
    back to the world-axis-aligned bounding box rather than raising --
    only correct for an unrotated column, but still the best available
    fallback."""
    from fake_revit_api import FakeXYZ as _XYZ

    class _BBox(object):
        Min = _XYZ(-300, -300, 0)
        Max = _XYZ(300, 300, 0)

    class _UnrotatedColumn(object):
        def __init__(self):
            self.Location = _LocationPoint(FakeXYZ(0, 0, 0))

        def get_Geometry(self, _options):
            return []

        def get_BoundingBox(self, _view):
            return _BBox()

    column = _UnrotatedColumn()
    axis_direction = FakeXYZ(1, 0, 0)

    width_mm = support_width_along_axis_mm(column, axis_direction, from_internal_units=lambda v: v)

    assert width_mm == pytest.approx(600.0)


def _beam_at_45_degrees(local_bbox, world_bbox=None):
    """A 250 x 600 beam, 6000 mm long, rotated 45 degrees in plan. Its
    family geometry runs along local X with the section in local Y/Z, and
    its instance transform is the 45 degree plan rotation about the beam's
    start point.
    """
    angle = math.radians(45)
    axis = FakeXYZ(math.cos(angle), math.sin(angle), 0)
    perp = FakeXYZ(-math.sin(angle), math.cos(angle), 0)
    transform = _Transform(basis_x=axis, basis_y=perp)
    geometry_instance = FakeGeometryInstance(local_bbox=local_bbox, transform=transform)
    return _Beam(
        start=FakeXYZ(0, 0, 0),
        end=axis.Multiply(6000.0),
        geometry_instances=[geometry_instance],
        world_bbox=world_bbox,
    )


def test_beam_section_dimensions_are_rotation_aware():
    """Issue #18 review finding #2: `get_BoundingBox(None)` is WORLD-axis
    aligned, so for a beam at 45 degrees the perpendicular projection of
    its AABB returns b + L -- 6250 mm for a 250 x 6000 beam -- instead of
    250. The local-bbox path must recover the true 250 x 600 section even
    though the (inflated) world AABB is also available.
    """
    half_diag = (6000.0 * math.cos(math.radians(45)) + 250.0 * math.cos(math.radians(45))) / 2.0

    class _InflatedAABB(object):
        Min = FakeXYZ(-half_diag, -half_diag, 0)
        Max = FakeXYZ(half_diag, half_diag, 600)

    local_bbox = _LocalBBox((0.0, -125.0), (6000.0, 125.0), min_z=-600.0, max_z=0.0)
    beam = _beam_at_45_degrees(local_bbox, world_bbox=_InflatedAABB())

    b_mm, h_mm = beam_section_dimensions_mm(beam, from_internal_units=lambda v: v)

    assert b_mm == pytest.approx(250.0)
    assert h_mm == pytest.approx(600.0)

    # What the pre-fix world-AABB path produced, kept explicit so the
    # regression is unmistakable if the local path is ever dropped.
    u_dir = FakeXYZ(-math.sin(math.radians(45)), math.cos(math.radians(45)), 0)
    aabb_corners = [
        FakeXYZ(-half_diag, -half_diag, 0),
        FakeXYZ(half_diag, -half_diag, 0),
        FakeXYZ(-half_diag, half_diag, 0),
        FakeXYZ(half_diag, half_diag, 0),
    ]
    aabb_proj = [u_dir.DotProduct(c) for c in aabb_corners]
    assert max(aabb_proj) - min(aabb_proj) == pytest.approx(6250.0)


def test_beam_section_dimensions_falls_back_to_aabb_without_geometry_instance():
    """No `GeometryInstance`: fall back to the world AABB, which is correct
    only for a beam parallel to a project axis (here, along world X)."""

    class _AABB(object):
        Min = FakeXYZ(0, -125, 0)
        Max = FakeXYZ(6000, 125, 600)

    beam = _Beam(start=FakeXYZ(0, 0, 0), end=FakeXYZ(6000, 0, 0), world_bbox=_AABB())

    b_mm, h_mm = beam_section_dimensions_mm(beam, from_internal_units=lambda v: v)

    assert b_mm == pytest.approx(250.0)
    assert h_mm == pytest.approx(600.0)


def test_beam_section_centre_offsets_recover_a_top_justified_beam():
    """Issue #18 review finding #1: with Revit's default top-justified
    structural framing the location curve lies on the beam's TOP face, so
    the section centroid is h/2 below it. A cage centred on the location
    curve would put half its depth outside the beam.
    """

    class _AABB(object):
        Min = FakeXYZ(0, -125, -600)
        Max = FakeXYZ(6000, 125, 0)

    beam = _Beam(start=FakeXYZ(0, 0, 0), end=FakeXYZ(6000, 0, 0), world_bbox=_AABB())

    du, dv = beam_section_centre_offsets(beam, station_point=FakeXYZ(2000, 0, 0))

    assert du == pytest.approx(0.0)
    assert dv == pytest.approx(-300.0)


def test_beam_section_centre_offsets_are_rotation_aware_and_catch_a_lateral_shift():
    """Both justifications at once on a rotated beam: the section sits
    100 mm off the location curve across the beam (local Y from -25 to
    225) and 300 mm below it (top-justified). The offsets must come back
    in the SECTION's own (u, v) axes, not world X/Y.
    """
    local_bbox = _LocalBBox((0.0, -25.0), (6000.0, 225.0), min_z=-600.0, max_z=0.0)
    beam = _beam_at_45_degrees(local_bbox)

    du, dv = beam_section_centre_offsets(beam, station_point=FakeXYZ(0, 0, 0))

    assert du == pytest.approx(100.0)
    assert dv == pytest.approx(-300.0)

    # The section dimensions read from the same bbox stay correct, which is
    # the point of deriving both from one source.
    b_mm, h_mm = beam_section_dimensions_mm(beam, from_internal_units=lambda v: v)
    assert (b_mm, h_mm) == (pytest.approx(250.0), pytest.approx(600.0))


# --- Issue #15 (S2): support detection generalised beyond columns -----------


def test_support_width_along_axis_uses_wall_thickness_for_any_incidence_angle():
    """R5, resolved: a wall's support width is its THICKNESS
    (``Wall.Width``), regardless of the beam's incidence angle -- not a
    swept intersection length. A beam meeting the wall at 30 degrees still
    reports the wall's own thickness, unchanged by ``axis_direction``."""
    wall = FakeWall(width_internal=250.0 / 304.8)
    oblique_axis = FakeXYZ(math.cos(math.radians(30)), math.sin(math.radians(30)), 0)

    width_mm = support_width_along_axis_mm(wall, oblique_axis, from_internal_units=lambda v: v * 304.8)

    assert width_mm == pytest.approx(250.0)


def test_support_width_along_axis_reuses_local_bbox_path_for_a_girder():
    """A girder is Structural Framing, not a column, but this ticket
    requires reusing the SAME rotation-aware ``_local_extent_along``
    projection (issue #14 review finding #5) rather than a second one --
    a 400x800 girder rotated 30 degrees, beam framing squarely into one of
    its faces, must still measure 400 mm along the beam axis."""
    half_w, half_h = 200.0, 400.0
    local_bbox = _LocalBBox((-half_w, -half_h), (half_w, half_h))

    angle = math.radians(30)
    basis_x = FakeXYZ(math.cos(angle), math.sin(angle), 0)
    basis_y = FakeXYZ(-math.sin(angle), math.cos(angle), 0)
    transform = _Transform(basis_x, basis_y)
    geometry_instance = FakeGeometryInstance(local_bbox=local_bbox, transform=transform)

    class _Girder(object):
        def __init__(self):
            self.Location = _LocationCurve(FakeXYZ(0, 0, 0), basis_x.Multiply(6000.0))
            self._geometry_instances = [geometry_instance]

        def get_Geometry(self, _options):
            return self._geometry_instances

        def get_BoundingBox(self, _view):
            return None

    girder = _Girder()
    axis_direction = basis_x  # beam frames squarely into the girder's face

    width_mm = support_width_along_axis_mm(girder, axis_direction, from_internal_units=lambda v: v)

    assert width_mm == pytest.approx(400.0)


def test_support_reference_point_uses_location_point_when_available():
    column = _Column(location_point=FakeXYZ(1.0, 2.0, 3.0))
    point = support_reference_point(column)
    assert (point.X, point.Y, point.Z) == (1.0, 2.0, 3.0)


def test_support_reference_point_falls_back_to_location_curve_midpoint():
    """A wall or girder's Location is typically a LocationCurve, not a
    Point (SHAPE UNVERIFIED design choice, see support_reference_point's
    docstring) -- the midpoint is used as its reference centre."""

    class _CurveLocatedSupport(object):
        def __init__(self):
            self.Id = 999
            self.Location = _LocationCurve(FakeXYZ(0, 0, 0), FakeXYZ(4000.0, 0, 0))

    point = support_reference_point(_CurveLocatedSupport())
    assert (point.X, point.Y, point.Z) == (2000.0, 0.0, 0.0)


def test_support_reference_point_raises_without_point_or_curve():
    class _NoLocation(object):
        Id = 42
        Location = None

    with pytest.raises(Exception):
        support_reference_point(_NoLocation())


class _TaggedElement(object):
    def __init__(self, id_value, category, bbox_center, half_extent=300.0):
        self.Id = id_value
        self._category = category
        cx, cy = bbox_center

        class _BBox(object):
            Min = FakeXYZ(cx - half_extent, cy - half_extent, 0)
            Max = FakeXYZ(cx + half_extent, cy + half_extent, 0)

        self._bbox = _BBox()

    def get_BoundingBox(self, _view):
        return self._bbox


def test_find_supporting_element_returns_nearest_across_all_three_categories(monkeypatch):
    from Autodesk.Revit.DB import BuiltInCategory

    near_column = _TaggedElement(1, BuiltInCategory.OST_StructuralColumns, (0, 0))
    far_wall = _TaggedElement(2, BuiltInCategory.OST_Walls, (5000, 0))
    near_girder = _TaggedElement(3, BuiltInCategory.OST_StructuralFraming, (10, 0))
    monkeypatch.setattr(
        FakeFilteredElementCollector, "_ITEMS", [near_column, far_wall, near_girder]
    )

    found = find_supporting_element(doc=None, point=FakeXYZ(0, 0, 0), to_internal_units=lambda v: v)

    assert found is near_column  # nearest bbox centre wins, regardless of category


def test_find_supporting_element_excludes_the_beam_being_detailed(monkeypatch):
    """A girder search uses OST_StructuralFraming, the SAME category the
    beam itself belongs to -- without exclusion the beam could find
    itself."""
    from Autodesk.Revit.DB import BuiltInCategory

    the_beam_itself = _TaggedElement(7, BuiltInCategory.OST_StructuralFraming, (0, 0))
    real_girder = _TaggedElement(8, BuiltInCategory.OST_StructuralFraming, (0, 0))
    monkeypatch.setattr(
        FakeFilteredElementCollector, "_ITEMS", [the_beam_itself, real_girder]
    )

    found = find_supporting_element(
        doc=None, point=FakeXYZ(0, 0, 0), to_internal_units=lambda v: v, exclude_element_id=7
    )

    assert found is real_girder


def test_find_supporting_element_returns_none_for_a_free_end(monkeypatch):
    """No support in range -- the caller must take the unsupported/free-end
    path (rev 2 section 2.5, A12/A14)."""
    monkeypatch.setattr(FakeFilteredElementCollector, "_ITEMS", [])

    found = find_supporting_element(doc=None, point=FakeXYZ(0, 0, 0), to_internal_units=lambda v: v)

    assert found is None
