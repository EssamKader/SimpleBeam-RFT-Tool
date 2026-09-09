# S6 Mock-Object Verification Write-up

Ticket [#19](https://github.com/EssamKader/rft-beam-detailing/issues/19) --
crack/skin reinforcement for deep beams (rev 2 section 5; A22-A26 as
amended by A42; residual question R2).

Required by `CONTEXT.md`'s standing rule: there is no live Revit host in
this environment, so any ticket touching Revit-API-dependent logic needs a
write-up demonstrating the logic is correct before it can close in review.
**201 tests pass** (200 baseline + 22 new in `tests/test_crack_bars.py`, plus
1 new adapter test in `tests/test_mock_revit_adapter.py` -- net +23; two of
the 22 new pure-core tests exercise a previously-untested but pre-existing
adapter combination indirectly, see below). What that does and does not
mean is set out below.

## What the pure-core tests verify (runs under plain CPython, no mocks needed)

- **Trigger (section 5).** `h == 700` does NOT fire (`n_crack_layers = 0`);
  `h == 701` fires. Both sides of the strict `>` tested explicitly.
- **A26: H_avail measured to the INNERMOST main bar layer.** A dedicated
  test (`test_a26_multilayer_beam_has_fewer_crack_layers_than_single_layer`)
  computes a 2-layer beam's `H_avail` against the SAME beam's 1-layer
  `H_avail` and asserts `n_crack_layers` is strictly fewer for the 2-layer
  case -- pinning the direction of the effect the brief warned about, not
  just the arithmetic in isolation. Uses `layer_offset_mm(..., layer_n=2)`
  (the innermost/last layer), never `first_layer_offset_mm` or a bare `1`.
- **Section 5.2 layer count and spacing.** Exact-multiple case (`H_avail =
  600, s_max = 200` -> 3 gaps, 2 crack layers, 200 mm spacing exactly) and a
  non-multiple case (`H_avail = 700, s_max = 200` -> 4 gaps, 3 crack layers,
  175 mm <= 200 mm). `H_avail <= s_max` (both `150 < 200` and `200 == 200`)
  gives `n_gaps = 1`, `n_crack_layers = 0` -- asserted as a legitimate
  outcome, not an exception.
- **The epsilon-tolerant ceiling.** `test_exact_multiple_from_float_
  division_noise_does_not_invent_a_gap` constructs `h_avail = 200.0 * 3`
  (the same arithmetic path a real caller's float division would take) and
  confirms `n_gaps == 3`, not 4 -- pinning the specific IEEE-754 failure
  mode the brief named (`600.0 / 200.0` landing fractionally above `3.0`).
- **Degenerate guards.** Non-positive `H_avail` and non-positive `s_max`
  both raise `ValueError` naming section 5.1/5.2 respectively.
- **Vertical datum (the brief's core trap).** `test_topmost_crack_layer_
  sits_one_spacing_below_innermost_top_layer` computes the innermost TOP
  layer's own `v` coordinate independently (`h/2 - offset_top`) and asserts
  the topmost crack layer sits exactly `actual_spacing` below it -- pinning
  BOTH ends of the crack-layer run at once, exactly as the brief specified.
  A companion test does the same for the bottommost crack layer against the
  innermost BOTTOM layer. A third test confirms zero crack layers produces
  an empty position list (no zero-length or off-by-one artifact).
- **A24 horizontal (u) positions.** Symmetric about the centroid, and
  algebraically checked against `rft.core.layout.first_layer_offset_mm`
  applied to the SIDE face -- not re-derived, reusing the exact same
  section-4 formula the corner-bar rule (section 6.1) already reuses.
- **A23/R2 embedment.** `crack_bar_embedment_mm(support_width, cover) =
  support_width - cover`, confirmed to apply NO section 2.3 cap/clamp even
  for a support narrow enough that the cap would fire on a main bar
  (`test_embedment_has_no_ld_cap_even_for_a_tiny_support`).
- **The unsupported-end reporting fix, verified BEFORE it could ship
  wrong.** `crack_bar_end_result`'s unsupported branch returns
  `embedment_mm=0.0` and `terminates_short_of_end_mm=beam_end_cover_mm`
  (always >= 0) rather than computing `0 - cover` and reporting a negative
  length -- `test_crack_bar_end_result_unsupported_reports_explicitly_no_
  negative_length` asserts the returned value is non-negative. This
  reproduces, and closes, issue #15's (S2) review finding for the
  crack-bar case before it ever reached a pushbutton.
- **A25 exemption.** `spacing_validation_exemption_note()` names both "A25"
  and "6.2" so a caller (and #17/S4's future section 6.2 validation) can
  grep for it rather than infer the exemption from an absence.

## What the mock-object tests verify (`test_mock_revit_adapter.py`)

**The crack-bar placement path reuses S2's already-verified adapter code
unchanged**, not a new geometry implementation:

- `bar_point_at_uv` (centroid-local u/v -> a 3D reference point) is the
  SAME function S2/S3 already verified for main bars
  (`test_bar_point_at_uv_applies_centroid_correction_and_bar_offset_
  single_point`) -- reused per crack bar inside a loop over layers x
  {left, right}, not reimplemented.
- `main_bar_end_geometry` at a SUPPORTED end with `b_internal=None` --
  the crack-bar case (A23: embed straight, no hook, even where a support
  IS present) -- is a combination S2 never explicitly exercised (S2's main
  bars always pass a real bend leg at a supported end). Added
  `test_main_bar_end_geometry_supported_end_with_no_bend_is_a_straight_
  embedment`, which confirms the function still returns the full
  `bent_end_corner` embedment point and `bend=None` -- i.e. reuse needs a
  caller that simply never supplies a bend leg, not a new code branch.
  (`main_bar_end_geometry`'s body is `return corner, b_internal` in the
  supported branch, so this is confirming a pass-through, not new logic --
  but the brief's own emphasis on "reuse, verify the reuse" is why this is
  pinned as a named test rather than left as "obviously fine.")
- `build_main_bar_curves` with BOTH ends unsupported/no-bend (the
  single-straight-segment case every crack bar takes, since neither end
  ever gets a hook) is ALREADY covered by S2's pre-existing
  `test_build_main_bar_curves_both_ends_unsupported_is_a_single_straight_
  segment` -- not re-tested here, cited instead, per the brief's own
  instruction to reuse rather than reinvent.
- `place_anchored_bar` and `run_in_transaction` are S1's already-verified
  machinery, called once per crack bar (up to `2 x n_crack_layers` times)
  inside one `Transaction`, identical in shape to how S3 already calls them
  once per main bar.

**The ad hoc import/smoke check** (same technique S2's write-up describes,
not part of the committed suite): a throwaway harness installed minimal fake
`pyrevit` modules alongside the existing `fake_revit_api` and executed
`Crack Bars.panel/Place Crack Bars.pushbutton/script.py`'s `main()` up to
`pick_element` returning `None`. It reached `script.exit()` cleanly with no
`NameError`/`AttributeError` -- confirming every import this ticket
introduced (in particular the new `rft.core.crack_bars` module and its
functions) resolves correctly. This is NOT a full placement run against a
real beam/support/RebarHostData chain, which remains unexercised, same
limitation every prior ticket's write-up carries.

## What is NOT verified, and why it matters

- **The pushbutton has never executed against a real Revit session.**
  Same limitation as every prior ticket. Beyond the pytest suite and the ad
  hoc import smoke check described above, no full placement run (with a
  real beam, a real support, and a real `RebarHostData` cover chain) has
  been exercised.
- **Superseded by issue #30 (Revit 2024 live probe):** `RebarHostData.GetFaces`/
  `GetCoverType`'s assumed shape did not exist, and neither did
  `RebarFaceType`. Cover reads here now go through `read_beam_face_covers_mm`
  / `read_support_side_cover_mm`, classifying each exposed face by its own
  normal -- see `docs/verification/issue-30-cover-face-reads.md`. This
  pushbutton's FOUR conceptually distinct cover reads (top, bottom, side,
  and the supporting element's own cover) are unchanged in concept, only in
  mechanism. `RebarBarType.BarNominalDiameter` vs. `BarModelDiameter`
  remains open, though issue #23's live probe found both properties exist
  and returned identical values in the test model.
- **`pyrevit.forms.SelectFromList.show`'s exact signature** -- same
  unconfirmed shape every other pushbutton's `select_bar_type_for_role`
  carries; this pushbutton's four calls to it (crack, top main, bottom
  main, stirrup) are equally unexecuted against a real pyRevit session.

## Interpretations made where the brief (or rev 2) does not fully settle the point

**1. The unsupported-end crack-bar length is reported without ever
computing a negative number, deliberately diverging from a literal reading
of "mirror `unsupported_end_straight_run_mm`".** The brief named
`rft.core.anchorage.unsupported_end_straight_run_mm` (`distance_to_beam_end
- cover`) as the formula to mirror. `crack_bar_end_result` does NOT apply
it with a synthetic `distance_to_beam_end_mm = 0.0` -- doing so would
reproduce issue #15's (S2) review finding verbatim (a negative reported
length). Instead the unsupported case reports `embedment_mm = 0.0` and
`terminates_short_of_end_mm = beam_end_cover_mm` as two separate,
non-negative quantities, mirroring the FIX S2's review made, not S2's
original formula application. This is a reading of "mirror the behaviour"
rather than "mirror the exact call", and it is the right one: the value
that matters to the engineer is how far short of the beam end the bar
stops, which is positive.

**2. A free end WARNS and proceeds; a beam unsupported at BOTH ends is
refused.** Section 5 never mentions an unsupported end at all, so the
per-end behaviour is inherited from section 2.5/A14 (warn), and the
both-ends refusal is this project's own judgement call. The refusal text
now says exactly that, rather than citing A9/A12/A14 as if the hard stop
came from the spec -- see review finding 4 below.

**3. Which layer counts (`layers_top`/`layers_btm`) feed A26's innermost
offset is a typed input on THIS pushbutton, independent of whatever was
typed into "Place Main Bars.pushbutton" for the same beam.** There is no
cross-pushbutton state (no read-back of already-placed main bars' own
layer count from the model) -- the engineer must re-enter the same layer
counts here as used for the main bars, or `H_avail` will not match the
as-built beam. This is the same "no persisted state between pushbuttons"
limitation "Place Main Bars.pushbutton" itself has for the stirrup
diameter it also re-selects rather than reads back; not a new gap this
ticket introduces, but worth naming since A26 is this ticket's central
correctness requirement.

## Scope boundaries held (see ticket instructions)

- **No `Ø_crack` free-text input.** Diameter comes solely from an explicit
  `ROLE_CRACK` `RebarBarType` selection (A42, per the ticket's own
  corrected acceptance criterion), exactly like every other role.
- **A25 exemption is explicit, not implicit.** No section 6.2 spacing
  validation is invoked anywhere in this module or pushbutton;
  `spacing_validation_exemption_note()` exists so #17 (S4) has something
  concrete to check against rather than an absence to notice.
- **`rft.core.anchorage` is never imported by `rft.core.crack_bars`** --
  confirmed by inspection of the module's own imports (only
  `rft.core.layout.first_layer_offset_mm`). Section 2.3's LD cap/clamp and
  mandatory-hook machinery cannot reach the crack-bar path even by an
  accidental transitive import.
- **`RebarStyle.Standard`, no `RebarHookType`.** `place_anchored_bar`
  (reused, unmodified) always passes `None` for both `startHook`/`endHook`
  -- crack bars never carry a `RebarHookType` argument at all, consistent
  with A23.

## Review findings (all five fixed before commit)

**1. `s_max` shipped a hand-picked default of 250 mm where A36 fixes it at
200.** Section 5.2 gives `s_max` no default of its own, which is precisely
why A36 lists one -- so a form pre-fill that disagrees with A36 is the tool
inventing a detailing value, the one thing `CONTEXT.md` forbids outright.
It would not have failed anything: on a deep beam it silently places one
extra crack layer and reports it as correct. `DEFAULT_S_MAX_MM = 200.0` now
lives in `rft.core.crack_bars` beside `H_TRIGGER_MM`, the form reads it,
and a test pins it to A36's value so the shipped default cannot drift from
the amendment that fixes it.

**2. A14's free-end WARNING was missing.** The pushbutton implemented R2's
unsupported-end path and reported the geometry ("terminating 25.0 mm short
of the beam's own end"), but never emitted A14's actual warning -- that
cantilever and free ends are OUT OF SCOPE for v1 and the configuration
should be reviewed. An engineer detailing a cantilever was told what the
bar does, not that the tool does not support the case.
`free_end_guard_message` (WARN, for a pushbutton that implements the path)
is now emitted per unsupported end. `no_support_detected_message` was
imported and never used -- it REFUSES, and is meant for pushbuttons that do
not implement the path -- so it is gone.

**3. `crack_bar_unsupported_end_straight_run_mm` was a documented trap.**
It reimplemented section 2.5's formula, had no call site, and its own
docstring explained that calling it the obvious way (with
`distance_to_beam_end_mm = 0.0`) reproduces issue #15's negative-length
bug. A function whose documentation warns against its only plausible use is
a trap left for the next reader, and the parity argument for keeping it
(`rft.core.anchorage`'s equivalent is uncalled too) argues for removing
that one, not for adding a second. Removed with its test. Its other stated
rationale -- that importing `rft.core.anchorage` for one formula risks
pulling in section 2.3's cap/clamp machinery -- does not hold either:
importing one name does not import behaviour, and the module already
imports from `rft.core.layout`. The real protection is that
`crack_bar_embedment_mm` applies no cap, which
`test_embedment_has_no_ld_cap_even_for_a_tiny_support` asserts directly.

**4. The both-ends-unsupported refusal presented a project judgement call
as a spec rule.** It cited "rev 2 section 2.4/2.5, A9/A12/A14" as its
authority while dropping the sentence "Place Main Bars.pushbutton" carries,
which states plainly that the hard stop is this project's own decision and
that A14's own requirement is only to warn. Restored.

**5. Dead import** (`crack_bar_embedment_mm` in the pushbutton, reached
only through `crack_bar_end_result`). Removed.

The four datum traps the brief named were all handled correctly, and the
tests pin them rather than merely exercising them: A26's innermost-layer
offset (a two-layer beam yields fewer crack layers than the same beam with
one), the three separate covers, the `v` datum at both ends of the run
(the topmost crack layer sits exactly one `actual_spacing` below the
innermost top layer -- which pins the whole chain, since `v` at `n_gaps`
reduces to `h/2 - offset_top` only if every term is right), and
`_epsilon_ceil` against real float-division noise.

## Any acceptance criterion NOT met

None identified against the brief as corrected by the ticket-owner's
comment (A22 superseded by A42). If review disagrees with an interpretation
in the section above, those are the specific points to revisit first.
