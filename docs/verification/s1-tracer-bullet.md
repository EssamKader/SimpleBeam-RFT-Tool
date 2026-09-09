> **Correction (issue #30, Revit 2024 live probe, `RevitAPI 24.3.40.0`):**
> the concern raised below under "The exact `RebarHostData` face-enumeration
> API" was correct, and the fresh research it describes was right:
> `DB.Structure.RebarFaceType` **does not exist** — it is not merely
> unconfirmed, the compiler rejects it. `read_face_cover_mm(host_data,
> face_type, ...)` and `SUPPORT_SIDE_FACE_TYPE`/etc. described in points 2
> and "Which `RebarFaceType` member is correct" below have been REMOVED and
> replaced by `rft.revit.host.read_beam_face_covers_mm` /
> `read_support_side_cover_mm`, which classify each exposed face's own
> normal against the beam's frame instead of looking it up by a
> nonexistent enum. See `docs/verification/issue-30-cover-face-reads.md`
> for the live measurements and the new design. The "24/24 pass" figure
> below is stale; the current count is reported in that write-up.

# S1 Mock-Object Verification Write-up

Required by `CONTEXT.md` ("no live Revit host" standing rule) and
`specs/beam-rft-detailing.md` DoD: any Revit-API-dependent behaviour needs a
mock-object verification since it cannot be executed against a real host.

**Updated for the issue #14 review fix pass (6 findings, all in the adapter
layer's coordinate construction).** The pure core and the transaction/
cover-read-back patterns were reviewed and confirmed sound; this update
covers the corrected 3-segment geometry, the derived support-face points,
the rotation-aware column width, the `LD < 200` guard, and the changed
column face-cover type.

Unlike a prose-only write-up, `tests/test_mock_revit_adapter.py` and
`tests/test_geometry.py` are **runnable pytest suites** that install fake
`Autodesk.Revit.DB` / `Autodesk.Revit.DB.Structure` modules
(`tests/fake_revit_api.py`) into `sys.modules`, then import and exercise the
**real** adapter source in `rft.revit.host`, `rft.revit.placement` and
`rft.revit.geometry` — not a re-implementation of its logic. Run:
`python -m pytest tests/ -v` (24/24 pass; see the implementation report for
the full run).

## The corrected geometry (findings #1, #2, #6)

The ticket's original "2-segment curve list (straight run `a`, then bent leg
`b`)" described one end only and contradicted its own both-ends acceptance
criteria. The corrected, implemented geometry is a **3-segment** curve list:
bend leg `b` at end A (up) → one continuous straight run spanning the beam
plus `a` into each support → bend leg `b` at end B (up)
(`rft.revit.placement.build_bottom_bar_curves`).

The straight run's endpoints (`corner_start`, `corner_end`) are derived from
each support's **near face** along the beam axis
(`rft.revit.geometry.start_support_face_point` /
`end_support_face_point`), not from the beam's `LocationCurve` endpoints —
`span_length_mm` derives `L` from the two columns' location points (c/c),
which implies those endpoints may sit at the column centreline rather than
its face, so measuring `a` from them (as the pre-review code did) could land
the bend past the far face of the support entirely.

## What is verified this way

1. **§10 host validation order** (`rft/revit/host.py:validate_rebar_host`) —
   unchanged by this fix pass, still passing (3 tests).

2. **Per-face cover read-back must not silently default**
   (`read_face_cover_mm`) — unchanged by this fix pass, still passing
   (3 tests). The face **type** passed at the call site changed (see below),
   not this function's own logic.

3. **Single-transaction-with-rollback pattern** (`run_in_transaction`) —
   unchanged, still passing (2 tests).

