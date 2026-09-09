# Issue #30 Mock-Object Verification Write-up — cover reads without `RebarFaceType`

Ticket [#30](https://github.com/EssamKader/rft-beam-detailing/issues/30) —
`DB.Structure.RebarFaceType` does not exist in the Revit API. Every cover
read in the tool (`read_face_cover_mm`) was built on it and raised
`AttributeError` on the first cover read in all four pushbuttons, before
anything was placed.

Required by `CONTEXT.md`'s standing rule: there is no live Revit host in
this environment, so this write-up demonstrates the replacement logic is
correct via `tests/fake_revit_api.py` and `tests/test_mock_revit_adapter.py`
before it can close in review. **241 tests pass** (`python -m pytest tests/
-q`). What that does and does not prove is set out below.

## What was verified live, and against what

Revit **2024** (build 24.3.40.26), `RevitAPI 24.3.40.0`, model
`RFT_V1_CONTROL_detached` — probed live through an MCP connector for issue
#23, whose findings this ticket implements. Confirmed:

- `DB.Structure.RebarFaceType` does not exist. The compiler rejects it
  outright (`The type or namespace name 'RebarFaceType' does not exist in
  the namespace 'Autodesk.Revit.DB.Structure'`). This was never merely
  unconfirmed — the `SHAPE UNVERIFIED` note on it (`rft/revit/host.py`,
  `tests/fake_revit_api.py`) is exactly what kept that honest until a host
  could say so.
- The real `RebarHostData` surface: `GetExposedFaces() -> IList<Reference>`,
  `GetCoverType(Reference) -> RebarCoverType`, `GetCommonCoverType()`,
  `IsFaceExposed(Reference)`, `IsValidHost()`. Cover is keyed by a
  geometric `Reference` to an actual face, never by a face-role enum.
- `face.ComputeNormal(UV(0.5, 0.5))` and
  `Element.GetGeometryObjectFromReference(Reference)` both work live and
  were how the probe recovered each face's normal.
- A SUPPORTED beam's `GetExposedFaces()` returns exactly **FOUR** faces —
  TOP, BOTTOM, two SIDEs — never six. Both ends are inside their columns
  and so are never exposed:

  ```
  [1] TOP        normal=(0,0,1)   cover -> Interior (framing, columns) | 38.1 mm
  [2] SIDE (-u)  normal=(0,-1,0)  cover -> Interior (framing, columns) | 38.1 mm
  [3] BOTTOM     normal=(0,0,-1)  cover -> Interior (framing, columns) | 38.1 mm
  [4] SIDE (+u)  normal=(0,1,0)   cover -> Interior (framing, columns) | 38.1 mm
  ```

- The model carries **two different `RebarCoverType` elements sharing the
  identical `Name`**, `Interior (framing, columns)`, at 38.1 mm and 40 mm —
  the live evidence for "compare cover types by element id, never name."
- `RebarCoverType.CoverDistance` is a real, readable property in internal
  units, confirmed live.

## The replacement design

`rft.revit.host.classify_face_role(normal, u_dir, v_dir, axis, tol)`
resolves a face's ROLE from its `ComputeNormal` result against the beam's
own local frame (`rft.revit.geometry.beam_section_axes`' `u_dir`/`v_dir`,
plus the beam's own axis direction) — reusing that frame, never deriving a
second one:

```
|n . v_dir| > tol  -> TOP (n . v_dir > 0) or BOTTOM
|n . axis|  > tol  -> END_END (n . axis > 0) or END_START
|n . u_dir| > tol  -> SIDE
otherwise          -> None (refuse, never guess)
```

`read_beam_face_covers_mm` calls this for every face `GetExposedFaces()`
returns, buckets them by role, and enforces:

- Exactly one TOP face, exactly one BOTTOM face — refuse otherwise.
- Exactly two SIDE faces, whose cover types must be the SAME element (`Id`
  equality) — a mismatch refuses rather than silently picking one.
- END faces (`END_START`/`END_END`) are only read when the caller's
  `need_end_start`/`need_end_end` flags say so, and a required-but-missing
  end face is a refusal, never a fallback to another face's cover.
- Any face whose normal is oblique to all three directions within
  tolerance is a refusal naming the face's index and normal, never a
  guessed role.

`read_support_side_cover_mm` resolves the SUPPORTING element's own cover
(rev 2 section 2.4, A8) by classifying the SUPPORT's own exposed faces
against the shared beam axis direction alone — not the beam's
`(u_dir, v_dir)` cross-section frame, which has no meaning against a
column's faces (this ticket's brief item 6). The face that governs is
whichever exposed face has an outward normal aligned with `axis_direction`
on the FAR side -- the face the anchored bar's tip approaches, not the
face it enters through: `-axis_direction` for the start support,
`+axis_direction` for the end support — the same sign convention
`start_support_face_point`/`end_support_face_point` already use. **This is
this ticket's own engineering choice for "the support's own frame"**; rev 2
does not itself define one, and it has not been confirmed against a live
host with a non-symmetric support cross-section.

## What the mocks verify

**Rotation is not a shortcut away.** `test_classify_face_role_is_rotation_aware_not_a_world_axis_shortcut`
builds a beam at 45° in plan whose SIDE and END face normals are oblique in
WORLD terms (neither a pure X nor Y vector) but exact against the beam's
OWN frame, and asserts `classify_face_role` gets them right — and that
reading the SAME 45°-beam END face normal against the wrong (world, +X)
frame makes it unclassifiable (refuses) rather than silently misclassifying
it as something else. A green suite against only a +X-aligned beam (the
live probe's own test beam) would never catch a `normal.Z`/`normal.X`
world-axis shortcut — this mirrors the exact defect issue #18's review
found in the bounding-box code.

**Two SIDE faces are handled deliberately, not by "first one found."**
`test_read_beam_face_covers_two_side_faces_with_equal_cover_ids_pass` and
`test_read_beam_face_covers_two_side_faces_same_name_different_id_refuses`
assert the equal-id case passes and the different-id case (same `Name`,
different `Id` and `CoverDistance` — the live model's own configuration)
refuses.

**`cover_end` is conditional.** `test_read_beam_face_covers_end_not_
requested_on_a_supported_beam_is_not_an_error` shows requesting neither end
face succeeds on a 4-face supported beam with no end face at all — the
whole point of the `need_end_start`/`need_end_end` flags.
`test_read_beam_face_covers_raises_when_a_required_end_face_is_missing`
shows requesting a required end face that is not exposed refuses rather
than falling back to another face's cover.

**Undefined cover and oblique faces still refuse.**
`test_read_beam_face_covers_raises_on_undefined_cover_rather_than_silently_
defaulting` and `test_read_beam_face_covers_raises_on_oblique_face_naming_
it_rather_than_guessing` are unchanged in intent from the pre-#30 tests,
rebuilt against the real `Reference`/`RebarCoverType`-keyed shape.

**The support's own cover reads the correct face by sign.**
`test_read_support_side_cover_mm_start_support_reads_face_facing_the_beam`
and `..._end_support_reads_the_opposite_face` build a support with a "near"
face (normal along `-axis`) and a "far" face (normal along `+axis`) with
deliberately different covers, and assert the start support reads the near
one while the end support reads the far one.

## The 229→241 test count and what changed in the fakes

`tests/fake_revit_api.py` was rebuilt to the confirmed-live shape:
`FakeRebarHostData` (per-scenario stubs) now expose `GetExposedFaces()` /
`GetCoverType(Reference)` directly; `FakeReference`, `FakeFace` (with
`ComputeNormal`) and `FakeUV` are new; `FakeRebarCoverType` replaces the old
`ElementId`-then-`doc.GetElement` round trip with the object
`GetCoverType` actually returns, carrying `CoverDistance`, `Name` and an
auto-incrementing `Id` so two same-name, different-id cover types can be
constructed for the exact live-model scenario. `FakeRebarFaceType` was
deleted outright — it faithfully reproduced an enum that does not exist,
which is precisely the risk `CONTEXT.md`'s `SHAPE UNVERIFIED` discipline
exists to flag before a host can say so.

The three `*_FACE_TYPE = DB.Structure.RebarFaceType.Other` aliases are gone
from all three pushbuttons that had them ("Place Bottom Bar", "Place Main
Bars", "Place Crack Bars"); "Place Stirrups" never used `RebarFaceType` at
all (its `Cover` is a typed input, not a host read-back) and is untouched.

## Ordering change this ticket forced (Main Bars, Crack Bars)

`cover_end` can now only be requested where an end face is actually
exposed — an unsupported end. That means support detection must run
BEFORE the beam-side cover read in both "Place Main Bars" and "Place Crack
Bars", where previously the cover read ran first unconditionally. Both
pushbuttons were reordered: continuous-run guard → support detection → (Main
Bars only: the "no support at either end" refusal) → cover reads → (Main
Bars only: §6.2-6.4 spacing validation, now after cover reads instead of
before support detection). `docs/verification/s4-spacing-validation.md` and
`s2-anchorage.md`'s claims about this ordering have been corrected in place
to point here rather than restating the old (now false) sequence.

"Place Crack Bars" now reads its two end-face covers SEPARATELY
(`cover_end_start_mm`, `cover_end_end_mm`) rather than the single shared
`cover_end_mm` the old `BEAM_END_FACE_TYPE` constant produced — each is
passed only to `crack_bar_end_result` for its own end. "Place Main Bars"
keeps a single `cover_end_mm`, since the pre-existing "no support at
either end" refusal already guarantees at most one end is ever
unsupported, so at most one of `end_start_mm`/`end_end_mm` is ever
populated there; this is not a discrepancy in correctness, only in how
defensively each pushbutton names its variables.

## Verified live on a ROTATED beam (2026-09-09)

The original probe ran on a beam aligned to **+X**, which is exactly the
case a world-axis shortcut survives. The project owner then modelled a
second, identical 300 x 900 beam at **45 deg in plan**, and both were
re-probed against the live host. This closes the one assumption this
ticket could not measure at the time.

```
beam 1944835  plan angle = 0 deg    axis=(1, 0, 0)       u_dir=(0, 1, 0)
  WORLD AABB in plan: dx=9000.0  dy=300.0
  TOP       n=(0, 0, 1)        world-axis check would also classify
  SIDE(-u)  n=(0, -1, 0)       world-axis check would also classify
  BOTTOM    n=(0, 0, -1)       world-axis check would also classify
  SIDE(+u)  n=(0, 1, 0)        world-axis check would also classify
  TRUE section from faces: b=300 mm, h=900 mm    (oblique faces: 0)

beam 1945073  plan angle = 45 deg   axis=(0.7071, 0.7071, 0)  u_dir=(-0.7071, 0.7071, 0)
  WORLD AABB in plan: dx=6576.1  dy=6576.1
  TOP       n=(0, 0, 1)        world-axis check would also classify
  SIDE(-u)  n=(0.707, -0.707, 0)   WORLD-AXIS CHECK WOULD FAIL/REFUSE
  BOTTOM    n=(0, 0, -1)       world-axis check would also classify
  SIDE(+u)  n=(-0.707, 0.707, 0)   WORLD-AXIS CHECK WOULD FAIL/REFUSE
  TRUE section from faces: b=300 mm, h=900 mm    (oblique faces: 0)
```

**Face classification: correct on both, and the rotated case proves the
frame-relative check is doing real work.** Both SIDE normals on the 45 deg
beam are `(+/-0.707, +/-0.707, 0)` — neither a world X nor a world Y
vector. A `abs(n.X) > tol` / `abs(n.Y) > tol` check refuses or misclassifies
both of them, while the beam-frame check resolves them exactly, with **zero
oblique faces** and the true `b = 300`, `h = 900` recovered from face areas
on both beams. The 45 deg unit test that shipped with this ticket asserted
this; the live host now measures it.

**S5's world-AABB defect, quantified.** On the 0 deg beam the world
bounding box gives `dy = 300.0` — which *is* `b`, by coincidence of
alignment, so reading it would have looked correct forever. On the 45 deg
beam the same read gives `dx = dy = 6576.1 mm`, where the true `b` is
**300 mm**: a factor of nearly 22. That value is exactly
`(9000 + 300) / sqrt(2)`, the `(b + L)` diagonal signature #18's review
predicted analytically. The prediction and the measurement agree to a
tenth of a millimetre.

**The z-datum, on both beams.** Location curve at `z = -3800 mm`, section
centroid at `z = -4250 mm`, so `dv = -450 mm = -h/2` — the beam hangs
entirely below its location curve under Revit's default justification.
Identical on both beams, so it is a convention rather than a property of
one element. Centring the cage on the location curve would place it half
outside the beam, which is precisely what S5's review found and fixed.

## Review finding (fixed before commit)

**The support-cover face was selected correctly and documented backwards.**
`read_support_side_cover_mm` picks the face whose outward normal is
`-axis_direction` at the start support -- which is the **far** face, the one
the anchored bar's tip approaches. That is right: §2.2's `a = support_width
- cover` measures `a` inward from the face the bar *enters*, so the tip
lands `cover` short of the opposite face, and it is the opposite face's own
cover that limits where the bar may stop.

Every label around it said the opposite -- the docstring called it "the
start support's near face", the reported label read "support side (facing
the beam)", both refusal messages said "on the side facing the beam", and
the test was named `..._reads_face_facing_the_beam`. The face facing the
beam is the `+axis` one, and it is *not* the one read.

That matters more than a wording slip. Correct behaviour described by an
inverted rule is worse than either alone: the next reader checks the
docstring against the code, concludes the code is wrong, and "fixes" a
correct sign. On a support with equal cover all round the two readings
coincide, so the regression would place bars and never show itself; it
separates only on something like an edge column with a larger exterior
cover, which is exactly where getting it right matters. Four of the six
review findings in this project have been a value measured against the
wrong reference, and this is the first time the reference was right and the
*documentation* carried the error.

Names, label and messages now say "far face (the face the anchored bar's
tip approaches)", the docstring derives why from §2.2 and warns against
inverting it, and the test carries deliberately different covers on the two
faces (38.1 vs 999.0) so an inversion fails loudly instead of coinciding.

## What is NOT verified, and why it matters

The fakes are written to match the API shape the probe recovered. A green
suite proves the adapter's **logic** is self-consistent against that shape.
It does not re-prove the shape itself beyond what issue #23's single live
session recorded — see the running `SHAPE UNVERIFIED` list in
`tests/fake_revit_api.py`'s header for what is newly confirmed and what
still is not.

- **`RebarCoverType.Id`/`.Name`** are assumed to be the standard `Element`
  members. The live probe confirmed `CoverDistance` specifically; `Id`/
  `Name` were not independently re-probed (though there is no reason to
  expect `RebarCoverType`, itself an `Element` subtype, to differ).
- **The support's own frame (`read_support_side_cover_mm`)** is this
  ticket's own design choice, not something the live probe or rev 2 itself
  settles. It has only been checked against a support whose cross-section
  is symmetric about the beam axis (a typical rectangular column/wall);
  an asymmetric or heavily rotated support is untested even by mock.
- **`NORMAL_ALIGNMENT_TOL = 0.999`** is this ticket's own choice (~2.5°),
  not a spec value or a live-probed tolerance. A real model with slightly
  non-planar or chamfered faces could refuse where a looser tolerance would
  have passed; that is the intended failure mode (refuse rather than
  silently accept a wrong role) but the exact tolerance is a judgement
  call, not a measurement.
- **The pushbuttons have never executed against a real Revit session.**
  pyRevit and the Revit API are not installed in this environment; the
  reordering in "Place Main Bars"/"Place Crack Bars" is verified by code
  reading and `python -m py_compile`, not by running it.
- **`RebarBarType.BarNominalDiameter` vs. `BarModelDiameter`** — issue
  #23's same live session found both properties exist and were identical
  for all 15 bar types in the test model, so this specific model cannot
  discriminate between them; the choice of which one is authoritative in
  general remains open, unrelated to this ticket's own scope.

First live-host session for THIS ticket should place a beam whose two SIDE
covers genuinely differ (to confirm the mismatch refusal fires instead of
being unreachable in practice), and a beam rotated in plan (to confirm the
rotation-aware classification the mocks can only simulate).
