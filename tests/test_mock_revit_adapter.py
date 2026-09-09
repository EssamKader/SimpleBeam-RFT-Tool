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

from fake_revit_api import (
    FakeElementId,
    FakeFace,
    FakeRebarBarType,
    FakeRebarCoverType,
    FakeRebarHookType,
    FakeReference,
    FakeTransaction,
    FakeXYZ,
)

from rft.core.anchorage import top_bar_anchorage
from rft.revit.host import (
    FACE_ROLE_BOTTOM,
    FACE_ROLE_END_END,
    FACE_ROLE_END_START,
    FACE_ROLE_SIDE,
    FACE_ROLE_TOP,
    HostValidationError,
    classify_face_role,
    face_normal,
    read_beam_face_covers_mm,
    read_support_side_cover_mm,
    validate_rebar_host,
)
from rft.revit.placement import (
    bar_face_points_at_uv,
    bar_point_at_uv,
    bend_plane_normal,
    bent_end_corner,
    build_bottom_bar_curves,
    build_main_bar_curves,
    main_bar_end_geometry,
    run_in_transaction,
    unsupported_end_corner,
)
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


FT_PER_MM = 1.0 / 304.8


def _ft(mm):
    return mm * FT_PER_MM


class _FakeBeamElement(object):
    """SHAPE UNVERIFIED companion for the classify-by-normal tests: a stub
    standing in for a beam ``Element``, only implementing
    ``GetGeometryObjectFromReference`` (confirmed live, issue #23) as a
    dict lookup from ``FakeReference`` to ``FakeFace``."""

    def __init__(self, id_value, faces_by_reference):
        self.Id = id_value
        self._faces_by_reference = faces_by_reference

    def GetGeometryObjectFromReference(self, reference):
        return self._faces_by_reference[reference]


class _HostDataFromFaces(object):
    """A ``RebarHostData`` stand-in built the CONFIRMED-LIVE way (issue #23):
    ``GetExposedFaces() -> IList<Reference>`` and
    ``GetCoverType(Reference) -> RebarCoverType`` directly (no ``doc.GetElement``
    round trip, and no ``RebarFaceType`` in sight)."""

    def __init__(self, cover_by_reference):
        self._cover_by_reference = cover_by_reference

    def GetExposedFaces(self):
        return list(self._cover_by_reference.keys())

    def GetCoverType(self, reference):
        return self._cover_by_reference[reference]


# A beam running along +X, axis-aligned with the world -- deliberately
# ALSO tested at 45 degrees below (issue #30's named trap: a beam parallel
# to a project axis cannot catch a world-axis-shortcut defect).
AXIS_X = FakeXYZ(1.0, 0.0, 0.0)
U_DIR_Y = FakeXYZ(0.0, -1.0, 0.0)  # (-axis.Y, axis.X, 0) per beam_section_axes
V_DIR_Z = FakeXYZ.BasisZ


def test_classify_face_role_top_bottom_side_and_end_axis_aligned():
    assert classify_face_role(FakeXYZ(0, 0, 1), U_DIR_Y, V_DIR_Z, AXIS_X) == FACE_ROLE_TOP
    assert classify_face_role(FakeXYZ(0, 0, -1), U_DIR_Y, V_DIR_Z, AXIS_X) == FACE_ROLE_BOTTOM
    assert classify_face_role(FakeXYZ(0, -1, 0), U_DIR_Y, V_DIR_Z, AXIS_X) == FACE_ROLE_SIDE
    assert classify_face_role(FakeXYZ(0, 1, 0), U_DIR_Y, V_DIR_Z, AXIS_X) == FACE_ROLE_SIDE
    assert classify_face_role(FakeXYZ(-1, 0, 0), U_DIR_Y, V_DIR_Z, AXIS_X) == FACE_ROLE_END_START
    assert classify_face_role(FakeXYZ(1, 0, 0), U_DIR_Y, V_DIR_Z, AXIS_X) == FACE_ROLE_END_END


def test_classify_face_role_oblique_face_refuses_rather_than_guesses():
    """rev 2 section 10: an unclassifiable face must never be assigned a
    role by whichever direction happens to have the largest (but still
    below-tolerance) dot product."""
    oblique = FakeXYZ(0.7, 0.7, 0.14).Normalize()
    assert classify_face_role(oblique, U_DIR_Y, V_DIR_Z, AXIS_X) is None


