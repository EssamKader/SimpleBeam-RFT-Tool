# -*- coding: utf-8 -*-
"""Stirrup leg geometry, closure types and 3-zone distribution math.

Pure Python: no Revit imports, no Revit types. Every value is a plain
number (or 2D tuple / namedtuple of plain numbers) in millimetres, matching
the spec 1:1 (rev 2 sections 3 and 7). Callers convert to Revit's internal
units, and to 3D points in the beam's cross-section plane, only at the
adapter boundary (``rft.revit.stirrups``).

Rev 2 sections 3 (distribution) and 7 (closure/hook style).
"""

import math
from collections import namedtuple

EDGE_OFFSET_MM = 50.0  # §3.1: first/last stirrup 50 mm from a support face


def centreline_leg_dimensions_mm(b_mm, h_mm, cover_mm, stirrup_dia_mm):
    """CENTRELINE rectangle passed to the Revit API (§7.1, A30):

        CENTRELINE = (b - 2*Cover - O_stirrup) x (h - 2*Cover - O_stirrup)

    Cover is measured to the stirrup's OUTER face, so the centreline sits
    half a diameter inside the outer face on each of two opposing sides --
    hence one full diameter subtracted per dimension, not two half-diameters
    that would cancel out.
    """
    width_mm = b_mm - 2.0 * cover_mm - stirrup_dia_mm
    height_mm = h_mm - 2.0 * cover_mm - stirrup_dia_mm
    return width_mm, height_mm


def outer_leg_dimensions_mm(b_mm, h_mm, cover_mm):
    """OUTER rectangle of the stirrup (§7.1, A30):

        OUTER = (b - 2*Cover) x (h - 2*Cover)

    Cover is measured to the stirrup's OUTER face, so this is simply the
    concrete section inset by the cover on all four sides -- no diameter
    term, unlike ``centreline_leg_dimensions_mm``, which subtracts one full
    stirrup diameter per dimension to reach the bar centreline.

    NOT passed to the Revit API: ``Rebar.CreateFromCurves`` receives the
    CENTRELINE rectangle, and this function must never be substituted for
    it. It exists because A30 defines both rectangles and the SKETCH draws
    the outer one, and A48 forbids the renderer from computing any dimension
    itself -- a number the drawing needs is added here rather than derived
    in the renderer, so the drawing and the placement cannot disagree.

    The arithmetic is trivial, which is precisely the trap this closes: an
    inline ``b - 2*cover`` in the renderer would be a §7.1 rule living
    outside the core, free to drift from it.
    """
    return b_mm - 2.0 * cover_mm, h_mm - 2.0 * cover_mm


_CORNER_ORDER = ("top_right", "top_left", "bottom_left", "bottom_right")


def _rectangle_corners_mm(width_mm, height_mm, start_corner):
    """The 4 centreline-rectangle corners, in a fixed winding order, rotated
    so ``start_corner`` becomes the first element.

    Local (u, v) coordinates: u is the cross-section width axis, v is the
    height axis, both centred on the section centroid.
    """
    if start_corner not in _CORNER_ORDER:
        raise ValueError(
            "start_corner must be one of {}, got {!r}".format(_CORNER_ORDER, start_corner)
        )
    hw = width_mm / 2.0
    hh = height_mm / 2.0
    by_name = {
        "top_right": (hw, hh),
        "top_left": (-hw, hh),
        "bottom_left": (-hw, -hh),
        "bottom_right": (hw, -hh),
    }
    ordered = [by_name[name] for name in _CORNER_ORDER]
    idx = _CORNER_ORDER.index(start_corner)
    return ordered[idx:] + ordered[:idx]


def _closed_loop_endpoints_mm(corners):
    """Consecutive-pair curve endpoints for a closed loop. `curves[0]`
    starts at `corners[0]`; `curves[-1]` ends back at `corners[0]` -- the
    hook-overlap point Types 1/2 share (§7.2, A32).
    """
    n = len(corners)
    return [(corners[i], corners[(i + 1) % n]) for i in range(n)]


