"""Unit tests for rft.core.stirrups: leg geometry, closure types, and
3-zone distribution math (rev 2 sections 3 and 7). Pure Python, no Revit
imports needed -- runs under plain CPython.
"""

import pytest

from rft.core.stirrups import (
    EDGE_OFFSET_MM,
    TYPE3_PARKED_MESSAGE,
    ZONE_LAYOUT_FLAGS,
    ZoneMM,
    centreline_leg_dimensions_mm,
    is_closed_type,
    stirrup_count_and_spacing,
    stirrup_curve_endpoints_mm,
    stirrup_zones_mm,
    zone_array_length_mm,
    _rectangle_corners_mm,
)


# --- §7.1 centreline rectangle arithmetic ----------------------------------


def test_centreline_leg_dimensions_subtracts_one_full_diameter_per_side():
    width_mm, height_mm = centreline_leg_dimensions_mm(
        b_mm=300.0, h_mm=600.0, cover_mm=25.0, stirrup_dia_mm=10.0
    )
    assert width_mm == pytest.approx(300.0 - 2 * 25.0 - 10.0)
    assert height_mm == pytest.approx(600.0 - 2 * 25.0 - 10.0)
    assert width_mm == pytest.approx(240.0)
    assert height_mm == pytest.approx(540.0)


def test_centreline_leg_dimensions_matches_spacer_length_check_1():
    """§7.1 Check 1: the spacer spans between the inner faces of the two
    vertical legs, b - 2*Cover - 2*O_stirrup -- one full diameter less than
    the centreline width (whose ½O per side already accounts for one leg
    thickness, not two)."""
    b_mm, cover_mm, dia_mm = 300.0, 25.0, 10.0
    width_mm, _ = centreline_leg_dimensions_mm(b_mm, 600.0, cover_mm, dia_mm)
    spacer_length_mm = b_mm - 2 * cover_mm - 2 * dia_mm
    assert width_mm - dia_mm == pytest.approx(spacer_length_mm)


# --- §7.2 closure types -----------------------------------------------------


def test_type3_is_rejected_with_parked_message():
    with pytest.raises(ValueError) as excinfo:
        stirrup_curve_endpoints_mm(3, 240.0, 540.0)
    assert str(excinfo.value) == TYPE3_PARKED_MESSAGE
    assert "inner loop" in str(excinfo.value)


def test_unsupported_closure_type_raises():
    with pytest.raises(ValueError, match="Unsupported stirrup closure type"):
        stirrup_curve_endpoints_mm(5, 240.0, 540.0)


def test_type1_and_type2_share_loop_and_winding_only_start_corner_differs():
    width_mm, height_mm = 240.0, 540.0
    type1 = stirrup_curve_endpoints_mm(1, width_mm, height_mm)
    type2 = stirrup_curve_endpoints_mm(2, width_mm, height_mm)

    assert len(type1) == 4
    assert len(type2) == 4

    # Same closed loop: as a cyclic rotation of directed edges, the two
    # must line up with the same winding direction, not an independently
    # authored / reversed shape. tuples of tuples are hashable.
    type1_t = tuple(tuple(map(tuple, e)) for e in type1)
    type2_t = tuple(tuple(map(tuple, e)) for e in type2)
    assert type2_t in {tuple(r) for r in _cyclic_rotations(type1_t)}

    # But the hook-overlap corner (curves[0] start point) differs.
    assert type1[0][0] != type2[0][0]


def _cyclic_rotations(seq):
    return [seq[i:] + seq[:i] for i in range(len(seq))]


def test_type1_hook_overlap_is_top_right_type2_is_top_left():
    width_mm, height_mm = 240.0, 540.0
    hw, hh = width_mm / 2.0, height_mm / 2.0
    type1 = stirrup_curve_endpoints_mm(1, width_mm, height_mm)
    type2 = stirrup_curve_endpoints_mm(2, width_mm, height_mm)
    assert type1[0][0] == (hw, hh)  # top-right
    assert type2[0][0] == (-hw, hh)  # top-left
    # Closed loop: last curve ends back where the first started.
    assert type1[-1][1] == type1[0][0]
    assert type2[-1][1] == type2[0][0]


def test_type4_is_open_u_with_no_top_closure():
    width_mm, height_mm = 240.0, 540.0
    hw, hh = width_mm / 2.0, height_mm / 2.0
    curves = stirrup_curve_endpoints_mm(4, width_mm, height_mm)
    assert len(curves) == 3  # not 4 -- no closing top segment
    # Two free ends, both at the top.
    assert curves[0][0] == (-hw, hh)
    assert curves[-1][1] == (hw, hh)
    # Not closed: the free ends are distinct points.
    assert curves[0][0] != curves[-1][1]


