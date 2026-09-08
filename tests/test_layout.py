"""Unit tests for rft.core.layout: layer offsets, corner-bar horizontal
distribution, spacer length, and the R1 warning (rev 2 sections 4, 4.1,
6.1, 6.3). Pure Python, no Revit imports needed -- runs under plain
CPython.
"""

import pytest

from rft.core.layout import (
    MAX_LAYERS,
    corner_bar_side_offset_mm,
    corner_bar_u_positions_mm,
    first_layer_offset_mm,
    layer_offset_mm,
    spacer_diameter_warning,
    spacer_length_mm,
)


# --- §4 first-layer offset ---------------------------------------------------


def test_first_layer_offset_bottom_face():
    # Cover 25, O_stirrup 10, O_BTM 16 -> 25 + 10 + 8 = 43
    assert first_layer_offset_mm(25.0, 10.0, 16.0) == pytest.approx(43.0)


def test_first_layer_offset_top_face_independent_diameter():
    # Same cover/stirrup, different O_TOP -> different offset (independent
    # per face, §4).
    assert first_layer_offset_mm(25.0, 10.0, 12.0) == pytest.approx(41.0)


def test_layer_offset_n1_equals_first_layer_offset():
    assert layer_offset_mm(25.0, 10.0, 16.0, 16.0, 1) == pytest.approx(
        first_layer_offset_mm(25.0, 10.0, 16.0)
    )


# --- §4.1 multi-layer accumulation, n = 2..5, differing top/bottom dia -------


@pytest.mark.parametrize("layer_n,expected", [
    (1, 43.0),               # offset_1 = 25 + 10 + 8
    (2, 43.0 + 1 * 32.0),    # + (O_bar=16 + O_spacer=16)
    (3, 43.0 + 2 * 32.0),
    (4, 43.0 + 3 * 32.0),
    (5, 43.0 + 4 * 32.0),
])
def test_layer_offset_bottom_face_2_to_5_layers(layer_n, expected):
    assert layer_offset_mm(
        cover_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=16.0,
        spacer_dia_mm=16.0, layer_n=layer_n,
    ) == pytest.approx(expected)


@pytest.mark.parametrize("layer_n,expected", [
    (1, 41.0),               # offset_1 = 25 + 10 + 6 (O_TOP=12)
    (2, 41.0 + 1 * 28.0),    # + (O_TOP=12 + O_spacer=16)
    (3, 41.0 + 2 * 28.0),
    (4, 41.0 + 3 * 28.0),
    (5, 41.0 + 4 * 28.0),
])
def test_layer_offset_top_face_2_to_5_layers_differing_diameter(layer_n, expected):
    assert layer_offset_mm(
        cover_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=12.0,
        spacer_dia_mm=16.0, layer_n=layer_n,
    ) == pytest.approx(expected)


def test_layer_offset_top_and_bottom_diverge_with_layer_count():
    # One diameter per face (A20): top (O=12) and bottom (O=16) offsets
    # start close but diverge as layers stack, since each face accumulates
    # its OWN diameter, not a shared one.
    top_n5 = layer_offset_mm(25.0, 10.0, 12.0, 16.0, 5)
    btm_n5 = layer_offset_mm(25.0, 10.0, 16.0, 16.0, 5)
    top_n1 = layer_offset_mm(25.0, 10.0, 12.0, 16.0, 1)
    btm_n1 = layer_offset_mm(25.0, 10.0, 16.0, 16.0, 1)
    assert (btm_n5 - top_n5) > (btm_n1 - top_n1)


@pytest.mark.parametrize("layer_n", [0, 6, -1, 100])
def test_layer_offset_rejects_n_out_of_range(layer_n):
    with pytest.raises(ValueError, match="section 4.1"):
        layer_offset_mm(25.0, 10.0, 16.0, 16.0, layer_n)


def test_layer_offset_accepts_every_boundary_of_1_to_5():
    for layer_n in range(1, MAX_LAYERS + 1):
        layer_offset_mm(25.0, 10.0, 16.0, 16.0, layer_n)  # must not raise


# --- §6.3 spacer length -------------------------------------------------------


def test_spacer_length_subtracts_two_stirrup_diameters():
    # b=300, Cover=25, O_stirrup=10 -> 300 - 50 - 20 = 230
    assert spacer_length_mm(300.0, 25.0, 10.0) == pytest.approx(230.0)