def test_classify_face_role_is_rotation_aware_not_a_world_axis_shortcut():
    """Issue #30's named trap, mirroring #18's bounding-box defect: a beam
    at 45 degrees in plan has face normals that are oblique in WORLD terms
    (n.Y and n.Z would both fail a naive `abs(n.Z) > tol` TOP test) but
    exact in the beam's OWN frame. A green suite against only the +X beam
    above would never catch a `normal.Z`/`normal.X` world-axis shortcut."""
    axis_45 = FakeXYZ(1.0, 1.0, 0.0).Normalize()
    u_dir_45 = FakeXYZ(-axis_45.Y, axis_45.X, 0.0).Normalize()
    v_dir_45 = FakeXYZ.BasisZ

    # The beam's own TOP face still normalises to (0, 0, 1) in world terms
    # (rotation only happens in-plan) -- classify against the beam's own
    # v_dir either way, no special case needed.
    assert classify_face_role(FakeXYZ(0, 0, 1), u_dir_45, v_dir_45, axis_45) == FACE_ROLE_TOP

    # The beam's SIDE face normal is perpendicular to the 45-degree axis in
    # plan: neither a pure world X nor a pure world Y vector, but EXACTLY
    # u_dir_45 -- a world-axis check (`abs(n.X) > tol` or `abs(n.Y) > tol`)
    # would misclassify or refuse this face; the frame-relative check must
    # not.
    assert classify_face_role(u_dir_45, u_dir_45, v_dir_45, axis_45) == FACE_ROLE_SIDE
    assert classify_face_role(u_dir_45.Negate(), u_dir_45, v_dir_45, axis_45) == FACE_ROLE_SIDE

    # The beam's END face normal is exactly +/- axis_45, again neither a
    # pure world X nor Y vector.
    assert classify_face_role(axis_45, u_dir_45, v_dir_45, axis_45) == FACE_ROLE_END_END
    assert classify_face_role(axis_45.Negate(), u_dir_45, v_dir_45, axis_45) == FACE_ROLE_END_START

    # And the SAME face normal, misread against the WRONG (world, +X)
    # frame, is oblique to every one of that frame's own directions (its
    # dot products with u/v/axis are all ~0.707, none above tolerance) and
    # so REFUSES rather than silently classifying as anything at all --
    # demonstrating why `beam_section_axes`' own (u_dir, v_dir, axis) must
    # be threaded through, never re-derived or approximated by a world
    # shortcut: get the frame wrong and a real END face stops classifying
    # as anything, rather than classifying as the wrong thing.
    assert classify_face_role(axis_45, U_DIR_Y, V_DIR_Z, AXIS_X) is None


def _beam_with_faces(role_normals, beam_id=101):
    """(_FakeBeamElement, _HostDataFromFaces) exposing one face per
    (role, normal, cover_mm) tuple in ``role_normals`` -- ``role`` unused by
    the fakes themselves, kept only for readability at each call site.

    Faces sharing the same ``cover_mm`` value get the SAME
    ``FakeRebarCoverType`` instance (and so the same ``Id``) -- otherwise
    every call would mint a distinct auto-incremented id per face even for
    an intentionally-equal cover, which would spuriously fail the two-SIDE-
    faces-must-match check these fakes exist to exercise.
    """
    faces_by_reference = {}
    cover_by_reference = {}
    covers_by_value = {}
    for index, (_role, normal, cover_mm) in enumerate(role_normals):
        reference = FakeReference("face-{}".format(index))
        faces_by_reference[reference] = FakeFace(normal)
        if cover_mm is None:
            cover_by_reference[reference] = None
            continue
        if cover_mm not in covers_by_value:
            covers_by_value[cover_mm] = FakeRebarCoverType(_ft(cover_mm), name="Interior")
        cover_by_reference[reference] = covers_by_value[cover_mm]
    beam = _FakeBeamElement(beam_id, faces_by_reference)
    host_data = _HostDataFromFaces(cover_by_reference)
    return beam, host_data


def test_read_beam_face_covers_reads_top_bottom_and_side_four_face_supported_beam():
    """The live-host shape (issue #23): a SUPPORTED beam exposes exactly
    FOUR faces -- TOP, BOTTOM, two SIDEs -- and NO end face at all."""
    beam, host_data = _beam_with_faces([
        ("TOP", FakeXYZ(0, 0, 1), 38.1),
        ("SIDE", FakeXYZ(0, -1, 0), 38.1),
        ("BOTTOM", FakeXYZ(0, 0, -1), 38.1),
        ("SIDE", FakeXYZ(0, 1, 0), 38.1),
    ])
    covers = read_beam_face_covers_mm(
        beam, host_data, U_DIR_Y, V_DIR_Z, AXIS_X, from_internal_units=lambda v: v / FT_PER_MM,
        element_id=beam.Id,
    )
    assert covers.top_mm == pytest.approx(38.1)
    assert covers.bottom_mm == pytest.approx(38.1)
    assert covers.side_mm == pytest.approx(38.1)
    assert covers.end_start_mm is None
    assert covers.end_end_mm is None


