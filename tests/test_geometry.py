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

from fake_revit_api import FakeGeometryInstance, FakeXYZ

from rft.revit.geometry import (
    column_width_along_axis_mm,
    end_support_face_point,
    start_support_face_point,
)


class _LocalBBox(object):
    def __init__(self, min_xy, max_xy):
        self.Min = FakeXYZ(min_xy[0], min_xy[1], 0)
        self.Max = FakeXYZ(max_xy[0], max_xy[1], 0)


class _Transform(object):
    def __init__(self, basis_x, basis_y):
        self.BasisX = basis_x
        self.BasisY = basis_y


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
    assert face.Y == 0


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

    width_mm = column_width_along_axis_mm(column, axis_direction, from_internal_units=lambda v: v)

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

    width_mm = column_width_along_axis_mm(column, axis_direction, from_internal_units=lambda v: v)

    assert width_mm == pytest.approx(600.0)
