# -*- coding: utf-8 -*-
"""#56 -- the shared placement plan.

These tests are the ones that matter most in the project: this module's
output becomes steel. Everything here is checked against the 300x900
verification beam the tool was proven on, and against the independently
authored notation drawing (docs/ui/sketch-notation.svg), so a wrong number
has to survive two unrelated sources agreeing.
"""

import pytest

from rft.core import plan
from rft.core.stirrups import centreline_leg_dimensions_mm, outer_leg_dimensions_mm

# The live-verified beam: 300 x 900, 25 mm cover, O10 stirrup, O16 mains.
B_MM, H_MM, COVER_MM = 300.0, 900.0, 25.0
STIRRUP_DIA_MM, BAR_DIA_MM, SPACER_DIA_MM = 10.0, 16.0, 16.0


def _bottom_face(layer_count=2, bar_count=3):
    return plan.face_plan(
        False, H_MM, B_MM, COVER_MM, COVER_MM, COVER_MM,
        STIRRUP_DIA_MM, BAR_DIA_MM, BAR_DIA_MM, SPACER_DIA_MM,
        bar_count, layer_count, 55.0,
        True, 400.0, 40.0, True, 400.0, 40.0,
    )


# --- layers ----------------------------------------------------------------


def test_first_layer_offset_matches_the_notation_drawing():
    """43 mm on the verification beam: 25 cover + 10 stirrup + 16/2.

    docs/ui/sketch-notation.svg was drawn from the spec by hand and states
    offset_1 = 43. Two independent derivations agreeing is worth more than
    either alone.
    """
    layers = _bottom_face(layer_count=1).layers
    assert len(layers) == 1
    assert layers[0].offset_mm == pytest.approx(43.0)


def test_second_layer_is_one_bar_plus_one_spacer_further_in():
    layers = _bottom_face(layer_count=2).layers
    assert layers[1].offset_mm - layers[0].offset_mm == pytest.approx(
        BAR_DIA_MM + SPACER_DIA_MM
    )
    assert layers[1].offset_mm == pytest.approx(75.0)


def test_bottom_layers_sit_below_the_centroid_and_top_layers_above():
    """The sign convention, which is the one thing that puts a whole cage
    outside the concrete if it is inverted."""
    bottom = _bottom_face(layer_count=2).layers
    assert all(layer.v_mm < 0 for layer in bottom)
    assert bottom[0].v_mm == pytest.approx(-H_MM / 2.0 + 43.0)

    top = plan.face_plan(
        True, H_MM, B_MM, COVER_MM, COVER_MM, COVER_MM,
        STIRRUP_DIA_MM, BAR_DIA_MM, BAR_DIA_MM, SPACER_DIA_MM, 3, 2, 60.0,
        True, 400.0, 40.0, True, 400.0, 40.0,
    ).layers
    assert all(layer.v_mm > 0 for layer in top)
    assert top[0].v_mm == pytest.approx(H_MM / 2.0 - 43.0)


def test_every_bar_lands_inside_the_concrete():
    for layer in _bottom_face(layer_count=3, bar_count=4).layers:
        assert -H_MM / 2.0 < layer.v_mm < H_MM / 2.0
        for u_mm in layer.u_positions_mm:
            assert -B_MM / 2.0 < u_mm < B_MM / 2.0


def test_layer_numbering_starts_at_one_and_is_dense():
    layers = _bottom_face(layer_count=4).layers
    assert [layer.layer_n for layer in layers] == [1, 2, 3, 4]


# --- anchorage, and A51 ----------------------------------------------------


def test_supported_end_gets_a_and_b():
    face = _bottom_face()
    assert face.start_end.a_mm is not None
    assert face.start_end.b_mm is not None
    assert face.start_end.refused_reason is None


def test_unsupported_end_has_no_hook_and_warns():
    """§2.5/A12/R3: a free end runs straight to beam-end-minus-cover, with
    no hook, and says so."""
    face = plan.face_plan(
        False, H_MM, B_MM, COVER_MM, COVER_MM, COVER_MM,
        STIRRUP_DIA_MM, BAR_DIA_MM, BAR_DIA_MM, SPACER_DIA_MM, 3, 1, 55.0,
        True, 400.0, 40.0, False, None, None,
    )
    assert face.end_end.b_mm is None
    assert face.end_end.warning is not None
    assert face.end_end.refused_reason is None