def test_read_beam_face_covers_end_not_requested_on_a_supported_beam_is_not_an_error():
    """Requesting neither end face (both ends supported) must succeed even
    though no end face is exposed at all -- the whole point of issue #30's
    `need_end_start`/`need_end_end` flags."""
    beam, host_data = _beam_with_faces([
        ("TOP", FakeXYZ(0, 0, 1), 38.1),
        ("SIDE", FakeXYZ(0, -1, 0), 38.1),
        ("BOTTOM", FakeXYZ(0, 0, -1), 38.1),
        ("SIDE", FakeXYZ(0, 1, 0), 38.1),
    ])
    covers = read_beam_face_covers_mm(
        beam, host_data, U_DIR_Y, V_DIR_Z, AXIS_X, from_internal_units=lambda v: v / FT_PER_MM,
        element_id=beam.Id, need_end_start=False, need_end_end=False,
    )
    assert covers.end_start_mm is None
    assert covers.end_end_mm is None


def test_read_beam_face_covers_raises_when_a_required_end_face_is_missing():
    """A missing end face at an UNSUPPORTED end is a refusal, never a
    fallback to another face's cover (issue #30 acceptance criterion)."""
    beam, host_data = _beam_with_faces([
        ("TOP", FakeXYZ(0, 0, 1), 38.1),
        ("SIDE", FakeXYZ(0, -1, 0), 38.1),
        ("BOTTOM", FakeXYZ(0, 0, -1), 38.1),
        ("SIDE", FakeXYZ(0, 1, 0), 38.1),
    ])
    with pytest.raises(HostValidationError, match="No END .start. face exposed"):
        read_beam_face_covers_mm(
            beam, host_data, U_DIR_Y, V_DIR_Z, AXIS_X, from_internal_units=lambda v: v / FT_PER_MM,
            element_id=beam.Id, need_end_start=True,
        )


def test_read_beam_face_covers_reads_end_face_when_present_and_required():
    beam, host_data = _beam_with_faces([
        ("TOP", FakeXYZ(0, 0, 1), 38.1),
        ("SIDE", FakeXYZ(0, -1, 0), 38.1),
        ("BOTTOM", FakeXYZ(0, 0, -1), 38.1),
        ("SIDE", FakeXYZ(0, 1, 0), 38.1),
        ("END_START", FakeXYZ(-1, 0, 0), 25.0),
    ])
    covers = read_beam_face_covers_mm(
        beam, host_data, U_DIR_Y, V_DIR_Z, AXIS_X, from_internal_units=lambda v: v / FT_PER_MM,
        element_id=beam.Id, need_end_start=True,
    )
    assert covers.end_start_mm == pytest.approx(25.0)


def test_read_beam_face_covers_raises_on_undefined_cover_rather_than_silently_defaulting():
    beam, host_data = _beam_with_faces([
        ("TOP", FakeXYZ(0, 0, 1), None),
        ("SIDE", FakeXYZ(0, -1, 0), 38.1),
        ("BOTTOM", FakeXYZ(0, 0, -1), 38.1),
        ("SIDE", FakeXYZ(0, 1, 0), 38.1),
    ])
    with pytest.raises(HostValidationError, match="document default"):
        read_beam_face_covers_mm(
            beam, host_data, U_DIR_Y, V_DIR_Z, AXIS_X, from_internal_units=lambda v: v / FT_PER_MM,
            element_id=beam.Id,
        )


def test_read_beam_face_covers_raises_on_oblique_face_naming_it_rather_than_guessing():
    oblique_normal = FakeXYZ(0.7, 0.7, 0.14).Normalize()
    beam, host_data = _beam_with_faces([
        ("TOP", FakeXYZ(0, 0, 1), 38.1),
        ("SIDE", FakeXYZ(0, -1, 0), 38.1),
        ("BOTTOM", FakeXYZ(0, 0, -1), 38.1),
        ("OBLIQUE", oblique_normal, 38.1),
    ])
    with pytest.raises(HostValidationError, match="oblique"):
        read_beam_face_covers_mm(
            beam, host_data, U_DIR_Y, V_DIR_Z, AXIS_X, from_internal_units=lambda v: v / FT_PER_MM,
            element_id=beam.Id,
        )