def test_spacer_length_differs_from_centreline_width_by_one_diameter():
    # Deliberate asymmetry vs rft.core.stirrups.centreline_leg_dimensions_mm
    # (which subtracts only ONE stirrup diameter): the spacer spans the
    # CLEAR gap between stirrup leg inner faces, the centreline rectangle
    # is measured to the leg centrelines.
    from rft.core.stirrups import centreline_leg_dimensions_mm

    b_mm, cover_mm, dia_mm = 300.0, 25.0, 10.0
    width_mm, _ = centreline_leg_dimensions_mm(b_mm, 600.0, cover_mm, dia_mm)
    assert width_mm - dia_mm == pytest.approx(spacer_length_mm(b_mm, cover_mm, dia_mm))


# --- §6.1 corner-bar rule -----------------------------------------------------


def test_corner_bar_side_offset_matches_first_layer_offset_formula():
    assert corner_bar_side_offset_mm(25.0, 10.0, 16.0) == pytest.approx(
        first_layer_offset_mm(25.0, 10.0, 16.0)
    )


def test_corner_bar_positions_two_bars_are_just_the_corners():
    # b=300, side offset = 25+10+8=43 -> +-(150-43) = +-107
    positions = corner_bar_u_positions_mm(
        b_mm=300.0, cover_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=16.0, bar_count=2,
    )
    assert positions == pytest.approx([-107.0, 107.0])


def test_corner_bar_positions_three_bars_middle_is_centred():
    positions = corner_bar_u_positions_mm(
        b_mm=300.0, cover_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=16.0, bar_count=3,
    )
    assert positions[0] == pytest.approx(-107.0)
    assert positions[-1] == pytest.approx(107.0)
    assert positions[1] == pytest.approx(0.0)


def test_corner_bar_positions_five_bars_are_equally_spaced():
    positions = corner_bar_u_positions_mm(
        b_mm=300.0, cover_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=16.0, bar_count=5,
    )
    assert len(positions) == 5
    assert positions[0] == pytest.approx(-107.0)
    assert positions[-1] == pytest.approx(107.0)
    gaps = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
    assert gaps == pytest.approx([gaps[0]] * len(gaps))  # equal spacing


def test_corner_bar_positions_rejects_bar_count_below_2():
    with pytest.raises(ValueError, match="section 6.1"):
        corner_bar_u_positions_mm(
            b_mm=300.0, cover_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=16.0, bar_count=1,
        )
    with pytest.raises(ValueError, match="section 6.1"):
        corner_bar_u_positions_mm(
            b_mm=300.0, cover_mm=25.0, stirrup_dia_mm=10.0, bar_dia_mm=16.0, bar_count=0,
        )


# --- R1 (resolved): non-blocking spacer-diameter warning ---------------------


def test_spacer_warning_fires_when_spacer_below_horizontal_minimum():
    # O_spacer=16 under O_bar=20, D_agg=20 -> min = max(25, 20, 26.6) = 26.6
    msg = spacer_diameter_warning(spacer_dia_mm=16.0, bar_dia_mm=20.0, d_agg_mm=20.0)
    assert msg is not None
    assert "16.0" in msg
    assert "26.6" in msg or "26.60" in msg


def test_spacer_warning_does_not_fire_when_spacer_meets_minimum():
    # O_spacer=30 >= max(25, 20, 1.33*10=13.3) = 25
    msg = spacer_diameter_warning(spacer_dia_mm=30.0, bar_dia_mm=20.0, d_agg_mm=10.0)
    assert msg is None


def test_spacer_warning_exact_minimum_does_not_fire():
    # Exactly at the boundary: spacer == governing minimum -> not "< min".
    msg = spacer_diameter_warning(spacer_dia_mm=25.0, bar_dia_mm=20.0, d_agg_mm=10.0)
    assert msg is None


def test_spacer_warning_governed_by_dagg_when_it_dominates():
    # D_agg large enough that 1.33*D_agg exceeds both 25 and O_bar.
    msg = spacer_diameter_warning(spacer_dia_mm=16.0, bar_dia_mm=12.0, d_agg_mm=25.0)
    assert msg is not None
    assert "33.2" in msg or "33.25" in msg


def test_spacer_warning_governed_by_bar_diameter_when_dagg_small():
    msg = spacer_diameter_warning(spacer_dia_mm=16.0, bar_dia_mm=32.0, d_agg_mm=5.0)
    assert msg is not None
    assert "32.0" in msg
