# -*- coding: utf-8 -*-
"""Crack / skin reinforcement for deep beams (rev 2 section 5; A22-A26 as
amended by A42; residual question R2, resolved).

Pure Python: no Revit imports, no Revit types. Every value is a plain
number in millimetres, matching the spec 1:1. Local (u, v) coordinate
convention, shared with ``rft.core.layout`` and ``rft.core.stirrups``:
centred on the section centroid, u the section width axis, v the vertical
axis. Callers convert to Revit points, and mm to internal units, only at
the adapter boundary.

Rev 2 section 5 (crack/skin reinforcement), section 2 (R2's "mirroring
section 2's straight run a" for an unsupported end).

DELIBERATELY DOES NOT IMPORT ``rft.core.anchorage``: crack bars run
straight into the support with no hook (A23) -- they are crack-control
steel, not flexural tension, so section 2's anchorage MACHINERY (the LD
split, section 2.3's mandatory-hook rule, its bend-leg cap/clamp) must
never reach this module, even by accident through a shared import. Where
R2 mirrors a piece of section 2's behaviour (the unsupported-end straight
run), that end is reported as a ZERO embedment plus a positive
termination distance (``crack_bar_end_result``) -- never as a negative
length, which is what issue #15's (S2) review found.
"""

import math
from collections import namedtuple

from .layout import first_layer_offset_mm

H_TRIGGER_MM = 700.0  # section 5: "only applies when h > 700 mm" -- strict >

# A36's v1 default for `s_max`, the maximum spacing between crack-bar
# layers (section 5.2 states only that it is a user input). Held here, not
# typed into the pushbutton's form, so the shipped default cannot drift
# away from the amendment that fixes it.
DEFAULT_S_MAX_MM = 200.0

# Epsilon-tolerant ceiling tolerance: IEEE float division of an exact
# multiple (e.g. 600.0 / 200.0) can land a hair above the integer (e.g.
# 3.0000000000000004), which bare `math.ceil` would push up to 4 --
# inventing an extra gap the spec's exact-multiple case does not call for.
_CEIL_EPSILON = 1e-9


def _epsilon_ceil(value):
    """ceil(value), tolerant of float noise around an exact integer. See
    module-level `_CEIL_EPSILON` for why this exists instead of a bare
    `math.ceil` call (section 5.2's acceptance criteria demand an
    exact-multiple test that a bare ceil would fail intermittently).
    """
    rounded = round(value)
    if abs(value - rounded) <= _CEIL_EPSILON:
        return int(rounded)
    return int(math.ceil(value))


def crack_reinforcement_triggered(h_mm):
    """Section 5 trigger: fires only when `h > 700` mm, strictly greater.
    `h == 700` does NOT trigger; `h == 701` does.

    `h_mm` must come from `rft.revit.geometry.beam_section_dimensions_mm`
    (the rotation-aware local bounding box) -- never from a separately
    typed input. Two sources of truth for `h` is the same defect class as
    the datum mistakes this ticket's brief warns about.
    """
    return h_mm > H_TRIGGER_MM


def available_height_mm(h_mm, offset_top_mm, offset_btm_mm):
    """H_avail = h - offset_top - offset_btm (section 5.1).

    A26: `offset_top_mm`/`offset_btm_mm` MUST be the INNERMOST main-bar
    layer's own offset for a multi-layer beam -- callers pass
    `layer_offset_mm(..., layer_n=layers_top)` /
    `layer_offset_mm(..., layer_n=layers_btm)`, i.e. the LAST layer's
    offset, never `first_layer_offset_mm`'s (layer 1's) value and never a
    bare `1` for the layer count. Section 5.1 as originally written never
    addressed the multi-layer case at all; A26 closes that gap. The
    innermost layer's offset is LARGER than the outermost layer's, so
    using it correctly gives a SMALLER `H_avail` (the true unreinforced
    web height) and therefore FEWER crack layers than a naive reading that
    used layer 1's offset regardless of layer count -- getting this
    backwards silently over-reinforces.
    """
    return h_mm - offset_top_mm - offset_btm_mm


