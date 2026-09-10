# Changelog

All notable changes to the RFT Beam Detailing tool.

A merge to `master` means the code exists; it does **not** mean it is safe
to load. Only a tagged commit should be loaded into a Revit session, never
`master` HEAD.

**`v0.3.0-rc1` is a CANDIDATE, not a release.** It adds the live sketch,
which is ~470 lines of WPF that nothing outside Revit can execute. Load it
to test it; the seven checks are in its own entry below.

**`v0.2.1` is the last VERIFIED release.** Go back to it if the candidate
misbehaves.
The single `Detail Beam` window opens, picks a beam, reports its plan and
places main bars, stirrups and crack bars in a live Revit 2024 session --
confirmed by the project owner on `v0.2.0` and again on `v0.2.1` after the
stirrup grouping changed, with the three stirrup sets checked in the
model.

`v0.2.1` fixes two defects in `v0.2.0`: a crash in Place on one valid
combination of inputs, and a Review report that described the stirrup sets
with the wrong grouping.

**`v0.1.0` was the first release**, and is also verified — but its ribbon
is three separate pushbuttons that `v0.2.0` deletes. It is kept tagged as
the fallback and as the A/B reference, not as something to install
alongside.

Both got there the same way: through candidates that a fully green test
suite could not have replaced. Six for `v0.1.0`, eight for `v0.2.0`.

## Delivery model

This is a **pyRevit extension** — not a standalone application, and not a
Revit `.addin` / compiled add-in. There is no installer, no `.sln`, no DLL to
build, and none should be added.

Deployment means registering, as a pyRevit extension search path, the
folder that **contains** `RFTBeamDetailing.extension` — checked out at a
**tagged commit**, never at whatever `master` happens to be:

```
git worktree add <somewhere>/rft-<tag> <tag>
pyrevit extensions paths add <somewhere>/rft-<tag>
```

then reload pyRevit. See `docs/deployment.md` for the full procedure and for
why `pyrevit extend` — which this section previously named — is the wrong
command: it clones a third-party extension from a git repo URL rather than
registering a local folder.

Layout follows pyRevit convention — `RFTBeamDetailing.extension/` containing
`RFT Beam Detailing.tab/` → `Detail Beam.panel/` →
`Detail Beam.pushbutton/script.py`, plus `lib/`, which pyRevit adds to
`sys.path` automatically so `rft.core`, `rft.revit` and `rft.ui` import
cleanly. As of `v0.2.0` that is the only panel and the only button: the
`Main Bars`, `Stirrups` and `Crack Bars` panels were removed by #55.

## [v0.3.0-rc1] — 2026-09-10

A candidate, deliberately. The live sketch is the first substantial WPF
this project has written since the window itself, and the entire
construction path is unverifiable without a Revit host -- which is the
exact class of assumption that took `v0.2.0` eight candidates to settle.

### The live sketch (#49, U5)

The three static teaching diagrams #51 added are replaced by drawings of
YOUR beam, redrawn as you type: cross-section on Main bars and Crack
bars, longitudinal elevation on Stirrups, following the active tab (A47).

Split the way the report was, and for the same reason: all the geometry
lives in `lib/rft/ui/sketch.py`, which imports only `collections` and
`rft.core.stirrups` -- no `pyrevit`, no WPF -- and returns plain shape
namedtuples in millimetres. `script.py` holds one renderer that applies
`translate(cx, cy) scale(s, -s)` and maps style keys to palette brushes,
and nothing else. So the drawing is testable, and 26 tests check it.

**Achieved spacing and the A7 clearance are drawn and coloured by
compliance** -- green when a layer passes, red when it does not. This is
the point of the story rather than decoration: the sketch is a
verification surface. It is also what answers the question asked on first
sight of the Stirrups tab -- "how would a user know the difference between
hook 1, 2, 3, 4 if he cannot see it" -- since the section now shows the
selected closure type and where its hooks land.