def test_a51_top_anchorage_uses_a_selected_bottom_diameter():
    """A51: the bottom face need not be PLACED for its selected bar type's
    diameter to be used -- the selection is an explicit statement of size.
    """
    with_bottom = plan.face_plan(
        True, H_MM, B_MM, COVER_MM, COVER_MM, COVER_MM,
        STIRRUP_DIA_MM, BAR_DIA_MM, 25.0, SPACER_DIA_MM, 3, 1, 60.0,
        True, 400.0, 40.0, True, 400.0, 40.0,
    )
    assert with_bottom.start_end.refused_reason is None
    assert with_bottom.start_end.a_mm is not None

    # A different bottom diameter must actually change a_t, or the
    # parameter is being ignored and this rule is decorative.
    other = plan.face_plan(
        True, H_MM, B_MM, COVER_MM, COVER_MM, COVER_MM,
        STIRRUP_DIA_MM, BAR_DIA_MM, 12.0, SPACER_DIA_MM, 3, 1, 60.0,
        True, 400.0, 40.0, True, 400.0, 40.0,
    )
    assert other.start_end.a_mm != with_bottom.start_end.a_mm


def test_a51_top_anchorage_refuses_when_no_bottom_type_is_selected():
    """The half of A51 that completes it: with no bottom type at all there
    is no diameter, and A42 forbids inventing one."""
    face = plan.face_plan(
        True, H_MM, B_MM, COVER_MM, COVER_MM, COVER_MM,
        STIRRUP_DIA_MM, BAR_DIA_MM, None, SPACER_DIA_MM, 3, 1, 60.0,
        True, 400.0, 40.0, True, 400.0, 40.0,
    )
    for end in (face.start_end, face.end_end):
        assert end.refused_reason is not None
        assert "A51" in end.refused_reason
        assert end.a_mm is None


def test_bottom_anchorage_never_needs_the_top_diameter():
    """§2.1's asymmetry: only a_t depends on the opposite face."""
    face = plan.face_plan(
        False, H_MM, B_MM, COVER_MM, COVER_MM, COVER_MM,
        STIRRUP_DIA_MM, BAR_DIA_MM, None, SPACER_DIA_MM, 3, 1, 55.0,
        True, 400.0, 40.0, True, 400.0, 40.0,
    )
    assert face.start_end.refused_reason is None
    assert face.start_end.a_mm is not None


def test_an_unsupported_top_end_is_not_refused_by_a51():
    """An unsupported end has no a_t formula to evaluate, so the missing
    bottom diameter cannot block it."""
    face = plan.face_plan(
        True, H_MM, B_MM, COVER_MM, COVER_MM, COVER_MM,
        STIRRUP_DIA_MM, BAR_DIA_MM, None, SPACER_DIA_MM, 3, 1, 60.0,
        False, None, None, False, None, None,
    )
    assert face.start_end.refused_reason is None
    assert face.start_end.a_mm is not None


# --- stirrups --------------------------------------------------------------


def test_stirrup_loop_is_the_centreline_not_the_outer_rectangle():
    """Rebar.CreateFromCurves receives the CENTRELINE loop. Using the
    outer rectangle would place every stirrup one full diameter oversize,
    and both functions exist in the core, so the wrong one is one word
    away.
    """
    result = plan.stirrup_plan(
        6000.0, B_MM, H_MM, COVER_MM, STIRRUP_DIA_MM, 1, 150.0, 200.0, 200.0, 200.0
    )
    centre_w, centre_h = centreline_leg_dimensions_mm(
        B_MM, H_MM, COVER_MM, STIRRUP_DIA_MM
    )
    outer_w, outer_h = outer_leg_dimensions_mm(B_MM, H_MM, COVER_MM)
    us = [u for pair in result.endpoints_mm for (u, _v) in pair]
    vs = [v for pair in result.endpoints_mm for (_u, v) in pair]
    assert max(us) - min(us) == pytest.approx(centre_w)
    assert max(vs) - min(vs) == pytest.approx(centre_h)
    assert max(us) - min(us) != pytest.approx(outer_w)


def test_three_zones_with_the_layout_flags_the_verified_button_uses():
    """The dense zones own both their boundary stirrups; the normal zone
    owns neither, so L/3 and 2L/3 are each claimed exactly once (the R4
    mitigation, rft.core.stirrups).

    This test used to assert (False, True) and (False, True) for zones 2
    and 3 -- the values of the second, private copy of ZONE_LAYOUT_FLAGS
    that plan.py had grown -- while its own name claimed they were the
    verified button's. They were not. A test that pins a duplicate is not
    a check on the duplicate; it is a second place the duplicate is
    written down.
    """
    from rft.core import stirrups

    result = plan.stirrup_plan(
        6000.0, B_MM, H_MM, COVER_MM, STIRRUP_DIA_MM, 1, 150.0, 200.0, 200.0, 200.0
    )
    assert [z.name for z in result.zones] == ["zone1", "zone2", "zone3"]
    assert [(z.include_first, z.include_last) for z in result.zones] == [
        (True, True), (False, False), (True, True)
    ]
    # And stated once more against the constant itself, so this cannot
    # drift back into being its own answer.
    assert [(z.include_first, z.include_last) for z in result.zones] == [
        stirrups.ZONE_LAYOUT_FLAGS[z.name] for z in result.zones
    ]
    assert result.total_count == sum(z.count for z in result.zones)