CrackLayerPlan = namedtuple(
    "CrackLayerPlan", ["n_gaps", "n_crack_layers", "actual_spacing_mm", "h_avail_mm"]
)


def crack_layer_plan(h_avail_mm, s_max_mm):
    """Section 5.2 layer count and spacing:

        n_gaps         = ceil(H_avail / s_max)
        n_crack_layers = n_gaps - 1
        actual_spacing = H_avail / n_gaps      (<= s_max, evenly distributed,
                                                 no single odd leftover gap)

    `s_max_mm` is a typed user input (section 5.2).

    `n_gaps` is clamped to >= 1. `H_avail <= s_max` is NOT an error: it
    collapses to exactly one gap and therefore zero crack layers -- a
    legitimate outcome for a deep beam whose main-bar layers already
    consume most of the available depth, not a degenerate case to refuse.

    Uses `_epsilon_ceil` rather than a bare `math.ceil` -- see that
    function's docstring.

    Raises ValueError if `h_avail_mm` or `s_max_mm` is not positive: no
    valid layer plan exists for a non-positive available height (the main
    bar layers already consume the full beam depth or more -- a
    configuration error upstream, not this function's to silently paper
    over) or a non-positive maximum spacing.
    """
    if s_max_mm <= 0:
        raise ValueError(
            "s_max_mm must be positive, got {!r} (rev 2 section 5.2).".format(s_max_mm)
        )
    if h_avail_mm <= 0:
        raise ValueError(
            "h_avail_mm must be positive, got {!r} (rev 2 section 5.1): "
            "H_avail = h - offset_top - offset_btm collapsed to zero or "
            "negative -- the main bar layers already consume the full "
            "beam depth.".format(h_avail_mm)
        )
    n_gaps = _epsilon_ceil(h_avail_mm / s_max_mm)
    if n_gaps < 1:
        n_gaps = 1
    n_crack_layers = n_gaps - 1
    actual_spacing_mm = h_avail_mm / n_gaps
    return CrackLayerPlan(
        n_gaps=n_gaps,
        n_crack_layers=n_crack_layers,
        actual_spacing_mm=actual_spacing_mm,
        h_avail_mm=h_avail_mm,
    )


def crack_layer_v_positions_mm(h_mm, offset_btm_mm, n_crack_layers, actual_spacing_mm):
    """v_i, i = 1..n_crack_layers, in the shared centroid-local `v` frame
    (section 5.2, per this ticket's brief):

        v_i = -h/2 + offset_btm + i * actual_spacing

    Crack layers are placed at the INTERIOR division points of `H_avail`
    only -- `i` never reaches `0` (the innermost BOTTOM main-bar layer's
    own centreline, the datum this is measured from) or `n_gaps` (the
    innermost TOP main-bar layer's own centreline), since those ARE the
    main bar layers, not crack bars. Measuring from the beam soffit
    instead of the innermost bottom layer's centreline would be the same
    class of datum defect as issue #18's S5 finding.
    """
    v0_mm = -(h_mm / 2.0) + offset_btm_mm
    return [v0_mm + i * actual_spacing_mm for i in range(1, n_crack_layers + 1)]


def crack_bar_u_positions_mm(b_mm, cover_side_mm, stirrup_dia_mm, crack_dia_mm):
    """One bar per side (left/right face) per layer (section 5.2), at:

        ±(b/2 - (cover_side + O_stirrup + 1/2*O_crack))     (A24)

    A24 applies section 4's layer-offset formula to a SIDE face, exactly
    as `rft.core.layout.corner_bar_side_offset_mm` already does for the
    corner bar (section 6.1) -- reused here via `first_layer_offset_mm`
    rather than re-derived, so the two side-face applications of section
    4's formula cannot drift apart.

    `cover_side_mm` MUST be the beam's own SIDE-face cover -- not
    `cover_top`/`cover_btm` (which govern `H_avail`, a vertical quantity)
    and not the supporting element's own cover (which governs embedment,
    R2). Three different covers appear across this one module; using the
    wrong one for this horizontal dimension is exactly the class of
    mistake issue #16's (S3) review found.
    """
    side_offset_mm = first_layer_offset_mm(cover_side_mm, stirrup_dia_mm, crack_dia_mm)
    half_b_mm = b_mm / 2.0
    return -(half_b_mm - side_offset_mm), (half_b_mm - side_offset_mm)