def test_read_beam_face_covers_two_side_faces_with_equal_cover_ids_pass():
    cover_a = FakeRebarCoverType(_ft(38.1), name="Interior (framing, columns)", id_value=42)
    cover_b = FakeRebarCoverType(_ft(38.1), name="Interior (framing, columns)", id_value=42)
    faces_by_reference = {
        FakeReference("top"): FakeFace(FakeXYZ(0, 0, 1)),
        FakeReference("bottom"): FakeFace(FakeXYZ(0, 0, -1)),
        FakeReference("side-a"): FakeFace(FakeXYZ(0, -1, 0)),
        FakeReference("side-b"): FakeFace(FakeXYZ(0, 1, 0)),
    }
    refs = list(faces_by_reference.keys())
    cover_by_reference = dict(zip(refs, [
        FakeRebarCoverType(_ft(38.1)), FakeRebarCoverType(_ft(38.1)), cover_a, cover_b,
    ]))
    beam = _FakeBeamElement(101, faces_by_reference)
    host_data = _HostDataFromFaces(cover_by_reference)
    covers = read_beam_face_covers_mm(
        beam, host_data, U_DIR_Y, V_DIR_Z, AXIS_X, from_internal_units=lambda v: v / FT_PER_MM,
        element_id=beam.Id,
    )
    assert covers.side_mm == pytest.approx(38.1)


def test_read_beam_face_covers_two_side_faces_same_name_different_id_refuses():
    """The live model's own trap (issue #23/#30): two `RebarCoverType`
    elements sharing the identical Name (`Interior (framing, columns)`) but
    different Ids and different CoverDistance values. Comparing by name
    would silently accept this; comparing by id must refuse."""
    cover_a = FakeRebarCoverType(_ft(38.1), name="Interior (framing, columns)", id_value=1)
    cover_b = FakeRebarCoverType(_ft(40.0), name="Interior (framing, columns)", id_value=2)
    faces_by_reference = {
        FakeReference("top"): FakeFace(FakeXYZ(0, 0, 1)),
        FakeReference("bottom"): FakeFace(FakeXYZ(0, 0, -1)),
        FakeReference("side-a"): FakeFace(FakeXYZ(0, -1, 0)),
        FakeReference("side-b"): FakeFace(FakeXYZ(0, 1, 0)),
    }
    refs = list(faces_by_reference.keys())
    cover_by_reference = dict(zip(refs, [
        FakeRebarCoverType(_ft(38.1)), FakeRebarCoverType(_ft(38.1)), cover_a, cover_b,
    ]))
    beam = _FakeBeamElement(101, faces_by_reference)
    host_data = _HostDataFromFaces(cover_by_reference)
    with pytest.raises(HostValidationError, match="different cover types"):
        read_beam_face_covers_mm(
            beam, host_data, U_DIR_Y, V_DIR_Z, AXIS_X, from_internal_units=lambda v: v / FT_PER_MM,
            element_id=beam.Id,
        )


def test_read_support_side_cover_mm_start_support_reads_the_far_face():
    """Section 2.2's `a = support_width - cover` measures `a` inward from
    the face the bar ENTERS, so the tip stops `cover` short of the FAR
    face -- and it is the far face's own cover that governs. For the start
    support that face's outward normal is -axis_direction, pointing AWAY
    from the span, not toward the beam.

    The two faces carry deliberately different covers (38.1 vs 999.0) so
    that reading the entry face instead would fail this test loudly rather
    than coincide, as it would on a support with equal cover all round."""
    support = _FakeBeamElement(501, {
        FakeReference("far (away from span, -axis)"): FakeFace(AXIS_X.Negate()),
        FakeReference("entry (toward span, +axis)"): FakeFace(AXIS_X),
        FakeReference("side"): FakeFace(FakeXYZ(0, 1, 0)),
    })
    refs = list(support._faces_by_reference.keys())
    host_data = _HostDataFromFaces(dict(zip(refs, [
        FakeRebarCoverType(_ft(38.1)), FakeRebarCoverType(_ft(999.0)), FakeRebarCoverType(_ft(999.0)),
    ])))
    cover_mm = read_support_side_cover_mm(
        support, host_data, AXIS_X, True, from_internal_units=lambda v: v / FT_PER_MM,
        element_id=support.Id,
    )
    assert cover_mm == pytest.approx(38.1)


