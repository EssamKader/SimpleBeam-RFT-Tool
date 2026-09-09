# Changelog

All notable changes to the RFT Beam Detailing tool.

**Nothing here is a release yet.** A merge to `master` means the code
exists; it does **not** mean it is safe to load. Only a tagged commit should
be loaded into a Revit session, never `master` HEAD.

`v0.1.0-rc1` is a **release candidate cut in order to be tested**, not a
release. It exists because the verification run itself needs something
stable to install from, and installing the working tree would let an edit to
`master` silently change what is loaded inside a running Revit session. It
carries no claim that the buttons work. `v0.1.0` will be cut only if the
candidate passes on a live host.

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
`RFT Beam Detailing.tab/` → `Anchorage.panel/` → `*.pushbutton/script.py`,
plus `lib/`, which pyRevit adds to `sys.path` automatically so `rft.core` and
`rft.revit` import cleanly.

## [v0.1.0-rc1] — 2026-09-09

First tagged commit in the project's history, cut at the `master` commit
that carries this entry, to give the live verification run a fixed thing to
install. **Candidate, not a release**
— see the note at the top of this file. Contents are everything listed under
Added / Fixed / Decided below, which is the whole of the work to date: six
detailing subsystems (S1–S7), the out-of-scope guards (S9), the pyRevit
bundle metadata, and 45 spec amendments. 252 tests pass. Not yet verified:
see Known risks, first entry.

## [Unreleased]

Nothing. `master` and `v0.1.0-rc1` are the same tree.

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
- **The tool's own execution path has never run.** This is now the single
  largest open risk, and it is what `v0.1.0-rc1` exists to test. Individual
  API shapes *have* been confirmed against a live Revit 2024 host
  (`RevitAPI 24.3.40.0`) — cover face reads, hook family and angle, the
  z-datum, rotation — but every one of those probes was driven as **C#
  through a connector**. Nothing has executed as **IronPython inside
  pyRevit**, which means `pyrevit.forms.SelectFromList.show`'s signature,
  `Rebar.CreateFromCurves` *as these scripts call it*, and the buttons'
  end-to-end behaviour are all still unexercised. A green suite plus a live
  API probe is not "the button works". See `CONTEXT.md`.

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
