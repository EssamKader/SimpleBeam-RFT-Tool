# S9 Mock-Object Verification Write-up

Ticket [#22](https://github.com/EssamKader/rft-beam-detailing/issues/22) --
out-of-scope configuration guards: continuous-run detection, the
cantilever/free-end warning, and stirrup type 3 rejection.

Required by `CONTEXT.md`'s standing rule: no live Revit host exists here, so
any Revit-API-dependent logic needs a write-up demonstrating correctness
before it can close in review. **141 tests pass** (121 baseline + 20 new: 14
pure-core in `test_guards.py`, 6 mock-adapter in `test_revit_guards.py`).
`python -m pytest tests/ -q` output: `141 passed in 0.35s`.

## What the pure-core tests verify (`test_guards.py`, runs under plain CPython)

- **The angular classification threshold** (`classify_neighbour_axis`,
  rev 2 section 2.4/section 9 item 2). Parallel (`dot=1.0`) and
  anti-parallel (`dot=-1.0`) axes both classify as continuous -- a beam
  continuing past a support is only "the same direction" if both are
  traversed consistently start to end, so a real continuation is just as
  likely to present as anti-parallel. Perpendicular (`dot=0.0`) classifies
  as transverse (a valid girder support). Floating-point drift past the
  unit range (`dot=1.0000000002`) is clamped before `acos`, which would
  otherwise raise a domain error.
- **The three cases this ticket names explicitly:**
  - Case 1 (girder support, not continuous) and case 2 (collinear beams
    over a column, IS continuous) are verified at the adapter level (see
    below); the underlying threshold math they depend on is pinned here.
  - Case 3, the ambiguous 45-degree angle: `classify_neighbour_axis` at
    exactly `cos(45deg)` returns `is_continuous=True` -- ties are resolved
    toward continuous, not transverse. 44 degrees (inside the 45-degree
    tolerance) is continuous; 46 degrees (outside it) is transverse.
- **Every guard message names its condition and spec section**
  (`continuous_run_guard_message`, `free_end_guard_message`,
  `stirrup_type3_guard_message`, `no_support_detected_message`) -- each
  returns a `GuardMessage(condition, spec_section, message)` namedtuple, and
  the tests assert the end label, the section number, and the amendment
  number all appear in the formatted text, not just that *some* string came
  back.

## What the mock-adapter tests verify (`test_revit_guards.py`)

Same pattern as `test_geometry.py`: installs `fake_revit_api`'s stand-in
`Autodesk.Revit.DB` modules, then imports and exercises the REAL
`rft.revit.guards` source (not a re-implementation of its logic).

- **Case 1 -- a beam framing into a transverse girder is NOT continuous.**
  A girder crossing the beam's end at 90 degrees: `continuous_run_guard`
  returns `None`, so placement would proceed. Confirms rev 2 section 2.4's
  explicit rule ("a beam framing into a girder is still a single span")
  survives the angular check.
- **Case 2 -- two collinear beams meeting at a column IS continuous, even
  though a column is present.** Both a column (point-located) and a
  collinear continuing beam (curve-located, same axis) sit at the same
  beam end, in the same `FilteredElementCollector` result set. Asserted:
  `continuous_run_guard` still returns a refusal. This is the mechanism
  that makes it work: `find_continuous_run_neighbour` searches
  `OST_StructuralFraming` ONLY and independently of whatever
  `find_supporting_element` would separately pick as "the support" for
  anchorage width (which, being nearest, could easily be the column) --
  so the column winning that unrelated proximity contest can never
  suppress this guard.
- **Case 3 -- the ambiguous 45-degree angle, at the adapter level.** A
  neighbour beam placed at exactly 45 degrees from the beam's axis:
  `continuous_run_guard` returns a refusal (not `None`). A 46-degree
  neighbour (just outside the tolerance) returns `None`. This exercises the
  same threshold as the pure-core test but through the full detection path
  (bounding-box proximity, exclusion, dot-product read-off), confirming the
  policy choice actually reaches the adapter's return value, not just the
  isolated math.
- **Per-end independence.** A beam with a collinear continuing neighbour at
  its "End end" only: `continuous_run_guard` at "End end" (the far point)
  returns a refusal; at "Start end" (the near point, no neighbour there)
  returns `None`. Confirms an end span of a continuous run is only flagged
  at the end that actually has the collinear neighbour, per this ticket's
  explicit instruction to test each end independently.
- **Self-exclusion.** A beam searching its own end point, with only itself
  present as an `OST_StructuralFraming` candidate: `exclude_element_id`
  correctly removes it, so `find_continuous_run_neighbour` returns `None`
  rather than the beam finding (and misclassifying) itself.
- **`neighbour_axis_dot_product` reads each element's OWN location curve.**
  Directly asserts the dot product for a perpendicular neighbour is exactly
  `0.0` and for a parallel one exactly `1.0`, confirming the function reads
  the NEIGHBOUR's own axis (not the beam's axis reused twice) -- the
  "wrong reference" bug class this project has hit before (wrong cover
  face, twice; wrong datum, location curve vs. section centroid; pre-cap vs.
  as-built values). Here the two directions are explicitly two different
  reads: `beam_axis_direction(beam)` and `beam_axis_direction(neighbour)`.

