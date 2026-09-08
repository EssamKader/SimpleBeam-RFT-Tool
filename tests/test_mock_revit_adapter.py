"""Mock-object verification for the Revit-dependent adapter (CONTEXT.md /
specs/beam-rft-detailing.md DoD): since no live Revit host exists, this
exercises the ACTUAL adapter source in ``rft.revit.host`` and
``rft.revit.placement`` against stand-in Revit types (``fake_revit_api``)
rather than re-describing the logic in prose.

Covers: the §10 host-validation order (GetRebarHostData -> IsValidHost),
the explicit per-face cover read-back that must not accept a silent
document-default fallback, and the single-Transaction-with-rollback
pattern.
"""

import pytest

from fake_revit_api import FakeElementId, FakeTransaction, FakeXYZ

from rft.revit.host import HostValidationError, read_face_cover_mm, validate_rebar_host
from rft.revit.placement import bend_plane_normal, build_bottom_bar_curves, run_in_transaction
import rft.revit.host as host_module


class _Element(object):
    def __init__(self, id_value, structural_usage=None):
        self.Id = id_value
        self.StructuralUsage = structural_usage


class _HostDataNoneRebar(object):
    @staticmethod
    def GetRebarHostData(_element):
        return None


class _HostDataInvalid(object):
    class _Data(object):
        def IsValidHost(self):
            return False

    @staticmethod
    def GetRebarHostData(_element):
        return _HostDataInvalid._Data()


class _HostDataValid(object):
    class _Data(object):
        def IsValidHost(self):
            return True

    @staticmethod
    def GetRebarHostData(_element):
        return _HostDataValid._Data()


def test_validate_rebar_host_raises_when_get_rebar_host_data_is_null(monkeypatch):
    monkeypatch.setattr(host_module, "RebarHostData", _HostDataNoneRebar)
    beam = _Element(id_value=101)
    with pytest.raises(HostValidationError) as excinfo:
        validate_rebar_host(beam)
    assert "101" in str(excinfo.value)
    assert excinfo.value.element_id == 101


def test_validate_rebar_host_raises_and_names_structural_usage_when_invalid(monkeypatch):
    monkeypatch.setattr(host_module, "RebarHostData", _HostDataInvalid)
    beam = _Element(id_value=202, structural_usage="NonBearing")
    with pytest.raises(HostValidationError) as excinfo:
        validate_rebar_host(beam)
    assert "StructuralUsage" in str(excinfo.value)
    assert "NonBearing" in str(excinfo.value)


def test_validate_rebar_host_succeeds_and_returns_host_data(monkeypatch):
    monkeypatch.setattr(host_module, "RebarHostData", _HostDataValid)
    beam = _Element(id_value=303)
    result = validate_rebar_host(beam)
    assert result.IsValidHost() is True


class _FaceStub(object):
    pass


class _HostDataNoFaces(object):
    def GetFaces(self, _face_type):
        return []


class _HostDataUndefinedCover(object):
    def GetFaces(self, _face_type):
        return [_FaceStub()]

    def GetCoverType(self, _face):
        return FakeElementId.InvalidElementId


class _CoverType(object):
    def __init__(self, distance_internal):
        self.CoverDistance = distance_internal


class _HostDataDefinedCover(object):
    def __init__(self, cover_internal):
        self._cover_internal = cover_internal

    def GetFaces(self, _face_type):
        return [_FaceStub()]

    def GetCoverType(self, _face):
        return FakeElementId(7)


class _DocReturningCoverType(object):
    def __init__(self, distance_internal):
        self._cover_type = _CoverType(distance_internal)

    def GetElement(self, _element_id):
        return self._cover_type


def test_read_face_cover_raises_when_no_face_found():
    with pytest.raises(HostValidationError, match="No .* face"):
        read_face_cover_mm(_HostDataNoFaces(), "Bottom", doc=None, from_internal_units=lambda v: v)


def test_read_face_cover_raises_on_undefined_cover_rather_than_silently_defaulting():
    """The whole point of §10's explicit read-back: an undefined face cover
    must surface as an error, never a silently-accepted document default."""
    with pytest.raises(HostValidationError, match="document default"):
        read_face_cover_mm(
            _HostDataUndefinedCover(), "Bottom", doc=None, from_internal_units=lambda v: v
        )


