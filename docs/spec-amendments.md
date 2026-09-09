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
| A45 | **CHANGE** | **§7.3's stirrup hook angle: 180° → 135°.** Verified against a live host (Revit 2024, `RevitAPI 24.3.40.0`): every **Stirrup/Tie**-family hook (`REBAR_HOOK_STYLE = 1`) in a stock library ships at 90° or 135°, and every 180° hook ships as **Standard** family (`= 0`), which `RebarStyle.StirrupTie` **rejects** with `InternalException` — so A33 as written could not be satisfied by any stock hook type. 135° is also what the project owner reports as normal practice. **The guard is two-part and both halves are required**: `REBAR_HOOK_STYLE` must be **1** (the half that actually prevents the opaque `InternalException`, needed regardless of angle) **and** the angle must be 135° ± 1°. Angle-only checking would pass a `Standard - 180 deg.` hook and then fail as "An internal error has occurred", on a hook whose angle was correct. Note the engineering tension recorded in #32: 135° is the **deformed**-bar convention, while A34 assigns stirrups plain round mild St 24/35, for which a semicircular hook is the classical requirement — A34 is being revisited separately and is NOT changed by this amendment. Decided by the project owner 2026-09-09 | #31, #25 |

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
