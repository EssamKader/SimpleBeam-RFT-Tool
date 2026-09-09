# S5 Mock-Object Verification Write-up

> **CORRECTED BY ISSUE #25 / A45 (2026-09-09).** Every claim below about a
> **180°** stirrup hook, and every open question about whether
> `RebarStyle.StirrupTie` permits one, has since been settled against a
> live host — and the required angle has changed to **135°**. The real
> constraint turned out to be the hook's **family**
> (`REBAR_HOOK_STYLE`, `0 = Standard`, `1 = Stirrup/Tie`), not its angle:
> a `StirrupTie` rebar rejects a Standard-family hook whatever the angle,
> and accepts a Stirrup/Tie-family hook at 135° *or* 180°. The
> `SHAPE UNVERIFIED` notes on `hook_angle_deg` are retired. See
> `docs/verification/issue-25-stirrup-hook-family-and-angle.md`; this
> document is kept as the record of what was known at the time.


Ticket [#18](https://github.com/EssamKader/rft-beam-detailing/issues/18) —
stirrup leg geometry, closure types 1/2/4, and the 3-zone distribution.

Required by `CONTEXT.md`'s standing rule: there is no live Revit host in this
environment, so any ticket touching Revit-API-dependent logic needs a
write-up demonstrating the logic is correct before it can close in review.
**58 tests pass.** What that does and does not mean is set out below.

## What the mocks verify

**Leg geometry (rev 2 §7.1, A30).** The centreline rectangle
`(b − 2·Cover − Ø_stirrup) × (h − 2·Cover − Ø_stirrup)` is checked against
the spec's own two independent formulas: §6.3's
`spacer_length = b − 2·Cover − 2·Ø_stirrup` and §4's
`offset₁ = Cover + Ø_stirrup + ½Ø_bar`. One full diameter is subtracted per
dimension (not two halves, which would cancel), because cover is measured to
the stirrup's **outer** face on each of two opposing sides.

**Closure types 1 and 2 (rev 2 §7.2, A32).** One parameterized code path.
The tests assert the two types produce the *same* four corners in the *same*
winding order, cyclically rotated so a different corner is `curves[0]` — and
that `curves[0]`'s start equals `curves[-1]`'s end, which is the hook-overlap
corner (top-right for type 1, top-left for type 2). A reversed loop would
also produce a different starting corner, but would flip which face the hook
swings toward; the winding assertion is what excludes it.

**Type 4** is an open U with no top closure and both free ends at the top.
**Type 3 is rejected** with a message naming residual question **R6** —
its inner loop's offset, diameter and hook corner are undefined in the spec,
and `CONTEXT.md` forbids inventing them.

**Zone arithmetic (rev 2 §3.1, A15–A17).** Zone bounds clipped to
`[face_A + 50, L/3]`, `[L/3, 2L/3]`, `[2L/3, face_B − 50]` on the c/c datum,
mirrored, with the degenerate guard tested firing independently at each end
for both causes (short span, wide support) and tested *not* firing just above
the boundary.

**Count and achieved spacing (rev 2 §3.2, A18).** `n_spaces =
ceil(array_length / max_spacing)` then `achieved = array_length / n_spaces`,
so the dense/normal inputs behave as **maximum** spacings.

**The R4 de-duplication mitigation.** `ZONE_LAYOUT_FLAGS` gives the dense
zones both boundary stirrups and the normal zone neither, so `L/3` and `2L/3`
are each claimed exactly once. A test asserts that property directly rather
than restating the flag values.

**Section datum (issue #18 review).** Rotation-aware `b`/`h` and the
location-curve-to-centroid offset are covered by four tests in
`tests/test_geometry.py`, including the 45° beam whose world AABB would
report `b = 6250 mm` for a 250 mm wide section, and a beam that is both
top-justified and laterally shifted.

## The two review findings and what they cost

**Finding #1 — the reported count contradicted the placement flags.**
`stirrup_count_and_spacing` returned `n_spaces + 1` unconditionally, counting
both boundary bars, while `ZONE_LAYOUT_FLAGS["zone2"] = (False, False)`
deliberately excludes both. On L = 6000 with 600 mm columns the normal zone
reported **11** stirrups where Revit places **9**. Since rev 2 §8.2 requires
per-zone counts in the report, the wrong number reached the engineer.

The include flags are now a **required** argument, so a caller cannot report a
count without stating which boundary bars the zone owns. That is the actual
fix: the two numbers can no longer drift apart, because they are computed from
the same input.

**Finding #2 — no pushbutton.** The core and adapter shipped with no entry
point, so nothing could place a stirrup or emit the report.
`Stirrups.panel/Place Stirrups.pushbutton/script.py` now does, following S1's
structure.

Two further defects were found reviewing that new pushbutton — both datum
errors, both fixed here:

- The cage was centred on the beam's **location curve** rather than its
  section centroid. With Revit's default top-justified structural framing
  that is the top face, so a 600 mm deep beam would have got a cage sitting
  300 mm high — half of it outside the host solid.
- `b` was read from the **world** AABB, which returns `b + L` for a beam that
  is not parallel to a project axis. This was pre-existing in S1 and only
  became visible here, because S5 is the first code to consume `b`.

Both now go through the beam's own local bounding box and instance transform,
the same technique S1's review adopted for rotated columns. Deriving the
centroid and `b`/`h` from **one** bounding box is deliberate: they cannot
disagree with each other.

## What is NOT verified, and why it matters

The fakes are written to match the API shape the adapter *assumes*. A green
suite proves the adapter's **logic** is self-consistent. It proves nothing
about whether the real Revit API has those members, signatures or return
types — see the running `SHAPE UNVERIFIED` list in `tests/fake_revit_api.py`.
For this ticket specifically:

- **R4 stays open.** Whether `includeFirstBar`/`includeLastBar` mean what the
  mitigation assumes cannot be observed without a live host. The flags are
  designed so that *either* reading avoids a duplicate at a zone boundary,
  but the assumption is untested.
- **`SetLayoutAsMaximumSpacing`'s parameter order** — and whether
  `GetShapeDrivenAccessor()` is even the right accessor for a
  `CreateFromCurves`-built stirrup, rather than a distinct free-form
  accessor — rests on documentation only.
- **Whether `RebarStyle.StirrupTie` permits a 180° hook.** This is the
  load-bearing unknown named in `CONTEXT.md`: if it does not, the mild-steel
  hook decision (rev 2 §7.3, A33) must be revisited.
- **The hook type itself is resolved by name with a fallback** to the first
  available `RebarHookType`. Nothing checks that its angle is actually 180°,
  so a project whose first hook type is a 90° bend gets non-compliant
  stirrups with only a printed note. Reading the angle back would need a
  parameter shape that cannot be confirmed here.
- **`GeometryInstance` extraction** for a beam or column — whether
  `get_Geometry()` yields a `GeometryInstance` wrapping symbol-space geometry
  rather than already-transformed solids — is assumed. The projection math is
  tested; the extraction step is not. If it returns solids directly, both
  datum fixes fall back to the world AABB and the rotated-beam case regresses
  silently.
- **A bounding box can be enlarged by joined or attached geometry**, in which
  case its centre is not the section centroid. Reading the justification
  parameters directly would be exact but assumes a parameter set that cannot
  be confirmed here.
- **The pushbutton has never executed.** It compiles; pyRevit and the Revit
  API are not installed in this environment, so its imports and its
  `FlexForm` interaction are unexercised — the same limitation as S1's
  script.

First live-host session should check, in this order: that the cage lands
inside the beam at the right depth (the datum fixes), that no duplicate
stirrup appears at `L/3` or `2L/3` (R4), and that a 180° hook is accepted on
a `StirrupTie` (the `CONTEXT.md` unknown).
