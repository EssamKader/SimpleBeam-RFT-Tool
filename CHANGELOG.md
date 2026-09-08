# Changelog

All notable changes to the RFT Beam Detailing tool.

**Nothing here is deployable yet.** A merge to `master` means the code
exists; it does **not** mean it is safe to load. Only a tagged release should
be loaded into a working Revit session, and no tag will be cut until a batch
of closed tickets has been verified **against a live Revit host** — which has
not yet happened for any of this work.

## Delivery model

This is a **pyRevit extension** — not a standalone application, and not a
Revit `.addin` / compiled add-in. There is no installer, no `.sln`, no DLL to
build, and none should be added.

Deployment means pointing pyRevit at the extension folder:

```
pyrevit extend <this repo>/RFTBeamDetailing.extension
```

or registering the path via pyRevit's extension manager, then reloading
pyRevit. Load from a **tagged commit**, never from whatever `master` happens
to be at the time.

Layout follows pyRevit convention — `RFTBeamDetailing.extension/` containing
`RFT Beam Detailing.tab/` → `Anchorage.panel/` → `*.pushbutton/script.py`,
plus `lib/`, which pyRevit adds to `sys.path` automatically so `rft.core` and
`rft.revit` import cleanly.

## [Unreleased]

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

### Known risks

- **#23 — `RebarHostData` cover read-back shape is unverified.** The adapter
  may be calling a non-existent API form; if so it throws on first real run.
  Accepted deliberately, to be corrected on first live Revit test.
- **#26 — the A7 clearance has no defined failure behaviour.** The tool warns
  and places anyway, which is a placeholder chosen to avoid inventing a
  detailing rule, not an answer. Needs a decision.
- **A beam in a continuous run is now detectable as "supported".** Since
  support detection includes structural framing (needed for girder supports,
  §2.4/A9), a beam framing into another beam collinear with it will be
  detailed as simply supported without complaint. The continuous-run guard is
  #22 (S9), and until it lands this is the sharpest edge in the tool.
- **Hook angle is not verified.** The stirrup pushbutton resolves
  `RebarHookType` by name and falls back to the first one in the document. A
  project whose first hook type is a 90° bend therefore gets non-compliant
  stirrups (rev 2 §7.3, A33 requires 180°) with only a printed note. Reading
  the angle back needs a parameter shape that cannot be confirmed here.
- No code in this project has ever been executed against a live Revit host.
  Every API decision rests on documentation, and passing tests validate
  adapter *logic* only — never API shape. See `CONTEXT.md`.

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