## The two design choices this ticket had to make where rev 2 does not settle the point

**1. The 45-degree angular tolerance** (`CONTINUOUS_RUN_ANGLE_THRESHOLD_DEG`
in `rft/core/guards.py`). Rev 2 gives no angular tolerance for distinguishing
a collinear continuation from a transverse girder at all -- this constant is
this ticket's own design choice, flagged inline exactly like
`DEFAULT_SUPPORT_SEARCH_RADIUS_MM` already is in `geometry.py`. Chosen at the
midpoint between "clearly collinear" and "clearly transverse" (45 degrees),
with ties resolved toward CONTINUOUS (refusal): the guard exists specifically
to prevent a continuous beam being silently detailed as simply supported and
missing its hogging steel, and a false-positive refusal (engineer re-checks
and confirms it is really a girder) costs far less than a false-negative
pass-through. Reasonable engineers could pick a narrower or wider tolerance;
this is a policy call, not a spec-derived number, and is the first thing a
project owner should revisit if the guard proves too eager or too lax in
practice.

**2. Refuse, not warn, on a detected continuous run.** A39 explicitly permits
either. This ticket refuses, for two stated reasons: (a) this story's entire
rationale is never handing the engineer plausible-looking detailing for an
unmodelled configuration, and a warning that is easy to click through does
not prevent that; (b) stirrup type 3, the only other v1-scope gap of the
same "we do not have the rule for this" character, is already rejected
outright rather than warned. This is a one-line change
(`continuous_run_guard_message`'s return, or the pushbutton call sites' use
of `forms.alert(...); script.exit()` vs. appending to a non-blocking
`warnings` list) if the project owner prefers a warning instead -- flagged
here and in the function's own docstring per this ticket's instructions, not
decided unilaterally as a closed question.

## Where the guards are wired

All three pushbuttons now run the continuous-run guard, at both ends,
immediately after the beam's own axis/endpoints are read and BEFORE any
support detection, cover read-back, or placement work:

- `Anchorage.panel/Place Bottom Bar.pushbutton` (S1) -- and its existing
  "no supporting element detected" hard-stop now uses
  `no_support_detected_message`, naming rev 2 section 2.4/2.5 (A9/A12/A14)
  explicitly instead of a generic sentence.
- `Main Bars.panel/Place Main Bars.pushbutton` (S2/S3) -- the only
  pushbutton that already implements the unsupported-end anchorage path, so
  its existing per-end `free_end_configuration_warning()` (A14, a WARNING,
  not a refusal) is untouched; only the continuous-run guard was added, and
  the "no support at EITHER end" hard-stop's message was tightened to name
  its own section and to state explicitly that A14 itself only requires a
  warning at a single unsupported end (this pushbutton's stricter
  both-ends-unsupported refusal remains this project's own scope decision,
  as it already was before this ticket).
- `Stirrups.panel/Place Stirrups.pushbutton` (S5) -- the continuous-run
  guard, plus stirrup type 3 now short-circuits via
  `stirrup_type3_guard_message()` before any zone or leg-geometry
  computation runs (previously it was only caught after
  `centreline_leg_dimensions_mm`/`stirrup_curve_endpoints_mm` had already
  been called, via the pre-existing `TYPE3_PARKED_MESSAGE` raised from
  `rft.core.stirrups`, which is reused unchanged, not reimplemented). Its
  own "no supporting element detected" hard-stop was updated the same way
  as S1's.

## The review finding, and what it cost

**Collinearity was tested by direction alone.** `classify_neighbour_axis`
compares the two axes' dot product, which is exactly right as far as it
goes — but a neighbour merely running *parallel* to the beam scores
`abs(dot) = 1` just as a true continuation does, and the search that feeds
it is a bounding-box proximity test around the beam end.

