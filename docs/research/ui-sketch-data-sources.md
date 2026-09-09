# Can the sketch be driven entirely from `rft.core`?

Research for issue #41, part of the UI Wayfinder (#33).

## The question, and why it is the most consequential one in the map

A sketch that computes its own geometry is **a second implementation of the
detailing rules**. When the two disagree the drawing is wrong while looking
authoritative, and the engineer trusts the drawing. This project has already
been bitten three times by a *test fake* that modelled something the real API
does not do (`RebarFaceType` in #23, `.Name` in rc3, `GetBoundingBox` in
rc4); a sketch renderer with its own arithmetic is the same hazard, aimed at
the engineer instead of the developer.

So: can every drawn element be sourced from the **same** functions that drive
placement, making disagreement impossible by construction rather than by
discipline?

## Answer

**Yes for almost everything, and the exceptions are important.**

`rft.core` is pure, Revit-free and already in millimetres — exactly the shape
a renderer wants. It turns out to compute nearly every dimension a drawing
should show, because the placement code needed those same numbers first. The
renderer's job for those is **mm → pixels plus a label**, with no detailing
logic of its own.

Two things cannot be sourced that way, and they must be drawn
**schematically and labelled with the core's numbers** rather than
to-scale. Both are cases where **Revit itself**, not this codebase, owns the
geometry.

---

## Cross-section — every element and its source

| Drawn element | Source | Notes |
|---|---|---|
| Section outline `b` × `h` | `revit.geometry.beam_section_dimensions_mm` | Adapter, not core; a model read. Live-verified on 0° and 45° beams. |
| The four covers | `revit.host.read_beam_face_covers_mm` → `BeamFaceCovers` | Adapter. `end_start_mm`/`end_end_mm` are `None` when that end is supported — the renderer must not draw an end cover that does not exist (this is exactly what crashed rc5). |
| Stirrup **centreline** rectangle | `core.stirrups.centreline_leg_dimensions_mm` | The rectangle Revit actually receives (§7.1, A30). |
| Stirrup **outer** rectangle | **GAP 1** — not exposed | A30 defines it as `(b − 2·Cover) × (h − 2·Cover)`, but no core function returns it. See Gaps. |
| Stirrup shape / open leg | `core.stirrups.stirrup_curve_endpoints_mm(closure_type, w, h)` | Returns `((u0,v0),(u1,v1))` pairs in section-local mm. **Directly drawable** — the same list that becomes Revit curves becomes polyline segments. Best case in the whole mapping. |
| Hook-overlap corner vs two free ends | `core.stirrups.is_closed_type` | Tells the renderer whether to draw one overlap or two hooks. |
| Main-bar layer offsets | `core.layout.layer_offset_mm` / `first_layer_offset_mm` | Per layer `n`, §4/§4.1 A20. |
| Main-bar `u` positions in a layer | `core.layout.corner_bar_u_positions_mm` | §6.1. Returns the list. |
| Main-bar `v` positions | **GAP 2** — lives in the pushbutton | `±(h/2) ∓ layer_offset`, currently inline in `Place Main Bars`. See Gaps. |
| Spacer bar | `core.layout.spacer_length_mm` | §6.3. |
| Crack-bar layer `v` positions | `core.crack_bars.crack_layer_v_positions_mm` | In core already — the symmetric counterpart of Gap 2. |
| Crack-bar `u` positions | `core.crack_bars.crack_bar_u_positions_mm` | Returns the ± pair (A24). |
| Crack-bar trigger | `core.crack_bars.crack_reinforcement_triggered` | `h > 700`, strict. Gates whether crack bars are drawn at all. |
| `H_avail` and layer plan | `core.crack_bars.available_height_mm`, `crack_layer_plan` | `CrackLayerPlan` carries `n_gaps`, `n_crack_layers`, `actual_spacing_mm`, `h_avail_mm` — all four are dimensions worth annotating. |
| Clear-spacing dimension + pass/fail | `core.spacing.achieved_clear_spacing_mm`, `governing_min_spacing_mm`, `validate_layer_spacing` | `LayerSpacingResult` carries `governing_min_mm`, `achieved_clear_mm` and `passes` — so the drawing can dimension the achieved spacing **and colour it by whether it complies**. This makes the sketch a validation surface, not decoration. |
| Suggested layer count on failure | `core.spacing.suggest_min_layer_count`, `max_bars_per_layer` | A44's reporting duty; drawable as an annotation on a failing layer. |

## Longitudinal elevation — every element and its source

