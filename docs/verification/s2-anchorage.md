# S2 Mock-Object Verification Write-up

Ticket [#15](https://github.com/EssamKader/rft-beam-detailing/issues/15) --
full end anchorage: top and bottom bars, all support types.

Required by `CONTEXT.md`'s standing rule: there is no live Revit host in this
environment, so any ticket touching Revit-API-dependent logic needs a
write-up demonstrating the logic is correct before it can close in review.
**119 tests pass** (91 baseline + 28 new: 12 pure-core in `test_anchorage.py`,
8 adapter in `test_geometry.py`, 8 adapter in `test_mock_revit_adapter.py`).
What that does and does not mean is set out below.

## What the pure-core tests verify (runs under plain CPython, no mocks needed)

- **Top bar anchorage (§2.1/§2.2).** `a_t = Support width - Cover - O_BTM`,
  bending downward, sharing the same §2.3 cap/clamp discipline as the bottom
  bar (refactored into a shared `_capped_anchorage` helper so the two
  formulas cannot drift apart independently). A dedicated regression test
  (`test_top_bar_uses_bottom_diameter_not_top_diameter`) computes what the
  result WOULD be if `O_TOP` were substituted for `O_BTM` and asserts the
  real result differs from it -- a test that only checked the formula's
  shape would not catch that specific "fix".
- **Top/bottom centreline clearance (§2.2, A7).** Both worked examples from
  this ticket: O_TOP=12/O_BTM=16 passes (16 mm achieved vs. 14 mm required,
  2 mm slack); O_TOP=25/O_BTM=16 fails (16 mm vs. 20.5 mm required). A third
  test pins the O_TOP == O_BTM boundary, where achieved == required exactly.
- **Unsupported-end anchorage (§2.5, A12, R3 resolved).**
  `unsupported_end_straight_run_mm` (the `beam end - cover` subtraction) and
  `unsupported_end_anchorage` (the warning, naming both required `LD` and
  achieved length) are tested both for the warning firing and for the
  (rarer) case where the achieved length happens to meet `LD` and no
  warning fires.
- **The free-end configuration warning (§2.5, A14)** is tested to name both
  "cantilever" and "out of scope".

## The clearance derivation, verified as instructed

The ticket asked to verify the stated derivation before implementing it.
Confirmed: because `a_btm - a_t = O_BTM` always (both formulas share
`Support width - Cover` before `a_t` additionally subtracts `O_BTM`), the
achieved separation is fixed at `O_BTM` regardless of `O_TOP`. The required
separation is `(O_TOP + O_BTM) / 2`. Clearance holds (`achieved >= required`)
**only when `O_TOP <= O_BTM`**. For O_TOP=12/O_BTM=16: 16 mm achieved vs.
14 mm required, 2 mm slack. For O_TOP=25/O_BTM=16: 16 mm vs. 20.5 mm
required -- a clash. Both are exactly the numbers the ticket gave, now
pinned as tests (`test_clearance_holds_for_top12_bottom16`,
`test_clearance_fails_when_top_diameter_exceeds_bottom`).

**This is a genuine spec gap**, not resolved by this ticket: rev 2 does not
say what to do when `O_TOP > O_BTM`. `top_bottom_clearance_warning` emits a
**non-blocking warning** naming achieved vs. required and says explicitly in
its own message that a decision ticket is needed -- warn, refuse or
auto-adjust was not decided here, per this ticket's instructions.

**A further, un-asked-for observation, not acted on**: `top_bottom_clearance_mm`
checks the FORMULA-level invariant (before the §2.3 cap/clamp is applied). If
the cap fires asymmetrically between the top and bottom bar -- e.g. very
different `LD_top`/`LD_btm` multipliers, or a support narrow enough that one
formula's `a` gets capped and the other's does not -- the ACTUAL as-built
separation could differ from this check's result. Rev 2 does not address
this either; flagged here rather than silently extended into new logic.

## What the mock-object tests verify (`test_geometry.py`, `test_mock_revit_adapter.py`)

**Support detection generalised to any structural support (§2.4, A9).**
`find_supporting_element` now searches `OST_StructuralColumns`,
`OST_Walls` and `OST_StructuralFraming` (for girders) in one pass, returns
the nearest bounding-box centre across all three categories, and excludes
the beam being detailed itself via `exclude_element_id` (necessary because a
girder search uses the SAME category the beam itself belongs to). Tested:
nearest-wins across mixed categories, self-exclusion when the beam and its
girder support tie on distance, and returning `None` for a genuinely free
end.

**Wall support width = wall thickness, any incidence angle (R5, resolved).**
`support_width_along_axis_mm` branches on `isinstance(support, Wall)` and
returns `Wall.Width` directly -- tested with the beam meeting the wall at
30 degrees, confirming the result is unaffected by `axis_direction` (as R5
requires: deliberately conservative, not a swept intersection length).

**Girder width reuses the column projection unchanged.** A 400x800 girder
rotated 30 degrees, with the beam framing squarely into one face, measures
400 mm via the SAME `_local_extent_along` path already used for columns --
not a second projection, per this ticket's instruction.

**`support_reference_point`'s Location.Point vs. Location.Curve fallback.**
Tested for a point-located support (returns the point unchanged), a
curve-located support (returns the curve's midpoint -- this ticket's own
design choice, see below), and an element with neither (raises).

**Bent vs. unsupported end-corner geometry.** `bent_end_corner` is checked
byte-for-byte against the corner points `build_bottom_bar_curves` already
computes inline (S1's already-verified baseline), for both ends' sign
conventions -- confirming the refactor changed nothing. `unsupported_end_corner`
is checked to move INWARD from the beam's physical end point by the cover,
for both ends. `main_bar_end_geometry` is checked to return a real bend leg
for a supported end and **`None`** (not zero) for an unsupported one, which
is the mechanism that keeps the §2.3 mandatory-hook rule from firing there.

**`build_main_bar_curves` covers all three segment counts.** Both ends bent
(3 segments, matching S1's baseline exactly, not just in length); one end
bent / one straight (2 segments, the new mixed case this ticket exists for);
both ends straight (1 segment).

## Two design choices this ticket had to make where rev 2 does not settle the point

**1. `support_reference_point`'s curve-midpoint fallback.** A column exposes
`Location.Point`; rev 2 says nothing about what a wall or girder's `Location`
looks like, and neither does `docs/research/revit-api-strategy.md` (support
detection beyond columns was never researched there -- see
`rft/revit/geometry.py`'s pre-existing module docstring). Falling back to the
`Location.Curve`'s midpoint is this ticket's own engineering choice, not a
spec-derived rule -- flagged inline with a `SHAPE UNVERIFIED / DESIGN CHOICE`
note and repeated here per this ticket's instructions.

**2. The unsupported-end "achieved length" formula.** Rev 2 (R3, resolved)
only says "run to beam end - cover and warn that LD is not achieved, stating
both numbers" -- it does not define what "achieved" means numerically when
there is no support to measure `a` from. This ticket's `distance_to_beam_end_mm
= 0.0`, applied at the script call site with an inline comment: with no
support there is no positive "into support" credit at all, equivalent to
plugging `support_width = 0` into the supported-end formula (`a_formula =
support_width - cover` becomes `-cover`, matching `unsupported_end_straight_run_mm`'s
result exactly). This is deliberately the smallest, most literal reading of
"run to beam end - cover" and is why the warning fires on essentially every
unsupported end -- which is the intended effect of A14 flagging that
configuration as out of scope for v1, not an accident of the formula. This is
this ticket's own interpretation, not a rev 2 formula, and is called out here
rather than presented as settled.

## The review-relevant scoping decision this ticket made

**Only "Place Main Bars.pushbutton" got the full S2 treatment.** Per this
ticket's explicit instruction ("close that hole there rather than adding a
fourth pushbutton"), the unsupported-end / any-support-type logic for
PLACEMENT was added only to `Main Bars.panel/Place Main Bars.pushbutton`,
which already placed bottom bars (S3) and now places top bars too, both
faces independently anchored at both ends. `Place Bottom Bar.pushbutton`
(S1) and `Place Stirrups.pushbutton` (S5) were updated only for the renamed
support-detection functions (`find_supporting_element`,
`support_width_along_axis_mm`) plus `exclude_element_id`; they keep their
original both-ends-supported assumption and still error out on a missing
support rather than taking the unsupported path. This is a scope decision,
not an oversight -- flagged explicitly per this ticket's report instructions.

## The two review findings, and what they cost

**1. The A7 clearance was only checked at formula level, so an asymmetric
cap slipped through.** `top_bottom_clearance_mm` tests the invariant
`a_btm − a_t = Ø_BTM` that §2.1/§2.2 guarantee *before* §2.3's
`a = min(a_formula, LD − 200)` cap. That cap fires per bar, and `LD_top`
and `LD_btm` are independent multipliers (60 vs 55), so at a wide support
it can fire on one bar and not the other.

Worked case, now pinned as a test: `Ø_TOP = Ø_BTM = 16` on an **800 mm**
support with 25 mm cover — an entirely ordinary column or wall.
`Support width − Cover = 775`; the bottom bar caps at `880 − 200 = 680`
while the top bar's formula value `759` stays under its own `960 − 200`
cap. The bars as built are separated by **−79 mm**: the top bar's straight
leg runs 79 mm *past* the bottom bar's, so the two bends have crossed —
while the formula-level check still reported a comfortable +16 mm against
a required 16 mm and stayed silent.

Fixed by adding `placed_clearance_mm` / `placed_clearance_warning`, which
run the same A7 comparison on the `a` values actually built, per end, and
say explicitly when the achieved separation is negative that the bends have
crossed rather than merely closed up. The formula-level check is kept —
it catches the `Ø_TOP > Ø_BTM` input case, which the as-built check would
also catch but for a different reason.

The implementer identified this risk class and consciously left it open as
out of scope. It was worth closing here: the numbers come from values the
pushbutton already had in hand, and the failure is silent otherwise.

**2. The unsupported-end report printed a negative length.** The achieved
length was computed as `0 − beam_end_cover`, i.e. **−25 mm** for a typical
cover, and that number went into R3's warning: "achieves only −25.0 mm
against LD = 880.0 mm". Two different quantities were being conflated —
where the bar *stops* (25 mm short of the beam end) and how much anchorage
it *achieves*.

At an unsupported end the embedment achieved is **0**: there is no support
to embed into. The termination short of the beam end is a separate
geometric fact and is now reported as one. R3 requires the warning to state
both the required `LD` and the achieved length, and it now does so with two
numbers an engineer can act on. A test asserts no negative number appears
in the warning at all.

Neither finding touched the placed geometry — the placement path already
used the cover directly rather than the negative value — so both were
reporting defects. That is not a reason to leave them: the report is the
deliverable an engineer reads to decide whether to trust the bars.

## What is NOT verified, and why it matters

- **The pushbutton has never executed against a real Revit session.**
  pyRevit and the Revit API are not installed in this environment. Beyond
  the pytest suite, this ticket additionally ran an ad hoc harness (not
  part of the committed test suite, not reusable as a regression check)
  that installs minimal fake `pyrevit` modules and imports/executes all
  three pushbuttons' `main()` up to the point where `pick_element` returns
  `None`. All three loaded and reached `script.exit()` cleanly with no
  `NameError`/`AttributeError` -- confirming every renamed import and every
  new name this ticket introduced resolves correctly, which is a stronger
  signal than a syntax check alone, but it is NOT a full placement run with
  a real beam/support/RebarHostData chain (that remains unexercised, same
  limitation S1/S3/S5 already carry).
- **Whether a girder or wall instance exposes `Location.Point` or
  `Location.Curve`** (`support_reference_point`'s fallback) was not
  confirmed against a live host.
- **`Wall.Width`'s exact semantics** -- whether it returns the wall's total
  thickness including both wythes/layers, or something narrower (e.g. the
  wall type's nominal thickness vs. as-built) -- is assumed, not confirmed.
  Flagged in `tests/fake_revit_api.py`'s header per `CONTEXT.md`.
- **Which `RebarFaceType` member (if any) actually addresses a framing
  element's cut END face**, as distinct from its side/top/bottom faces, for
  the unsupported-end `beam_end_cover` read. This ticket kept
  `BEAM_END_FACE_TYPE = RebarFaceType.Other` -- the same placeholder already
  used for the support's side cover and the beam's own side cover -- but
  named it as a THIRD, conceptually distinct constant so a future fix to any
  one of the three does not silently change the other two. Whether
  `RebarHostData` exposes an end-face cover AT ALL is unconfirmed and
  flagged in the script's own module-level comment, which is stronger than
  the pre-existing uncertainty this whole area already carried (see
  `rft/revit/host.py`'s module docstring).
- **`OST_Walls`/`OST_StructuralFraming` as valid `FilteredElementCollector.OfCategory`
  arguments** are assumed to exist and behave like `OST_StructuralColumns`
  already did (untested new API surface, flagged in `tests/fake_revit_api.py`).
- **The exclusion tie-break in `find_supporting_element`.** When the beam
  and a real girder support tie on bounding-box-centre distance (as tested),
  the exclusion check runs BEFORE the distance comparison, so the excluded
  element can never win regardless of tie order. This is correct by
  construction in the current loop, but has not been checked against how a
  real model's element iteration ORDER might vary run to run.

## Scope boundaries held (see this ticket's instructions)

- No new detailing rule was invented for the `O_TOP > O_BTM` clearance
  failure -- it is reported and warned, not decided (spec gap, needs a
  decision ticket).
- R3 and R5 were implemented exactly as resolved, not re-opened or
  re-decided.
- The multi-span / continuous-beam guard (spec §9 item 2, still deferred)
  is out of this ticket's scope and was not touched.
