"""Mock-object verification for the Revit-dependent adapter (CONTEXT.md /
specs/beam-rft-detailing.md DoD): since no live Revit host exists, this
exercises the ACTUAL adapter source in ``rft.revit.host`` and
``rft.revit.placement`` against stand-in Revit types (``fake_revit_api``)
rather than re-describing the logic in prose.

Covers: the §10 host-validation order (GetRebarHostData -> IsValidHost),
the explicit per-face cover read-back that must not accept a silent
document-default fallback, the single-Transaction-with-rollback pattern,
and (issue #18, S5) stirrup curve/hook placement plus the R4
de-duplication-guard mitigation on `SetLayoutAsMaximumSpacing`.
"""

import pytest

from fake_revit_api import FakeElementId, FakeRebarHookType, FakeTransaction, FakeXYZ

from rft.revit.host import HostValidationError, read_face_cover_mm, validate_rebar_host
from rft.revit.placement import bend_plane_normal, build_bottom_bar_curves, run_in_transaction
from rft.revit.stirrups import apply_maximum_spacing_layout, build_stirrup_curves, place_stirrup
from rft.core.stirrups import (
    ZONE_LAYOUT_FLAGS,
    stirrup_curve_endpoints_mm,
    stirrup_zones_mm,
    zone_array_length_mm,
)
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


# --- Issue #18 (S5): stirrups -----------------------------------------------


def _to_internal(value_mm):
    return value_mm / 304.8  # matches FakeUnitUtils


def test_build_stirrup_curves_maps_local_uv_into_the_section_plane():
    origin = FakeXYZ(1000, 0, 0)
    u_dir = FakeXYZ(0, 1, 0)  # cross-section width axis
    v_dir = FakeXYZ(0, 0, 1)  # cross-section height axis
    endpoints_mm = stirrup_curve_endpoints_mm(1, width_mm=240.0, height_mm=540.0)

    curves = build_stirrup_curves(origin, u_dir, v_dir, endpoints_mm, _to_internal)

    assert len(curves) == 4
    # First curve starts at the top-right corner (Type 1, §7.2).
    _, p0, p1 = curves[0]  # FakeLine.CreateBound(p0, p1) -> ("Line", p0, p1)
    assert p0.X == pytest.approx(1000)
    assert p0.Y == pytest.approx(120.0 / 304.8)  # +hw
    assert p0.Z == pytest.approx(270.0 / 304.8)  # +hh


def test_place_stirrup_type1_closed_loop_uses_stirrup_tie_and_same_hook_both_ends():
    import rft.revit.stirrups as stirrups_module

    doc, host, bar_type = object(), object(), object()
    hook_type = FakeRebarHookType(angle_deg=180)
    origin, u_dir, v_dir = FakeXYZ(0, 0, 0), FakeXYZ(0, 1, 0), FakeXYZ(0, 0, 1)
    endpoints_mm = stirrup_curve_endpoints_mm(1, 240.0, 540.0)
    curves = build_stirrup_curves(origin, u_dir, v_dir, endpoints_mm, _to_internal)
    norm = FakeXYZ(1, 0, 0)

    rebar = place_stirrup(doc, host, bar_type, hook_type, curves, norm)

    assert rebar.args[1] is stirrups_module.RebarStyle.StirrupTie
    assert rebar.args[2] is bar_type
    assert rebar.args[3] is hook_type  # startHookType
    assert rebar.args[4] is hook_type  # endHookType -- same hook both ends
    assert len(rebar.args[7]) == 4  # closed 4-curve loop


def test_place_stirrup_type4_open_u_still_gets_hook_type_at_both_ends():
    doc, host, bar_type = object(), object(), object()
    hook_type = FakeRebarHookType(angle_deg=180)
    origin, u_dir, v_dir = FakeXYZ(0, 0, 0), FakeXYZ(0, 1, 0), FakeXYZ(0, 0, 1)
    endpoints_mm = stirrup_curve_endpoints_mm(4, 240.0, 540.0)
    curves = build_stirrup_curves(origin, u_dir, v_dir, endpoints_mm, _to_internal)
    norm = FakeXYZ(1, 0, 0)

    rebar = place_stirrup(doc, host, bar_type, hook_type, curves, norm)

    assert len(rebar.args[7]) == 3  # open 3-curve chain, no top closure
    assert rebar.args[3] is hook_type
    assert rebar.args[4] is hook_type


