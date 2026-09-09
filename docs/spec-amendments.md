# Spec Amendment Register

Authoritative record of every change to `beam_rebar_detailing_spec.docx`
arising from the Wayfinder decision cycle (root issue
[#1](https://github.com/EssamKader/rft-beam-detailing/issues/1)),
resolved 2026-09-08.

Each amendment cites the ticket that decided it. Per `CONTEXT.md` the spec
is the source of truth, so **this register must be applied to the .docx
before any implementation ticket that touches the affected section**.

Legend: **NEW** = adds something absent · **CLARIFY** = states a
convention the spec left implicit · **CHANGE** = contradicts what the spec
currently says · **CONFIRM** = validates an existing placeholder unchanged.

---

## §1 Notation

| # | Type | Amendment | Ticket |
|---|---|---|---|
| A1 | NEW | Add `Ø_spacer` — spacer bar diameter, user input, default 16 | #4 |
| A2 | NEW | Add `Ø_crack` — crack bar diameter, user input, default 12 | #5 |
| A3 | NEW | Add steel grades: **mild St 24/35** (`fy` 240, plain round) for stirrups; **high tensile St 36/52** (`fy` 360, deformed) for every other bar. ECP designations | #13 |
| A4 | CLARIFY | `Cover` is context-dependent: the **beam's** cover governs §4, §6 and §7; the **support's own** cover governs the §2 anchorage formulas | #2 |
| A5 | CLARIFY | `a` and `b` are measured to the **theoretical corner** — where the two bar centrelines would meet at a sharp corner (BS 8666-style datum), not the actual straight run | #12 |
| A6 | CLARIFY | `L` = **centreline-to-centreline** distance between supports | #3 |

## §2 Development Length & End Anchorage

| # | Type | Amendment | Ticket |
|---|---|---|---|
| A7 | CONFIRM | §2.2's placeholder is **correct as written** — `a_btm = Column width − Cover`. Not replaced. Record the rationale: the two bent legs overlap in depth and need horizontal separation; only this variant delivers the required `(Ø_TOP + Ø_BTM)/2` centreline clearance, and it makes `a_t = a_btm − Ø_BTM` the deliberate clash-avoidance §2.1 already claims. **Closes §9 open item #1** | #2 |
| A8 | CLARIFY | `Cover` in `a_t` / `a_btm` is the **support's** cover, since the dimension is measured inside the support | #2 |
| A9 | NEW | `Column width` is **read from the model** at each end and user-overridable. Support detection covers **any structural support** — column, wall or girder — using its width/thickness | #2, #11 |
| A10 | CHANGE | **Two** independent multipliers: `LD_top` (default 60 × Ø) and `LD_btm` (default 55 × Ø), each shared across both ends. UI must label the assumed grade (36/52) | #2, #13 |
| A11 | NEW | Cap the straight leg so anchorage is not over-delivered: `a = min(a_formula, LD − 200)`, `b = max(200, LD − a)`, giving total = `LD` exactly while preserving the 200 mm minimum bend | #2 |
| A12 | **CHANGE** | **§2.3's mandatory-hook rule is scoped to SUPPORTED ends only.** The current text — "a hook is never omitted" — must be reworded. A beam end with no detectable support gets a **straight bar, no hook**, anchorage length `LD` | #11 |
| A13 | CLARIFY | "Hook" in §2.3 means the **bent leg `b`** (an L-bend formed as a curve segment) — **not** a Revit `RebarHookType`. Without this an implementer reaches for the wrong API | #8 |
| A14 | NEW | Cantilever / free ends are **out of scope for v1**; they fall into the A12 unsupported path and must warn | #11 |

> **A12 is the only outright contradiction of existing spec text in this
> register.** Everything else adds, clarifies or confirms.

## §3 Stirrup Distribution

| # | Type | Amendment | Ticket |
|---|---|---|---|
| A15 | NEW | Zones are measured on the **c/c** span but stirrups are **clipped** to the clear region: zone 1 `[face_A + 50, L/3]`, zone 2 `[L/3, 2L/3]`, zone 3 `[2L/3, face_B − 50]`. First and last stirrup both sit 50 mm from a support face (mirrored) | #3 |
| A16 | CLARIFY | Consequence of A15: the two **dense zones carry stirrups over less than `L/3`** each (short by roughly half the support width plus 50 mm), while the normal zone gets the full `L/3`. Documented so it is not mistaken for a defect | #3 |
| A17 | NEW | Degenerate-case guard: if `face_A + 50 >= L/3` (short span and/or wide support), error with a clear message rather than passing a non-positive array length to the API. Same test at the far end | #3 |
| A18 | CLARIFY | Dense and normal values are **maximum** spacings. Spacing is redistributed evenly to exactly fill each zone, so there is **no remainder to allocate and no rounding rule** — this dissolves the original open questions about leftover gaps | #3, #8 |

## §4 Main Bar Layer Offset

| # | Type | Amendment | Ticket |
|---|---|---|---|
| A19 | CHANGE | The vertical gap between stacked layers is the **user-defined `Ø_spacer`** (default 16), as a **clear** distance. This resolves the §4-vs-§6.3 conflict: §4's "layer gap is a user input" and §6.3's fixed "convention: Ø16" are reconciled as *user-defined, defaulting to 16* | #4 |
| A20 | CLARIFY | **One diameter per face.** `offset_1 = Cover + Ø_stirrup + ½Ø_bar`; `offset_n = offset_1 + (n − 1) × (Ø_bar + Ø_spacer)` for n = 1..5. §4's existing wording is confirmed correct | #4 |
| A21 | CLARIFY | §6.2's `min_spacing` is **horizontal-only** and does not govern the vertical direction. Accepted consequence: nothing prevents `Ø_spacer` being below the horizontal minimum | #4, #6 |

## §5 Crack / Skin Reinforcement

| # | Type | Amendment | Ticket |
|---|---|---|---|
| A22 | NEW | `Ø_crack` is a **user input** (default 12). The spec previously listed only `s_max`, leaving crack bars with no placeable diameter | #5 |
| A23 | NEW | Crack bars run the full span and embed **straight into the support, no hook** — they are crack-control steel, not flexural tension, so §2's anchorage machinery does not apply | #5 |
| A24 | CLARIFY | Horizontal position uses the §4 rule: `Cover + Ø_stirrup + ½Ø_crack` from each side face. Matches Figure 4 | #5 |
| A25 | CLARIFY | Crack bars are **exempt from spacing validation** — one bar per side per layer leaves no horizontal question, and vertical spacing is even by construction via `actual_spacing` | #5 |
| A26 | CLARIFY | For a multi-layer beam, `offset_top` / `offset_btm` in `H_avail` are measured to the **innermost** layer centrelines, so `H_avail` is the true unreinforced web height. §5.1 never addressed the multi-layer case | #4 |

## §6 Bar Spacing Rules

| # | Type | Amendment | Ticket |
|---|---|---|---|
| A27 | NEW | Violation behaviour follows the user's §6.3 choice: **Option 1** (single wide row) → **hard stop** reporting governing vs achieved spacing; **Option 2** (stacked with spacer) → **auto-stack** until satisfied, capped at 5 layers, then report layer count and per-layer spacing | #6 |
| A28 | NEW | If 5 layers cannot satisfy `min_spacing`, that is a **hard error** in both options. The cap is absolute | #6 |
| A29 | CLARIFY | The optional override acts as a **floor**: `governing = max(formula_result, user_override)`. It can only increase spacing, never reduce it below the computed minimum | #6 |

## §7 Stirrup Type

| # | Type | Amendment | Ticket |
|---|---|---|---|
| A30 | NEW | **Stirrup leg dimensions** (closes the un-deferred §9 item #3): outer rectangle `(b − 2·Cover) × (h − 2·Cover)`; **centreline** rectangle `(b − 2·Cover − Ø_stirrup) × (h − 2·Cover − Ø_stirrup)`, which is what the API receives. Derived from §1's outer-face cover definition and independently corroborated by both §6.3's `spacer_length` and §4's offset formula | #10 |
| A31 | **CHANGE** | Stirrup type input narrows from **(1–4)** to **(1, 2, 4)** for v1. **Type 3 (nested double perimeter) is parked** — its inner loop's dimensions, diameter and corner rule are undefined in the spec, and it requires two separate `Rebar` elements rather than one | #7 |
| A32 | CLARIFY | Type 2 is type 1 with the **same** 4-curve loop and **same** winding, cyclically rotated so a different corner becomes `curves[0]`. One parameterized code path via a starting-corner index — *not* a reversed loop, which would flip which face the hook swings toward | #7 |
| A33 | NEW | Stirrup hook angle is fixed at **180° semicircular** — the ECP/BS detail for plain round mild steel, which needs a full hook for lack of bond. Hook *length* stays derived from bar diameter via `RebarHookType`'s multiplier and is not a user input. **Supersedes** the §7 research's 135° ACI recommendation, which assumed deformed bar | #13 |
| A34 | NEW | Stirrups are placed with the **mild 24/35** bar type; every other bar uses **high tensile 36/52** | #13 |

## §8 Inputs vs Outputs

| # | Type | Amendment | Ticket |
|---|---|---|---|
| A35 | NEW | Input table gains: `Ø_spacer`, `Ø_crack`, **two `RebarBarType` selections** (mild + high tensile), and per-end `Column width` (pre-filled, editable). Geometry (`L`, `b`, `h`, `cover`) is pre-filled from the picked beam and editable | #4, #5, #13, #9 |
| A36 | NEW | v1 defaults: `cover` 25, `Ø_stirrup` 10, dense 150, normal 200, `LD_top` 60Ø, `LD_btm` 55Ø, `Ø_spacer` 16, `Ø_crack` 12, `s_max` 200, stirrup type 1, layer option 1, `Dagg` **blank** (so §6.2's 50 mm fallback governs until set) | #9 |
| A37 | NEW | Output reporting: full breakdown to the pyRevit **output window** (per-layer spacing and layer count for both faces per §6.3, zone stirrup counts and achieved spacings, computed `a`/`b`, crack layer count and `actual_spacing`), plus a **summary dialog** with headline numbers and warnings. No file export in v1 | #9 |

## §9 Open Items — updated status

| # | Type | Amendment | Ticket |
|---|---|---|---|
| A38 | CHANGE | Item **#1** (bottom bar anchorage bend geometry) → **CLOSED**. Formula confirmed unchanged, rationale recorded per A7 | #2 |
| A39 | — | Item **#2** (multi-span) → **still deferred**. Single-span remains the hard scope boundary. The tool should warn on, or refuse, a beam in a continuous run rather than silently detailing it as simply supported | #10 |
| A40 | CHANGE | Item **#3** (stirrup leg formulas) → **CLOSED** per A30, **except** type 3's inner loop, which remains open and is why A31 parks type 3 | #10, #7 |
| A41 | CHANGE | A39's "warn on, **or** refuse" latitude → **CLOSED in favour of REFUSE**, decided by the project owner 2026-09-08. A beam detected as part of a continuous run is refused outright, not warned, in every pushbutton — consistent with type 3's outright rejection (A31), and because the guard exists to prevent plausible-looking detailing for an unmodelled configuration | #22 |
| A42 | CHANGE | **A35 superseded**: one `RebarBarType` selection per bar **ROLE** (top main, bottom main, stirrup, spacer, crack), not two per grade. In Revit a `RebarBarType` **is** a diameter, so two selections cannot express different top and bottom bar diameters. Bar diameter is therefore **derived from the selected type**, and the free-text diameter inputs are removed. Grade stops being a selection axis: A34's assignment becomes the **label** on each role's picker and a line in the report, not something inferred from the type. Decided by the project owner 2026-09-09 | #27 |
| A43 | CHANGE | **§6.4's clear-spacing datum corrected.** As written, `clear = (b − 2×offset − n×Ø_bar)/(n − 1)` with "offset per §4" subtracts **n + 1** bar diameters from a face holding **n** bars, because §4's offset is measured to the bar's own centreline and already contains ½Ø_bar. The formula becomes `clear = (b − 2×Cover − 2×Ø_stirrup − n×Ø_bar)/(n − 1)`, i.e. the **clear width inside the stirrup legs** — the same datum §6.3's `spacer_length` uses — which is arithmetically identical to keeping §4's offset and subtracting `(n − 1)×Ø_bar`. A datum correction, not a change of rule: the literal text under-reports achieved spacing by `Ø_bar/(n − 1)`, which hard-stops compliant sections under Option 1 and auto-stacks unnecessarily under Option 2. `n = 1` (a single bar in a face) has no horizontal spacing question and skips the check rather than dividing by zero. Decided by the project owner 2026-09-09 | #28 |
| A44 | **CHANGE** | **A27's Option 2 auto-stacking superseded: the tool never re-splits the engineer's bars.** The engineer states the **bar count per layer** and the **number of layers** per face (the input model `Place Main Bars` already uses), and the tool **validates every layer independently** against the governing minimum. On violation it **refuses in both §6.3 options** — Option 1 because a single wide row has nowhere to go (A27, unchanged), Option 2 because redistributing bars the engineer specified would silently detail something other than what was asked for. The refusal reports, per face and per layer, the governing minimum, the achieved clear spacing, and the **smallest layer count that would satisfy the minimum** for that total, so the engineer can re-enter it (§6.3's reporting duty). A28's 5-layer cap stays absolute: if no arrangement within 5 layers satisfies the minimum, that is a hard error and the report says so rather than naming an unreachable layer count. Rev 2 never defined how a total would be split across auto-stacked layers, and this closes that gap by removing the need for a split rule. Decided by the project owner 2026-09-09 | #29 |
| A45 | **CHANGE** | **§7.3's stirrup hook angle: 180° → 135°.** Verified against a live host (Revit 2024, `RevitAPI 24.3.40.0`): every **Stirrup/Tie**-family hook (`REBAR_HOOK_STYLE = 1`) in a stock library ships at 90° or 135°, and every 180° hook ships as **Standard** family (`= 0`), which `RebarStyle.StirrupTie` **rejects** with `InternalException` — so A33 as written could not be satisfied by any stock hook type. 135° is also what the project owner reports as normal practice. **The guard is two-part and both halves are required**: `REBAR_HOOK_STYLE` must be **1** (the half that actually prevents the opaque `InternalException`, needed regardless of angle) **and** the angle must be 135° ± 1°. Angle-only checking would pass a `Standard - 180 deg.` hook and then fail as "An internal error has occurred", on a hook whose angle was correct. Note the engineering tension recorded in #32: 135° is the **deformed**-bar convention, while A34 assigns stirrups plain round mild St 24/35, for which a semicircular hook is the classical requirement — A34 is being revisited separately and is NOT changed by this amendment. Decided by the project owner 2026-09-09 and **REAFFIRMED the same day, on the practice argument alone**: a library import then gave the model 48 hook types **including `Stirrup/Tie - 180 deg.` at family 1**, and a live test confirmed such a hook creates successfully and reads back 180° — so 180° *was* achievable after all and the availability half of this rationale has expired. Told that, the project owner kept 135° because it is what stirrups normally use, which is now the whole basis of the amendment. The two-part guard is unaffected either way: `REBAR_HOOK_STYLE = 1` is required whatever angle is chosen | #31, #25 |
| A46 | **CHANGE** | **The four pushbuttons are consolidated into ONE command driven by a single form.** Rev 2 §8 specified one dialog collecting every parameter, but the tool was built as four separate pushbuttons each with its own prompts (S1/S3/S5/S6), which is what the project owner saw on first load and rejected as unlike the CADS-style UI he expects. The single form now also carries **per-element placement checkboxes** — top mains, bottom mains, stirrups, crack bars — so partial re-runs survive the consolidation, and **all selected reinforcement is placed in ONE transaction**. This is not only ergonomics: the four-button split is the **direct cause of two logged defects**, and one form removes both by construction rather than by adding a guard. (1) Bar-type selections were not shared between buttons, so `Place Main Bars` could lay out against a Ø10 stirrup while `Place Stirrups` placed Ø8 — undetectable within any single run, producing bars in quietly wrong positions. (2) `Place Crack Bars` re-asked for the main-bar layer counts and read nothing back from the placed bars, so §5's `H_avail` could silently disagree with the as-built beam, with no clash and no warning. Four commands also meant four transactions and four undo steps, leaving a half-detailed beam if the engineer stopped midway; one transaction is all-or-nothing. **Consequences:** the crack-bar checkbox follows §8's existing rule and is enabled only when `h > 700`; **`Place Bottom Bar` is deleted** — it was the S1 tracer bullet placing a single bottom bar, superseded by `Place Main Bars` and then by the bottom-mains checkbox, and it had no business in the engineer's ribbon; and the **`Anchorage` panel name is retired**, having named a spec section (§2) rather than anything the engineer wants. A35's dialog-first-then-pick ordering is unaffected. Decided by the project owner 2026-09-09 | #21 |
| A47 | **CHANGE** | **A46's per-element checkboxes superseded: FIVE TABS, and the Review tab DERIVES what will be placed.** A46 settled that the four pushbuttons collapse into one command in one transaction, with per-element checkboxes choosing what to place. On first seeing the ribbon after v0.1.0 was verified, the project owner asked instead for one CADS-Rebar-style window whose sub-sections are switched by clicking, plus a sketch with a defined legend and symbol set so a new user can learn the tool without reading the spec. A46's substance survives intact -- one command, one transaction, all-or-nothing, partial runs still possible; only the mechanism changes. Decided across issues #33-#42: **(1) Tabs** are `Beam & Materials` (pick, geometry, the four covers, support detection, one `RebarBarType` per role, the stirrup hook), `Main bars` (counts, layers, `LD` multipliers, layer option, `Dagg`, spacing override, `Ospacer`), `Stirrups` (dense/normal spacing, closure type), `Crack bars` (`Ocrack`, `s_max`, enabled only when `h > 700`), and `Review`. Bar types on a SHARED tab is the load-bearing part: the stirrup diameter feeding the main-bar layer offsets and corner-bar inset (§4, §6.1) is then the same element as the stirrup placed, making A46's motivating mismatch structurally impossible rather than merely guarded. **(2) No toggles** -- Review lists what will be placed, derived from which tabs were filled in, and must STATE that derivation per section in words, since a derived decision the engineer cannot see is worse than a checkbox they forgot to tick. §8.1's defaults mean "filled in" needs an explicit rule, which Phase 4 must define. **(3) The sketch** shows BOTH the cross-section and the longitudinal elevation, following the active tab -- section while editing main or crack bars, elevation while editing stirrups or anchorage -- because nearly every input appears in exactly one of the two, and a section alone cannot define `a`, `b`, `LD` or the three-zone stirrup distribution. **(4) Symbols** are ECP drawing conventions on the sketch, with the legend MAPPING each to the spec symbol used in the fields and messages; that mapping table is the deliverable for a new user. Where generic ECP practice and the owner's office convention differ, the office convention wins. **(5) Field labels** are plain English with the spec symbol in brackets -- "Bottom bar development length (LD_btm)" -- and this BINDS the refusal and report text too, since a form that says "development length" while its own error says `LD_btm` still confuses the reader it was written for. **(6) Validation** is inline per field, a banner plus header badge on the owning tab for cross-field refusals, modal only for blocking refusals that end the run, and the full §8.2/A37 report on Review with a copy still written to the pyRevit output window -- the Review tab is where it is read, the output window where it is kept. Consequence for the code: `GuardMessage` carries `condition`, `spec_section` and `message` but nothing distinguishing a BLOCKING refusal from a warning -- today that is implicit in whether the call site follows it with `script.exit()`, and Phase 4 must make it explicit. Decided by the project owner 2026-09-09 | #33, #34, #35, #36, #37, #38, #39 |
| A48 | **ADD** | **The sketch is a LIVE preview driven entirely from `rft.core`, and the renderer contains no detailing arithmetic.** A47 established that the UI carries a sketch showing both the cross-section and the longitudinal elevation; this settles that it redraws from the current inputs rather than being a fixed reference diagram, and fixes the constraint that makes that safe. Decided on evidence (#41, #40), not preference: `rft.core` is pure, Revit-free and already in millimetres, and it turns out to compute nearly every dimension a drawing needs -- because the placement code needed those same numbers first -- so the renderer is a coordinate transform rather than a second implementation of the detailing rules. **The deciding factor is verification**: `spacing.validate_layer_spacing` returns the achieved clear spacing alongside a `passes` flag and `anchorage.placed_clearance_mm` returns `ClearanceResult(achieved_mm, required_mm, ok)`, so the drawing can dimension those values AND colour them by compliance -- making the sketch the place a violation is seen BEFORE a transaction is committed. A static diagram cannot show the engineer's own beam and so cannot verify anything. **BINDING: the renderer contains no detailing arithmetic.** Every dimension comes from a `rft.core` function; a number the drawing needs and the core does not expose is ADDED TO THE CORE, never computed in the renderer. That is the entire safety property -- the moment the renderer does its own maths it can disagree with what is placed, and the engineer will believe the drawing. This project has already been misled three times by a TEST FAKE modelling something the real API does not do (`RebarFaceType` in #23, `.Name` in rc3, `GetBoundingBox` in rc4); a renderer with its own arithmetic is the same hazard aimed at the engineer instead of the developer. **Two core additions follow, both refactors with no behaviour change:** `stirrups.outer_leg_dimensions_mm(b, h, cover)`, since A30 defines the outer rectangle but only the centreline rectangle is exposed; and `layout.main_layer_v_positions_mm(...)`, currently inline in `Place Main Bars` while the crack-bar equivalent (`crack_layer_v_positions_mm`) sits properly in the core -- the pushbutton must call the new function too, so one implementation exists rather than two. That asymmetry is the single most likely place for drawing and placement to drift apart. **Two elements are SCHEMATIC and must be labelled as such on the drawing, because REVIT owns them, not this codebase:** individual stirrup positions (`SetLayoutAsMaximumSpacing` distributes the array, so the core knows the count and achieved spacing but never enumerates stations -- draw true zone bands with evenly spaced ticks annotated `n @ s mm` from `StirrupCount`, and dimension no individual stirrup), and hook fillet geometry (the `RebarBarType`'s bend radius -- draw the correct 135-degree angle and leg length, not the arc). The governing principle is EXACT WHERE WE OWN THE TRUTH, SCHEMATIC WHERE REVIT DOES, and the drawing says which is which. Redraw smoothness (per keystroke versus debounced) is left to the #42 prototype as a feel judgement. Decided by the project owner 2026-09-09 | #43, #41, #40 |
| A49 | **CHANGE** | **A47's ECP-sourced symbol set superseded: the sketch notation is AUTHORED IN THIS REPO.** A47 settled that the sketch would use ECP drawing symbols with the legend mapping each to the spec symbol, which left the work blocked on an input only the project owner could supply -- a sample detail drawing or a marked-up sketch. On 2026-09-09 he instead asked for the notation to be generated rather than sourced, so it is defined here: `docs/ui/sketch-notation.svg` is the definition, carrying the cross-section (true scale, on the real 300x900 verification beam, with per-face cover, the stirrup on its centreline, two stacked bottom layers and their spacer, and four crack layers), the longitudinal elevation (end anchorage `a`/`b`, both bend directions, the three stirrup zones annotated `n @ s`, and a 135-degree Stirrup/Tie hook detail), and a twelve-row LEGEND mapping what is drawn to what it means to the tool's symbol to the spec section -- that mapping being the artefact a new user actually needs, and what A47's plain-English field labels point at. **Authored SVG rather than a generated image, deliberately**: an AI-generated raster of a rebar detail would look plausible and be dimensionally wrong, which for a drawing whose whole purpose is to teach correct notation is worse than having none. SVG is exact, diffable, and maps 1:1 onto the WPF `Canvas` primitives the live renderer uses, so the drawing DOUBLES AS THE RENDERER'S SPECIFICATION instead of being a picture to interpret -- it even shares the renderer's coordinate convention, `translate(cx,cy) scale(s,-s)` with the origin at the section centroid and `v` positive upward. Per A48 the drawing states its own limits on its face: individual stirrup positions and hook bend arcs are marked SCHEMATIC because Revit owns them, since implying precision it does not have would be the same class of failure as a test fake modelling an API that does not exist. **This notation is a starting point defined for clarity and is NOT a claim of ECP compliance**; adjusting it to the owner's own office conventions remains open and is cheap, every symbol being one SVG element. Decided by the project owner 2026-09-09 | #37, #33 |

## Proposed new §10 — Implementation Constraints (Revit API)

Optional but recommended, so the API decisions live alongside the geometry
rules they serve. Full detail in `docs/research/revit-api-strategy.md` and
`docs/research/stirrup-types.md`.

- All detailing math in **millimetres**; convert only at the API boundary
  via `UnitUtils.ConvertToInternalUnits(v, UnitTypeId.Millimeters)`.
- Longitudinal bars: `Rebar.CreateFromCurves`, `RebarStyle.Standard`, the
  §2 bend as a **second curve segment** with `startHook`/`endHook` = null.
- Stirrups: `RebarStyle.StirrupTie`, closed 4-curve loop (or open for
  type 4), mild bar type, 180° hooks.
- Stirrup distribution: **one rebar set per zone** via
  `SetLayoutAsMaximumSpacing` on `RebarShapeDrivenAccessor`. Never
  `SetLayoutAsNumberWithSpacing`, which takes no `arrayLength`.
- Host validation order: `RebarHostData.GetRebarHostData(beam)` non-null →
  `IsValidHost()` → explicitly read back per-face `RebarCoverType`, because
  an undefined face cover **silently falls back to a document default**.
- **One `Transaction` per beam** wrapping all bars and stirrup sets, with
  `RollBack()` on any exception so a half-placed cage never commits.

---

## Residual questions — status as of 2026-09-08

These were deliberately **not** guessed, per `CONTEXT.md`. Four were resolved
with the owner during Phase 4; two remain open.

| # | Question | Status | Origin |
|---|---|---|---|
| R1 | Should the tool warn when `Ø_spacer < max(25, Ø_bar, 1.33 × D_agg)`? A21 leaves the vertical direction unchecked | **RESOLVED** — emit a **non-blocking warning** and place anyway, naming the spacer diameter and the horizontal minimum it falls below. Preserves A21's user control while making an under-spaced layer visible | #4 |
| R2 | **Crack bar embedment depth.** A23 fixes "straight, no hook" but not a length | **RESOLVED** — `Support width − Cover`, mirroring §2's straight run `a`. No new input | #5 |
| R3 | **Unsupported-end anchorage length.** A12 says a straight bar of `LD`, but with no support there is no region for it | **RESOLVED** — run to `beam end − cover` and **warn that `LD` was not achieved**, stating both required and achieved lengths | #11 |
| R4 | **Zone-boundary duplicate stirrup.** Can zone 1's last bar and zone 2's first bar coincide at `L/3`? Depends on `includeFirstBar` / `includeLastBar` | **OPEN** — cannot be closed without a live host. Mitigation: S5 implements an explicit de-duplication guard at each zone boundary, and the mock-object write-up must demonstrate it | #3, #8 |
| R5 | **Non-perpendicular wall support**: thickness or swept intersection length? | **RESOLVED** — **wall thickness**, measured perpendicular to the wall face. Conservative: understates embedment for oblique beams, giving a shorter `a` and longer bend | #11 |
| R6 | **Type 3 inner loop** dimensions, diameter and corner rule — the gap that parks type 3 | **OPEN** — permanently for v1, since type 3 is parked (A31) | #7, #10 |

**R4 is the only open question affecting shippable v1 scope.** It is mitigated
by a guard rather than answered, and that mitigation is what the verification
write-up must cover.

## Unverified against a live host

No live Revit host was available during this cycle, so per `CONTEXT.md`
every API-touching decision above rests on documentation. Requiring
empirical confirmation: exact default bend radii and the fillet/trim
magnitude; real-world `IsValidHost()` behaviour; undefined-cover fallback
behaviour; zone-set boundary interaction (R4); whether
`SetLayoutAsMaximumSpacing` behaves identically for open vs closed shapes;
live-template stirrup shape names; and whether `StirrupTie`'s restricted
hook set actually permits 180°.

**The last item is load-bearing for A33** — if `StirrupTie` disallows 180°
hooks, the mild-steel hook decision must be revisited.