4. **The 3-segment curve list is structurally correct**
   (`test_bottom_bar_curve_list_has_exactly_three_segments_no_hooks`) —
   asserts exactly 3 curves; that the straight run's endpoints are `a`
   behind/beyond each face; that the straight run's length equals the
   face-to-face span plus `a_start` plus `a_end` (i.e. it actually spans the
   beam, not a floating stub — finding #1); and that both bend legs increase
   in Z (upward) from their corner.

5. **Support-face derivation** (`test_start_support_face_point_is_half_width_toward_the_span`,
   `test_end_support_face_point_is_half_width_toward_the_span`, finding #2) —
   confirms the near face sits half the support width toward the span from
   the column's own location point, on the correct side for each end,
   independent of where the beam curve's endpoint happens to be.

6. **Rotation-aware column width** (`test_column_width_along_axis_uses_rotation_aware_local_bbox_when_available`,
   finding #5) — a 600×600 column rotated 45°, with a beam framing squarely
   into one of its (rotated) faces, must still measure 600 mm along the beam
   axis. Verified by projecting the column's own local (un-rotated) bounding
   box after expressing the beam axis in the column's local frame via its
   instance transform, rather than projecting a world-axis-aligned AABB
   (which the fallback path, also tested, still uses when no
   `GeometryInstance` is found — correct only for an unrotated column).

7. **`LD < 200` raises instead of producing a negative `a`**
   (`test_ld_below_minimum_bend_leg_raises_instead_of_negative_a`,
   `test_ld_exactly_at_minimum_bend_leg_does_not_raise`, finding #3) — the
   pure core now raises `ValueError` before a negative/zero-length straight
   run could ever reach curve construction; 200 mm exactly is still valid
   (`a` can legitimately be 0), only below it errors.

## What could not be verified even with mocks, and why

- **`rft/revit/geometry.py`'s `find_supporting_column` and
  `beam_section_dimensions_mm`** remain unexercised by the mock suite, for
  the same reason as before this fix pass: `docs/research/revit-api-strategy.md`
  does not cover "how do I find the column supporting a beam's end" at all,
  and the bounding-box-proximity approach is this ticket's own design
  choice, untested against a real model.

- **`_rotation_aware_local_bbox`'s use of `FamilyInstance.get_Geometry()` /
  `GeometryInstance`** (finding #5's fix) is new and explicitly flagged
  UNVERIFIED in its own docstring: whether a structural column instance
  reliably yields a `GeometryInstance` wrapping symbol-space geometry (vs.
  some families/`Options` combinations returning already-world-transformed
  `Solid`s directly, bypassing the wrapper) has not been confirmed without a
  real model. The tests above verify the **projection math** is correct
  given such an object; they cannot verify the extraction step itself.

- **The exact `RebarHostData` face-enumeration API** — flagged before as
  "best-documented candidate, not confirmed" — is now flagged more strongly.
  Fresh research during this fix pass turned up published Revit API
  reference pages (revitapidocs.com, several versions) describing
  `RebarHostData.GetExposedFaces() -> IList<Reference>` and
  `GetCoverType(Reference face) -> RebarCoverType` directly, with **no**
  `GetFaces(RebarFaceType)` overload and no `RebarFaceType`-keyed lookup
  appearing at all. If accurate, this module's whole face/cover-lookup
  shape — not just which `RebarFaceType` member is passed — may not match
  the real API. This is a bigger redesign than the review's finding #4
  (which asked only to stop passing `Bottom` for a column's side), so the
  existing shape was kept for this fix pass, but the concern is recorded
  here and in `rft/revit/host.py`'s module docstring rather than quietly
  left as a footnote: **this whole area needs live-host verification before
  shipping**, more urgently than previously understood.

- **Which `RebarFaceType` member is correct for a column's side face**
  (finding #4): `Bottom` was definitely wrong (a column's base, not a side).
  `RebarHostData`'s documented per-face cover parameters
  (`CLEAR_COVER_TOP`/`CLEAR_COVER_BOTTOM`/`CLEAR_COVER_OTHER` for "most
  hosts", vs. `CLEAR_COVER_EXTERIOR`/`CLEAR_COVER_INTERIOR` specifically for
  walls) suggest `Other` is the best-documented candidate for a column's
  lumped side faces, and the code now uses it
  (`SUPPORT_SIDE_FACE_TYPE` in script.py) — but this is a best-effort
  substitution under the API-shape uncertainty above, not a confirmed
  answer, and is marked UNVERIFIED at its declaration.

- **`Rebar.CreateFromCurves`'s `useExistingShapeIfPossible`/`createNewShape`
  flags** (`True, True` in `place_anchored_bar`) and whether the resulting
  Rebar defaults to a single physical bar with no further layout call
  needed — unchanged from before, still unverified.

- **The pushbutton `script.py` orchestration end-to-end** (picking an
  element via `revit.pick_element`, `pyrevit.forms.FlexForm`,
  `script.get_output()`) depends on the live pyRevit/Revit session and
  cannot be executed or meaningfully mocked outside one.

These are exactly the categories `docs/research/revit-api-strategy.md`'s own
"Unverified against a live host" section already anticipated, plus the two
new items this fix pass surfaced (the `GetExposedFaces`/`GetCoverType`
API-shape mismatch, and the `GeometryInstance` extraction step for
rotation-aware width).