def _open_u_endpoints_mm(width_mm, height_mm):
    """Type 4: open U, no top closure (§7.2). Free ends at top-left and
    top-right each get their own hook.
    """
    hw = width_mm / 2.0
    hh = height_mm / 2.0
    top_left = (-hw, hh)
    bottom_left = (-hw, -hh)
    bottom_right = (hw, -hh)
    top_right = (hw, hh)
    return [
        (top_left, bottom_left),
        (bottom_left, bottom_right),
        (bottom_right, top_right),
    ]


TYPE3_PARKED_MESSAGE = (
    "Stirrup type 3 (nested double perimeter) is parked: the outer "
    "perimeter is dimensioned by rev 2 section 7.1, but the inner loop's "
    "offset, diameter and hook-overlap-corner rule are entirely undefined "
    "in the spec. Inventing that rule is prohibited by CONTEXT.md -- type 3 "
    "waits for a spec amendment (residual question R6). Supported types: "
    "1, 2, 4."
)


def stirrup_curve_endpoints_mm(closure_type, width_mm, height_mm):
    """Curve list as a list of ((u0, v0), (u1, v1)) endpoint pairs, mm,
    local to the beam cross-section plane.

    Types 1 and 2 are ONE parameterized code path: the same closed 4-curve
    loop and the same winding direction, only the starting corner (and
    therefore which corner the hooks meet at) differs (§7.2, A32). This is
    NOT a reversed loop -- reversing winding would flip which face the hook
    swings toward.

    Type 4 is a separate branch: an open U with no top closure (§7.2).

    Type 3 is rejected outright (§7.2, A31) -- see ``TYPE3_PARKED_MESSAGE``.
    """
    if closure_type == 3:
        raise ValueError(TYPE3_PARKED_MESSAGE)
    if closure_type == 4:
        return _open_u_endpoints_mm(width_mm, height_mm)
    if closure_type in (1, 2):
        start_corner = "top_right" if closure_type == 1 else "top_left"
        corners = _rectangle_corners_mm(width_mm, height_mm, start_corner)
        return _closed_loop_endpoints_mm(corners)
    raise ValueError(
        "Unsupported stirrup closure type: {!r}. Valid types are 1, 2, 4 "
        "(type 3 is parked, see TYPE3_PARKED_MESSAGE).".format(closure_type)
    )


def is_closed_type(closure_type):
    """Whether the closure type has a single hook-overlap corner (True, for
    1/2) rather than two independent free-end hooks (False, for 4)."""
    return closure_type in (1, 2)


ZoneMM = namedtuple("ZoneMM", ["start", "end"])
StirrupZones = namedtuple("StirrupZones", ["zone1", "zone2", "zone3"])

# R4 mitigation: explicit de-duplication guard at each zone boundary.
# Zone boundaries L/3 and 2L/3 could otherwise receive a stirrup from BOTH
# adjoining zones (whether that actually happens depends on
# SetLayoutAsMaximumSpacing's include-first/include-last flag semantics,
# which cannot be observed without a live host -- residual question R4,
# left OPEN). The mitigation: the dense zones (1, 3) own both of their
# boundary stirrups; the normal zone (2) owns neither of its boundary
# stirrups, so each of L/3 and 2L/3 is claimed by exactly one zone.
ZONE_LAYOUT_FLAGS = {
    "zone1": (True, True),
    "zone2": (False, False),
    "zone3": (True, True),
}