def test_read_support_side_cover_mm_end_support_reads_the_far_face_mirrored():
    """Mirror of the start-support case: at the END support the bar enters
    through the -axis face and its tip approaches the +axis face, so the
    sign flips and the far face is the +axis one."""
    support = _FakeBeamElement(502, {
        FakeReference("entry (toward span, -axis)"): FakeFace(AXIS_X.Negate()),
        FakeReference("far (beyond beam end, +axis)"): FakeFace(AXIS_X),
    })
    refs = list(support._faces_by_reference.keys())
    host_data = _HostDataFromFaces(dict(zip(refs, [
        FakeRebarCoverType(_ft(999.0)), FakeRebarCoverType(_ft(38.1)),
    ])))
    cover_mm = read_support_side_cover_mm(
        support, host_data, AXIS_X, False, from_internal_units=lambda v: v / FT_PER_MM,
        element_id=support.Id,
    )
    assert cover_mm == pytest.approx(38.1)


def test_read_support_side_cover_mm_no_aligned_face_refuses():
    support = _FakeBeamElement(503, {
        FakeReference("side-a"): FakeFace(FakeXYZ(0, 1, 0)),
        FakeReference("side-b"): FakeFace(FakeXYZ(0, -1, 0)),
    })
    refs = list(support._faces_by_reference.keys())
    host_data = _HostDataFromFaces(dict(zip(refs, [
        FakeRebarCoverType(_ft(38.1)), FakeRebarCoverType(_ft(38.1)),
    ])))
    with pytest.raises(HostValidationError, match="No exposed face"):
        read_support_side_cover_mm(
            support, host_data, AXIS_X, True, from_internal_units=lambda v: v / FT_PER_MM,
            element_id=support.Id,
        )


def test_face_normal_resolves_reference_via_get_geometry_object_and_normalises():
    """Confirmed live (issue #23):
    ``Element.GetGeometryObjectFromReference(Reference).ComputeNormal(UV)``.
    ``FakeReference`` has no custom ``__eq__``, so the SAME reference
    object identity must be used to both build the beam's face dict and
    look it up here -- matching the real API's Reference-as-opaque-handle
    behaviour."""
    reference = FakeReference("f")
    beam = _FakeBeamElement(101, {reference: FakeFace(FakeXYZ(2.0, 0.0, 0.0))})
    normal = face_normal(beam, reference)
    assert normal.X == pytest.approx(1.0)
    assert normal.Y == pytest.approx(0.0)
    assert normal.Z == pytest.approx(0.0)


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


# --- Issue #16 (S3): main bar cross-section layout -> support-face points ---


def test_bar_face_points_at_uv_applies_centroid_correction_and_bar_offset():
    """Issue #16: du/dv (curve-to-centroid correction) and the bar's own
    (u, v) mm coordinate must BOTH land in the final face point -- neither
    alone is correct (issue #18 review findings #1/#2, reused here)."""
    face_start = FakeXYZ(0, 0, 0)
    face_end = FakeXYZ(6000, 0, 0)
    u_dir = FakeXYZ(0, 1, 0)
    v_dir = FakeXYZ(0, 0, 1)

    bar_start, bar_end = bar_face_points_at_uv(
        face_start, face_end, u_dir, v_dir,
        du_internal=10.0, dv_internal=-300.0,  # centroid correction, internal units
        u_mm=107.0, v_mm=-257.0,  # bar's own centroid-local (u, v), mm
        to_internal_units=_to_internal,
    )

    expected_u_internal = 10.0 + _to_internal(107.0)
    expected_v_internal = -300.0 + _to_internal(-257.0)
    assert bar_start.X == pytest.approx(0.0)
    assert bar_start.Y == pytest.approx(expected_u_internal)
    assert bar_start.Z == pytest.approx(expected_v_internal)
    assert bar_end.X == pytest.approx(6000.0)
    assert bar_end.Y == pytest.approx(expected_u_internal)
    assert bar_end.Z == pytest.approx(expected_v_internal)


def test_bar_face_points_at_uv_matches_plain_offset_when_centroid_correction_is_zero():
    face_start = FakeXYZ(0, 0, 0)
    face_end = FakeXYZ(6000, 0, 0)
    u_dir = FakeXYZ(0, 1, 0)
    v_dir = FakeXYZ(0, 0, 1)

    bar_start, bar_end = bar_face_points_at_uv(
        face_start, face_end, u_dir, v_dir,
        du_internal=0.0, dv_internal=0.0,
        u_mm=100.0, v_mm=200.0,
        to_internal_units=_to_internal,
    )
    assert bar_start.Y == pytest.approx(_to_internal(100.0))
    assert bar_start.Z == pytest.approx(_to_internal(200.0))


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