def test_apply_maximum_spacing_layout_calls_accessor_with_expected_args():
    doc, host, bar_type = object(), object(), object()
    hook_type = FakeRebarHookType(angle_deg=180)
    origin, u_dir, v_dir = FakeXYZ(0, 0, 0), FakeXYZ(0, 1, 0), FakeXYZ(0, 0, 1)
    endpoints_mm = stirrup_curve_endpoints_mm(1, 240.0, 540.0)
    curves = build_stirrup_curves(origin, u_dir, v_dir, endpoints_mm, _to_internal)
    rebar = place_stirrup(doc, host, bar_type, hook_type, curves, FakeXYZ(1, 0, 0))

    accessor = apply_maximum_spacing_layout(
        rebar,
        max_spacing_internal=_to_internal(150.0),
        array_length_internal=_to_internal(1750.0),
        include_first_bar=True,
        include_last_bar=True,
    )

    assert len(accessor.calls) == 1
    call = accessor.calls[0]
    assert call["spacing"] == pytest.approx(_to_internal(150.0))
    assert call["array_length"] == pytest.approx(_to_internal(1750.0))
    assert call["include_first_bar"] is True
    assert call["include_last_bar"] is True
    assert call["bars_on_normal_side"] is True


def test_r4_mitigation_three_zone_placement_claims_each_boundary_exactly_once():
    """R4 (open question) mitigation demonstration: simulate placing all
    three zones' rebar sets end-to-end and show the explicit
    include-first/include-last flags mean the L/3 and 2L/3 boundaries are
    each claimed by exactly ONE zone's `SetLayoutAsMaximumSpacing` call --
    never both, which is the failure mode R4 asks about and that cannot be
    observed on a live host from this environment.
    """
    doc, host, bar_type = object(), object(), object()
    hook_type = FakeRebarHookType(angle_deg=180)
    origin, u_dir, v_dir = FakeXYZ(0, 0, 0), FakeXYZ(0, 1, 0), FakeXYZ(0, 0, 1)
    endpoints_mm = stirrup_curve_endpoints_mm(1, 240.0, 540.0)
    curves = build_stirrup_curves(origin, u_dir, v_dir, endpoints_mm, _to_internal)

    zones = stirrup_zones_mm(l_mm=6000.0, face_a_offset_mm=250.0, face_b_offset_mm=250.0)
    dense_spacing_mm, normal_spacing_mm = 150.0, 200.0
    zone_specs = [
        ("zone1", zones.zone1, dense_spacing_mm),
        ("zone2", zones.zone2, normal_spacing_mm),
        ("zone3", zones.zone3, dense_spacing_mm),
    ]

    accessors = {}
    for name, zone, max_spacing_mm in zone_specs:
        rebar = place_stirrup(doc, host, bar_type, hook_type, curves, FakeXYZ(1, 0, 0))
        include_first, include_last = ZONE_LAYOUT_FLAGS[name]
        accessors[name] = apply_maximum_spacing_layout(
            rebar,
            max_spacing_internal=_to_internal(max_spacing_mm),
            array_length_internal=_to_internal(zone_array_length_mm(zone)),
            include_first_bar=include_first,
            include_last_bar=include_last,
        )

    # L/3 boundary: owned by zone1's LAST bar, NOT by zone2's first bar.
    assert accessors["zone1"].calls[0]["include_last_bar"] is True
    assert accessors["zone2"].calls[0]["include_first_bar"] is False

    # 2L/3 boundary: owned by zone3's FIRST bar, NOT by zone2's last bar.
    assert accessors["zone3"].calls[0]["include_first_bar"] is True
    assert accessors["zone2"].calls[0]["include_last_bar"] is False

    # Every zone still got exactly one SetLayoutAsMaximumSpacing call
    # (one rebar set per zone, §3.2, A18).
    for name in accessors:
        assert len(accessors[name].calls) == 1