def test_read_face_cover_returns_explicit_value_in_mm():
    host_data = _HostDataDefinedCover(cover_internal=0.08202099737532808)  # 25mm in ft
    doc = _DocReturningCoverType(distance_internal=0.08202099737532808)
    cover_mm = read_face_cover_mm(
        host_data, "Bottom", doc=doc, from_internal_units=lambda v: v * 304.8
    )
    assert cover_mm == pytest.approx(25.0, abs=0.01)


def test_transaction_commits_on_success(monkeypatch):
    import rft.revit.placement as placement_module

    monkeypatch.setattr(placement_module, "Transaction", FakeTransaction)
    calls = []
    result = run_in_transaction(doc=None, transaction_name="test", action=lambda: calls.append(1) or "ok")
    assert result == "ok"
    assert calls == [1]


def test_transaction_rolls_back_and_reraises_on_exception(monkeypatch):
    import rft.revit.placement as placement_module

    monkeypatch.setattr(placement_module, "Transaction", FakeTransaction)
    captured = {}

    def _spy_transaction(doc, name):
        tx = FakeTransaction(doc, name)
        captured["tx"] = tx
        return tx

    monkeypatch.setattr(placement_module, "Transaction", _spy_transaction)

    def _failing_action():
        raise ValueError("placement blew up")

    with pytest.raises(ValueError, match="placement blew up"):
        run_in_transaction(doc=None, transaction_name="test", action=_failing_action)

    assert captured["tx"].rolled_back is True
    assert captured["tx"].committed is False


def test_bottom_bar_curve_list_has_exactly_three_segments_no_hooks():
    """Issue #14 review findings #1/#6, corrected 3-segment requirement:
    bend leg `b` at end A (up) -> one continuous straight run spanning the
    beam plus `a` into each support -> bend leg `b` at end B (up). Not a
    RebarHookType -- startHook/endHook are passed as None separately in
    rft.revit.placement.place_anchored_bar."""
    face_start = FakeXYZ(0, 0, 0)
    face_end = FakeXYZ(6000, 0, 0)  # 6 m beam, face to face
    axis_direction = FakeXYZ(1, 0, 0)
    bend_direction = FakeXYZ.BasisZ

    curves = build_bottom_bar_curves(
        face_start, face_end, axis_direction, bend_direction,
        a_start_internal=559, b_start_internal=200,
        a_end_internal=275, b_end_internal=605,
    )
    assert len(curves) == 3

    bend_a_line, straight_line, bend_b_line = curves
    # FakeLine.CreateBound(p0, p1) -> ("Line", p0, p1)

    corner_start = FakeXYZ(-559, 0, 0)  # `a_start` behind face_start
    corner_end = FakeXYZ(6275, 0, 0)  # `a_end` beyond face_end

    assert bend_a_line[2] == corner_start
    assert bend_a_line[1] == FakeXYZ(-559, 0, 200)  # bend up by b_start

    assert straight_line[1] == corner_start
    assert straight_line[2] == corner_end

    assert bend_b_line[1] == corner_end
    assert bend_b_line[2] == FakeXYZ(6275, 0, 605)  # bend up by b_end

    # The straight run actually spans the beam (plus `a` at each end) --
    # not a floating stub at one end (finding #1).
    straight_length = straight_line[2].X - straight_line[1].X
    assert straight_length == 6000 + 559 + 275

    # Both bend legs go upward (Z increases from the corner).
    assert bend_a_line[1].Z > corner_start.Z  # bend_end_start above corner_start
    assert bend_b_line[2].Z > corner_end.Z  # bend_end_end above corner_end


def test_bend_plane_normal_is_perpendicular_to_both_legs():
    straight_direction = FakeXYZ(1, 0, 0)
    bend_direction = FakeXYZ(0, 0, 1)
    normal = bend_plane_normal(straight_direction, bend_direction)
    assert normal.DotProduct(straight_direction) == pytest.approx(0.0)
    assert normal.DotProduct(bend_direction) == pytest.approx(0.0)
