"""Mock-object verification for `rft.revit.guards`'s continuous-run
detection (S9, GitHub issue #22). Installs the fake `Autodesk.Revit.DB`
modules (`fake_revit_api.install()`, run at import time via `conftest.py`)
and exercises the REAL adapter source, same pattern as `test_geometry.py`.
"""

import math

import pytest

from fake_revit_api import FakeFilteredElementCollector, FakeXYZ

from rft.core.guards import CONTINUOUS_RUN_LATERAL_TOLERANCE_MM, is_on_same_axis_line
from rft.revit.guards import (
    continuous_run_guard,
    find_continuous_run_neighbour,
    neighbour_axis_dot_product,
    neighbour_lateral_offset_mm,
)


class _Curve(object):
    def __init__(self, start, end):
        self._points = (start, end)

    def GetEndPoint(self, index):
        return self._points[index]


class _LocationCurve(object):
    def __init__(self, start, end):
        self.Curve = _Curve(start, end)


class _LocationPoint(object):
    def __init__(self, point):
        self.Point = point


class _Framing(object):
    """A structural-framing neighbour (beam or girder): a location curve
    (fixing its own axis) plus a plan bounding box for proximity search."""

    def __init__(self, id_value, start, end, bbox_center, half_extent=300.0, category=None):
        self.Id = id_value
        self.Location = _LocationCurve(start, end)
        self._category = category
        cx, cy = bbox_center

        class _BBox(object):
            Min = FakeXYZ(cx - half_extent, cy - half_extent, 0)
            Max = FakeXYZ(cx + half_extent, cy + half_extent, 0)

        self._bbox = _BBox()

    def get_BoundingBox(self, _view):
        return self._bbox


class _Column(object):
    """A column neighbour: point-located, never collinear (excluded from
    `find_continuous_run_neighbour`'s OST_StructuralFraming-only search by
    construction, not by any axis check)."""

    def __init__(self, id_value, point, bbox_center, half_extent=300.0, category=None):
        self.Id = id_value
        self.Location = _LocationPoint(point)
        self._category = category
        cx, cy = bbox_center

        class _BBox(object):
            Min = FakeXYZ(cx - half_extent, cy - half_extent, 0)
            Max = FakeXYZ(cx + half_extent, cy + half_extent, 0)

        self._bbox = _BBox()

    def get_BoundingBox(self, _view):
        return self._bbox


def _beam_along_x(length=6000.0, id_value=1):
    beam = _Framing(id_value, FakeXYZ(0, 0, 0), FakeXYZ(length, 0, 0), bbox_center=(length / 2.0, 0))
    return beam


def test_beam_framing_into_a_transverse_girder_is_not_continuous(monkeypatch):
    """Case 1: a beam framing into a transverse girder is NOT continuous --
    placement proceeds (rev 2 section 2.4)."""
    from Autodesk.Revit.DB import BuiltInCategory

    beam = _beam_along_x()
    girder = _Framing(
        99, FakeXYZ(6000, -1000, 0), FakeXYZ(6000, 1000, 0),
        bbox_center=(6000, 0), category=BuiltInCategory.OST_StructuralFraming,
    )
    monkeypatch.setattr(FakeFilteredElementCollector, "_ITEMS", [girder])

    result = continuous_run_guard(
        doc=None, beam=beam, point=FakeXYZ(6000, 0, 0), to_internal_units=lambda v: v,
        end_label="End end", exclude_element_id=beam.Id,
    )

    assert result is None


def test_two_collinear_beams_meeting_at_a_column_is_continuous_despite_the_column(monkeypatch):
    """Case 2 (the dangerous one this story exists for): a collinear
    neighbouring beam AND a column both sit at the same end. The guard must
    fire even though a column support is present -- gating on whichever
    element `find_supporting_element` would pick (the column, nearest) must
    NOT suppress it."""
    from Autodesk.Revit.DB import BuiltInCategory

    beam = _beam_along_x()
    continuing_beam = _Framing(
        99, FakeXYZ(6000, 0, 0), FakeXYZ(12000, 0, 0),
        bbox_center=(6000, 0), category=BuiltInCategory.OST_StructuralFraming,
    )
    column = _Column(
        100, FakeXYZ(6000, 0, 0), bbox_center=(6000, 0), category=BuiltInCategory.OST_StructuralColumns,
    )
    monkeypatch.setattr(FakeFilteredElementCollector, "_ITEMS", [column, continuing_beam])

    result = continuous_run_guard(
        doc=None, beam=beam, point=FakeXYZ(6000, 0, 0), to_internal_units=lambda v: v,
        end_label="End end", exclude_element_id=beam.Id,
    )

    assert result is not None
    assert "End end" in result.message
    assert "REFUSED" in result.message