| Drawn element | Source | Notes |
|---|---|---|
| Span, support faces | `revit.geometry.support_width_along_axis_mm`, `support_reference_point` | Adapter. |
| Anchorage `a` and bend `b` | `core.anchorage.bottom_bar_anchorage`, `top_bar_anchorage` → `AnchorageResult(a, b, ld)` | **Directly drawable**, and all three values are worth dimensioning. |
| `LD` | `core.anchorage.development_length` | §2.1. |
| Minimum bend leg | `core.anchorage.MIN_BEND_LEG_MM` = 200 | §2.3's clamp; annotate when it governs. |
| Free/unsupported end run | `core.anchorage.unsupported_end_straight_run_mm`, `unsupported_end_anchorage` → `UnsupportedEndResult(achieved_length_mm, ld_mm, warning)` | Lets the drawing show achieved-versus-required side by side, and show the **deliberate absence of a hook** (§2.5, A12) — which a newcomer would otherwise read as a bug. |
| A7 top/bottom clearance | `core.anchorage.placed_clearance_mm` → `ClearanceResult(achieved_mm, required_mm, ok)` | Measured on the `a` values actually built, not the pre-cap formulas. Drawable as a dimension with a pass flag. |
| Three stirrup zones | `core.stirrups.stirrup_zones_mm(l, face_a, face_b)` → `StirrupZones(zone1, zone2, zone3)`, each `ZoneMM(start, end)` | **Directly drawable** as three labelled bands. |
| Zone count and achieved spacing | `core.stirrups.stirrup_count_and_spacing` → `StirrupCount(count, spacing_mm)` | Per zone. Annotate as `n @ s`. |
| Which zone ends carry a bar | `core.stirrups.ZONE_LAYOUT_FLAGS` | Needed to avoid drawing a duplicate at a zone boundary — the same R4 concern the placement path has. |
| Individual stirrup positions | **GAP 3 — cannot be sourced.** Revit's rebar set lays the array out itself via `SetLayoutAsMaximumSpacing`. | See Gaps. |
| Crack-bar embedment / extent | `core.crack_bars.crack_bar_end_result` → `CrackBarEndResult(embedment_mm, is_supported, terminates_short_of_end_mm)` | Per end. |
| Hook geometry (bend radius, arc) | **GAP 4 — cannot be sourced.** Owned by the `RebarBarType`'s bend radius inside Revit. | See Gaps. |

## The gaps, and what to do about each

**Gap 1 — the outer stirrup rectangle is not exposed.** A30 defines both the
outer `(b − 2·Cover) × (h − 2·Cover)` and the centreline rectangle; the core
returns only the centreline, because that is what the API needs. The
arithmetic is trivial, which is exactly the trap: if the renderer computes
it, the renderer owns a §7.1 rule. **Fix: add
`stirrups.outer_leg_dimensions_mm(b, h, cover)` to the core** and have both
the drawing and any future consumer read it from there. Cheap, and it keeps
the rule in one place.

**Gap 2 — main-bar `v` positions live in the pushbutton.** `±(h/2) ∓
layer_offset` is computed inline in `Place Main Bars`, while the *crack-bar*
equivalent (`crack_layer_v_positions_mm`) sits properly in the core. That
asymmetry is the whole problem: a renderer would have to reimplement the
main-bar case while importing the crack-bar case. **Fix: move it to
`layout.main_layer_v_positions_mm(h, offsets, is_top)`**, and have the
pushbutton call it too. This is a refactor with no behaviour change, and it
removes the single most likely place for the drawing and the placement to
drift apart.

**Gap 3 — individual stirrup positions are Revit's, not ours.** The
placement path hands Revit a zone and a maximum spacing and lets
`SetLayoutAsMaximumSpacing` distribute the bars. The core knows the *count*
and the *achieved spacing* but never enumerates stations, and any renderer
that did so would be **predicting** what Revit's rebar set will do — a
prediction that can be wrong in exactly the way this research exists to
prevent.

**Recommendation: draw the stirrup array schematically and label it with the
core's numbers.** Show the three zone bands with their true boundaries (which
*are* sourced), and inside each band draw evenly spaced ticks annotated
`n @ s mm` from `StirrupCount` — with the tick spacing explicitly a
schematic, not a measurement. Do **not** dimension individual stirrup
stations. The engineer gets the information that matters (how many, at what
spacing, between which faces) without the drawing making a claim it cannot
back.

**Gap 4 — hook bend geometry is Revit's.** The arc a hook actually traces
depends on the bar type's bend radius, which lives in the `RebarBarType`.
**Recommendation: draw hooks schematically** — a straight leg at the correct
**angle** (135°, from `grades.HOOK_ANGLE_REQUIRED_DEG` and the live read-back
`bar_types.hook_angle_deg`) and of the correct **length** where the core
knows it (`b` from `AnchorageResult`), without attempting the fillet. Label
the angle. Same principle: schematic where we do not own the truth, exact
where we do.

## Consequence for the static-vs-live decision

The finding inverts the expected cost. A live preview was assumed expensive
and risky; in fact **the core already computes the numbers, so a live sketch
is mostly a coordinate transform** — and because `validate_layer_spacing`,
`placed_clearance_mm` and `LayerSpacingResult.passes` are all available to
the renderer, a live sketch stops being decoration and becomes **the place
the engineer sees a violation before committing a transaction**.

That is a materially stronger reason to build it than "CADS has one".

The two schematic exceptions are the honest cost, and they are cheap to
disclose: a short note on the drawing that the stirrup array and the hook
fillets are indicative, with the governing numbers printed beside them.

## What this does not answer

Whether the *rendering surface* can do it at the required smoothness — WPF
`Canvas` redraw on input change under IronPython 2.7 — is issue #40 and
issue #42. This document is about where the numbers come from, not whether
they can be painted.