Two elements are drawn as schematic and say so on the drawing: individual
stirrup stations (the bands and `n @ s` are exact, the stations are
Revit's own rebar-set layout) and hook bend arcs (angle and leg length
exact, the fillet belongs to the bar type's bend radius).

Verified by execution, independently of the implementer's own tests: the
drawn bar positions EQUAL `rft.core.plan`'s values on the 300x900 beam
(v = +/-407.0 and +/-375.0, u = -107.0/0.0/107.0, radius = dia/2, twelve
bars, v increasing upward), a failing spacing really does colour red where
a passing one colours green, and a REFUSED end (A51) draws the plan's own
refusal text rather than crashing on a `None`.

### Guards can say whether they block (#45)

`GuardMessage` gained `severity`, declared at all thirteen construction
sites with no default -- omitting it is a `TypeError`. The values were
read back out of the `v0.1.0` tag rather than inferred from the message
wording, because #55 deleted the pushbuttons that held the behaviour:
every guard there was `forms.alert()` then `script.exit()` except the
free-end one, which warned and carried on placing. Twelve blocking, one
warning. Nothing reads `severity` yet, so no behaviour changed.

### Two duplicated shapes collapsed

Both found by review, both agreeing with their originals at the time,
both the same pattern as the `ZONE_LAYOUT_FLAGS` copy that had the report
and the placer describing different stirrup sets for three releases:

- The support-detection dict had grown a second writer in the pick
  handler, spelling out all twelve keys again.
- `rft.core.plan` no longer restates `ZONE_LAYOUT_FLAGS` (fixed in
  `v0.2.1`, noted here because the new guard belongs to the same family).

A duplicate that agrees is still a duplicate. Both are guarded now.

### Numbers

Tests: 415 -> 442. Guards proven by mutation: 20 -> 24.

### NOT VERIFIED

Every WPF call: `FindResource`, `Canvas.SetLeft`/`SetTop`,
`PointCollection`, and constructing `Line`/`Ellipse`/`Polygon`/`TextBlock`
from IronPython inside a modeless `WPFWindow`. Flagged `SHAPE UNVERIFIED`
in the source per CONTEXT.md. Three defects have reached a live host in
this project because a fake modelled something the real API does not
provide.

### What to check on the live run

1. Pick the 300x900 beam -- Main bars and Crack bars each show a to-scale
   cross-section immediately.
2. Switch to Stirrups -- the longitudinal elevation, not the section.
3. Enter a bar count that fails spacing (9 bars in a 300 mm web) -- the
   spacing dimension renders RED; a passing count renders GREEN.
4. Pick a beam with one unsupported end -- a caption with the refusal or
   warning text, no crash, no bar segment on that face.
5. Resize the window -- the sketches rescale without clipping.
6. The stirrup ticks read as schematic; the `n @ s` zone labels read as
   exact.
7. The window OPENS, with no `AttributeError` and no "Cannot find
   resource". This is the one thing the text guards cannot replace, and
   it is what broke rc6 of the last release.

### Known, and not fixed here

Place still does not refuse on a section 6.2-6.4 spacing violation
(issue #61). The Review report prints "REFUSED" and the bars are placed
anyway -- a regression against `v0.1.0`, found while establishing #45's
severities. It affects steel rather than pixels and is the most
consequential thing still open.

---

## [v0.2.1] — 2026-09-10

**Two defects in `v0.2.0`, and the report is finally testable.** Load this
one: `v0.2.0`'s Place could crash outright on one valid combination of
inputs, and its Review report described your stirrups with the wrong
grouping.

**Verified on a live host** (2026-09-10, Revit 2024): the window places
main bars, stirrups and crack bars, and the three stirrup sets are present
in the model after the grouping change. Nothing here moves a bar -- the
report's output is byte-identical across 84 renderings, and the stirrup
positions were computed under both flag sets and diffed -- but the
grouping change was the one thing only a live run could show, and it did.

### A crack-bar crash, reachable in `v0.2.0`

The placer read each face's innermost layer offset off a whole `FacePlan`,
and built both faces a SECOND time inside the crack branch after having
already built them above. A `FacePlan` needs a per-layer bar count,
because it also computes every bar's `u`. A50 only requires a face to be
DETAILED: a bar type and a layer count. So detail both faces, place only
one, request crack bars -- a combination the derivation explicitly
declares valid -- and the second build raised

```
TypeError: '<' not supported between instances of 'NoneType' and 'int'
```

from inside `corner_bar_u_positions_mm`, with the transaction already
open. `H_avail` never needed a bar count:
`core_plan.innermost_layer_offset_mm` now answers exactly the question the
crack plan asks, and names the fact that the innermost layer is layer
number `layer_count` rather than layer 1 -- which had been re-stated at
three call sites, each spelling it differently.

### The report and the placer disagreed about the stirrup zones

`rft.core.plan` had grown its own copy of `ZONE_LAYOUT_FLAGS`, and the
copy said something different from the original in `rft.core.stirrups`:

| | zone 1 | zone 2 | zone 3 |
|---|---|---|---|
| original (tested) | `(True, True)` | `(False, False)` | `(True, True)` |
| `plan.py`'s copy | `(True, True)` | `(False, True)` | `(False, True)` |

Both give each zone boundary exactly one owner, so both place bars at the
**same positions** -- confirmed by computing both position sets, which are
identical -- and both total 47 stirrups on the verification beam. That is
why nothing noticed. What differed is WHICH ZONE owns the bar at 2L/3. The
Review report imported the original and said "zone2: count = 9, zone3:
count = 19"; Place used the copy and built sets of 10 and 18. In `v0.2.0`
the report described the right steel with the wrong grouping.

`plan.py` now re-exports the constant. **This changes Place**: the bar at
2L/3 belongs to zone 3's set rather than zone 2's, which is what the three
verified pushbuttons did. Positions are unchanged.

#56's own test had pinned the copy, and was named
`test_three_zones_with_the_layout_flags_the_verified_button_uses`. It was
not what the verified button used. A test that pins a duplicate is not a
check on the duplicate; it is a second place the duplicate is written
down.

### The report is out of `script.py`, and tested

~400 lines of the most detailed prose the tool produces -- every layer
offset, every achieved spacing, every anchorage `a` and `b`, every warning
-- lived inside `script.py`, which imports `pyrevit` and cannot be
imported under CPython at all. Not one line of it could be executed by a
test. It was the largest untested piece of the project, and it is the text
the engineer reads before committing steel to a model.

It is now `rft/ui/report.py`: pure functions over values already
computed. `script.py` keeps one job on that path -- read the model, hand
over plain values -- and the report's stirrup and crack sections now
FORMAT the `StirrupPlan` and `CrackPlan` the placer executes instead of
recomputing them.

The move itself was mechanical, deliberately: nothing here can execute the
old report to compare, so the transform only dedented a method or
substituted a `self.<x>` read for the parameter now carrying the same
value. Then a harness ran the report before and after over 28
configurations x 3 sections and diffed all 84 renderings line for line:
zero differences.

### Two things it stopped re-reading

- **Bar diameters.** `bar_type_diameter_mm` is a Revit parameter read, and
  the live `H_avail` readout made three of them on EVERY KEYSTROKE in `h`,
  in either layer count, and in the spacer field -- on the UI thread,
  while the engineer is typing. A bar type's diameter cannot change while
  the window is open, so it is read once per type.
- **Support detection.** `find_supporting_element` is a document-wide
  scan, run once per end, plus a host validation and a cover read per
  support. The whole pass ran again for every report and again for Place.
  It is now computed once per pick, and cleared on re-pick along with the
  rest of the beam-scoped state -- the previous beam's supports would
  report and place against the wrong span, plausibly and silently, which
  is the worst way for a cache to be wrong.

### CI

There was none. `.github/workflows/tests.yml` runs pytest, the mutation
prover and a compile pass on every push. The prover is the one that
matters: a text guard that matches nothing passes silently, and two of
them did.

### Numbers

`script.py`: 2145 -> 1738 lines. Tests: 363 -> 399. Guards proven by
mutation: 12 -> 18.

### The prover deadlocked while proving this

Worth recording, because it is the second time this tool has failed in the
same direction. `tools/prove_guards.py` ran its pytest child with
`stdout=PIPE` and never read the pipe. One of the new guards failed with a
500-line module source as an assertion operand -- pytest prints an
assert's operands -- which overflowed the 8 KB pipe buffer: the child
blocked on write, the parent waited forever, and the restore in its
`finally` never ran, so a MUTATED source file sat in the working tree the
whole time.

Fixed in the general form rather than the specific one: `subprocess.run`
drains the pipes, a 300 s timeout turns a future hang into a reported
failure, and the guard now asserts on a short list of missing calls
instead of on the file it read. An assertion message should be the size of
the fact it reports.

---

## [v0.2.0] — 2026-09-10

**Second release, and the first one that details a beam in one place.** One
button, one window, one transaction. `Detail Beam` picks a beam, reads its
geometry and its per-face covers, collects every input across five tabs,
derives exactly what it is going to place, reports it in words, and then
places main bars, stirrups and crack bars in a single all-or-nothing
transaction.

**Verified on a live Revit 2024 host**: the window opens modeless,
`Pick beam` selects while the window stays open, `Review` reports the plan,
and `Place` puts real reinforcement in the model.

The three original pushbuttons are **gone**. `v0.1.0`'s ribbon carried
`Place Main Bars`, `Place Stirrups` and `Place Crack Bars`; this release
carries one button. **A full Revit restart is required**, not a pyRevit
reload — pyRevit builds ribbon panels only at startup, and three panels
have been removed.

### What is new since `v0.1.0`

- **One window, five tabs** — Beam & Materials, Main bars, Stirrups, Crack
  bars, Review — replacing three buttons that each asked for the same beam
  again (#46, #47, #48).
- **Modeless**, so `Pick beam` works with the window on screen, with every
  Revit API call dispatched through `revit.events.execute_in_revit_context`
  and a `persistent` engine declared in `bundle.yaml` (#57, #58).
- **Covers are read per face** from the beam itself, with a supported end
  shown as "n/a (supported)" rather than a number.
- **One `RebarBarType` picker per role**, plus the stirrup `RebarHookType`,
  each option labelled with its **measured** diameter — the type names
  disagree with the diameters (`16M` measures 15.9 mm), and the measured
  value is what the tool details against. High-tensile steel for every
  longitudinal bar, mild for stirrups.
- **`H_avail` is computed live** from the Main bars tab and shown read-only,
  so it can no longer disagree with the beam the way `v0.1.0` allowed.
- **The Review tab derives what will be placed** and refuses by name when a
  requirement is missing, instead of describing a beam it is not going to
  build (#50).
- **One computation behind both the report and the steel.**
  `lib/rft/core/plan.py` composes the core functions into the numbers that
  become reinforcement; the report formats the plan the placer executes, so
  the two cannot describe different beams (#56).
- **Sky blue and white palette**, the selected tab highlighted, and the
  beam icon on both the ribbon button and the window title bar (#60).
- **A teaching diagram in each of the three input tabs** — static vector,
  no dimensions: they name the vocabulary (layer 1, bars per layer, dense
  and normal zones, `H_avail`) and deliberately state no size, because a
  static drawing carrying "43 mm" would contradict whichever beam is loaded
  (#51).
- **Two new spec amendments.** A50: crack bars need both faces detailed, or
  are refused by name. A51: top-bar anchorage uses a *selected* bottom bar
  type, whether or not that bottom face is placed, and is refused if none is
  selected.

### What the eight candidates found

Every one of these was invisible to a fully green test suite.

| Candidate | What the live host found |
|---|---|
| `rc1` | The window was **modal**. `Pick beam` could not select anything until the window was closed (#57). |
| `rc2` | pyRevit tore down the IronPython engine when the script returned, so the `ExternalEvent` never delivered: `Pick beam` hung on "waiting for Revit..." forever. Fixed by `engine: persistent` in `bundle.yaml` (#58). |
| `rc3` | Labels an engineer could not read — clipped mid-word by fixed-width columns, and written in spec notation ("1/2, section 6.3") where `v0.1.0` had said "1=single wide row, 2=stacked". |
| `rc4` | `Place` died on `AttributeError: 'ReviewDerivation' object has no attribute 'crack'` — the field is `crack_bars`. The transaction rolled back, so nothing was placed and nothing was damaged. |
| `rc5` | **Two guards were incapable of failing.** A literal backspace byte had been written where a regex `\b` belonged, so the pattern matched nothing and the test passed *against the defect it was written for*. Found `tools/prove_guards.py`. |
| `rc6` | The window would not open: `Cannot find resource named 'SurfaceWhite'`. A `StaticResource` on the `<Window>` element itself, whose attributes resolve **before** `Window.Resources` is populated. The XML was well-formed, so `test_xaml_parses` was green — a WPF semantic error inside valid markup. |
| `rc7` | Palette and ribbon icon accepted. The window's own title bar still showed Revit's default icon: `WPFWindow.set_icon` is a separate call from the button's `icon.png`. |
| `rc8` | **Working.** Palette, both icons and the three teaching diagrams confirmed by the owner. Promoted to `v0.2.0` with no code change. |

### Closes

Wayfinder #33 and its decision tickets #34–#43 (recorded as A47–A49),
#44 (U0 core additions), #46 (the shell), #47 (Beam & Materials), #48 (the
three reinforcement tabs), #50 (Review derivation and report), #51 (legend
and symbol reference), #55 (retire the three pushbuttons), #56 (port the
placement paths into the one transaction), and the four defects the live
tests found: #57, #58, #59, #60.

### Verified, and not verified

**Verified**: the window opens, picks a beam, reads geometry and covers,
derives its plan, reports it, and places main bars, stirrups and crack bars
in one transaction on a live host.

**Not verified**: that every placed bar is dimensionally correct in every
configuration. The A/B comparison against `v0.1.0` — the same beam detailed
through the old three buttons and through the new window, then measured —
has **not** been run. `v0.1.0` stays tagged so it still can be.

**Also not verified by anything automated**: the window itself. `script.py`
imports `pyrevit` and cannot be imported under CPython, so 12 of its
invariants are checked as **source text** instead. Each of those 12 is
proven by mutation — `python tools/prove_guards.py` reintroduces the defect
each guard was written for and requires the guard to fail. A guard that has
never been shown to fail has not been tested, only written.

### Still deferred

Multi-span beams (rev 2 section 9 item 2) remain out of scope by decision,
and are refused at runtime rather than silently mishandled. Single-span
rectangular beams only.

### Tests

363 pass. 12 of 12 text guards proven by mutation.

---

## [v0.2.0-rc5] — 2026-09-10

Fixes the one defect rc4's live test found, and two tests that could never
have found it.

### Place died on an `AttributeError` (#56 follow-up)

`_do_place` read `review.crack` while the field is `crack_bars`. Everything
upstream worked — the derivation was right, the report printed, the
transaction opened — and placement failed at the last step. The transaction
rolled back, so nothing was placed and nothing was damaged, but a beam that
should have been detailed was not.

One word, and no test could reach it: `script.py` imports `pyrevit` and
cannot be imported under CPython. The names are now compared as **text**
against `ReviewDerivation._fields`, the same trick the `x:Name` cross-check
uses.

### Two guards were passing vacuously — the worse finding

Writing that guard exposed it. Its own mutation test reported MISSED, and
the cause was a literal **backspace byte** where a regex word boundary
should have been: `\b` written into the file as the control character it
denotes rather than as two characters. The pattern matched nothing, so the
check passed — against the very defect it was written for.

The same corruption was already sitting in rc2's modal-window guard, whose
`show_dialog(` branch had therefore never matched anything. Its mutation
test had passed only because the mutation happened to hit the *other*
branch.

Both are fixed, there is a control-character sweep, and the new guard
asserts that it **matched something at all** — a text check that finds
nothing is indistinguishable from one that finds nothing wrong unless it
says which it is.

A third guard was merely too coarse: it checked that `core_plan.` appeared
somewhere in a method, which stayed true with one of several plan calls
ripped out. It now names each required call.

### `tools/prove_guards.py`

The mutation prover is now part of the repo. Every text-based guard is
reintroduced its own defect and must fail. **9 of 9 do — two of which did
not before this release.**

360 tests pass.

---

## [v0.2.0-rc4] — 2026-09-10

**The single window places reinforcement.** First candidate where Place is
not a stub.

### What to test, and what "correct" looks like

Detail a beam with the window, then detail an identical beam with the three
old buttons, and **compare**. That comparison is the whole point of keeping
them, and it is the acceptance criterion on #55: it shows the rework changed
the *interface* and not the *detailing*.

Place now reports a **count** — "Placed 47 rebar elements." — which you can
check against the Review report's own totals and against what the old
buttons produce for the same inputs.

### Only what is REQUESTED gets placed (#50)

Review states, in words, what will and will not be placed and why. A section
is requested when the selection only it needs has been made: a bar type plus
a non-blank count for a face, the hook for stirrups, and for crack bars a
crack bar type, `h > 700`, **and both faces detailed** (A50).

### One computation behind both the report and the steel (#56)

New module `rft/core/plan.py`. The report and the placer were going to need
the same numbers — layer offsets and positions, anchorage per end, stirrup
zones, the crack-bar plan. Computing them twice is how a report and the bars
it describes drift apart: both would keep calling the correct functions and
could still be handed different arguments. The report now *formats* the plan
the placer *executes*.

The detailing arithmetic itself is unchanged — every position still comes
from the `rft.core` functions `v0.1.0` was verified with. The two
live-verified geometry facts are carried across verbatim: the
centroid-to-location-curve offset at every stirrup station, and the
support-face reference point per end.

### A51 — anchorage with only one face detailed

§2.1's top anchorage needs the *bottom* bar's diameter. Since the faces are
independent, that face may not be placed — so the diameter is taken from the
**selected** bottom bar type, placed or not. With no bottom type selected at
all the end is **refused by name**, inside the transaction, so nothing is
left half detailed.

### Everything is all-or-nothing

One transaction (A46). Any refusal — A51's, an invalid input, a Revit error
— rolls back every section, including ones already placed in the same run.

### Tests

20 new tests on the plan module, the one whose output becomes steel.
Cross-checked against the 300×900 verification beam **and** against
`docs/ui/sketch-notation.svg`, drawn by hand from the spec weeks earlier:
both give `offset₁ = 43 mm` and four crack layers at 162.8 mm.

359 tests pass. **None of that is evidence that a single bar is correctly
placed.** No rebar has been placed by this code — that needs a live host, and
it is the only thing that matters next.

---

## [v0.2.0-rc3] — 2026-09-10

Two things the second live test found: the pick still did nothing, and the
labels could not be understood or even fully read.

### `Pick beam...` hung on "waiting for Revit..." (#58)

rc2 made the window modeless and routed API calls through an
`ExternalEvent`, which was right but **incomplete**. pyRevit tears down the
IronPython engine when a script returns, and a modeless window's handlers
run *after* that. The window survives — it is a CLR object, which is why the
status line still updated — but the `ExternalEvent` was raised into a
torn-down engine and never delivered. No error appeared anywhere, because
the failure is upstream of the wrapper that reports failures.

The fix is one setting in `bundle.yaml`:

```yaml
engine:
  persistent: true
```

rc2 followed `Measure.pushbutton`'s **script** and not its **bundle.yaml**,
where that setting lives. Reading the code and not the configuration is the
whole of the mistake.

### Labels the engineer could not read or interpret (#58)

Reported on sight of the Main bars and Stirrups tabs:

- **Labels were clipped mid-word** — "Max aggregate size D_agg (mm, blank =
  50 mm f". Fixed columns with no wrapping; now star-width columns and
  `TextWrapping` throughout.
- **"Top face option (1/2, section 6.3)"** said nothing. `v0.1.0`'s
  pushbutton actually said *"1=single wide row, 2=stacked"* and the single
  window lost it — a clarity regression introduced by #48 and missed in
  review, which compared the diff for correctness and never against the
  working button's wording. It is now a **dropdown**: "one single wide row
  (no stacking)" / "stacked rows, separated by a spacer bar".
- **Closure type 1/2/4 was unguessable.** Types 1 and 2 are the *same*
  closed loop and differ only in which top corner the hooks meet at. The
  dropdown now says so: "closed loop, hooks meet at the TOP-RIGHT corner",
  "…TOP-LEFT corner", "open U, no top leg, hooked free ends at both top
  corners".
- **`§6.2` min-spacing override** now reads "Raise the minimum bar spacing —
  blank lets the tool decide", with a tooltip giving the actual rule: it is
  a **floor only**, `max(computed, yours)`, so it can make spacing stricter
  but never looser.
- Tooltips added to the inputs whose rule cannot fit on one line: `D_agg`'s
  two-branch formula, `O_spacer` being a clear gap with no spacer bar
  placed, and why the bar counts ship blank.

**Seeing** the stirrup shape rather than reading about it is #49's live
sketch, which draws the section and will show the selected closure type
directly. This candidate makes the words right; #49 makes them unnecessary.

### Guards

`bundle.yaml` is now read by a test at all — it never was, which is why a
green suite said nothing about a button that could not work. That guard is
coupled to the modeless check, since the two must change together. The
closure and face-option labels are asserted to keep naming the corner and
the stacking, and the label→value lookup deliberately refuses a label it did
not offer rather than falling back to reading the leading numeral.

315 tests pass.

---

## [v0.2.0-rc2] — 2026-09-10

Fixes the one defect rc1's live test found, on the first click.

**`Pick beam...` could not select anything** until the window was closed
outright. The window was shown with `ShowDialog()`, and a WPF modal dialog
disables every other top-level window in the process — Revit's main window
included — so `Selection.PickObject` could never receive a click in the
viewport. Nothing past step 1 of the test plan was reachable (#57).

The window is now **modeless**, and every Revit API call it makes is routed
through `revit.events.execute_in_revit_context`, which runs it inside a real
API context via an `ExternalEvent`. Both halves are required: a modeless
window's handlers run *outside* the API context, where `PickObject` and
`Transaction` raise `InvalidOperationException`.

This follows pyRevit's own precedent rather than an inference — of the
extensions shipped with pyRevit, exactly one combines a WPF window with
element picking (`Measure.pushbutton`) and it does precisely these two
things.

Two properties of that helper shaped the fix:

- It is **asynchronous and returns nothing**, so the dispatched function
  does the pick *and* updates the window itself.
- Its handler **swallows exceptions into the pyRevit log**, which would make
  any error appear as *nothing happening at all*. The wrapper catches
  everything and puts it on screen instead.

### Consequence for #56

The placement port must use the same routing: a `Transaction` started from a
modeless window's handler fails exactly the way the pick did.

### Guards added

Three, all mutation-tested by reintroducing the defect and confirming the
guard fails: the window is never shown modally, the click handlers make no
direct Revit API call, and the dispatch wrapper cannot stop catching.
rc1's suite was entirely green while this defect shipped — nothing in it
modelled how the window is *shown*.

311 tests pass.

---

## [v0.2.0-rc1] — 2026-09-10

**A test candidate, not a release.** Cut so the new single window can be
opened for the first time. `v0.1.0` remains the only *verified* version, and
its three pushbuttons are still on the ribbon and still work — this
candidate **adds** a fourth button and deletes nothing.

### What to expect on the ribbon

A new **Detail Beam** panel and button, alongside `Place Main Bars`,
`Place Stirrups` and `Place Crack Bars`. Both sets are loaded deliberately:
the three are the verified tool, the new one cannot place anything yet.

**A full Revit restart is required**, not just a pyRevit reload — the panel
is new, and pyRevit only builds ribbon panels at startup.

### What the new window does

- Five tabs: Beam & Materials, Main bars, Stirrups, Crack bars, Review.
- Pick a beam and its `L`, `b`, `h` fill in and stay **editable**; the four
  covers are read from the beam's own faces, per face, with a supported end
  shown as "n/a (supported)" rather than a number.
- One `RebarBarType` picker per role plus the stirrup `RebarHookType`, each
  option labelled with the **measured** diameter — the type names disagree
  with the diameters in this document (`16M` is 15.9 mm), and the measured
  value is what the tool details against.
- The hook list is filtered to the Stirrup/Tie family, and the pick is
  re-checked after selection (A45). An unreadable hook angle is accepted but
  says so, rather than passing in silence.
- Main bars, Stirrups and Crack bars tabs collect their inputs. Bar counts
  and layer counts ship **blank** on purpose.
- `H_avail` is computed live from the Main bars tab and shown read-only, so
  it can no longer disagree with the beam the way it could in `v0.1.0`.
- The Crack bars tab enables itself only when `h > 700`, tracking edits to
  `h` as they are typed.

### What it does NOT do

**Place is a stub.** It validates the inputs, refuses by name if a required
bar type or hook is unpicked, and then reports that placement is not built
yet — pointing at the three existing buttons. That is expected, not a fault.
Placement is #56, which ports the verified buttons' placement paths into the
single all-or-nothing transaction.

### Closes

#46 (the shell), #47 (Beam & Materials), #48 (the three reinforcement tabs).
Opened #56 after finding that no story in the set owned the placement port.

### What is verified, and what is not

308 tests pass, both modules compile, and the XAML/script name cross-check
covers every filled-in tab. **None of that is evidence the window opens.**
This candidate exists precisely because a green suite has never been
evidence of that in this project — six candidates were needed to get
`v0.1.0` running, and every one of those failures was a wrong API name that
the tests could not see.

Three WPF assumptions are load-bearing here and unexercised: that a
programmatic `.Text` assignment raises `TextChanged` (this is what enables
the Crack bars tab after a pick), that `TabItem.IsEnabled = False` greys a
tab header, and that a `ComboBox` bound to a list of strings renders the
text rather than a Python repr.

---

## [v0.1.0] — 2026-09-09

**First release, and the first version of this code ever to run.** All three
pushbuttons — "Place Main Bars", "Place Stirrups", "Place Crack Bars" —
placed real reinforcement on a real beam in a live Revit 2024 session
(`RevitAPI 24.3.40.0`), on both a 0° and a 45° 300×900 single-span beam.

Contents: six detailing subsystems (S1–S7), the out-of-scope configuration
guards (S9), pyRevit bundle metadata and deployment docs, 46 spec
amendments. 264 tests pass.

### What the six candidates found

Every failure between rc1 and this release was **a wrong API name, never
wrong detailing arithmetic** — the core maths, unit boundary and guard logic
worked first time. The candidates, in order:

| Candidate | Reached | Failed on |
|---|---|---|
| rc1 | ribbon built, button pressed | `FlexForm` imported from `pyrevit.forms`; it lives in `rpw.ui.forms` |
| rc2 | imports resolved | no PEP 263 encoding cookie — Python 2 rejects non-ASCII source without one |
| rc3 | library compiled, picker opened | `.Name` on an `ElementType` is unreachable from IronPython |
| rc4 | pickers and input form cleared | `GetBoundingBox` is on `GeometryElement`, not `GeometryInstance` |
| rc5 | **stirrups and crack bars PLACED** | Main Bars formatted a `None` cover with `{:.1f}` |
| rc6 | **all three place rebar** | — |

**Three of those five were concealed rather than merely missed by the test
suite**: a fake modelled an API shape that does not exist (`RebarFaceType`
in #23, `.Name` in rc3, `GetBoundingBox` in rc4), so the suite was green
against code that could not run. Each fake now mirrors the live surface,
with a test asserting the absence so that restoring the convenience turns
the suite red. `tests/test_ironpython_compat.py` additionally guards the
Python-2 constraints that CPython 3.10 cannot see.

**What is verified**: that the buttons run, place rebar, and read the model.
**What is not**: that every placed bar is dimensionally correct in every
configuration. The 0° and 45° beams were detailed successfully; a
measured check of covers and bar positions against the spec, per
configuration, has not been done.

## Development log up to `v0.1.0`

Kept for the record: what was built, decided and risk-assessed on the way
to the first release. This section was headed "[Unreleased]" and opened
with "Nothing -- `master` and `v0.1.0` are the same tree", which was true
the day `v0.1.0` was cut and has been wrong ever since. Current unreleased
work is at the top of this file.

### Added

- **Project scaffold and detailing spec.** Technical spec plus the CADS
  reference manual, `CONTEXT.md` standing rules, MIT licence.
- **Spec revision 2** (`beam_rebar_detailing_spec_v2.docx`) incorporating 40
  amendments from the Wayfinder decision cycle, each traced to its deciding
  ticket in `docs/spec-amendments.md`. Revision 1 is retained as the
  historical baseline and must not be implemented from.
- **Research findings**: `docs/research/revit-api-strategy.md` (unit boundary,
  rebar creation API, bend-radius datum, host prerequisites, rebar-set layout
  rules, transaction pattern) and `docs/research/stirrup-types.md` (closure
  type mapping).
- **User stories**: `specs/beam-rft-detailing.md` — nine stories sliced
  tracer-bullet-first, acceptance criteria traced to rev 2 sections.
- **S1 tracer bullet** (#14): places one bottom main bar anchored at both
  ends, establishing the architecture the remaining stories inherit — a
  Revit-free pure calculation core, a thin Revit adapter converting units only
  at the API boundary, host validation with explicit cover read-back, and one
  transaction per beam with rollback on failure. 24 tests.
- **S5 stirrups** (#18): full cage on a single-span beam — centreline leg
  geometry, closure types 1/2/4 (type 3 rejected), and three
  `SetLayoutAsMaximumSpacing` rebar sets clipped to the clear region with
  dense spacing at the supports, all inside one transaction, plus a per-zone
  and beam-total report. New `Stirrups.panel` pushbutton. 58 tests.
- **S3 cross-section bar layout** (#16): first-layer and stacked-layer
  offsets for both faces, the corner-bar distribution rule, spacer length,
  and the R1 non-blocking spacer warning. New `Main Bars.panel` pushbutton
  places the bottom-face bars through S1's anchorage machinery, one per
  layer x corner position, in one transaction. 91 tests.
- **S2 full end anchorage** (#15): top-bar anchorage bending downward,
  independent `LD_top` / `LD_btm` multipliers, support detection widened to
  **any** structural support (column, wall or girder, with wall width taken
  as thickness per R5), each beam end handled independently, and the
  unsupported-end straight run with no hook and an explicit warning that
  `LD` was not achieved (R3). Top bars are now placed, closing the hole S3
  left. 121 tests.

### Fixed

- **Section datum, found reviewing #18.** The stirrup cage was centred on the
  beam's *location curve* rather than its section centroid — with Revit's
  default top-justified structural framing that is the top face, so half the
  cage would have sat outside a 600 mm deep beam. `b` was also read from the
  *world* bounding box, which returns `b + L` for a beam not parallel to a
  project axis (a 250×6000 beam at 45° measured 6250 mm). Both now use the
  beam's own local bounding box and instance transform, the technique S1's
  review already adopted for rotated columns. The second half was
  pre-existing in S1 and only became visible once S5 consumed `b`.
- **The A7 top/bottom clearance was only checked before §2.3's cap, found
  reviewing #15.** The cap fires per bar and `LD_top` / `LD_btm` are
  different multipliers, so at a wide support it fires on one bar and not the
  other. With `Ø_TOP = Ø_BTM = 16` on an 800 mm support the bars end up
  **79 mm crossed** while the formula-level check reported a comfortable
  +16 mm and stayed silent. The same check now also runs on the `a` values
  actually built, per end, and says when the bends have crossed rather than
  merely closed up. What to *do* on failure is #26, for decision.
- **The unsupported-end report printed a negative length, found reviewing
  #15.** R3's warning read "achieves only −25.0 mm", conflating where the bar
  stops with how much anchorage it achieves. An unsupported end achieves
  **0 mm** of embedment; the bar's termination short of the beam end is now
  reported as the separate fact it is.
- **Collinearity was tested by direction alone, found reviewing #22.** A
  neighbour merely running *parallel* to the beam scores a perfect
  direction match, and the search is a proximity test around the beam end —
  so twin beams a few hundred millimetres apart, or an edge beam alongside a
  floor beam, would have been refused as a "continuous run". Collinear means
  same direction **and** same line; the neighbour's perpendicular offset
  from the beam's own axis line is now checked too, with a 50 mm tolerance
  to absorb modelling slop.
- **Horizontal dimensions read off the wrong cover, found reviewing #16.**
  The corner-bar rule and the spacer length are horizontal dimensions across
  the section, but were computed from the top or bottom face cover — so the
  top and bottom layers came out at different horizontal positions in the same
  beam, and §6.3's single spacer length was reported as two contradictory
  values. Both now use the beam's side cover, read once. This is the third
  wrong-cover-face defect in the project (after S1's column cover), so it is
  worth checking first on #17 and #19.
- **Reported stirrup counts contradicted the placement flags, found reviewing
  #18.** The count ignored the R4 de-duplication flags, so the normal zone
  reported 11 stirrups where 9 are placed. The flags are now a required
  argument, so a count cannot be reported without stating which boundary bars
  the zone owns.

### Decided

- Spec §9 open item 1 (bottom bar anchorage geometry) **confirmed correct as
  written**, with the clearance rationale that justifies it recorded.
- Spec §9 open item 3 (stirrup leg dimensions) **resolved** by derivation from
  the spec's own cover definition, corroborated independently by two existing
  formulas. This rescued stirrups from being cut from v1.
- Spec §9 open item 2 (multi-span) **remains deferred**; single-span is a hard
  scope boundary.
- Steel grade is now first-class: **mild St 24/35** for stirrups, **high
  tensile St 36/52** for all other bars.
- **Stirrup type 3 parked**, narrowing the type input to (1, 2, 4), because
  its inner loop has no defined dimensions.
- **Stirrup hook family and angle (#25, A45): a two-part guard, verified
  against a live Revit 2024 host.** The required angle is **135 deg**
  (A45, superseding A33's 180), and the constraint that actually matters
  is the hook FAMILY: `REBAR_HOOK_STYLE` must be 1 (Stirrup/Tie), because
  `RebarStyle.StirrupTie` rejects a Standard-family hook with an opaque
  `InternalException` whatever its angle. The two checks are reported
  separately, so a Standard hook at exactly 135 deg is diagnosed as a
  family problem rather than an angle problem. The picker filters to
  family 1, and a model with no such hook refuses with the fix named
  instead of falling back to the first hook found. Names are never used:
  the live model holds a hook called `Stirrup/Tie - 45` whose family is
  Standard.
- **Spacing validation (S4, #17): `lib/rft/core/spacing.py`, wired into
  `Place Main Bars` before any placement.** Governing minimum per rev 2
  section 6.2 -- `max(25, O_bar, 1.33*D_agg)` when `D_agg` is defined, the
  50 mm fallback only when it is not, with A29's optional override acting
  as a floor that can only raise it. Achieved clear spacing per **A43's
  corrected datum**, `(b - 2*Cover_side - 2*O_stirrup - n*O_bar)/(n - 1)`;
  `n = 1` skips the check. Every layer of every face is validated
  independently and both section 6.3 options **refuse** on a violation
  (**A44**: the tool never re-splits the bars the engineer stated), naming
  the governing minimum, the achieved spacing, the maximum bars per layer
  that would satisfy it and the layer count that would then be needed --
  or, where A28's absolute 5-layer cap makes that impossible, saying so
  instead of naming an unreachable count. Section 6.3's option is now a
  per-face input, cross-checked against the layer count so option 1 with
  stacked layers is refused rather than silently reinterpreted.
- **`D_agg` is optional again, as A36 intends.** Blank selects section
  6.2's 50 mm fallback, which had been unreachable behind a hard stop
  inherited from S3, and section 6.2's minimum is now evaluated in exactly
  one place (`governing_min_spacing_mm`) rather than re-derived for R1.
- **Crack / skin reinforcement (S6, #19): `lib/rft/core/crack_bars.py`
  plus a `Place Crack Bars` pushbutton.** Fires only when `h > 700`
  (rev 2 section 5, strict). `H_avail = h - offset_top - offset_btm`
  measured to the **innermost** main bar layer (A26), so it is the true
  unreinforced web height and yields fewer layers than a naive reading.
  `n_gaps = ceil(H_avail / s_max)` with an epsilon-tolerant ceiling, so an
  exact multiple cannot invent an extra gap; `H_avail <= s_max` collapses
  to zero crack layers, a legitimate outcome rather than an error. One bar
  per side face per layer, inset `cover_side + O_stirrup + 1/2*O_crack`
  (A24), diameter from a `ROLE_CRACK` bar-type selection (A42, superseding
  A22's free-text input), running the full span and embedding straight
  into the support with no hook (A23) by `support width - support cover`
  (R2, and no section 2.3 cap). Exempt from section 6.2 spacing validation
  (A25), stated explicitly in code so #17 cannot sweep crack bars into it.
  `s_max` defaults to A36's 200 mm.
- **Per-role bar types (A42, #27): one `RebarBarType` selection per bar
  role, and the diameter comes from the selected type.** A Revit
  `RebarBarType` *is* a diameter, so A35's two selections could not express
  a Ø12 top bar and a Ø16 bottom bar — the normal case. The free-text
  `Ø_TOP` / `Ø_BTM` / `Ø_stirrup` inputs are gone, along with the
  diameter cross-check they needed. `Ø_spacer` stays typed, since A19
  defines it as the clear *gap* between layers rather than a bar diameter.
  Grade can no longer be inferred from a type, so A34's assignment is now
  the label on each role's picker and a line in the report; the one
  mechanical check — the stirrup type must not be the same element as a
  main-bar type — runs in `Place Main Bars`, which holds all three
  selections at once.
- **Steel grades (S7, #20): every bar type is now an explicit selection, and
  nothing falls back.** The §1.1/A34 role→grade mapping lives in
  `rft/core/grades.py` as data — stirrups mild St 24/35, everything else
  (including spacer bars, applied literally) high tensile St 36/52. All three
  pushbuttons lost their resolve-by-name-with-fallback code: a missing
  selection is a blocking error naming its condition and spec section, and
  the typed diameter is cross-checked against the selected bar type's own
  diameter before any placement math runs, so `LD`, layer offsets and the
  stirrup rectangle can never be computed against a diameter that is not the
  one being placed. `LD` fields now name the St 36/52 grade they assume
  (A10). The stirrup hook is an explicit selection whose angle is read back
  and blocked when it is not 180° (A33) — see #25 for what is still
  unverified there.
- **Continuous-run guard (S9, #22): a collinear neighbouring beam at either
  end now REFUSES placement, in all three pushbuttons, before any support
  detection or placement work.** Discriminates by angle, not category: a
  beam framing into a transverse girder still passes (§2.4, a valid single
  span); a collinear neighbouring beam is refused even when a column is
  ALSO present at that end -- the dangerous case this guard exists for. The
  45-degree angular tolerance and the 50 mm lateral tolerance are this
  ticket's own design choices, not spec rules, and are flagged as such in
  `rft/core/guards.py`. **Refusing rather than warning is now the project
  owner's decision** (A41), closing the either/or latitude A39 left open. Cantilever/free-end warnings
  (A14) and the stirrup type 3 rejection (A31) were already implemented;
  this ticket wires both into all three pushbuttons and makes every
  rejection/warning name its condition and spec section via a
  `GuardMessage(condition, spec_section, message)` result, never a bare
  string. See `docs/verification/s9-guards.md`.

### Known risks

- ~~**#23 — `RebarHostData` cover read-back shape is unverified.**~~
  **Resolved, and the risk was real.** The live probe found that
  `RebarFaceType` *does not exist* in Revit 2024 — all four pushbuttons
  would have raised `AttributeError` on their first cover read. Replaced in
  #30 by classifying exposed-face normals against the beam's own frame,
  confirmed on a live host including a beam rotated 45° in plan
  (`docs/verification/issue-30-cover-face-reads.md`).
- **`Place Crack Bars` re-asks for the main bar layer counts.** A26's
  `H_avail` is measured to the innermost main bar layer, so the crack-bar
  run needs `layers_top` / `layers_btm` -- and nothing reads them back from
  the bars already placed. Enter different counts than `Place Main Bars`
  used and `H_avail` will silently not match the as-built beam. Per-project
  persistence of these inputs is #21 (S8); this is the sharpest instance of
  that gap, because unlike a wrong bar type it produces no visible clash.
- **Bar-type selections are not shared between pushbuttons.** Each run picks
  its own, so `Place Main Bars` can position main bars against one stirrup
  type while `Place Stirrups` places another — nothing in a single run can
  detect that. Per-project persistence of these selections is #21 (S8).
- ~~**#25 — the stirrup hook angle read-back is unverified.**~~
  **Resolved.** `REBAR_HOOK_ANGLE` reads back live (in **radians**, and it
  is writable), and `REBAR_HOOK_STYLE` distinguishes Standard (0) from
  Stirrup/Tie (1). The probe also found the constraint that matters: a
  Standard-family hook is rejected by `RebarStyle.StirrupTie` with an opaque
  `InternalException` *whatever* its angle — so the guard checks family as
  well as angle (A45; `docs/verification/issue-25-stirrup-hook-family-and-angle.md`).
- **#26 — the A7 clearance has no defined failure behaviour.** The tool warns
  and places anyway, which is a placeholder chosen to avoid inventing a
  detailing rule, not an answer. Needs a decision.
- ~~**The tool's own execution path has never run.**~~ **Two of the three
  pushbuttons now do.** As of `v0.1.0-rc5`, **"Place Stirrups" and "Place
  Crack Bars" placed real reinforcement on a real beam** in Revit 2024 — so
  `Rebar.CreateFromCurves` works as these scripts call it,
  `pyrevit.forms.SelectFromList.show` takes the arguments they pass, and
  `rpw.ui.forms.FlexForm` drives the inputs. That was the single largest
  open risk in this project and it is now retired.

  **"Place Main Bars" is still not working** — see the entry below.

  Getting there took five candidates, and every failure was a wrong API
  name rather than wrong detailing arithmetic: the `FlexForm` import module
  (rc1), PEP 263 source encoding for IronPython 2.7 (rc2), `.Name` on an
  `ElementType` (rc3), `GetBoundingBox` on a `GeometryInstance` (rc4). None
  was caught by the test suite, and in three cases **the suite actively
  concealed the defect** because a fake modelled an API shape that does not
  exist. Each is now mirrored to the live surface with a test asserting the
  absence, so restoring the convenience turns the suite red.

- **"Place Main Bars" has not completed a run.** It clears the pickers, the
  form, the geometry read and the cover reads, then fails in its own report
  (`v0.1.0-rc5`: a numeric format applied to `cover_end_mm`, which is
  `None` whenever both ends are supported — the normal single-span case).
  Fixed for rc6, untested at the time of writing. Its report also showed
  empty bar-type names, from `getattr(bar_type, "Name", "")` swallowing the
  same IronPython binding failure rc3 hit head-on.

## Tickets closed

| Ticket | |
|---|---|
| #1 | Wayfinder root map |
| #2, #11, #12 | §2 anchorage decisions |
| #3 | §3 stirrup distribution decisions |
| #4 | §4 layer offset decisions |
| #5 | §5 crack bar decisions |
| #6 | §6 spacing rule decisions |
| #7 | §7 stirrup type research |
| #8 | Revit API strategy research |
| #9 | UI scope decisions |
| #13 | Steel grade requirement |
| #14 | S1 tracer bullet |
| #15 | S2 full end anchorage |
| #16 | S3 cross-section layout |
| #18 | S5 stirrups |
| #20 | S7 steel grades and bar type resolution |
| #27 | A42 per-role bar type selection |
| #19 | S6 crack / skin reinforcement |
| #17 | S4 spacing validation and layer decisions |
| #25 | Stirrup hook family and angle (A45) |
| #30 | Cover reads via real face references |
| #31 | A45 stirrup hook angle decision |
| #28 | A43 section 6.4 clear-spacing datum |
| #29 | A44 engineer-stated bars per layer |
| #22 | S9 out-of-scope configuration guards |
| #23 | Cover read-back API shape (superseded by #30) |
| #24 | pyRevit bundle metadata and deployment doc |
