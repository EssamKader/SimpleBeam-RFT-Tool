"""Adapter for stirrup placement: converts core-computed centreline curve
lists and zone arrays into Revit `Rebar.CreateFromCurves` /
`RebarShapeDrivenAccessor.SetLayoutAsMaximumSpacing` calls.

Units convert to Revit internal feet only at this boundary
(``rft.revit.units``), mirroring every other adapter module in this
extension. No detailing math lives here -- that is
``rft.core.stirrups``.

Rev 2 sections 3 (distribution) and 7 (closure/hook style). Hook ANGLE
(180 deg, §7.3, A33) lives on the project's `RebarHookType`, selected
outside this module (mirroring how S1's script.py resolves `RebarBarType`
by name) -- this module only decides WHICH curve-list ends get a hook,
never the angle.
"""

from Autodesk.Revit.DB import Line
from Autodesk.Revit.DB.Structure import Rebar, RebarHookOrientation, RebarStyle


def build_stirrup_curves(origin_internal, u_dir, v_dir, endpoints_mm, to_internal_units):
    """3D curve list for a stirrup: maps the core's local (u, v) mm
    endpoint pairs (``rft.core.stirrups.stirrup_curve_endpoints_mm``) into
    the beam cross-section plane at `origin_internal`.

    `u_dir`/`v_dir` are the section's own width/height unit vectors
    (horizontal perpendicular-to-axis, and vertical) -- this is purely a
    coordinate change, no detailing logic of its own.
    """

    def to_point(uv):
        u_mm, v_mm = uv
        u_internal = to_internal_units(u_mm)
        v_internal = to_internal_units(v_mm)
        return origin_internal + u_dir.Multiply(u_internal) + v_dir.Multiply(v_internal)

    return [Line.CreateBound(to_point(a), to_point(b)) for a, b in endpoints_mm]


def place_stirrup(doc, host, bar_type, hook_type, curves, norm):
    """`Rebar.CreateFromCurves` for one stirrup shape: `RebarStyle.StirrupTie`,
    the mild-steel `bar_type` (§7.3, §1.1). Every closure type this tool
    supports (1, 2, 4) has a hook at both ends of the curve list -- closed
    types 1/2 share one hook-overlap corner (curves[0] start == curves[-1]
    end), open type 4 has two independent free ends -- so `hook_type` is
    passed identically as both `startHookType`/`endHookType`; only the
    curve topology built upstream differs.
    """
    return Rebar.CreateFromCurves(
        doc,
        RebarStyle.StirrupTie,
        bar_type,
        hook_type,
        hook_type,
        host,
        norm,
        curves,
        RebarHookOrientation.Left,
        RebarHookOrientation.Left,
        True,
        True,
    )


def apply_maximum_spacing_layout(
    rebar,
    max_spacing_internal,
    array_length_internal,
    include_first_bar,
    include_last_bar,
    bars_on_normal_side=True,
):
    """One rebar set per zone via `SetLayoutAsMaximumSpacing` (§3.2, A18) --
    NEVER `SetLayoutAsNumberWithSpacing`, which takes no `arrayLength` and
    cannot be pinned to a zone boundary.

    `include_first_bar`/`include_last_bar` are the R4 de-duplication guard
    (see ``rft.core.stirrups.ZONE_LAYOUT_FLAGS``) -- callers must pass the
    flags decided for THIS zone; this function does not choose them, so the
    guard stays visible at the call site rather than buried in the adapter.

    SHAPE UNVERIFIED: `Rebar.GetShapeDrivenAccessor()` and
    `RebarShapeDrivenAccessor.SetLayoutAsMaximumSpacing`'s exact parameter
    order/count are assumed from
    docs/research/revit-api-strategy.md's documentation-only research
    (`SetLayoutAsMaximumSpacing(spacing, arrayLength, barsOnNormalSide,
    includeFirstBar, includeLastBar)`), not confirmed against a live host.
    See tests/fake_revit_api.py header.
    """
    accessor = rebar.GetShapeDrivenAccessor()
    accessor.SetLayoutAsMaximumSpacing(
        max_spacing_internal,
        array_length_internal,
        bars_on_normal_side,
        include_first_bar,
        include_last_bar,
    )
    return accessor
