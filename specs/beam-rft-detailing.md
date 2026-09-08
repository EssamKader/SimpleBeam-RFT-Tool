# Beam RFT Detailing Tool — User Stories

Phase 4 output of the AI-KaderSkill cycle. Converts the decisions resolved in
the Wayfinder cycle (root issue
[#1](https://github.com/EssamKader/rft-beam-detailing/issues/1)) into
implementable user stories.

**Source of truth:** `00.Technical Material/beam_rebar_detailing_spec_v2.docx`
(revision 2). Amendment provenance: [`docs/spec-amendments.md`](../docs/spec-amendments.md).
Standing rules: [`CONTEXT.md`](../CONTEXT.md).

Throughout, **"the engineer"** means the BIM/structural engineer running the
tool inside Revit.

---

## Architecture constraint (applies to every story)

Two decisions govern how all of these are built:

**1. Revit-free pure core.** All detailing mathematics lives in modules that
import nothing from the Revit API, take plain numbers, and return plain
numbers and coordinate tuples in **millimetres**. Only a thin adapter layer
translates those results into Revit API calls, converting units at the
boundary via `UnitUtils.ConvertToInternalUnits(v, UnitTypeId.Millimeters)`.

*Why this matters here:* nothing in the development environment can execute
Revit API code. A Revit-free core is the only part that can be genuinely
executed and unit-tested, which turns the mock-object verification
`CONTEXT.md` demands from a prose write-up into a real, runnable test suite.

**2. Tracer bullet first.** Story **S1** places one bar end-to-end through
every layer of the pipeline before any subsystem is built out, so
integration risk and API surprises surface immediately rather than at the end.

### Definition of done (every story)

- Detailing logic sits in the Revit-free core with unit tests that run under
  plain CPython.
- Any Revit-API-dependent behaviour has a mock-object verification write-up
  (per `CONTEXT.md`), since it cannot be executed here.
- Every implemented rule cites its rev 2 spec section.
- All Revit mutation is inside a single `Transaction` per beam that rolls
  back on any exception.
- No residual question (R1–R6) is answered by assumption. If a story hits
  one, it stops and asks.

---

## S1 — Tracer bullet: one bar, end to end

> **As** the engineer, **I want** to select a supported beam and have the tool
> place a single correctly-anchored bottom main bar, **so that** the entire
> pipeline is proven working in Revit before any further detailing logic is
> built on top of it.

Deliberately the thinnest possible vertical slice: one bar, one face, both
ends, no layers, no stirrups, no crack bars, no UI beyond a minimal prompt.

**Acceptance criteria**

- Engineer picks one structural framing element; the tool validates it can
  host rebar — `RebarHostData.GetRebarHostData()` non-null, then
  `IsValidHost()` — and reports an actionable error naming
  `StructuralUsage` when invalid (rev 2 §10).
- Per-face cover is read back explicitly rather than trusted, because an
  undefined face cover silently falls back to a document default (rev 2 §10).
- `b`, `h` and the c/c span `L` are read from the beam (rev 2 §1, A6).
- A supporting column is detected at each end and its width and own cover
  read (rev 2 §2.4). **S1 assumes a column is found at both ends** —
  other support types and the no-support path belong to S2.
- Anchorage computed in the pure core per rev 2 §2.2 and §2.3:
  `a_btm = Support width − Cover`, `b_btm = LD_btm − a_btm`, then
  `a = min(a_formula, LD − 200)` and `b = max(200, LD − a)`.
- Bar placed with `Rebar.CreateFromCurves`, `RebarStyle.Standard`, as a
  **2-segment curve list** (straight run `a`, then bent leg `b`) with
  `startHook`/`endHook` = `null` — the L-shape *is* the anchorage
  (rev 2 §2.3 note A13). Bottom bar bends **upward**.
- `a` and `b` are fed **raw**, since they are theoretical-corner dimensions
  (rev 2 §1, A5). No bend-radius compensation is applied.
- Placement wrapped in one `Transaction` with `RollBack()` on exception, so a
  failed run leaves no partial bar.
- Computed `a`, `b` and `LD` are echoed to the pyRevit output window.
- Unit tests cover the anchorage core, including the cap firing
  (`LD` short relative to support width) and the 200 mm clamp firing.

**Dependencies:** none — this is the foundation.

---

## S2 — Full end anchorage (§2)

> **As** the engineer, **I want** every top and bottom bar anchored correctly
> at both beam ends regardless of what supports the beam, **so that** the
> anchorage detail is complete and does not silently fail on walls, girders or
> unsupported ends.

**Acceptance criteria**

- Top bars: `a_t = Support width − Cover − Ø_BTM`, bending **downward**;
  bottom bars as S1, bending upward (rev 2 §2.1, §2.2).
- The `Ø_BTM` term in `a_t` is preserved and commented as deliberate clash
  avoidance — it yields `a_btm − a_t = Ø_BTM` centreline separation against a
  required `(Ø_TOP + Ø_BTM)/2` (rev 2 §2.2 note A7). A unit test asserts this
  clearance holds.
- Independent `LD_top` (default 60 × Ø) and `LD_btm` (default 55 × Ø)
  multipliers, each shared across both ends (rev 2 §2.1, A10).
- Support detection covers **any structural support** — column, wall or
  girder — using its width or thickness (rev 2 §2.4, A9). Detected width is
  user-overridable.
- At an end with **no detectable support**: a straight bar, no hook (rev 2
  §2.5, A12). The §2.3 mandatory-hook rule must **not** fire there.
- A free/cantilever end takes the unsupported path and **warns** that it is
  not a supported v1 configuration (rev 2 §2.5, A14).

**R3 — RESOLVED 2026-09-08.** At an unsupported end the bar runs straight to
`beam end − cover` and the tool **warns that `LD` was not achieved**. Always
geometrically possible, and consistent with §2.5 already treating such an end
as an unsupported v1 configuration that warns. The warning must state both the
required `LD` and the achieved length.

**R5 — RESOLVED 2026-09-08.** For a wall support, `Support width` is the
**wall thickness** measured perpendicular to the wall face, regardless of the
beam's incidence angle. Deliberately conservative: it understates available
embedment for an oblique beam, yielding a shorter `a` and a longer bend `b`,
which errs safe.

**Dependencies:** S1.

---

## S3 — Cross-section bar layout (§4, §6.1)

> **As** the engineer, **I want** main bars positioned correctly across the
> section including stacked layers, **so that** bar coordinates respect cover,
> the stirrup cage and the spacer convention without my having to compute
> offsets by hand.

**Acceptance criteria**

- First-bar offset `offset₁ = Cover + Ø_stirrup + ½Ø_bar`, applied
  independently to top (`Ø_TOP`) and bottom (`Ø_BTM`) faces (rev 2 §4).
- Corner-bar rule: a bar at each stirrup corner, the remainder distributed at
  equal spacing between them (rev 2 §6.1).
- Multi-layer accumulation `offsetₙ = offset₁ + (n − 1) × (Ø_bar + Ø_spacer)`
  for n = 1..5, one diameter per face (rev 2 §4.1, A20).
- `Ø_spacer` is a user input defaulting to 16 and represents the **clear**
  vertical gap (rev 2 §4.1, A19).
- Spacer bars placed at `spacer_length = b − 2×Cover − 2×Ø_stirrup`
  (rev 2 §6.3).
- Unit tests verify offsets for single-layer and for 2–5 stacked layers, with
  differing top and bottom diameters.

**R1 — RESOLVED 2026-09-08.** Emit a **non-blocking warning** when
`Ø_spacer < max(25, Ø_bar, 1.33 × D_agg)`, and place the bars anyway. This
preserves the user control chosen in A21 while making an under-spaced layer
visible rather than silent. The warning names the spacer diameter and the
horizontal minimum it falls below.

**Dependencies:** S1.

---

## S4 — Spacing validation and layer decisions (§6)

> **As** the engineer, **I want** the tool to tell me when my requested bar
> count cannot achieve minimum clear spacing — and to respect the arrangement
> option I chose — **so that** I never unknowingly detail a non-compliant
> section.

**Acceptance criteria**

- `min_spacing = max(25, Ø_bar, 1.33 × D_agg)` when `D_agg` is given, else the
  50 mm fallback; `D_agg` always governs over the fallback (rev 2 §6.2).
- Optional override acts as a **floor**:
  `governing = max(formula_result, override)` — it can only increase spacing
  (rev 2 §6.2, A29).
- Achieved spacing `clear = (b − 2×offset − n×Ø_bar) / (n − 1)` tested against
  the governing minimum (rev 2 §6.4).
- On violation, behaviour follows the engineer's §6.3 choice (A27):
  **Option 1** → hard stop reporting governing vs achieved spacing, nothing
  placed; **Option 2** → auto-stack to further layers until satisfied, capped
  at 5.
- 5 layers exhausted without satisfying the minimum is a **hard error** in
  both options (rev 2 §6.4, A28).
- `min_spacing` is applied **horizontally only** (rev 2 §4.1, A21).
- Per-face results reported: resulting spacing per layer and number of layers
  used, top and bottom independently (rev 2 §6.3).
- Unit tests cover: comfortable fit, exact-minimum boundary, Option 1
  violation, Option 2 auto-stacking, and the 5-layer hard error.

**Dependencies:** S3.

---

## S5 — Stirrups: geometry, closure types and distribution (§3, §7)

> **As** the engineer, **I want** stirrups of my chosen closure type
> distributed across the three span zones, **so that** the beam gets a
> complete cage with dense spacing at the supports without my placing sets by
> hand.

The largest story. Kept whole because leg geometry, closure type and
distribution are meaningless separately — a distributed set of undimensioned
stirrups is not a deliverable.

**Acceptance criteria**

- Leg dimensions: centreline rectangle
  `(b − 2·Cover − Ø_stirrup) × (h − 2·Cover − Ø_stirrup)` passed to the API
  (rev 2 §7.1, A30).
- Closure types **1, 2 and 4** supported; **type 3 is rejected** with a
  message explaining it is parked (rev 2 §7.2, A31).
- Type 2 implemented as type 1 with the **same** loop and winding, cyclically
  rotated so a different corner is `curves[0]` — one parameterized code path
  taking a starting-corner index, **not** a reversed loop (rev 2 §7.2, A32).
- Type 4 as an open U with hooks at both free top ends (rev 2 §7.2).
- Hook angle fixed at **180° semicircular**; hook length derived from bar
  diameter via the hook type's multiplier, not a user input (rev 2 §7.3, A33).
- `RebarStyle.StirrupTie` with the **mild St 24/35** bar type (rev 2 §7.3,
  §1.1).
- Three zones on the c/c span, arrays **clipped** to the clear region:
  zone 1 `[face_A + 50, L/3]`, zone 2 `[L/3, 2L/3]`,
  zone 3 `[2L/3, face_B − 50]` — mirrored, first and last stirrup 50 mm from
  a support face (rev 2 §3.1, A15).
- One rebar set per zone via `SetLayoutAsMaximumSpacing` on
  `RebarShapeDrivenAccessor`; dense/normal values treated as **maximum**
  spacings. `SetLayoutAsNumberWithSpacing` must **not** be used (rev 2 §3.2,
  A18, §10).
- Degenerate-case guard: if `face_A + 50 ≥ L/3`, error clearly rather than
  pass a non-positive array length; same test at the far end (rev 2 §3.1,
  A17).
- Reported per zone: stirrup count and achieved spacing.
- Unit tests cover zone clipping arithmetic, the degenerate guard firing, and
  the starting-corner rotation producing four distinct corners.

**Residual question**

- **R4** — can zone 1's last bar and zone 2's first bar coincide at `L/3` and
  produce a **duplicate stirrup**? Depends on the include-first/include-last
  flags. Rev 2 §10 names this the prime candidate for mock-object
  verification, since it cannot be observed without a live host.

**Dependencies:** S1. (Independent of S2–S4 — could run in parallel.)

---

## S6 — Crack / skin reinforcement (§5)

> **As** the engineer, **I want** skin bars generated automatically on deep
> beams, **so that** crack-control steel is placed and evenly distributed
> without my computing layer counts.

**Acceptance criteria**

- Fires **only** when `h > 700`; `h ≤ 700` yields `n_crack_layers = 0` and no
  bars (rev 2 §5).
- `H_avail = h − offset_top − offset_btm`, measured to the **innermost** main
  bar layer centrelines in the multi-layer case (rev 2 §5.1, A26).
- `n_gaps = ceil(H_avail / s_max)`, `n_crack_layers = n_gaps − 1`,
  `actual_spacing = H_avail / n_gaps` — even, no odd leftover gap
  (rev 2 §5.2).
- One bar per side (left/right face) per layer, at each internal division
  point (rev 2 §5.2).
- Horizontal position `Cover + Ø_stirrup + ½Ø_crack` from each side face
  (rev 2 §5.3, A24).
- `Ø_crack` is a user input, default 12 (rev 2 §5.3, A22).
- Bars run the full span, embedding **straight into the support with no
  hook** — §2's anchorage machinery must not be applied (rev 2 §5.3, A23).
- Crack bars are **exempt** from spacing validation (rev 2 §5.3, A25).
- High tensile **St 36/52** bar type (rev 2 §1.1).
- Unit tests cover: `h = 700` (no fire), `h = 701` (fires), exact-multiple and
  non-multiple `H_avail/s_max`, and the multi-layer `H_avail` datum.

**R2 — RESOLVED 2026-09-08.** Crack bar embedment depth is
`Support width − Cover`, mirroring §2's straight run `a` exactly — so a crack
bar crosses the support the same distance a main bar's straight leg does, with
no bend. Reuses existing inputs; no new field.

**Dependencies:** S3 (needs `offset_top`/`offset_btm`), S2 (support width).

---

## S7 — Steel grades and bar type resolution (§1.1)

> **As** the engineer, **I want** to nominate the mild and high-tensile bar
> types once, **so that** every bar is placed in the correct grade without my
> checking each one.

**Acceptance criteria**

- Two explicit selections from the document's available `RebarBarType`s: one
  mild (**St 24/35**), one high tensile (**St 36/52**) (rev 2 §1.1, A35).
- Assignment: stirrups → mild; top bars, bottom bars, crack bars **and
  spacer bars** → high tensile (rev 2 §1.1, A34).
- Both types coexist in one beam, each carrying its own bend radius
  (rev 2 §1.1).
- The `LD` multiplier fields are **labelled with the grade they assume**
  (St 36/52), so a grade change prompts revisiting them (rev 2 §2.1, A10).
- No bar is placed with a defaulted or guessed bar type; a missing selection
  is a blocking validation error.

**Dependencies:** S1 (which may use a provisional single bar type until S7
lands).

---

## S8 — Input form, persistence and reporting (§8)

> **As** the engineer, **I want** one dialog collecting every parameter with
> sensible defaults that persist across beams, **so that** detailing a series
> of beams does not mean retyping fifteen fields each time.

**Acceptance criteria**

- A single WPF/XAML form with cross-field validation (rev 2 §8.2).
- **Dialog opens first, then the engineer picks the beam.** Geometry and
  support fields stay disabled until a beam is picked; re-picking
  re-populates them and re-runs support detection (rev 2 §8.2, A35).
- Geometry (`L`, `b`, `h`, `cover`) and per-end support width pre-fill from
  the model and remain **editable** (rev 2 §8, A35).
- Crack bar fields (`Ø_crack`, `s_max`) active only when `h > 700`
  (rev 2 §8).
- Defaults exactly as rev 2 §8.1: cover 25, `Ø_stirrup` 10, dense 150,
  normal 200, `LD_top` 60Ø, `LD_btm` 55Ø, `Ø_spacer` 16, `Ø_crack` 12,
  `s_max` 200, stirrup type 1, layer option 1, `D_agg` **blank**.
- Parameters persist **per project** via `script.store_data`; a different
  project starts from defaults (rev 2 §8.2).
- Full report to the pyRevit output window: per-layer spacing and layer count
  for both faces, zone stirrup counts and achieved spacings, computed `a`/`b`
  legs, crack layer count and `actual_spacing` (rev 2 §8.2, A37).
- Summary dialog with headline numbers plus any warnings. **No file export in
  v1** (rev 2 §8.2).

**Dependencies:** S2–S7 (the input list is only meaningful once the
subsystems consuming it exist). Buildable in parallel against stubs.

---

## S9 — Out-of-scope configuration guards

> **As** the engineer, **I want** the tool to refuse or clearly warn on
> configurations it was not designed for, **so that** I am never handed
> plausible-looking but unsupported detailing.

**Acceptance criteria**

- A beam that is part of a **continuous run** is warned about or refused, not
  silently detailed as simply supported (rev 2 §9 item 2, A39).
- Cantilever/free ends warn as an unsupported v1 configuration (rev 2 §2.5,
  A14).
- Stirrup type 3 is rejected with an explanation (rev 2 §7.2, A31).
- Every rejection names the specific unsupported condition and the spec
  section, never a generic failure.

**Dependencies:** S2, S5.

---

## Dependency graph

```
S1 (tracer)
 ├─> S2 (anchorage) ────┬─> S6 (crack bars)
 ├─> S3 (layout) ───────┴─> S4 (spacing)
 ├─> S5 (stirrups)
 └─> S7 (grades)
            S2,S5 ─────────> S9 (guards)
        S2..S7 ────────────> S8 (UI)
```

S2, S3, S5 and S7 are mutually independent once S1 lands and can be worked in
any order or in parallel.

## Explicitly out of scope for v1

- **Multi-span / continuous beams** — spec §9 item 2, still deferred. Hard
  boundary.
- **Stirrup type 3** (nested double perimeter) — parked; inner loop undefined
  (R6).
- **Cantilever ends** as a supported configuration.
- **Multi-leg stirrups / crossties** — spec §7.
- **Any design calculation** — no flexural or shear capacity, no crack-width
  analysis. Reduced effective depth from stacked layers is explicitly not
  accounted for (rev 2 §6.4).
- **Non-rectangular sections**, and non-concrete hosts.
- **File export** of the report.

## Residual question status

| # | Story | Status |
|---|---|---|
| R1 | S3 | **Resolved** — non-blocking warning when `Ø_spacer` < horizontal minimum |
| R2 | S6 | **Resolved** — embedment = `Support width − Cover` |
| R3 | S2 | **Resolved** — run to `beam end − cover`, warn that `LD` is unmet |
| R4 | S5 | **OPEN** — cannot be closed without a live Revit host |
| R5 | S2 | **Resolved** — wall thickness, perpendicular to the wall face |
| R6 | — | **OPEN** — type 3 only, out of scope for v1 |

Both hard blockers (R2, R3) are resolved, so no story is length-blocked and
S2/S6 can reach `ready-for-agent`.

**R4 is the only open question affecting shippable scope.** It asks whether
zone 1's last stirrup and zone 2's first stirrup can coincide at `L/3` and
produce a duplicate. It depends on the include-first/include-last flag
semantics of `SetLayoutAsMaximumSpacing`, which cannot be observed here. S5
therefore proceeds with an explicit de-duplication guard at each zone
boundary, and the mock-object verification write-up must demonstrate that
guard's behaviour — the guard is the mitigation, not the answer.

**R6** stays open permanently for v1, since stirrup type 3 is parked (A31).