def crack_bar_embedment_mm(support_width_mm, support_cover_mm):
    """R2 (resolved): embedment = support_width - support_cover, mirroring
    section 2.2's `a_btm` formula but WITHOUT section 2.3's LD split,
    cap/clamp, or mandatory hook (A23: crack bars run straight into the
    support, no hook -- they are crack-control steel, not flexural
    tension). Deliberately NOT routed through
    `rft.core.anchorage._capped_anchorage` -- do not "fix" this by adding
    that cap; A23 is the reason it must not apply here.

    `support_cover_mm` is the SUPPORTING element's own cover (rev 2
    section 2.4, A8's rule, reused here) -- not the beam's own top/bottom
    or side cover.
    """
    return support_width_mm - support_cover_mm


CrackBarEndResult = namedtuple(
    "CrackBarEndResult", ["embedment_mm", "is_supported", "terminates_short_of_end_mm"]
)


def crack_bar_end_result(is_supported, support_width_mm=None, support_cover_mm=None,
                          beam_end_cover_mm=None):
    """(embedment_mm, is_supported, terminates_short_of_end_mm) for ONE end
    of a crack bar (A23, R2).

    A SUPPORTED end embeds `support_width - support_cover` straight into
    the support, no hook (`crack_bar_embedment_mm`); `terminates_short_of_
    end_mm` is `None` since a supported end has no such concept.

    An UNSUPPORTED end has no support width to embed into -- reported
    EXPLICITLY as an unsupported end (`is_supported=False`), with
    `embedment_mm=0.0` (there is nothing to embed into) and the bar's
    termination point given SEPARATELY and POSITIVELY as
    `terminates_short_of_end_mm=beam_end_cover_mm` -- exactly the fix
    issue #15's (S2) review made for the equivalent main-bar case: never
    conflate "achieved embedment" (0 here) with "distance short of the
    beam's own physical end" (a positive, meaningful number) by
    subtracting one from a synthetic zero and reporting a negative
    length.
    """
    if is_supported:
        embedment_mm = crack_bar_embedment_mm(support_width_mm, support_cover_mm)
        return CrackBarEndResult(
            embedment_mm=embedment_mm, is_supported=True, terminates_short_of_end_mm=None
        )
    return CrackBarEndResult(
        embedment_mm=0.0, is_supported=False, terminates_short_of_end_mm=beam_end_cover_mm
    )


def spacing_validation_exemption_note():
    """A25: crack bars are EXEMPT from section 6.2's horizontal
    `min_spacing` validation -- one bar per side per layer leaves no
    horizontal spacing question (only two bars total per layer, one per
    side face), and vertical spacing is even by construction via
    `crack_layer_plan`'s `actual_spacing_mm`.

    Returns a plain informational string, not a `GuardMessage` -- this is
    a statement that section 6.2 validation does not apply here at all,
    not a guard condition that can fire. Kept as an explicit, importable
    statement (rather than simply omitting a call to section 6.2's
    validation and relying on that omission to be noticed) so issue #17
    (S4, section 6.2 validation) has something concrete to check against
    instead of silently sweeping crack bars into that validation by
    accident.
    """
    return (
        "Crack/skin bars are EXEMPT from rev 2 section 6.2 spacing "
        "validation (section 5, A25): one bar per side per layer leaves "
        "no horizontal spacing question, and vertical spacing is even by "
        "construction via `actual_spacing`."
    )
