"""Main bar cross-section layout: layer offsets, corner-bar horizontal
distribution, spacer bar length, and the R1 vertical-spacing warning.

Pure Python: no Revit imports, no Revit types. Every value is a plain
number (or namedtuple/list of plain numbers) in millimetres, matching the
spec 1:1 (rev 2 sections 4, 4.1 and 6.1). Local (u, v) coordinate
convention, shared with ``rft.core.stirrups``: centred on the section
centroid, u the section width axis, v the vertical axis. Callers convert
to Revit points, and mm to internal units, only at the adapter boundary.

Rev 2 section 4 (layer offset), section 6.1 (corner-bar rule).
"""

MAX_LAYERS = 5  # §4.1: "for n = 1..5"


def first_layer_offset_mm(cover_mm, stirrup_dia_mm, bar_dia_mm):
    """offset_1 = Cover + O_stirrup + 1/2*O_bar (§4).

    Measured from the beam face to the bar's OWN centreline -- not to the
    stirrup, and not to the bar's outer edge. Applied independently with
    O_TOP or O_BTM depending on which face is being offset, and (per §6.1)
    reused unchanged as the corner bar's offset from a SIDE face -- the
    formula does not care which face it is measured from, only which
    bar's diameter it uses.
    """
    return cover_mm + stirrup_dia_mm + 0.5 * bar_dia_mm


def layer_offset_mm(cover_mm, stirrup_dia_mm, bar_dia_mm, spacer_dia_mm, layer_n):
    """offset_n = offset_1 + (n - 1) * (O_bar + O_spacer), n = 1..5 (§4.1,
    A20). ONE diameter per face: every stacked row in a face uses that
    face's single bar diameter, not a per-row diameter.

    O_spacer is a user input (default 16) representing the CLEAR vertical
    gap between stacked layers, not a centre-to-centre pitch (§4.1, A19).
    A physical spacer bar occupies that gap, so "one bar diameter plus one
    spacer diameter" per additional row is a sum of two clear thicknesses,
    not a pitch computed from bar centrelines.

    Raises ValueError if layer_n is outside 1..5 (§4.1).
    """
    if not (1 <= layer_n <= MAX_LAYERS):
        raise ValueError(
            "layer_n = {!r} is outside the valid range 1..{} (rev 2 section "
            "4.1: 'for n = 1..5').".format(layer_n, MAX_LAYERS)
        )
    offset_1 = first_layer_offset_mm(cover_mm, stirrup_dia_mm, bar_dia_mm)
    return offset_1 + (layer_n - 1) * (bar_dia_mm + spacer_dia_mm)


def spacer_length_mm(b_mm, cover_mm, stirrup_dia_mm):
    """spacer_length = b - 2*Cover - 2*O_stirrup (§6.3).

    Deliberately subtracts TWO stirrup diameters, unlike
    ``rft.core.stirrups.centreline_leg_dimensions_mm`` which subtracts
    ONE. Both are correct -- they use different datums, not conflicting
    ones: the centreline rectangle is measured to the stirrup leg's own
    centreline (half a diameter inside the outer face on each side, one
    full diameter total), while this spacer spans the CLEAR gap between
    the two legs' INNER faces (a full diameter inside the outer face on
    each side, two full diameters total). Do not "harmonise" these -- the
    difference is the point, not a typo (rev 2 section 7.1, A30, Check 1).
    """
    return b_mm - 2.0 * cover_mm - 2.0 * stirrup_dia_mm


# --- §6.1 corner-bar rule ----------------------------------------------------


def corner_bar_side_offset_mm(cover_mm, stirrup_dia_mm, bar_dia_mm):
    """The corner bar's own offset from the SIDE face, to its centreline.

    Same formula as ``first_layer_offset_mm`` (§4) -- the corner bar sits
    against the stirrup's inner face exactly like the first vertical
    layer does, only measured horizontally instead of vertically. Rev 2
    section 6.1 gives the rule ("a bar at each corner") but not a
    restated formula, so this is derived from the shared §4 function
    rather than re-deriving the arithmetic.
    """
    return first_layer_offset_mm(cover_mm, stirrup_dia_mm, bar_dia_mm)


def corner_bar_u_positions_mm(b_mm, cover_mm, stirrup_dia_mm, bar_dia_mm, bar_count):
    """Horizontal (u) centreline positions for ``bar_count`` bars in one
    layer, centred on the section centroid (§6.1):

        a bar is placed at each stirrup corner; the remainder in that face
        is distributed at EQUAL SPACING between the corner bars.

    ``bar_count`` must be >= 2: the corner-bar rule requires a bar at
    EACH of two corners per face, so a single bar has no rule to apply to
    it -- rev 2 section 6.1 never addresses a one-bar face (this is a
    documented gap, not a guess; see this ticket's report). Raises
    ValueError for bar_count < 2.
    """
    if bar_count < 2:
        raise ValueError(
            "bar_count = {!r} is invalid for the corner-bar rule (rev 2 "
            "section 6.1): a bar is required at EACH of two corners, so "
            "fewer than 2 bars has no corner-bar layout to compute. Rev 2 "
            "does not define a single-bar face.".format(bar_count)
        )
    side_offset_mm = corner_bar_side_offset_mm(cover_mm, stirrup_dia_mm, bar_dia_mm)
    u_left = -(b_mm / 2.0 - side_offset_mm)
    u_right = b_mm / 2.0 - side_offset_mm
    if bar_count == 2:
        return [u_left, u_right]
    spacing_mm = (u_right - u_left) / (bar_count - 1)
    return [u_left + i * spacing_mm for i in range(bar_count)]


# --- R1 (resolved): non-blocking vertical-spacing warning --------------------


def spacer_diameter_warning(spacer_dia_mm, bar_dia_mm, d_agg_mm):
    """R1 -- RESOLVED (non-blocking): warn, never block, when

        O_spacer < max(25, O_bar, 1.33 * D_agg)

    Returns a message string naming the spacer diameter and the
    horizontal minimum it falls below, or None if no warning fires.
    Callers place the bars regardless of this warning (§4.1, A21: the
    horizontal min_spacing formula does not itself govern the vertical
    gap; this is the one check the spec adds on top of that, and it is a
    warning, not a guard).

    ``d_agg_mm`` is REQUIRED -- rev 2 gives no default for D_agg (§6.2's
    50 mm fallback only applies when D_agg is undefined, a state this
    pure function cannot represent with a bare float without inventing a
    sentinel the spec does not define). Callers with no D_agg input must
    resolve that at the boundary (e.g. by not calling this function, or
    by passing whatever value the D_agg-undefined fallback resolves to)
    rather than this module guessing one.
    """
    min_horizontal_mm = max(25.0, bar_dia_mm, 1.33 * d_agg_mm)
    if spacer_dia_mm < min_horizontal_mm:
        return (
            "Spacer diameter O_spacer = {:.1f} mm is below the horizontal "
            "minimum spacing max(25, O_bar, 1.33*D_agg) = {:.1f} mm (rev 2 "
            "section 4.1, A21; residual question R1, resolved as a "
            "non-blocking warning). Bars are placed regardless.".format(
                spacer_dia_mm, min_horizontal_mm
            )
        )
    return None
