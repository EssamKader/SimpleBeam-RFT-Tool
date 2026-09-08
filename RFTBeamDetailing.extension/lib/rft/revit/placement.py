"""Builds the anchored-bar curve list and commits it inside one Transaction
with rollback on failure.

Rev 2 section 2.3 note A13: "hook" here means a bent leg `b`, built as a
curve segment -- NOT a RebarHookType. `a`/`b` are theoretical-corner
dimensions (A5) and are fed to Line.CreateBound raw: Revit inserts its own
fillet at each shared vertex and the rendered straight segments come out
shorter than `a`/`b` -- expected, not a bug, no bend-radius compensation
applied here (docs/research/revit-api-strategy.md section 3).

Corrected per issue #14 review (the ticket's original "2-segment" wording
described one end only and contradicted its own both-ends acceptance
criteria): a bottom bar in a single-span beam is anchored at BOTH ends, so
the curve list is 3 segments -- bend leg `b` at end A (up), one continuous
straight run spanning the beam plus `a` into each support, bend leg `b` at
end B (up) -- not a 2-segment stub at one end.

Rev 2 section 10: RebarStyle.Standard, startHook/endHook = None, one
Transaction per beam, RollBack() on any exception.
"""

from Autodesk.Revit.DB import Line, Transaction
from Autodesk.Revit.DB.Structure import Rebar, RebarHookOrientation, RebarStyle


def bend_plane_normal(straight_direction, bend_direction):
    """Normal to the plane containing both anchorage legs -- the `norm`
    argument `Rebar.CreateFromCurves` expects, distinct from either leg's
    own direction.
    """
    return straight_direction.CrossProduct(bend_direction).Normalize()


def build_bottom_bar_curves(face_start, face_end, axis_direction, bend_direction,
                             a_start_internal, b_start_internal,
                             a_end_internal, b_end_internal):
    """3-segment curve list for a bottom bar anchored at both ends (rev 2
    section 2.2/2.3, corrected per issue #14 review): bend leg `b` at end A
    (up) -> one continuous straight run spanning the beam plus `a` into
    each support -> bend leg `b` at end B (up).

    `face_start`/`face_end` are the supports' near faces along the beam
    axis (``rft.revit.geometry.start_support_face_point`` /
    ``end_support_face_point``), not the beam's `LocationCurve` endpoints
    -- finding #2 of the review: those endpoints are not guaranteed to sit
    on the support faces. `axis_direction` runs from end A to end B;
    `bend_direction` is upward for a bottom bar (rev 2 section 2.2).

    The corners (theoretical anchorage vertices, A5) are `a` further INTO
    each support from its face, along `axis_direction`: `corner_start` is
    `a_start` behind `face_start` (against `axis_direction`), `corner_end`
    is `a_end` beyond `face_end` (with `axis_direction`). The straight run
    is `corner_start -> corner_end`, so its length is the face-to-face span
    plus `a_start` plus `a_end` -- it is continuous through the beam, not a
    stub at either end.
    """
    corner_start = face_start - axis_direction.Multiply(a_start_internal)
    corner_end = face_end + axis_direction.Multiply(a_end_internal)
    bend_end_start = corner_start + bend_direction.Multiply(b_start_internal)
    bend_end_end = corner_end + bend_direction.Multiply(b_end_internal)
    return [
        Line.CreateBound(bend_end_start, corner_start),
        Line.CreateBound(corner_start, corner_end),
        Line.CreateBound(corner_end, bend_end_end),
    ]


def build_main_bar_curves(start_corner, end_corner, bend_direction,
                           start_bend_internal=None, end_bend_internal=None):
    """General-purpose curve list for a main bar whose two ends need not
    match: each end is either BENT (rev 2 section 2.2/2.3, a supported end)
    or STRAIGHT with no hook (rev 2 section 2.5, A12, an unsupported end)
    -- issue #15 (S2), which needs this because a beam's two ends can
    differ, unlike S1's both-ends-bent bottom bar (``build_bottom_bar_
    curves``, kept unchanged and still used where both ends ARE bent).

    ``start_corner``/``end_corner`` are each end's THEORETICAL CORNER (rev
    2 section 1, A5): for a bent end this is `a` behind/beyond the support
    face along the beam axis (same datum as ``build_bottom_bar_curves``);
    for an unsupported end this is simply the point the straight run
    terminates at (``beam end - cover``, R3 resolved) -- there is no
    support face to measure `a` from.

    ``start_bend_internal``/``end_bend_internal`` is that end's bend leg
    length `b` (internal units) when BENT, or None when that end is
    unsupported and gets NO hook -- passing None omits the bend segment
    entirely rather than emitting a zero-length one.

    ``bend_direction`` is shared by both ends here (a single bar's bend
    direction does not change end to end -- e.g. always upward for a
    bottom bar, always downward for a top bar); it is unused when neither
    end is bent.
    """
    curves = []
    if start_bend_internal is not None:
        bend_end_start = start_corner + bend_direction.Multiply(start_bend_internal)
        curves.append(Line.CreateBound(bend_end_start, start_corner))
    curves.append(Line.CreateBound(start_corner, end_corner))
    if end_bend_internal is not None:
        bend_end_end = end_corner + bend_direction.Multiply(end_bend_internal)
        curves.append(Line.CreateBound(end_corner, bend_end_end))
    return curves


