# S3 Mock-Object Verification Write-up

Ticket [#16](https://github.com/EssamKader/rft-beam-detailing/issues/16) —
cross-section bar layout: layer offsets, corner-bar distribution, spacer
length, and the R1 warning.

Required by `CONTEXT.md`'s standing rule: there is no live Revit host in this
environment, so any ticket touching Revit-API-dependent logic needs a
write-up demonstrating the logic is correct before it can close in review.
**91 tests pass** (58 baseline + 33 new: 31 pure-core in `test_layout.py`,
2 adapter in `test_mock_revit_adapter.py`). What that does and does not mean
is set out below.

## What the pure-core tests verify (runs under plain CPython, no mocks needed)

- **First-layer offset (§4).** `offset_1 = Cover + Ø_stirrup + ½Ø_bar`,
  applied independently per face with each face's own diameter.
- **Multi-layer accumulation (§4.1, A20).** `offset_n = offset_1 + (n-1) x
  (Ø_bar + Ø_spacer)` for `n = 1..5`, tested for every layer 1 through 5 with
  differing top (Ø12) and bottom (Ø16) diameters, and shown to diverge
  further apart as layers stack (one diameter per face, not shared).
- **n out of range (§4.1).** `n = 0, 6, -1, 100` all raise `ValueError`
  naming "section 4.1".
- **Spacer length (§6.3)** and its deliberate two-diameter-vs-one-diameter
  difference from `rft.core.stirrups.centreline_leg_dimensions_mm` (§7.1),
  checked algebraically against the existing stirrup module rather than
  merely re-asserting the formula.
- **Corner-bar rule (§6.1).** 2, 3 and 5-bar cases: the two ends are always
  exactly the corner offset (`±(b/2 - side_offset)`), the middle bar of an
  odd count sits exactly on the centroid, and all gaps in a 5-bar layer are
  equal. The corner offset itself is asserted to equal `first_layer_offset_mm`
  bit-for-bit (not merely approximately), since the ticket requires deriving
  it from the shared function rather than restating the arithmetic.
- **R1 warning.** Fires when `Ø_spacer < max(25, Ø_bar, 1.33*D_agg)`, tested
  with each of the three terms as the governing one, tested not firing when
  comfortably above the minimum, and tested at the exact boundary (`spacer ==
  minimum` does not fire, since the rule is `<`, not `<=`).

## The two decisions this ticket had to make where rev 2 does not settle the point

**1. Corner-bar rule with `bar_count < 2` is refused, not guessed.** Rev 2
§6.1 says "a bar at each corner of the stirrup cage; remaining bars ... at
equal spacing between the corner bars." A one-bar face has no "each corner"
to place bars at, and the spec never addresses a single-bar face (in
practice a real design would use `bar_count >= 2`, but nothing in rev 2 says
so explicitly). Rather than silently placing one bar at the centroid or at
one arbitrary corner, `corner_bar_u_positions_mm` raises `ValueError` naming
§6.1 for `bar_count < 2`. **This is a judgement call, not a spec-derived
rule** — flagging it here per this ticket's instructions rather than burying
it in a docstring only.

**2. `D_agg` has no fallback in this module.** §6.2's 50 mm fallback is
explicitly scoped to the *horizontal* `min_spacing` check (S4, #17), which is
a different formula from R1's vertical-spacer warning. Making `D_agg`
required here (rather than reusing S4's 50 mm fallback, which rev 2 never
says applies to R1) avoids inventing a rule the spec does not state. The
pushbutton enforces this by refusing to proceed if `D_agg` is left blank,
even though rev 2 §8.1 ships the *field* blank by default — the field being
blank does not mean this specific check has a default.

## What the mock-object tests verify (`test_mock_revit_adapter.py`)

**`bar_face_points_at_uv`.** Given the section's `u_dir`/`v_dir`, the
curve-to-centroid correction (`du`/`dv`, from `beam_section_centre_offsets`,
issue #18's finding), and a bar's own centroid-local `(u, v)` mm coordinate
from `rft.core.layout`, the function is checked to add BOTH offsets into the
final support-face point — not just one of them, which would silently
reproduce issue #18's original datum bug for main bars instead of stirrups.
A second test with a zero centroid-correction confirms the bar offset alone
degenerates to the expected plain case.

This function, and the whole placement pipeline it feeds
(`build_bottom_bar_curves`, `place_anchored_bar`, `run_in_transaction`), is
otherwise identical to S1's already-verified machinery — reused per bar
inside a loop over layers x corner-bar positions, not reimplemented.

## The review finding, and what it cost

**Horizontal dimensions were computed from the wrong cover.** The pushbutton
passed the *top* face cover to the corner-bar rule for the top layers and the
*bottom* face cover for the bottom layers, and computed the spacer length
twice — once per face cover.

Both of those are horizontal dimensions across the section, so the **side**
face cover governs them:

- The corner bar's inset from a side face (§6.1) has nothing to do with the
  top or bottom cover. Whenever the side cover differs from a face cover, every
  corner bar was misplaced horizontally — and the top and bottom layers came
  out at *different* u positions in the same beam, which no reading of §6.1
  produces.
- §6.3 defines **one** `spacer_length = b − 2·Cover − 2·Ø_stirrup` per section.
  Reporting two contradictory values means at least one is wrong, and nothing
  in the spec chooses between them.

The pure core was never at fault: its `cover_mm` argument is deliberately
face-agnostic, which is exactly why the caller has to pick the right face. The
fix reads the beam's side cover once through the same
`read_face_cover_mm` machinery and uses it for both the corner-bar positions
and a single spacer length. `cover_side` is now in the report, so a wrong
value is visible rather than silent.

This is the same class of mistake as S1's review finding #4 (the wrong column
cover face) — the third time a cover has been read off the wrong face in this
project. Worth remembering when reviewing #17 and #19.

## What is NOT verified, and why it matters

- **The pushbutton has never executed.** pyRevit and the Revit API are not
  installed in this environment; `Main Bars.panel/Place Main
  Bars.pushbutton/script.py`'s imports, its `FlexForm` interaction, and its
  end-to-end wiring of core + adapter are unexercised, same limitation as S1
  and S5's pushbuttons.
- **`RebarFaceType.Top` and the beam's side-face read-back** carry the same
  unresolved-shape caveat already flagged in `rft/revit/host.py`'s module
  docstring for `Bottom`/`Other` — using it for the top face, and (after the
  review) for the beam's own side face, changes nothing about that risk: it is
  the same unconfirmed API shape applied to more enum members. If
  `RebarFaceType.Other` is not how a beam's side face is actually addressed,
  the side cover read throws on first run rather than returning a wrong
  number, which is the failure mode to prefer.
- **Placing many `Rebar.CreateFromCurves` calls inside one loop, inside one
  `Transaction`, for a multi-layer x multi-bar-count beam** has not been
  exercised against a real document for performance or for any undocumented
  per-call side effect (e.g. whether Revit's regeneration behaviour differs
  when dozens of independent `Rebar` elements are created in one
  transaction vs. one at a time, as S1 did).
- **Whether a beam's bounding box centroid still matches its section
  centroid when the beam already hosts other rebar** (e.g. previously placed
  stirrups) is unconfirmed — `beam_section_dimensions_mm`/
  `beam_section_centre_offsets` read the beam's own geometry, which should be
  unaffected by hosted rebar, but this has not been checked against a live
  document that already has stirrups placed by `Place Stirrups.pushbutton`.

## Scope boundaries held (see ticket instructions)

- **Top-face bars are computed and reported only.** No top-bar anchorage is
  invented; #15 (S2) owns that.
- **Spacer bars are not placed.** `spacer_length_mm` is computed and
  reported for both faces; rev 2 §6.3 gives a length and no longitudinal
  spacing rule for *placing* a spacer bar along the span, and inventing one
  is prohibited by `CONTEXT.md`. This is a genuine spec gap, not an
  oversight — flagged for a decision ticket rather than guessed.
- **No steel-grade logic.** `resolve_bar_type` is the same by-name-with-
  fallback stub S1/S5 use; grade assignment (mild vs. high tensile) is S7
  (#20).
- **No spacing validation / auto-stacking.** The pushbutton takes the
  engineer's own layer count (1-5) and bar count per layer as direct inputs;
  it does not check §6.2's `min_spacing` or auto-stack per §6.4's Option
  1/2 behaviour. That is S4 (#17), which this ticket's core deliberately
  does not duplicate.