def test_is_closed_type():
    assert is_closed_type(1) is True
    assert is_closed_type(2) is True
    assert is_closed_type(4) is False


def test_starting_corner_rotation_produces_four_distinct_corners():
    """Ticket-mandated coverage: rotating the starting-corner index around
    the same rectangle produces 4 physically distinct corner points, never
    a reversed winding."""
    width_mm, height_mm = 240.0, 540.0
    corners_by_start = {
        name: _rectangle_corners_mm(width_mm, height_mm, name)[0]
        for name in ("top_right", "top_left", "bottom_left", "bottom_right")
    }
    starts = list(corners_by_start.values())
    assert len(set(starts)) == 4  # all four distinct

    # Winding direction is preserved across every rotation (each is a
    # cyclic rotation of the same 4-tuple, never reversed).
    base = _rectangle_corners_mm(width_mm, height_mm, "top_right")
    for name in ("top_left", "bottom_left", "bottom_right"):
        rotated = _rectangle_corners_mm(width_mm, height_mm, name)
        assert rotated in _cyclic_rotations(base) or rotated == base


# --- §3.1 zone clipping arithmetic ------------------------------------------


def test_stirrup_zones_normal_case():
    # L = 6000, face_A offset = 250 (500-wide column), face_B offset = 300
    zones = stirrup_zones_mm(l_mm=6000.0, face_a_offset_mm=250.0, face_b_offset_mm=300.0)
    assert zones.zone1 == ZoneMM(250.0 + EDGE_OFFSET_MM, 2000.0)
    assert zones.zone2 == ZoneMM(2000.0, 4000.0)
    assert zones.zone3 == ZoneMM(4000.0, 6000.0 - 300.0 - EDGE_OFFSET_MM)


def test_stirrup_zones_are_mirrored_50mm_from_each_face():
    zones = stirrup_zones_mm(l_mm=9000.0, face_a_offset_mm=200.0, face_b_offset_mm=200.0)
    assert zones.zone1.start == pytest.approx(200.0 + EDGE_OFFSET_MM)
    assert zones.zone3.end == pytest.approx(9000.0 - 200.0 - EDGE_OFFSET_MM)


def test_dense_zones_are_shorter_than_l_over_3_a16_consequence():
    zones = stirrup_zones_mm(l_mm=9000.0, face_a_offset_mm=200.0, face_b_offset_mm=200.0)
    third = 9000.0 / 3.0
    assert zone_array_length_mm(zones.zone1) < third
    assert zone_array_length_mm(zones.zone3) < third
    assert zone_array_length_mm(zones.zone2) == pytest.approx(third)


def test_degenerate_guard_fires_at_zone1_short_span():
    # face_A + 50 exactly equals L/3 -> must raise (>=), not silently clip.
    l_mm = 900.0
    face_a_offset_mm = (l_mm / 3.0) - EDGE_OFFSET_MM  # region_start == L/3
    with pytest.raises(ValueError, match="Zone 1"):
        stirrup_zones_mm(l_mm=l_mm, face_a_offset_mm=face_a_offset_mm, face_b_offset_mm=50.0)


def test_degenerate_guard_fires_at_zone1_wide_support():
    with pytest.raises(ValueError, match="Zone 1"):
        stirrup_zones_mm(l_mm=1000.0, face_a_offset_mm=500.0, face_b_offset_mm=50.0)


def test_degenerate_guard_fires_at_zone3_short_span():
    l_mm = 900.0
    face_b_offset_mm = (l_mm / 3.0) - EDGE_OFFSET_MM  # region_end == 2L/3
    with pytest.raises(ValueError, match="Zone 3"):
        stirrup_zones_mm(l_mm=l_mm, face_a_offset_mm=50.0, face_b_offset_mm=face_b_offset_mm)


def test_degenerate_guard_fires_at_zone3_wide_support():
    with pytest.raises(ValueError, match="Zone 3"):
        stirrup_zones_mm(l_mm=1000.0, face_a_offset_mm=50.0, face_b_offset_mm=500.0)


def test_degenerate_guard_does_not_fire_just_above_the_boundary():
    # One mm of slack should be fine.
    l_mm = 900.0
    face_a_offset_mm = (l_mm / 3.0) - EDGE_OFFSET_MM - 1.0
    zones = stirrup_zones_mm(l_mm=l_mm, face_a_offset_mm=face_a_offset_mm, face_b_offset_mm=50.0)
    assert zone_array_length_mm(zones.zone1) == pytest.approx(1.0)


# --- §3.2 spacing semantics --------------------------------------------------


def test_stirrup_count_and_spacing_exact_multiple():
    # array_length exactly divisible by max_spacing: no tightening needed.
    # Both boundary bars included (dense-zone flags): 4 spaces + 1.
    result = stirrup_count_and_spacing(
        array_length_mm=600.0, max_spacing_mm=150.0,
        include_first_bar=True, include_last_bar=True,
    )
    assert result.count == 5  # 4 spaces + 1
    assert result.spacing_mm == pytest.approx(150.0)