def bent_end_corner(face_point, axis_direction, a_internal, toward_span):
    """The theoretical corner (A5) for a BENT end: `a_internal` further
    INTO the support from its near face, along the beam axis. ``toward_span``
    is True for a beam-start support (corner sits AGAINST axis_direction,
    behind the face, per ``build_bottom_bar_curves``'s ``corner_start``) and
    False for a beam-end support (corner sits WITH axis_direction, beyond
    the face, per its ``corner_end``) -- kept as one function so both ends
    share the same derivation instead of restating the sign by hand at each
    call site.
    """
    sign = -1.0 if toward_span else 1.0
    return face_point + axis_direction.Multiply(sign * a_internal)


def unsupported_end_corner(beam_end_point, axis_direction, cover_internal, toward_span):
    """The theoretical corner (A5) for an UNSUPPORTED end: the straight run
    terminates at ``beam end - cover`` (rev 2 section 2.5, R3 resolved) --
    moved INWARD from the beam's own physical end point by the beam's own
    end-face cover, along the beam axis. ``toward_span`` matches
    ``bent_end_corner``'s convention: True at a beam-start end (move WITH
    axis_direction, into the span), False at a beam-end end (move AGAINST
    axis_direction).
    """
    sign = 1.0 if toward_span else -1.0
    return beam_end_point + axis_direction.Multiply(sign * cover_internal)


def main_bar_end_geometry(is_supported, reference_point, axis_direction, toward_span,
                           a_or_cover_internal, b_internal=None):
    """(corner_point, bend_internal_or_None) for ONE end of a main bar
    (issue #15, S2): a SUPPORTED end is bent -- ``bent_end_corner`` plus
    its own bend leg `b` (rev 2 section 2.2/2.3) -- an UNSUPPORTED end is
    straight with no hook (``unsupported_end_corner``, rev 2 section 2.5,
    A12), returning None for the bend so ``build_main_bar_curves`` omits
    that segment entirely rather than emitting a zero-length one.

    ``a_or_cover_internal`` is `a` (internal units) when ``is_supported``,
    or the beam's own end-face cover (internal units) when not -- the two
    functions it is forwarded to read it differently, matching each one's
    own formula.
    """
    if is_supported:
        corner = bent_end_corner(reference_point, axis_direction, a_or_cover_internal, toward_span)
        return corner, b_internal
    corner = unsupported_end_corner(reference_point, axis_direction, a_or_cover_internal, toward_span)
    return corner, None


def bar_face_points_at_uv(face_start, face_end, u_dir, v_dir,
                          du_internal, dv_internal, u_mm, v_mm, to_internal_units):
    """The two support-face points (internal units) for ONE bar within a
    layer/corner-bar layout, at local (u, v) mm offset from the section
    CENTROID (issue #16, S3, rev 2 sections 4/6.1).

    `face_start`/`face_end` are the on-axis support-face points S1 already
    builds (``start_support_face_point``/``end_support_face_point``), sat
    on the beam's LOCATION CURVE, not its centroid. `du_internal`/
    `dv_internal` (``beam_section_centre_offsets``) carry that curve-to-
    centroid correction; `u_mm`/`v_mm` (``rft.core.layout``) are then
    added on top, in the SAME (u, v) axes, so a bar's centroid-local
    coordinate reaches the right point on the support face without
    re-deriving the datum this ticket's geometry helpers already fixed
    (issue #18 review findings #1/#2).
    """
    u_total_internal = du_internal + to_internal_units(u_mm)
    v_total_internal = dv_internal + to_internal_units(v_mm)
    lateral_offset = u_dir.Multiply(u_total_internal) + v_dir.Multiply(v_total_internal)
    return face_start + lateral_offset, face_end + lateral_offset


def bar_point_at_uv(reference_point, u_dir, v_dir, du_internal, dv_internal,
                     u_mm, v_mm, to_internal_units):
    """Single-end variant of ``bar_face_points_at_uv`` (issue #15, S2): a
    beam's two ends can now differ (one bent/supported, one straight/
    unsupported), so each end's on-axis reference point -- a support face
    point OR, for an unsupported end, the beam's own end point -- is
    offset into the bar's local (u, v) position independently, rather than
    always in a matched face_start/face_end pair.
    """
    u_total_internal = du_internal + to_internal_units(u_mm)
    v_total_internal = dv_internal + to_internal_units(v_mm)
    lateral_offset = u_dir.Multiply(u_total_internal) + v_dir.Multiply(v_total_internal)
    return reference_point + lateral_offset


def place_anchored_bar(doc, host, bar_type, curves, norm):
    """Rebar.CreateFromCurves, RebarStyle.Standard, no hooks -- the bent
    curve list IS the anchorage (rev 2 section 2.3 note A13, section 10).

    UNVERIFIED AGAINST A LIVE HOST: whether the `useExistingShapeIfPossible`/
    `createNewShape` flags below (True, True) are the correct choice for a
    single free-form bar, and whether the resulting Rebar defaults to a
    single physical bar with no further `SetLayoutAsSingle`-style call
    needed, are documented behaviour we could not confirm without a live
    host. See docs/verification/s1-tracer-bullet.md.
    """
    rebar = Rebar.CreateFromCurves(
        doc,
        RebarStyle.Standard,
        bar_type,
        None,  # startHook -- A13, the bent curve list is the anchorage, not a hook
        None,  # endHook
        host,
        norm,
        curves,
        RebarHookOrientation.Left,
        RebarHookOrientation.Left,
        True,
        True,
    )
    return rebar


def run_in_transaction(doc, transaction_name, action):
    """One Transaction per beam, RollBack() on any exception before it
    propagates, so a failed run leaves no partial bar (rev 2 section 10).
    """
    tx = Transaction(doc, transaction_name)
    tx.Start()
    try:
        result = action()
    except Exception:
        tx.RollBack()
        raise
    tx.Commit()
    return result