def stirrup_zones_mm(l_mm, face_a_offset_mm, face_b_offset_mm):
    """Three zones on the c/c span (0..L), clipped to the clear region
    between support faces (§3.1, A15/A16):

        region_start = face_A + 50
        region_end   = face_B - 50
        zone 1: [ region_start , L/3          ]
        zone 2: [ L/3          , 2L/3         ]
        zone 3: [ 2L/3         , region_end   ]

    ``face_a_offset_mm``/``face_b_offset_mm`` are each support's own
    near-face offset from ITS OWN centreline in the c/c datum (i.e. half
    that support's width along the beam axis) -- not a beam-face position.

    Raises ``ValueError`` (degenerate-case guard, A17) if either dense zone
    would have a non-positive array length: a short span and/or a wide
    support, tested independently at each end.
    """
    region_start = face_a_offset_mm + EDGE_OFFSET_MM
    region_end = l_mm - face_b_offset_mm - EDGE_OFFSET_MM
    third = l_mm / 3.0
    two_third = 2.0 * l_mm / 3.0

    if region_start >= third:
        raise ValueError(
            "Zone 1 (support A) has no valid stirrup array: face_A + 50 "
            "= {:.1f} mm >= L/3 = {:.1f} mm -- span too short and/or "
            "support too wide (rev 2 section 3.1, A17).".format(region_start, third)
        )
    if region_end <= two_third:
        raise ValueError(
            "Zone 3 (support B) has no valid stirrup array: face_B - 50 "
            "= {:.1f} mm <= 2L/3 = {:.1f} mm -- span too short and/or "
            "support too wide (rev 2 section 3.1, A17).".format(region_end, two_third)
        )

    return StirrupZones(
        zone1=ZoneMM(region_start, third),
        zone2=ZoneMM(third, two_third),
        zone3=ZoneMM(two_third, region_end),
    )


def zone_array_length_mm(zone):
    return zone.end - zone.start


StirrupCount = namedtuple("StirrupCount", ["count", "spacing_mm"])


def stirrup_count_and_spacing(array_length_mm, max_spacing_mm, include_first_bar, include_last_bar):
    """Count and achieved spacing for `SetLayoutAsMaximumSpacing` (§3.2,
    A18): dense/normal values are MAXIMUM spacings, redistributed evenly so
    the zone is filled exactly with no remainder.

        n_spaces = ceil(array_length / max_spacing)
        achieved_spacing = array_length / n_spaces   (<= max_spacing)
        placed_count = (n_spaces + 1) - (0 if include_first_bar else 1)
                                       - (0 if include_last_bar else 1)

    ``include_first_bar``/``include_last_bar`` are the SAME flags passed to
    `SetLayoutAsMaximumSpacing` for this zone (see ``ZONE_LAYOUT_FLAGS``,
    the R4 de-duplication mitigation) -- they are required here, not
    optional, so a caller cannot report a count without also stating which
    boundary bars this zone actually owns. A prior version returned
    ``n_spaces + 1`` unconditionally, which double-counted zone 2's L/3 and
    2L/3 boundary bars that ``(False, False)`` deliberately excludes from
    placement (issue #18 review finding #1).

    This mirrors the documented "Place a Rebar Set" behaviour (see
    docs/research/revit-api-strategy.md): "the number of rebar changes...
    maintaining a distance no larger than the maximum". Used here for
    reporting (per-zone count/spacing) computed independently of the Revit
    call, matching the reporting pattern already established in S1
    (`rft.core.anchorage` values are printed directly, not read back from
    the placed element).
    """
    if array_length_mm <= 0:
        raise ValueError(
            "array_length_mm must be positive, got {:.1f} mm.".format(array_length_mm)
        )
    if max_spacing_mm <= 0:
        raise ValueError(
            "max_spacing_mm must be positive, got {:.1f} mm.".format(max_spacing_mm)
        )
    n_spaces = int(math.ceil(array_length_mm / max_spacing_mm))
    if n_spaces < 1:
        n_spaces = 1
    achieved_spacing_mm = array_length_mm / n_spaces
    placed_count = (n_spaces + 1) - (0 if include_first_bar else 1) - (0 if include_last_bar else 1)
    if placed_count < 1:
        raise ValueError(
            "Zone has no stirrups to place: array_length = {:.1f} mm, "
            "max_spacing = {:.1f} mm gives only {} space(s) and both "
            "boundary bars are excluded by this zone's layout flags "
            "(include_first_bar={}, include_last_bar={}).".format(
                array_length_mm, max_spacing_mm, n_spaces, include_first_bar, include_last_bar
            )
        )
    return StirrupCount(count=placed_count, spacing_mm=achieved_spacing_mm)