def test_stirrup_count_and_spacing_non_multiple_tightens_spacing():
    # 610 / 150 -> 4.07 -> ceil to 5 spaces, spacing tightens to 122 <= 150.
    result = stirrup_count_and_spacing(
        array_length_mm=610.0, max_spacing_mm=150.0,
        include_first_bar=True, include_last_bar=True,
    )
    assert result.count == 6
    assert result.spacing_mm == pytest.approx(610.0 / 5.0)
    assert result.spacing_mm <= 150.0


def test_stirrup_count_and_spacing_exact_minimum_spacing_case():
    # array_length equal to exactly one max_spacing: minimum valid layout,
    # 2 bars, 1 space.
    result = stirrup_count_and_spacing(
        array_length_mm=150.0, max_spacing_mm=150.0,
        include_first_bar=True, include_last_bar=True,
    )
    assert result.count == 2
    assert result.spacing_mm == pytest.approx(150.0)


def test_stirrup_count_and_spacing_rejects_non_positive_inputs():
    with pytest.raises(ValueError):
        stirrup_count_and_spacing(
            array_length_mm=0.0, max_spacing_mm=150.0,
            include_first_bar=True, include_last_bar=True,
        )
    with pytest.raises(ValueError):
        stirrup_count_and_spacing(
            array_length_mm=100.0, max_spacing_mm=0.0,
            include_first_bar=True, include_last_bar=True,
        )


# --- issue #18 review finding #1: flag-aware count ---------------------


def test_stirrup_count_is_flag_aware_for_the_l6000_600col_worked_example():
    """L=6000, 600 mm columns (face offsets 300 each), normal max spacing
    200 mm. Zone 2 = [2000, 4000], array length 2000, n_spaces = 10 ->
    the function must report 9 (the placed count with (False, False)), not
    the boundary-inclusive 11 -- the 11-vs-9 discrepancy from the review
    must never regress silently. Zones 1/3 use dense spacing 150 mm and
    keep (True, True), so their count is unaffected by the fix."""
    zones = stirrup_zones_mm(l_mm=6000.0, face_a_offset_mm=300.0, face_b_offset_mm=300.0)
    zone2_len = zone_array_length_mm(zones.zone2)
    assert zone2_len == pytest.approx(2000.0)

    zone2_result = stirrup_count_and_spacing(
        array_length_mm=zone2_len, max_spacing_mm=200.0,
        include_first_bar=False, include_last_bar=False,
    )
    assert zone2_result.count == 9
    assert zone2_result.spacing_mm == pytest.approx(200.0)

    zone1_result = stirrup_count_and_spacing(
        array_length_mm=zone_array_length_mm(zones.zone1), max_spacing_mm=150.0,
        include_first_bar=True, include_last_bar=True,
    )
    zone3_result = stirrup_count_and_spacing(
        array_length_mm=zone_array_length_mm(zones.zone3), max_spacing_mm=150.0,
        include_first_bar=True, include_last_bar=True,
    )
    assert zone1_result.count == 12
    assert zone3_result.count == 12
    beam_total = zone1_result.count + zone2_result.count + zone3_result.count
    assert beam_total == 33  # 12 + 9 + 12, not 12 + 11 + 12 = 35 pre-fix


def test_stirrup_count_zero_flags_can_drop_count_to_zero_or_below_and_raises():
    # A single space (n_spaces == 1) with both boundary bars excluded
    # leaves nothing to place: n_spaces + 1 - 1 - 1 == 0. Raise, rather
    # than silently reporting a zero-count zone as if it were valid.
    with pytest.raises(ValueError, match="no stirrups to place"):
        stirrup_count_and_spacing(
            array_length_mm=100.0, max_spacing_mm=150.0,
            include_first_bar=False, include_last_bar=False,
        )


# --- R4 mitigation: zone-boundary de-duplication guard ----------------------


def test_zone_layout_flags_claim_each_boundary_exactly_once():
    """R4 stays OPEN (cannot be resolved without a live host) -- this only
    verifies the chosen mitigation's own internal consistency: the dense
    zones (1, 3) include both of their boundary stirrups; the normal zone
    (2) includes neither of its boundary stirrups. So the L/3 boundary is
    claimed only by zone 1's last bar, and 2L/3 only by zone 3's first bar
    -- never by both adjoining zones at once."""
    assert ZONE_LAYOUT_FLAGS["zone1"] == (True, True)
    assert ZONE_LAYOUT_FLAGS["zone2"] == (False, False)
    assert ZONE_LAYOUT_FLAGS["zone3"] == (True, True)