# --- Issue #15 (S2): full end anchorage, mixed bent/straight ends ----------


def test_bar_point_at_uv_applies_centroid_correction_and_bar_offset_single_point():
    """Single-end variant of ``bar_face_points_at_uv`` (issue #15): same
    both-offsets-must-combine check, but for one reference point rather
    than a matched start/end pair, since a beam's two ends can now differ."""
    reference_point = FakeXYZ(0, 0, 0)
    u_dir = FakeXYZ(0, 1, 0)
    v_dir = FakeXYZ(0, 0, 1)

    point = bar_point_at_uv(
        reference_point, u_dir, v_dir,
        du_internal=10.0, dv_internal=-300.0,
        u_mm=107.0, v_mm=-257.0,
        to_internal_units=_to_internal,
    )

    assert point.Y == pytest.approx(10.0 + _to_internal(107.0))
    assert point.Z == pytest.approx(-300.0 + _to_internal(-257.0))


def test_bent_end_corner_matches_build_bottom_bar_curves_datum():
    """``bent_end_corner`` must reproduce the SAME corner points
    ``build_bottom_bar_curves`` already computes inline, for both ends'
    sign conventions -- this is a refactor, not a behaviour change."""
    face_start = FakeXYZ(0, 0, 0)
    face_end = FakeXYZ(6000, 0, 0)
    axis_direction = FakeXYZ(1, 0, 0)

    corner_start = bent_end_corner(face_start, axis_direction, a_internal=559, toward_span=True)
    corner_end = bent_end_corner(face_end, axis_direction, a_internal=275, toward_span=False)

    assert corner_start == FakeXYZ(-559, 0, 0)
    assert corner_end == FakeXYZ(6275, 0, 0)


def test_unsupported_end_corner_moves_inward_from_the_beam_end_by_cover():
    """R3 resolved: the straight run terminates at `beam end - cover` --
    moved INWARD (toward the span) from the beam's own physical end point
    by the cover, for both ends' sign conventions."""
    beam_start = FakeXYZ(0, 0, 0)
    beam_end = FakeXYZ(6000, 0, 0)
    axis_direction = FakeXYZ(1, 0, 0)
    cover_internal = 25.0

    start_corner = unsupported_end_corner(beam_start, axis_direction, cover_internal, toward_span=True)
    end_corner = unsupported_end_corner(beam_end, axis_direction, cover_internal, toward_span=False)

    assert start_corner == FakeXYZ(25.0, 0, 0)  # moved +axis, INTO the span
    assert end_corner == FakeXYZ(5975.0, 0, 0)  # moved -axis, INTO the span


def test_main_bar_end_geometry_supported_end_returns_bend_leg():
    face_start = FakeXYZ(0, 0, 0)
    axis_direction = FakeXYZ(1, 0, 0)

    corner, bend = main_bar_end_geometry(
        is_supported=True, reference_point=face_start, axis_direction=axis_direction,
        toward_span=True, a_or_cover_internal=559, b_internal=200,
    )

    assert corner == FakeXYZ(-559, 0, 0)
    assert bend == 200


def test_main_bar_end_geometry_unsupported_end_returns_no_bend():
    """The §2.3 mandatory-hook rule must NOT fire at an unsupported end
    (rev 2 section 2.5, A12) -- ``bend`` must come back None, not 0 or any
    other value ``build_main_bar_curves`` could mistake for a real leg."""
    beam_end = FakeXYZ(6000, 0, 0)
    axis_direction = FakeXYZ(1, 0, 0)

    corner, bend = main_bar_end_geometry(
        is_supported=False, reference_point=beam_end, axis_direction=axis_direction,
        toward_span=False, a_or_cover_internal=25.0,
    )

    assert corner == FakeXYZ(5975.0, 0, 0)
    assert bend is None


def test_main_bar_end_geometry_supported_end_with_no_bend_is_a_straight_embedment():
    """Issue #19 (S6): a crack/skin bar's SUPPORTED end embeds straight
    into the support with NO hook (A23) -- `b_internal` is explicitly
    `None` even though `is_supported=True`. `main_bar_end_geometry` must
    still return the full `bent_end_corner` embedment point (the corner IS
    the embedment depth into the support) and `bend=None`, exactly as the
    unsupported-end case already does -- confirming reuse of this
    function for crack bars needs no new branch, only a caller that never
    passes a bend leg."""
    face_start = FakeXYZ(0, 0, 0)
    axis_direction = FakeXYZ(1, 0, 0)

    corner, bend = main_bar_end_geometry(
        is_supported=True, reference_point=face_start, axis_direction=axis_direction,
        toward_span=True, a_or_cover_internal=360, b_internal=None,
    )

    assert corner == FakeXYZ(-360, 0, 0)
    assert bend is None