So twin beams running alongside each other 250 mm apart, or an edge beam
next to a floor beam, would have been refused with the message "this beam
is part of a CONTINUOUS RUN, not a single span". Both are valid single
spans. A false refusal is the safe direction to fail, but the explanation
would have been wrong, and an engineer who reads a specific, confident
message that does not match what they see in the model loses trust in
every other message the tool prints.

Collinear means same direction **and** same line. `neighbour_lateral_offset_mm`
now measures the perpendicular distance from the beam's own axis line to the
neighbour endpoint nearest the end being checked, and `is_on_same_axis_line`
applies a 50 mm policy tolerance — loose enough for real modelling slop
where a continuation is meant to be on-axis, far tighter than any plausible
gap between two deliberately separate parallel members.

Three tests pin it: the parallel twin (250 mm off-axis, direction match of
exactly 1.0, correctly **not** refused), a continuation modelled 40 mm
off-axis (still refused, slop absorbed), and a long continuation listed
far-endpoint-first, proving the offset is measured at the shared node rather
than at whichever endpoint the location curve happens to list first.

That last test is the one worth keeping: measuring from the wrong endpoint
would have reported a large offset for a genuine continuation and silently
disabled the whole guard — the same "measured against the wrong reference"
class as the four findings before it.

## The A39 decision, now closed

A39 left "warn on, or refuse" open. The project owner chose **refuse**
(2026-09-08), recorded as **A41** in `docs/spec-amendments.md`. What the
code does is unchanged; what changed is that it is no longer this ticket's
own policy guess sitting in a docstring.

## What could not be verified even with mocks, and why

- **Whether a real `OST_StructuralFraming` neighbour actually exposes
  `Location.Curve`.** This ticket assumed it does, matching the existing
  assumption already made for the beam being detailed
  (`beam_axis_direction`/`beam_endpoints` in `rft/revit/geometry.py`). This
  is the FIRST place that assumption is relied on for a SECOND,
  independently-picked framing element, and it has not been confirmed
  against a live host either -- flagged in
  `rft/revit/guards.py:neighbour_axis_dot_product`'s own docstring and in
  `tests/fake_revit_api.py`'s header.
- **Whether either tolerance is right for real models — the 45-degree
  angular one or the 50 mm lateral one.**
  Real framing rarely meets at a clean 90 or 0 degrees; skewed grids,
  angled girders and beams meeting slightly off a right angle are common.
  This ticket's tolerance has not been checked against any real project's
  geometry -- it is a reasoned default, not an empirically-tuned one.
  Only observing real false positives/negatives in practice can validate
  or correct it.
- **The pushbutton orchestration end-to-end.** Beyond the pytest suite, an
  ad hoc harness (not part of the committed test suite, same limitation
  S1/S2/S5 already carry) installed minimal fake `pyrevit` modules and
  imported/executed all three pushbuttons' `main()` up to
  `pick_element` returning `None`. All three loaded and reached
  `script.exit()` cleanly with no `NameError`/`AttributeError`/`ImportError`
  -- confirming every new import this ticket introduced resolves correctly.
  This is NOT a full run with a real beam/neighbour/support chain, which
  remains unexercised.
- **`FilteredElementCollector`'s real iteration order and whether a real
  Revit project ever returns a beam framing member and its own supporting
  column in a way that ties on bounding-box proximity the way this
  ticket's case-2 test constructs it.** The test demonstrates the LOGIC is
  correct given such an arrangement; it does not demonstrate that this
  arrangement is how a real structural model's elements actually present
  themselves at a shared node.

## Scope boundaries held (see this ticket's instructions)

- No new detailing rule was invented; the angular tolerance and the
  refuse-vs-warn choice are guard POLICY, which A39 explicitly leaves open,
  and both are flagged as this ticket's own choices, not spec rules.
- R4 and R6 were not touched or re-decided; `stirrup_type3_guard_message`
  reuses `TYPE3_PARKED_MESSAGE` verbatim rather than reimplementing it.
- `free_end_configuration_warning` (A14) is reused verbatim from
  `rft.core.anchorage`, only wrapped for the end label and the
  condition/spec-section fields this ticket's `GuardMessage` shape
  requires -- its underlying text and the WARN-not-refuse behaviour for
  free ends were not changed.
- Multi-span placement itself remains entirely out of scope; this ticket
  only detects and refuses the configuration, per A39.