def test_dense_zones_are_never_spaced_wider_than_the_normal_zone():
    result = plan.stirrup_plan(
        6000.0, B_MM, H_MM, COVER_MM, STIRRUP_DIA_MM, 1, 150.0, 200.0, 200.0, 200.0
    )
    by_name = dict((z.name, z) for z in result.zones)
    assert by_name["zone1"].spacing_mm <= by_name["zone2"].spacing_mm
    assert by_name["zone3"].spacing_mm <= by_name["zone2"].spacing_mm


def test_achieved_spacing_never_exceeds_the_maximum_asked_for():
    for dense, normal in ((150.0, 200.0), (100.0, 250.0), (200.0, 200.0)):
        result = plan.stirrup_plan(
            6000.0, B_MM, H_MM, COVER_MM, STIRRUP_DIA_MM, 1,
            dense, normal, 200.0, 200.0,
        )
        for zone in result.zones:
            assert zone.spacing_mm <= zone.max_spacing_mm + 1e-9


def test_parked_closure_type_3_is_refused_here_too():
    with pytest.raises(ValueError):
        plan.stirrup_plan(
            6000.0, B_MM, H_MM, COVER_MM, STIRRUP_DIA_MM, 3,
            150.0, 200.0, 200.0, 200.0,
        )


# --- crack bars ------------------------------------------------------------


def test_crack_plan_matches_the_notation_drawing():
    """Four layers at 162.8 mm on the verification beam -- the same figure
    docs/ui/sketch-notation.svg carries, derived independently."""
    result = plan.crack_plan(
        H_MM, B_MM, COVER_MM, STIRRUP_DIA_MM, 12.0, 43.0, 43.0, 200.0
    )
    assert result.n_layers == 4
    assert result.spacing_mm == pytest.approx(162.8, abs=0.1)
    assert len(result.v_positions_mm) == 4


def test_crack_layers_count_interior_divisions_not_gaps():
    """§5.2 divides H_avail into n gaps and puts a layer at each INTERIOR
    division, so layers = gaps - 1. Reading ``n_gaps`` instead would place
    an extra layer on top of a main-bar layer -- a one-word error with no
    visible symptom in a count.
    """
    from rft.core.crack_bars import crack_layer_plan

    h_avail = plan.crack_plan(
        H_MM, B_MM, COVER_MM, STIRRUP_DIA_MM, 12.0, 43.0, 43.0, 200.0
    )
    raw = crack_layer_plan(h_avail.h_avail_mm, 200.0)
    assert h_avail.n_layers == raw.n_crack_layers
    assert h_avail.n_layers == raw.n_gaps - 1


def test_crack_bars_sit_between_the_innermost_main_layers():
    result = plan.crack_plan(
        H_MM, B_MM, COVER_MM, STIRRUP_DIA_MM, 12.0, 43.0, 43.0, 200.0
    )
    top_limit = H_MM / 2.0 - 43.0
    btm_limit = -H_MM / 2.0 + 43.0
    for v_mm in result.v_positions_mm:
        assert btm_limit < v_mm < top_limit


def test_crack_bars_are_one_per_side():
    result = plan.crack_plan(
        H_MM, B_MM, COVER_MM, STIRRUP_DIA_MM, 12.0, 43.0, 43.0, 200.0
    )
    assert len(result.u_positions_mm) == 2
    assert result.u_positions_mm[0] == pytest.approx(-result.u_positions_mm[1])


# --- the innermost layer offset, which H_avail is measured to ---------------


def test_innermost_offset_matches_the_last_layer_of_a_full_face_plan():
    """The number this replaces: ``face_plan(...).layers[-1].offset_mm``.

    They must agree exactly, because the crack plan used to be fed the
    second and is now fed the first. If these two ever diverge, H_avail
    silently moves and every crack bar moves with it.
    """
    for layer_count in (1, 2, 3):
        face = _bottom_face(layer_count=layer_count)
        assert plan.innermost_layer_offset_mm(
            COVER_MM, STIRRUP_DIA_MM, BAR_DIA_MM, SPACER_DIA_MM, layer_count
        ) == pytest.approx(face.layers[-1].offset_mm)