def test_build_main_bar_curves_both_ends_bent_matches_three_segment_baseline():
    """Sanity check against S1's already-verified 3-segment baseline
    (``build_bottom_bar_curves``): with both ends bent, ``build_main_bar_
    curves`` must produce the identical geometry, not merely a
    same-length curve list."""
    face_start = FakeXYZ(0, 0, 0)
    face_end = FakeXYZ(6000, 0, 0)
    axis_direction = FakeXYZ(1, 0, 0)
    bend_direction = FakeXYZ.BasisZ

    baseline = build_bottom_bar_curves(
        face_start, face_end, axis_direction, bend_direction,
        a_start_internal=559, b_start_internal=200,
        a_end_internal=275, b_end_internal=605,
    )

    corner_start = bent_end_corner(face_start, axis_direction, 559, toward_span=True)
    corner_end = bent_end_corner(face_end, axis_direction, 275, toward_span=False)
    generalised = build_main_bar_curves(
        corner_start, corner_end, bend_direction,
        start_bend_internal=200, end_bend_internal=605,
    )

    assert len(generalised) == 3
    for base_curve, gen_curve in zip(baseline, generalised):
        assert base_curve[1] == gen_curve[1]
        assert base_curve[2] == gen_curve[2]


def test_build_main_bar_curves_one_end_unsupported_omits_that_bend_segment():
    """A bar bent at the start, straight (no hook) at the end: exactly TWO
    segments, not three -- issue #15's core geometric requirement, since
    the §2.3 mandatory-hook rule must not fire at the unsupported end."""
    corner_start = FakeXYZ(-559, 0, 0)
    corner_end = FakeXYZ(5975, 0, 0)  # beam end - cover, no support
    bend_direction = FakeXYZ.BasisZ

    curves = build_main_bar_curves(
        corner_start, corner_end, bend_direction,
        start_bend_internal=200, end_bend_internal=None,
    )

    assert len(curves) == 2
    bend_a_line, straight_line = curves
    assert bend_a_line[2] == corner_start
    assert bend_a_line[1] == FakeXYZ(-559, 0, 200)
    assert straight_line[1] == corner_start
    assert straight_line[2] == corner_end


def test_build_main_bar_curves_both_ends_unsupported_is_a_single_straight_segment():
    corner_start = FakeXYZ(25, 0, 0)
    corner_end = FakeXYZ(5975, 0, 0)
    bend_direction = FakeXYZ.BasisZ

    curves = build_main_bar_curves(corner_start, corner_end, bend_direction)

    assert len(curves) == 1
    assert curves[0][1] == corner_start
    assert curves[0][2] == corner_end


# --- Issue #20 (S7): RebarBarType/RebarHookType read-back -------------------


def test_bar_type_diameter_mm_reads_back_bar_nominal_diameter():
    from rft.revit.bar_types import bar_type_diameter_mm

    bar_type = FakeRebarBarType(bar_nominal_diameter=16.0 / 304.8, name="High Tensile 16mm")
    assert bar_type_diameter_mm(bar_type, from_internal_units=lambda v: v * 304.8) == pytest.approx(16.0)


def test_list_bar_types_and_hook_types_return_collector_items(monkeypatch):
    from fake_revit_api import FakeFilteredElementCollector
    from rft.revit.bar_types import list_bar_types, list_hook_types

    bar_type = FakeRebarBarType(bar_nominal_diameter=16.0, name="High Tensile 16mm")
    hook_type = FakeRebarHookType(angle_deg=180, name="Standard-180")
    monkeypatch.setattr(FakeFilteredElementCollector, "_ITEMS", [bar_type, hook_type])

    assert list_bar_types(None) == [bar_type, hook_type]
    assert list_hook_types(None) == [bar_type, hook_type]


def test_hook_angle_deg_reads_back_180_from_a_readable_hook_type():
    from rft.revit.bar_types import hook_angle_deg

    hook_type = FakeRebarHookType(angle_deg=180, name="Standard-180")
    assert hook_angle_deg(hook_type) == pytest.approx(180.0)


