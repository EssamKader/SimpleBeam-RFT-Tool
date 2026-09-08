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