def test_ambiguous_45_degree_neighbour_is_treated_as_continuous(monkeypatch):
    """Case 3: an ambiguous 45-degree neighbour resolves toward continuous
    (this ticket's own tolerance choice, see rft.core.guards)."""
    from Autodesk.Revit.DB import BuiltInCategory

    beam = _beam_along_x()
    dx = math.cos(math.radians(45.0)) * 2000.0
    dy = math.sin(math.radians(45.0)) * 2000.0
    diagonal_neighbour = _Framing(
        99, FakeXYZ(6000, 0, 0), FakeXYZ(6000 + dx, dy, 0),
        bbox_center=(6000, 0), category=BuiltInCategory.OST_StructuralFraming,
    )
    monkeypatch.setattr(FakeFilteredElementCollector, "_ITEMS", [diagonal_neighbour])

    result = continuous_run_guard(
        doc=None, beam=beam, point=FakeXYZ(6000, 0, 0), to_internal_units=lambda v: v,
        end_label="End end", exclude_element_id=beam.Id,
    )

    assert result is not None


def test_ambiguous_46_degree_neighbour_is_treated_as_transverse(monkeypatch):
    from Autodesk.Revit.DB import BuiltInCategory

    beam = _beam_along_x()
    dx = math.cos(math.radians(46.0)) * 2000.0
    dy = math.sin(math.radians(46.0)) * 2000.0
    diagonal_neighbour = _Framing(
        99, FakeXYZ(6000, 0, 0), FakeXYZ(6000 + dx, dy, 0),
        bbox_center=(6000, 0), category=BuiltInCategory.OST_StructuralFraming,
    )
    monkeypatch.setattr(FakeFilteredElementCollector, "_ITEMS", [diagonal_neighbour])

    result = continuous_run_guard(
        doc=None, beam=beam, point=FakeXYZ(6000, 0, 0), to_internal_units=lambda v: v,
        end_label="End end", exclude_element_id=beam.Id,
    )

    assert result is None


def test_end_span_of_a_continuous_run_is_flagged_only_at_its_continuous_end(monkeypatch):
    """Per-end independence: an end span has a collinear neighbour at ONE
    end only, and must not be flagged at the other (free/girder/whatever)
    end."""
    from Autodesk.Revit.DB import BuiltInCategory

    beam = _beam_along_x()
    continuing_beam = _Framing(
        99, FakeXYZ(6000, 0, 0), FakeXYZ(12000, 0, 0),
        bbox_center=(6000, 0), category=BuiltInCategory.OST_StructuralFraming,
    )
    monkeypatch.setattr(FakeFilteredElementCollector, "_ITEMS", [continuing_beam])

    result_far_end = continuous_run_guard(
        doc=None, beam=beam, point=FakeXYZ(6000, 0, 0), to_internal_units=lambda v: v,
        end_label="End end", exclude_element_id=beam.Id,
    )
    result_near_end = continuous_run_guard(
        doc=None, beam=beam, point=FakeXYZ(0, 0, 0), to_internal_units=lambda v: v,
        end_label="Start end", exclude_element_id=beam.Id,
    )

    assert result_far_end is not None
    assert result_near_end is None


def test_beam_excludes_itself_from_its_own_continuous_run_search(monkeypatch):
    from Autodesk.Revit.DB import BuiltInCategory

    beam = _beam_along_x(id_value=7)
    monkeypatch.setattr(
        FakeFilteredElementCollector, "_ITEMS",
        [_Framing(7, FakeXYZ(0, 0, 0), FakeXYZ(6000, 0, 0), bbox_center=(0, 0),
                  category=BuiltInCategory.OST_StructuralFraming)],
    )

    found = find_continuous_run_neighbour(
        doc=None, beam=beam, point=FakeXYZ(0, 0, 0), to_internal_units=lambda v: v,
        exclude_element_id=7,
    )

    assert found is None