def test_hook_angle_deg_reads_back_a_non_180_angle_without_judging_it():
    """Reading back is separate from judging (rft.core.grades.
    hook_angle_guard_message does the judging) -- this only proves the
    read-back itself is faithful to whatever the fake carries."""
    from rft.revit.bar_types import hook_angle_deg

    hook_type = FakeRebarHookType(angle_deg=90, name="Standard-90")
    assert hook_angle_deg(hook_type) == pytest.approx(90.0)


def test_hook_angle_deg_returns_none_when_unreadable():
    """Issue #25's 'cannot be read back at all' case: get_Parameter comes
    back None. Must return None, not raise and not guess 180."""
    from rft.revit.bar_types import hook_angle_deg

    hook_type = FakeRebarHookType(angle_deg=None, name="Unknown hook")
    assert hook_angle_deg(hook_type) is None


def test_hook_angle_deg_returns_none_when_get_parameter_is_missing_entirely():
    """A hook-type stand-in with no get_Parameter method at all (a
    different, equally plausible wrong-shape scenario) must also come back
    None rather than raising AttributeError up into the pushbutton."""
    from rft.revit.bar_types import hook_angle_deg

    class _NoParameterHookType(object):
        pass

    assert hook_angle_deg(_NoParameterHookType()) is None


# --- Issue #27 (A42): per-role RebarBarType resolution and reworked -------
# --- Place Main Bars' diameter source, verified at the adapter boundary --


def test_bar_type_diameter_mm_reads_top_and_bottom_types_independently():
    """A42's whole point: a top RebarBarType and a bottom RebarBarType can
    carry DIFFERENT diameters (the default 12/16 mm case) -- each read
    independently through the same adapter function, no shared state."""
    from rft.revit.bar_types import bar_type_diameter_mm

    top_type = FakeRebarBarType(bar_nominal_diameter=12.0 / 304.8, name="High Tensile 12mm")
    btm_type = FakeRebarBarType(bar_nominal_diameter=16.0 / 304.8, name="High Tensile 16mm")

    dia_top_mm = bar_type_diameter_mm(top_type, from_internal_units=lambda v: v * 304.8)
    dia_btm_mm = bar_type_diameter_mm(btm_type, from_internal_units=lambda v: v * 304.8)

    assert dia_top_mm == pytest.approx(12.0)
    assert dia_btm_mm == pytest.approx(16.0)


def test_top_bar_anchorage_uses_the_bottom_bar_types_diameter_not_the_top_bar_types():
    """The §2.2/A7 cross-dependency this ticket's instructions flagged by
    name: `a_t = Support width - Cover - O_BTM` -- so the value threaded
    into ``top_bar_anchorage`` after A42's rework must still be the
    BOTTOM RebarBarType's own diameter (Ø16 here), never the TOP
    RebarBarType's own diameter (Ø12) it is placed alongside. Proven by
    showing the reworked call disagrees with what a same-diameter-both-
    ways mistake would produce."""
    from rft.revit.bar_types import bar_type_diameter_mm

    top_type = FakeRebarBarType(bar_nominal_diameter=12.0 / 304.8, name="High Tensile 12mm")
    btm_type = FakeRebarBarType(bar_nominal_diameter=16.0 / 304.8, name="High Tensile 16mm")

    dia_top_mm = bar_type_diameter_mm(top_type, from_internal_units=lambda v: v * 304.8)
    dia_btm_mm = bar_type_diameter_mm(btm_type, from_internal_units=lambda v: v * 304.8)

    correct = top_bar_anchorage(
        support_width_mm=300, support_cover_mm=25, bottom_bar_diameter_mm=dia_btm_mm, ld_top_mm=720
    )
    wrong_if_using_top_diameter = top_bar_anchorage(
        support_width_mm=300, support_cover_mm=25, bottom_bar_diameter_mm=dia_top_mm, ld_top_mm=720
    )

    assert correct.a != pytest.approx(wrong_if_using_top_diameter.a)
    # a_t = 300 - 25 - 16 = 259, capped by LD - 200 = 520 -- comfortably
    # under the cap, so the formula value is what is actually built.
    assert correct.a == pytest.approx(300 - 25 - dia_btm_mm)


class _FakeDocGetElement(object):
    """``FakeElementId`` defines ``__eq__`` but not ``__hash__`` (matching
    plain equality semantics assumed for a real ``ElementId``), so this
    looks up by equality over a list of pairs rather than a dict keyed by
    id."""

    def __init__(self, elements_by_id):
        self._pairs = list(elements_by_id)

    def GetElement(self, element_id):
        for id_, element in self._pairs:
            if id_ == element_id:
                return element
        return None
