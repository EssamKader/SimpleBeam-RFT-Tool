# Single-Window UI — User Stories

Phase 4 output of the AI-KaderSkill cycle. Converts the decisions resolved
under Wayfinder root
[#33](https://github.com/EssamKader/rft-beam-detailing/issues/33) into
implementable user stories.

**Source of truth:** `00.Technical Material/beam_rebar_detailing_spec_v2.docx`
(revision 2) §8, as amended by **A46, A47, A48, A49**. Amendment provenance:
[`docs/spec-amendments.md`](../docs/spec-amendments.md). Standing rules:
[`CONTEXT.md`](../CONTEXT.md). Research:
[`docs/research/ui-wpf-hosting.md`](../docs/research/ui-wpf-hosting.md),
[`docs/research/ui-sketch-data-sources.md`](../docs/research/ui-sketch-data-sources.md).
Notation: [`docs/ui/sketch-notation.svg`](../docs/ui/sketch-notation.svg).

**This document supersedes [#21](https://github.com/EssamKader/rft-beam-detailing/issues/21)**
(S8 WPF form). #21's substance — one dialog, A35's dialog-then-pick ordering,
the §8.1 defaults, per-project persistence, the §8.2 report — is carried
forward into the stories below and expanded. #21 should be closed as
superseded when Phase 5 opens these tickets.

Throughout, **"the engineer"** means the BIM/structural engineer running the
tool inside Revit.

---

## What is already released, and must keep working

`v0.1.0` is verified: all three pushbuttons placed real reinforcement on
real beams in Revit 2024, on both a 0° and a 45° 300×900 single-span beam.
**None of the detailing logic is in question here.** These stories replace
the *input and reporting layer* only. Any story that changes a `rft.core`
result rather than how it is gathered or displayed is out of scope and must
stop and ask.

## Architecture constraints (apply to every story)

**1. The existing Revit-free core / thin adapter split is unchanged.** All
detailing mathematics stays in `rft.core` in millimetres; the adapter
converts units only at the API boundary.

**2. A48 — the renderer owns no detailing arithmetic.** Every dimension the
sketch draws comes from an `rft.core` function. A number the drawing needs
that the core does not expose is **added to the core**, never computed in
the renderer. This is the story set's single most important constraint: the
moment the renderer does its own maths it can disagree with what gets
placed, and the engineer will believe the drawing.

**3. A46 — one command, one transaction, all-or-nothing.** Everything the
Review tab lists is placed inside a single `Transaction` that rolls back
entirely on any exception. No partially detailed beam.

**4. IronPython 2.7 is the runtime.** Python 2: PEP 263 encoding cookie in
every module, no f-strings, no Python-3-only stdlib.
`tests/test_ironpython_compat.py` enforces this and must stay green.

**5. Fakes mirror the live API surface.** Three defects reached a live host
because a test fake modelled something the real API does not provide
(`RebarFaceType`, `.Name` on an `ElementType`, `GetBoundingBox` on a
`GeometryInstance`). Any new fake must withhold what the real thing
withholds, with a test asserting the absence.

### Definition of done (every story)

- Logic in the Revit-free core with unit tests running under plain CPython.
- WPF/Revit-dependent behaviour verified by mock objects where possible, and
  **by pressing the button on a live host** where not — `v0.1.0` proved that
  a green suite is not evidence that a button works.
- Every implemented rule cites its rev 2 section or amendment.
- All Revit mutation inside one `Transaction` per beam, rolling back on any
  exception.
- No residual question (R1–R6) answered by assumption.

---

## U0 — Core additions the renderer needs (prerequisite)

> **As** the maintainer, **I want** every dimension the sketch draws to exist
> as a `rft.core` function, **so that** the drawing and the placement cannot
> disagree.

A48's constraint is unenforceable until these exist. Pure refactors: **no
behaviour change, no new rule.**

**Acceptance criteria**

- [ ] `stirrups.outer_leg_dimensions_mm(b_mm, h_mm, cover_mm)` returning
  `(b − 2·cover, h − 2·cover)` — the outer rectangle §7.1/A30 defines but
  which no function returns. The `#42` spike computed it in the renderer and
  left the line commented as the argument for this addition.
- [ ] `layout.main_layer_v_positions_mm(h_mm, layer_offsets_mm, is_top)`
  returning the centroid-local `v` positions of a face's bar layers,
  mirroring the existing `crack_bars.crack_layer_v_positions_mm`.
- [ ] **`Place Main Bars`' inline `±(h/2) ∓ offset` is replaced by a call to
  it**, so one implementation exists rather than two. This is the point of
  the story; adding the function while leaving the pushbutton's own copy in
  place would achieve nothing.
- [ ] Unit tests for both, including the sign convention for `is_top`.
- [ ] The full suite still passes and placement output is unchanged.

**Depends on:** nothing. **Blocks:** U6, U7.

---

## U1 — `GuardMessage` can say whether a refusal blocks (prerequisite)

> **As** the engineer, **I want** blocking refusals and non-blocking warnings
> to be visibly different, **so that** I can tell what stops the run from what
> merely deserves my attention.

Today `GuardMessage` carries `condition`, `spec_section` and `message`, and
**nothing expresses severity** — it is implicit in whether the call site
happens to follow the message with `script.exit()`. U8 cannot route by
severity until severity exists.

**Acceptance criteria**

- [ ] `GuardMessage` gains a `severity` field: `SEVERITY_BLOCKING` or
  `SEVERITY_WARNING`.
- [ ] **Every construction site declares it explicitly.** No default value —
  a default would silently mislabel any site the migration missed, and there
  are only about fifteen.
- [ ] Severity is assigned to match today's behaviour exactly: a message
  currently followed by `script.exit()` is `BLOCKING`; every other is
  `WARNING`. **This story changes no decision about what blocks** — it only
  makes the existing decision inspectable.
- [ ] A test asserts that every `GuardMessage` factory in `rft.core` returns
  a declared severity, so a new guard cannot omit it.
- [ ] Existing tests updated; no change in which runs succeed or refuse.

**Depends on:** nothing. **Blocks:** U8.

---

## U2 — One command, five tabs, one transaction

> **As** the engineer, **I want** a single "Detail Beam" command whose
> sub-sections I switch by clicking, **so that** I configure a whole beam in
> one place instead of running three separate buttons that cannot see each
> other's inputs.

The shell only: tabs, navigation, the pick control, the Place button, the
transaction. Tab *contents* are U3–U6.

**Acceptance criteria**

- [ ] One pushbutton, `Detail Beam`, **added alongside** the existing
  `Place Main Bars`, `Place Stirrups` and `Place Crack Bars` (A46, A47).
- [ ] **Nothing is deleted in this story.** The three pushbuttons and
  `Spike.panel` stay until the single window has been verified on a live
  host — see **U11** (#55). The ribbon carries both temporarily, and that is
  intended: the three buttons are the only *verified* tool (`v0.1.0`), so
  while the new window's Place button is still a stub the tool as a whole is
  never broken. They do not conflict at runtime — separate `*.pushbutton`
  folders, loaded independently, sharing `lib/rft/` read-only.
- [ ] `forms.WPFWindow` loading a XAML **file** by bare filename from the
  pushbutton folder. A plain `TabControl` — proven by the #42 spike, so the
  `Expander` fallback in `docs/research/ui-wpf-hosting.md` is **not** needed.
- [ ] Five tabs in order: **Beam & Materials · Main bars · Stirrups · Crack
  bars · Review**.
- [ ] **A35 — the dialog opens first, then the engineer picks the beam.** The
  pick control sits at the top of Beam & Materials; every geometry and
  support field is disabled until a beam is picked; re-picking repopulates
  them and re-runs support detection.
- [ ] Placement happens in **one `Transaction`** covering everything Review
  lists, rolling back entirely on any exception (A46).
- [ ] The continuous-run refusal (A41) and the no-support-at-both-ends
  refusal fire **before** any placement work, as they do today.
- [ ] Verified on a live host on both the 0° and 45° beams.

**Depends on:** U0, U1 (so the shell is not built twice).
**Blocks:** U3, U4, U5, U6, U7, U8.

---

## U3 — Beam & Materials tab

> **As** the engineer, **I want** the beam's geometry, its four covers and one
> bar type per role in a single first tab, **so that** the same stirrup
> diameter positions my main bars and gets placed as my stirrups.

**Acceptance criteria**

- [ ] Pick control; then `L`, `b`, `h` **read from the model** and
  **editable** (§8, A35), with `b`/`h` from
  `geometry.beam_section_dimensions_mm` — the rotation-safe read, live-proven
  on the 45° beam.
- [ ] The four covers pre-filled from `host.read_beam_face_covers_mm`, each
  face separately. **End covers are `None` when that end is supported** —
  display "n/a (supported)", never a number, and never format `None`
  numerically. This is the rc5 crash and it must not reappear.
- [ ] Support detection result per end: type, width, and the support's own
  cover (§2.4, A8/A9), or "none detected".
- [ ] One `RebarBarType` picker **per role** — top main, bottom main,
  stirrup, crack — plus the stirrup `RebarHookType`, all explicit with **no
  fallback to "first found"** (A42, A45, #27).
- [ ] Every picker labels each option with its **measured diameter**, since
  names disagree with diameters (`16M` is 15.9 mm in the verification model).
  Reuse `bar_types.bar_type_options` / `hook_type_options`.
- [ ] The hook picker is filtered to the **Stirrup/Tie family**
  (`REBAR_HOOK_STYLE == 1`) and the selection re-checked after picking
  (A45).
- [ ] Grade required by A34 shown per role (`role_picker_label`).
- [ ] **The stirrup type selected here is the one placed by U4** — the
  mismatch A46 exists to eliminate must be structurally impossible, not
  guarded.

**Depends on:** U2.

---

## U4 — Main bars, Stirrups and Crack bars tabs

> **As** the engineer, **I want** each reinforcement type's own inputs on its
> own tab, **so that** I am not scrolling one long form.

Grouped as one story because they are the same work three times over the
existing pushbutton inputs; Phase 5 may split them if it prefers.

**Acceptance criteria — Main bars**

- [ ] Bars per layer and number of layers, per face (A44 — the engineer
  states them; **the tool never re-splits**). `LD` multipliers, §6.3 layer
  option, `Dagg` (**blank by default** so §6.2's 50 mm fallback governs),
  `Ospacer`, optional minimum-spacing override (A29).
- [ ] **Bar counts and layer counts ship BLANK.** §8.1's defaults cover
  dimensions and multipliers, not counts — see U6 for why this matters.

**Acceptance criteria — Stirrups**

- [ ] Dense and normal spacing (defaults 150 / 200), closure type limited to
  **1, 2, 4** — type 3 stays parked with A31's message (R6).

**Acceptance criteria — Crack bars**

- [ ] `Ocrack` and `s_max` (default 200), and the whole tab is **enabled only
  when `crack_bars.crack_reinforcement_triggered(h)`** — strict `h > 700`
  (§5).
- [ ] `H_avail` is measured to the **innermost main-bar layer** (A26), read
  from the Main bars tab rather than re-entered. **This closes the sharpest
  gap in `v0.1.0`**: `Place Crack Bars` re-asked for layer counts and read
  nothing back, so `H_avail` could silently disagree with the as-built beam —
  no clash, no warning.

**Depends on:** U2, U3.

---

## U5 — The live sketch

> **As** the engineer, **I want** a sketch that redraws as I type, **so that**
> I can see what will be placed — and see a violation — before I commit
> anything to the model.

**Acceptance criteria**

- [ ] A WPF `Canvas` drawn from code, following the notation defined in
  `docs/ui/sketch-notation.svg`. Vector only — no bitmaps (#40 found no
  precedent for relative `<Image>` paths and a concrete reason to expect
  failure).
- [ ] **Cross-section and longitudinal elevation, following the active tab**
  (A47): section while editing Main bars or Crack bars, elevation while
  editing Stirrups or anchorage.
- [ ] Coordinate convention shared with the notation SVG and the #42 spike:
  origin at the section centroid, `v` positive **up**, `translate(cx,cy)
  scale(s,−s)`.
- [ ] **Every drawn dimension sourced from `rft.core`** per A48 and the
  element-by-element mapping in `docs/research/ui-sketch-data-sources.md`.
- [ ] Achieved clear spacing and the A7 clearance are drawn **and coloured by
  compliance**, from `LayerSpacingResult.passes` and `ClearanceResult.ok`.
  This is the story's real value: the sketch is a verification surface.
- [ ] **The two schematic elements are drawn as schematic and labelled so on
  the drawing**: individual stirrup positions (bands and `n @ s` are exact,
  stations are not — Revit's rebar set lays them out) and hook bend arcs
  (angle and leg length exact, fillet not — the bar type's bend radius owns
  it).
- [ ] Redraw is wrapped so a half-typed or empty input cannot kill the
  window. The spike proved plain redraw-on-change needs no debouncing; if
  measurement says otherwise, debounce.
- [ ] Rescales on window resize without clipping.

**Depends on:** U0, U2. **Blocked by nothing else.**

---

## U6 — Review tab: derived placement list, and the report

> **As** the engineer, **I want** one place that tells me exactly what is
> about to be placed and why, **so that** I am never surprised by what the
> Place button does.

**Acceptance criteria — the derivation rule (A47's open question, closed here)**

§8.1's defaults make every tab hold valid-looking values the moment the
window opens, so "filled in" cannot mean "has values". The rule:

- [ ] **A section is REQUESTED when the explicit selection only it needs has
  been made**, leaning on A42's existing no-defaults-for-bar-types rule:
  - **Main bars** — a top and/or bottom `RebarBarType` selected **and** a
    non-blank bar count for that face (hence U4's blank counts).
  - **Stirrups** — the `RebarHookType` selected. The hook is
    stirrup-exclusive, so it cannot be confused with the stirrup *bar type*,
    which Main bars also needs for its offsets.
  - **Crack bars** — a crack `RebarBarType` selected **and** `h > 700`.
- [ ] **Review states the derivation per section, in words** — "stirrups:
  will be placed", "crack bars: not requested (no crack bar type selected)".
  A derived decision the engineer cannot see is worse than a checkbox they
  forgot to tick.
- [ ] Place is disabled when nothing is requested, saying so.

**Acceptance criteria — the report (§8.2, A37)**

- [ ] The full report on the Review tab: per-layer offsets and positions,
  governing and achieved spacing, anchorage `a`/`b`/`LD` per end, stirrup
  zones and counts, crack-bar plan, the grade required per role against the
  bar type used, and every warning raised.
- [ ] **A copy still written to the pyRevit output window.** Review is where
  it is read; the output window is where it is kept — scrollable, copyable,
  and it survives closing the dialog.
- [ ] Bar type names read via `bar_types.element_name` (`SYMBOL_NAME_PARAM`),
  never `.Name` and never `getattr(x, "Name", "")` — the latter silently
  produced empty names in `v0.1.0`'s report, which is worse than crashing
  because it claims a grade check against a type it could not identify.

**Depends on:** U0, U2, U3, U4.

---

## U7 — Legend and symbol reference in the window

> **As** an engineer who has never read the spec, **I want** the drawing's
> symbols defined inside the tool, **so that** I can use it without being
> taught.

**Acceptance criteria**

- [ ] The legend from `docs/ui/sketch-notation.svg` reachable from the
  window — drawn on the Canvas, or a dedicated pane on Review.
- [ ] Each row maps **drawn symbol → meaning → the tool's symbol → the spec
  section**, matching the SVG exactly.
- [ ] The two schematic elements are called out as schematic here too.
- [ ] The notation is **not claimed to be ECP-compliant** (A49); it is
  defined for clarity and is open to adjustment against the engineer's own
  drawing conventions.

**Depends on:** U5.

---

## U8 — Validation where the engineer is looking

> **As** the engineer, **I want** problems shown next to what caused them,
> **so that** I am not reading a modal that has lost its context.

**Acceptance criteria**

- [ ] **Per-field** errors (negative cover, non-numeric spacing) inline
  beside the field.
- [ ] **Cross-field refusals** (§6.2/§6.4 spacing per A43/A44, the A7
  clearance, A28's 5-layer cap) as a banner on the owning tab, **plus a badge
  on that tab's header** so an unhappy tab is visible without visiting it.
- [ ] **Blocking refusals** (continuous run A41, no support at both ends,
  wrong hook family A45, stirrup type 3 A31) remain **modal** — they end the
  run, so interrupting is correct.
- [ ] Routing is driven by `GuardMessage.severity` from U1, never by
  re-deriving severity in the UI.
- [ ] Each message shows its **spec section**, which `GuardMessage` already
  carries.
- [ ] A44's refusal keeps reporting the governing minimum, the achieved
  spacing, and the smallest layer count that would comply.

**Depends on:** U1, U2.

---

## U9 — Plain-English labels, and messages that speak the same language

> **As** a new user, **I want** the fields and the error messages to use the
> same words, **so that** an error tells me which field to fix.

**Acceptance criteria**

- [ ] Every field label is **plain English with the spec symbol in
  brackets** — "Bottom bar development length (LD_btm)" (A47).
- [ ] **Every `GuardMessage` text is revised to the same convention.** This
  is the half of A47 that is easy to skip: a form saying "development
  length" whose error says `LD_btm violated` still fails the newcomer it was
  relabelled for.
- [ ] `spec_section` stays on every message.
- [ ] Field labels, legend rows and message text use **one vocabulary** —
  the mapping in `docs/ui/sketch-notation.svg` is the authority.

**Depends on:** U1, U8.

---

## U10 — Per-project persistence

> **As** the engineer detailing a series of beams, **I want** my inputs
> remembered for this project, **so that** I am not retyping fifteen fields
> per beam.

**Acceptance criteria**

- [ ] Inputs persist **per project** via `script.store_data` (§8.2) — bar
  types, layer counts, covers, spacings, multipliers.
- [ ] A different project starts from §8.1 defaults. **Not per-user-global**,
  which would carry one job's cover conventions into an unrelated job.
- [ ] Bar and hook types persist by a stable identity that survives reopening
  the model, and a persisted type that no longer exists degrades to "not
  selected" rather than to a wrong type or a crash.
- [ ] Persistence never resurrects a *requested* state that would place
  reinforcement the engineer did not ask for in this session — restoring
  values is not the same as restoring intent (see U6).

**Depends on:** U2, U3, U4.

---

## U11 — Retire the three pushbuttons

> **As** the maintainer, **I want** the old pushbuttons removed only once the
> single window has replaced them in practice, **so that** the engineer is
> never left without a tool that is known to work.

Split out of U2 on the project owner's instruction (2026-09-09): *"I
recommend not deleting three buttons until we test single UI, if they do not
affect each other."* They do not affect each other, so there is no reason to
delete early and one good reason not to.

**Acceptance criteria**

- [ ] `Place Main Bars`, `Place Stirrups`, `Place Crack Bars` and
  `Spike.panel` deleted.
- [ ] **Blocked until the single window has placed correct reinforcement on
  a live host** — on both the 0° and the 45° beam, with the results compared
  against what the old buttons produce for the same inputs. That comparison
  is the point of keeping them: it is a direct A/B check that the rework
  changed the interface and not the detailing.
- [ ] The `Detail Beam` window is the only reinforcement command left, per
  A46/A47.
- [ ] No dead code or commented-out remnants left behind; the old logic
  stays available through git history and the `v0.1.0` tag.

**Known cost of deferring, accepted deliberately:** U1 (`GuardMessage`
severity) and U9 (message text) touch guard construction sites, some of
which live in the pushbuttons this story deletes. Doing those before U11
means editing call sites that are about to disappear. Sequence U1 and U9
*after* U11 where practical, or accept the duplicated edit — but do not
resolve the tension by deleting the buttons early.

**Depends on:** U2, U3, U4, U6 — and on live-host verification, which is a
human step, not an agent one.

---

## U12 (#56) — Port the three placement paths into the one transaction

> **As** the engineer, **I want** the single window to place exactly the
> reinforcement the three verified buttons place, **so that** the rework
> changed my interface and not my steel.

Added 2026-09-09, closing a gap in this spec's own decomposition rather than
in the tool. U4 collects inputs; U6 derives what is *requested* and reports
it. **Neither ports the `Rebar.CreateFromCurves` calls themselves**, and no
other story did either — the shell's stub message (#46) asserted #47/#48/#50
would build placement, which the acceptance criteria of those three do not
support. Rather than let the largest and riskiest piece of work in the set
arrive as a side effect of a ticket that did not name it, it gets its own
story.

**Why it is separated deliberately, not merely overlooked twice**

This is the only story in the set that can put wrong steel in a model.
Everything else changes what the engineer sees or types. It therefore earns
its own review pass and its own live-host verification, instead of being
reviewed alongside thirty new input fields where a placement defect competes
for attention with a mislabelled textbox.

**Acceptance criteria**

- [ ] The main-bar, stirrup and crack-bar placement paths from
  `Place Main Bars`, `Place Stirrups` and `Place Crack Bars` all run inside
  the **single** `run_in_transaction` the shell already opens — A46's
  all-or-nothing, no partially detailed beam.
- [ ] Placement reads its inputs from the tabs (U4) and its bar types from
  the one `BeamMaterialsSelection` (U3). **No second collector call, no
  re-prompting, no free-text diameter** (A42).
- [ ] Only the sections U6 derives as *requested* are placed, and the
  transaction is not opened at all when nothing is requested.
- [ ] **`rft.core` results are unchanged.** This is a port of the CALLING
  code, not of the detailing arithmetic. A diff that changes what a core
  function returns is out of scope — stop and ask.
- [ ] The two live-verified geometry facts are preserved verbatim: the
  centroid-to-location-curve offset applied at each stirrup station, and
  `GetSymbolGeometry()` (symbol space) rather than `GetInstanceGeometry()`
  for the rotation-safe bounding box — the 45° beam is the test that
  catches getting either wrong.
- [ ] The A/B check of #55 (U11) is run against this: the same beam
  detailed by the old buttons and by the window, results compared.

**Depends on:** U2, U3, U4, U6 — U6 in particular, since "place what is
requested" has no meaning until the derivation rule exists.

**Blocks:** U11 (#55). The old buttons cannot retire before the window can
place.

---

## Dependency order

```
U0 (core additions) ─┐
U1 (severity) ───────┼─> U2 (shell) ─┬─> U3 ─> U4 ─> U6 ─> U10
                     │               ├─> U5 ─> U7
                     └───────────────┴─> U8 ─> U9

                       U12 (port placement) <- U2, U3, U4, U6
                       U11 (retire the old buttons) <- U12
                       + live-host verification, a human step
```

U0 and U1 are pure refactors with no visible change and can be done in any
order, or in parallel. Nothing else should start before U2.

## Out of scope

- **Multi-span.** Deferred (§9 item 2), refused at runtime. Unchanged.
- **Stirrup type 3.** Parked (A31, R6).
- **Any change to a `rft.core` detailing result.** These stories change how
  numbers are gathered and shown, never what they are — except U0's two
  additions, which introduce no new rule.
- **A34's mild-versus-deformed question** ([#32](https://github.com/EssamKader/rft-beam-detailing/issues/32))
  and **A7's unachievable-clearance policy**
  ([#26](https://github.com/EssamKader/rft-beam-detailing/issues/26)) —
  both still open, both awaiting the project owner, neither blocking this UI.
- **Localisation.** pyRevit supports it for free
  (`<name>.<locale>.xaml`); not requested.