def test_the_innermost_layer_is_the_last_one_not_the_first():
    """Section 4.1 counts outwards from the concrete face, so the layer
    NEAREST the beam's centre is layer ``layer_count``. Reading layer 1
    instead would compute H_avail between the OUTERMOST layers -- larger
    than the truth, so too many crack layers, the last of them sitting on
    top of a main bar.
    """
    outermost = plan.innermost_layer_offset_mm(
        COVER_MM, STIRRUP_DIA_MM, BAR_DIA_MM, SPACER_DIA_MM, 1
    )
    innermost = plan.innermost_layer_offset_mm(
        COVER_MM, STIRRUP_DIA_MM, BAR_DIA_MM, SPACER_DIA_MM, 3
    )
    assert innermost > outermost


def test_the_innermost_offset_needs_no_bar_count():
    """The defect this function exists to remove, stated as a test.

    A50 requires both faces to be DETAILED -- a bar type and a layer
    count -- before crack bars can be planned. It does NOT require both
    faces to be PLACED, and an unplaced face has no bar count (#48: blank
    means blank, never a default).

    The placer used to read this offset off a full ``face_plan``, which
    needs the per-layer bar count because it also computes every bar's
    ``u``. With that count blank it raised ``TypeError: '<' not supported
    between instances of 'NoneType' and 'int'`` from inside the bar
    position arithmetic -- with the transaction already open, for a
    combination the derivation had just declared valid.
    """
    with pytest.raises(TypeError):
        plan.face_plan(
            True, H_MM, B_MM, COVER_MM, COVER_MM, COVER_MM,
            STIRRUP_DIA_MM, BAR_DIA_MM, BAR_DIA_MM, SPACER_DIA_MM,
            None, 2, 55.0,
            True, 400.0, 40.0, True, 400.0, 40.0,
        )

    # The same inputs, asking only for what H_avail actually needs.
    assert plan.innermost_layer_offset_mm(
        COVER_MM, STIRRUP_DIA_MM, BAR_DIA_MM, SPACER_DIA_MM, 2
    ) == pytest.approx(75.0)


def test_a_crack_plan_survives_one_face_being_detailed_but_not_placed():
    """End to end over the combination that used to crash: both faces
    detailed with 2 layers each, only the bottom face carrying a bar
    count, crack bars requested.
    """
    offsets = [
        plan.innermost_layer_offset_mm(
            COVER_MM, STIRRUP_DIA_MM, BAR_DIA_MM, SPACER_DIA_MM, 2
        )
        for _ in range(2)
    ]
    result = plan.crack_plan(
        H_MM, B_MM, COVER_MM, STIRRUP_DIA_MM, 12.0, offsets[0], offsets[1], 200.0
    )
    assert result.h_avail_mm == pytest.approx(H_MM - offsets[0] - offsets[1])
    assert result.n_layers >= 1


# --- one constant, one definition ------------------------------------------


def test_the_zone_layout_flags_are_the_tested_ones_not_a_second_copy():
    """This module restated ZONE_LAYOUT_FLAGS instead of importing it, and
    the copy said something different: zone2 (False, True), zone3
    (False, True), against the original's zone2 (False, False), zone3
    (True, True).

    Both give each zone boundary exactly one owner, so both place bars at
    the SAME POSITIONS and both total 47 on the verification beam. That is
    why it went unnoticed. What differed was which zone owns the bar at
    2L/3 -- so the Review report, which imported the original, said
    "zone2: count = 9, zone3: count = 19" while Place built sets of 10 and
    18. Identical steel, described wrongly, in a released version.
    """
    from rft.core import stirrups

    assert plan.ZONE_LAYOUT_FLAGS is stirrups.ZONE_LAYOUT_FLAGS, (
        "rft.core.plan must re-export rft.core.stirrups.ZONE_LAYOUT_FLAGS, "
        "not hold its own copy: the copy is free to disagree, and did."
    )
    assert plan.ZONE_LAYOUT_FLAGS == {
        "zone1": (True, True),
        "zone2": (False, False),
        "zone3": (True, True),
    }


def test_only_one_module_defines_the_zone_layout_flags():
    """The `is` check above passes the moment plan.py imports the name --
    including if some third module grows its own literal copy. This looks
    for the literal itself, anywhere in the library.
    """
    import io
    import os
    import re

    lib = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "RFTBeamDetailing.extension", "lib")
    definers = []
    for dirpath, _dirnames, filenames in os.walk(lib):
        if "__pycache__" in dirpath:
            continue
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            text = io.open(path, encoding="utf-8").read()
            # An assignment to a literal dict, as opposed to an import or
            # the re-export.
            if re.search(r"^ZONE_LAYOUT_FLAGS = \{", text, re.MULTILINE):
                definers.append(os.path.relpath(path, lib).replace("\\", "/"))
    assert definers == ["rft/core/stirrups.py"], (
        "ZONE_LAYOUT_FLAGS must be defined in exactly one place -- the "
        "module whose docstring carries the R4 de-duplication reasoning. "
        "Defined in: %s" % definers
    )
