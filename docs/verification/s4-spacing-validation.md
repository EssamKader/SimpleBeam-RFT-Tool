# S4 Mock-Object Verification Write-up

Ticket [#17](https://github.com/EssamKader/rft-beam-detailing/issues/17) --
spacing validation and layer decisions (rev 2 sections 6.2-6.4; A21, A25,
A27, A28, A29, A36, A43, A44).

Required by `CONTEXT.md`'s standing rule: there is no live Revit host in
this environment, so any ticket touching Revit-API-dependent logic needs a
write-up demonstrating the logic is correct before it can close in review.
**225 tests pass** (201 baseline + 24 new in `tests/test_spacing.py`). No
new `test_mock_revit_adapter.py` tests were added -- see "What was NOT
added to the mock-adapter suite, and why" below.

## What the pure-core tests verify (runs under plain CPython, no mocks needed)

This story is almost entirely arithmetic, and the arithmetic is exactly
what pytest can check directly:

- **Section 6.2 governing minimum, both branches.** `D_agg` defined ->
  `max(25, O_bar, 1.33*D_agg)`; `D_agg` undefined -> exactly 50, never
  folded together. The brief's own trap case is pinned directly: O12 with
  `D_agg=20` gives 26.6 mm (`test_d_agg_defined_governs_formula_branch`),
  and a dedicated test (`test_d_agg_is_not_folded_into_the_same_max_as_
  the_50mm_fallback`) asserts the result is strictly below 50, which a
  `max(25, O_bar, 1.33*D_agg, 50)` mistake would violate.
- **A29's floor, asserted on the returned value.** An override above the
  formula result raises the governing value
  (`test_a29_override_above_formula_result_is_used_as_floor`); an override
  BELOW the formula result (20 against a formula result of 26.6) is
  asserted to leave the governing value at 26.6, unchanged
  (`test_a29_override_below_formula_result_is_ignored_entirely`) -- an
  assertion on the number itself, not on any message text, per the brief's
  explicit instruction.
- **A43's corrected datum, pinned both ways.** `b=250, Cover=25 (side),
  O_stirrup=10, 3xO16` gives 66.0 mm under the corrected formula
  (`test_a43_numeric_pin_correct_value`); a companion test confirms this
  value is NOT the printed formula's 58.0 mm
  (`test_a43_numeric_pin_diverges_from_printed_formula_wrong_answer`); a
  third test computes the governing minimum with `D_agg=45` (59.85 mm) and
  asserts the section PASSES under the corrected value while the printed
  formula's 58.0 mm would have REFUSED
  (`test_a43_section_passes_under_corrected_formula_but_would_refuse_
  under_printed_one`).
- **`n = 1` skips the check.** Returns `None`, never divides by zero;
  raises `ValueError` for `bar_count < 1`.
- **The exact-minimum boundary PASSES, not fails.** A dedicated test
  constructs a section whose achieved clear spacing equals the governing
  minimum exactly (both are 66.0 mm, reusing the A43 pin) and asserts
  `passes is True` -- section 6.4 only calls `clear < governing_min_
  spacing` invalid, so equality must never refuse.
- **Per-layer, per-face independence (A44).** `validate_face_spacing` is
  exercised for: a comfortable Option 1 pass; an Option 1 violation
  (refuses, names the achieved/governing values); an Option 2 violation
  (refuses -- explicitly asserted NOT to auto-stack, which is A44's whole
  point); the A28 absolute 5-layer hard error (asserted to say "HARD
  ERROR" and cite "A28" rather than naming an unreachable layer count);
  the A36 option/layer-count cross-check (option 1 with 2 layers refuses
  as a contradiction, before any per-layer validation runs -- asserted via
  `layer_results == []`); and per-face independence (a failing top face
  and a passing bottom face are validated in the same test, and the
  bottom face's report is asserted unaffected by the top face's failure).
- **A44's suggested layer count is reporting-only, and its search is
  pinned to actually be the smallest.** One test constructs a violating
  12-bar case, confirms the returned `k` satisfies the minimum under the
  same even-split rule the suggestion computes, and confirms `k - 1` does
  NOT satisfy it (pinning "smallest", not just "some" `k`). A second test
  confirms the function returns `None` when no `k` in `1..5` would work.

## What was NOT added to the mock-adapter suite, and why

This ticket adds no new Revit API surface. `rft.core.spacing` is pure
arithmetic with no Revit-facing counterpart of its own -- it is wired into
"Place Main Bars.pushbutton" as a pre-transaction refusal check using
values (`b_mm`, `cover_side_mm`, `dia_stirrup_mm`, `dia_top_mm`,
`dia_btm_mm`) that pushbutton already reads via S3's already-verified
adapter calls (`beam_section_dimensions_mm`, `read_face_cover_mm`,
`bar_type_diameter_mm`). No new `RebarFaceType`, `RebarBarType`, or other
Revit-shaped object is introduced, so there is nothing new to add a
`SHAPE UNVERIFIED` fake for.

What WAS re-verified: an ad hoc import/smoke check (the same throwaway
technique described in S2's and S6's write-ups, not part of the committed
suite) installed `fake_revit_api`'s stand-in `Autodesk.Revit.DB` /
`Autodesk.Revit.DB.Structure` modules plus minimal fake `pyrevit` modules,
then executed "Main Bars.panel/Place Main Bars.pushbutton/script.py"'s
`main()` with `pick_element` returning `None`. It reached `script.exit()`
cleanly with no `NameError`/`AttributeError` -- confirming the new
`from rft.core.spacing import (...)` import and the new §6.2-6.4 form
fields (`option_top`, `option_btm`, `min_spacing_override`) do not break
the pushbutton's module-level wiring. This does not exercise the
validation call itself (that requires a real beam past `pick_element`),
only that the import and the surrounding code still load.

## What is NOT verified, and why it matters

- **The pushbutton has never executed against a real Revit session.**
  Same limitation as every prior ticket. The spacing refusal path itself
  (reading `b_mm`/`cover_side_mm`/bar diameters from a real beam, then
  hitting `forms.alert` + `script.exit()` before any transaction) has
  never been exercised past `pick_element`.
- **All pre-existing SHAPE UNVERIFIED items this pushbutton already
  carries (S3's write-up) are unchanged by this ticket** --
  `RebarHostData.GetFaces`/`GetCoverType`, `RebarBarType` diameter
  properties, `pyrevit.forms.SelectFromList.show`'s signature, and which
  `RebarFaceType` member actually addresses the beam's own side face.
  This ticket introduces no new one.
- **Whether the refusal genuinely fires BEFORE any Revit mutation in
  practice** rests on the placement in the pushbutton's control flow
  (verified by code reading: the check runs immediately after
  `beam_section_dimensions_mm`/cover reads, before the continuous-run
  guard, support detection, or `run_in_transaction`), not by executing it
  against a live document.

## Review findings (all five fixed before commit)

**1. `Place Main Bars` refused to run at all with a blank `D_agg`, which
made §6.2's 50 mm fallback unreachable and the tool unable to run in its
own documented default configuration.** S3 had made `D_agg` mandatory
because R1's spacer warning needed a number, and its refusal text said the
50 mm fallback was "not computed here; that is S4, issue #17". S4 arrived
and computed it — but the mandatory-field refusal stayed, so
`governing_min_spacing_mm(..., d_agg_mm=None, ...)` could never be reached
from the UI. A36 ships `D_agg` **blank on purpose**, *"so §6.2's 50 mm
fallback governs until an aggregate size is supplied"*: the one branch A36
says governs out of the box was dead code behind a hard stop. `D_agg` is
now optional, blank selects the fallback, and the form label says so.

**2. §6.2's minimum was derived in two places.** `layout.spacer_diameter_
warning` re-computed `max(25, Ø_bar, 1.33×D_agg)` for R1 while
`spacing.governing_min_spacing_mm` computed the same thing for §6.4 — the
two-sources-of-truth pattern this project keeps removing, and the reason
finding 1 was possible at all: a bare `d_agg_mm` float cannot represent
"undefined", so R1's copy of the formula had no fallback branch to reach.
`spacer_diameter_warning(spacer_dia_mm, min_horizontal_mm)` now takes the
already-resolved minimum, and `governing_min_spacing_mm` is the only place
§6.2 is evaluated. R1 is passed the minimum **without** A29's override
applied: R1's text names the formula, not the engineer's raised floor, so a
raised floor must not manufacture a warning about an otherwise acceptable
spacer.

**3. The refusal suggested an arrangement the form cannot express.** It
named a layer count for a face *total* — "re-entering 2 layers for this
face's 11 bars" — but the pushbutton takes one count **per layer** and
applies it to every layer, so 6 + 5 is not enterable. Added
`max_bars_per_layer`, and the refusal now speaks in the input model's own
terms: *at most N bars per layer satisfy this minimum; your total needs k
layers at that count*. `suggest_min_layer_count` is derived from it
(`ceil(total / max_per_layer)`), which returns the same k as the previous
search while also yielding the number the engineer actually types.

**4. Spacing validation ran ahead of the continuous-run refusal.** Both
refuse, so nothing wrong was placed — but the continuous-run guard rejects
the beam's whole configuration (A41), so reporting a section-level spacing
problem first sends the engineer to fix bar counts on a beam this tool is
going to refuse anyway. Moved after it. Structural configuration is
checked before section detail.

**5. A stale refusal message** pointing at #17 as future work, removed with
finding 1.

The traps the brief named were all handled correctly: the **side** cover in
A43's formula (the S3/S6 finding, which did not recur), `D_agg` governing
*over* the 50 mm fallback rather than being floored by it (Ø12 with
`D_agg = 20` gives 26.6 mm, asserted), A29's override ignored when below
the formula result, A21's horizontal-only scope, A25's crack-bar exemption
left untouched, and the exact-minimum boundary passing rather than failing
— `clear == governing` is not a violation, since §6.4 says *invalid when
`clear < governing`*.

**On the implementer's own query about trap 6's margin:** the 59.85 mm
governing minimum against A43's 66.0 mm is not a typo and the 6.15 mm
margin is the point. That case exists to sit inside the window where the
two formulas disagree — the printed formula's 58.0 mm refuses, A43's 66.0
mm passes. A wider margin would clear both and prove nothing.

## Interpretations made where the brief does not fully settle the point

**1. The `bar_count` typed per face applies uniformly to every layer of
that face.** "Place Main Bars.pushbutton" has one bar-count field per
face (`count_top`/`count_btm`), not a per-layer field -- this predates S4
and is the input model the brief explicitly says to keep ("the engineer
states the bar count per layer and the number of layers per face -- the
input model Place Main Bars already uses"). Read literally, that model
gives ONE count that already applies to every layer uniformly (the same
count feeds every layer's corner-bar u-positions in S3's code), so
`layer_bar_counts = [count_top] * layers_top` is the natural reading, not
a new assumption -- but adding a genuinely PER-LAYER count field (so
layer 1 could hold a different count than layer 2) was not in this
ticket's scope and was not added. If a future ticket wants true per-layer
counts, `validate_face_spacing` already accepts an arbitrary list, so no
`rft.core.spacing` change would be needed -- only the pushbutton's form.

**2. §6.3's option input (A36) is added as a new per-face typed field
(`option_top`/`option_btm`), defaulting to 1 (single wide row, matching
A36's stated v1 default).** The brief says "Add it" without specifying
where; a per-face field was chosen because section 6.3 states the option
"for both top and bottom faces independently."

**3. An optional `min_spacing_override_mm` field was added (A29), applied
identically to both faces.** Rev 2 does not say whether the override is
one value for the whole beam or per-face; a single beam-wide override
field was chosen as the simpler reading, consistent with `D_agg` already
being one beam-wide input in this pushbutton.

## Scope boundaries held (see ticket instructions)

- **Crack bars are never validated here.** `rft.core.spacing` is never
  imported by, and never imports, `rft.core.crack_bars`; nothing in this
  module is wired into "Place Crack Bars.pushbutton". A25's exemption
  (`rft.core.crack_bars.spacing_validation_exemption_note`) remains the
  sole statement of that exemption.
- **A21: horizontal only.** No vertical/layer-gap check was added or
  touched; `rft.core.layout.spacer_diameter_warning` (R1) is untouched.
- **"Place Bottom Bar.pushbutton" is exempt by A43 (n=1)** and now carries
  a one-line comment saying so, rather than leaving the absence of a
  spacing call to be noticed.
- **A44's suggested layer count is never used to place or split
  anything.** `suggest_min_layer_count`'s docstring and every call site
  say so explicitly; it feeds only the refusal message text.