def test_neighbour_axis_dot_product_uses_each_elements_own_location_curve():
    beam = _beam_along_x()
    perpendicular_neighbour = _Framing(2, FakeXYZ(6000, -1000, 0), FakeXYZ(6000, 1000, 0), bbox_center=(6000, 0))
    assert neighbour_axis_dot_product(beam, perpendicular_neighbour) == 0.0

    parallel_neighbour = _Framing(3, FakeXYZ(6000, 0, 0), FakeXYZ(12000, 0, 0), bbox_center=(6000, 0))
    assert neighbour_axis_dot_product(beam, parallel_neighbour) == 1.0


def _mm(value_mm):
    """mm -> the fake API's internal units (1 internal unit == 1 foot)."""
    return value_mm / 304.8


def test_a_parallel_neighbour_off_the_axis_line_is_not_a_continuous_run(monkeypatch):
    """Issue #22 review: same DIRECTION is only half of collinear. Twin
    beams running alongside each other 250 mm apart both score
    abs(dot) = 1, and the bounding-box proximity search around the beam end
    reaches the twin -- but they are two separate valid single spans, not a
    continuous run, and refusing one of them with "this beam is part of a
    continuous run" would be both wrong and confusing."""
    from Autodesk.Revit.DB import BuiltInCategory

    beam = _beam_along_x()
    twin = _Framing(
        77, FakeXYZ(0, _mm(250.0), 0), FakeXYZ(6000, _mm(250.0), 0),
        bbox_center=(6000, _mm(250.0)), category=BuiltInCategory.OST_StructuralFraming,
    )
    monkeypatch.setattr(FakeFilteredElementCollector, "_ITEMS", [twin])

    # The direction test alone would call this collinear ...
    assert abs(neighbour_axis_dot_product(beam, twin)) == 1.0
    # ... and it is 250 mm off the beam's axis line, so it is not.
    assert neighbour_lateral_offset_mm(beam, twin, FakeXYZ(6000, 0, 0)) == pytest.approx(250.0)

    assert continuous_run_guard(
        doc=None, beam=beam, point=FakeXYZ(6000, 0, 0), to_internal_units=lambda v: v,
        end_label="End end", exclude_element_id=beam.Id,
    ) is None


def test_a_continuation_slightly_off_axis_is_still_a_continuous_run(monkeypatch):
    """The lateral tolerance absorbs modelling slop: a continuation modelled
    40 mm off the beam's axis line is still a continuous run, and must still
    be refused."""
    from Autodesk.Revit.DB import BuiltInCategory

    beam = _beam_along_x()
    continuation = _Framing(
        78, FakeXYZ(6000, _mm(40.0), 0), FakeXYZ(12000, _mm(40.0), 0),
        bbox_center=(6000, _mm(40.0)), category=BuiltInCategory.OST_StructuralFraming,
    )
    monkeypatch.setattr(FakeFilteredElementCollector, "_ITEMS", [continuation])

    offset_mm = neighbour_lateral_offset_mm(beam, continuation, FakeXYZ(6000, 0, 0))
    assert offset_mm == pytest.approx(40.0)
    assert offset_mm <= CONTINUOUS_RUN_LATERAL_TOLERANCE_MM

    result = continuous_run_guard(
        doc=None, beam=beam, point=FakeXYZ(6000, 0, 0), to_internal_units=lambda v: v,
        end_label="End end", exclude_element_id=beam.Id,
    )
    assert result is not None
    assert "REFUSED" in result.message


def test_lateral_offset_is_measured_to_the_endpoint_nearest_the_end_checked():
    """A long continuation has one endpoint at the shared node and another
    far away; the offset must be measured at the shared node, not from
    whichever endpoint the location curve happens to list first."""
    beam = _beam_along_x()
    # Runs away from the beam's END end, and is deliberately listed
    # far-endpoint-first.
    continuation = _Framing(
        79, FakeXYZ(12000, _mm(250.0), 0), FakeXYZ(6000, 0, 0), bbox_center=(6000, 0),
    )
    assert neighbour_lateral_offset_mm(beam, continuation, FakeXYZ(6000, 0, 0)) == pytest.approx(0.0)


def test_is_on_same_axis_line_applies_the_policy_tolerance():
    assert is_on_same_axis_line(0.0) is True
    assert is_on_same_axis_line(CONTINUOUS_RUN_LATERAL_TOLERANCE_MM) is True
    assert is_on_same_axis_line(CONTINUOUS_RUN_LATERAL_TOLERANCE_MM + 1.0) is False
    assert is_on_same_axis_line(-250.0) is False  # sign-independent
