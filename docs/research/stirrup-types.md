# Stirrup Types 1–4 — Revit API Research Findings

Documentation-only research, no live Revit host used. Builds on
`docs/research/revit-api-strategy.md` (mm-internal/convert-at-boundary,
`Rebar.CreateFromCurves`, `RebarStyle`, `SetLayoutAsMaximumSpacing`, one
`Transaction` per beam — all treated as fixed here, not re-litigated).

## Summary Table

| # | Question | One-line answer |
|---|---|---|
| 1 | Native shapes vs custom | No stock shape encodes a specific hook corner; `CreateFromCurves(..., createNewShape:true)` auto-matches/authors the needed `RebarShape` at creation time — hand-authored families aren't a prerequisite. |
| 2 | Type 1 vs Type 2 | Same 4-curve loop and winding; only the **starting vertex index** (which corner is `curves[0]`) changes — one parameterized code path, not a reversed loop. |
| 3 | Type 3 nested | No single-element multi-loop shape exists in the API; needs **two** separate `Rebar` elements (outer + inner). Inner loop dimensioning is an **unresolved spec gap** — recommend parking. |
| 4 | Type 4 open U | Yes, placeable — openness is a curve-topology choice, not a `RebarStyle` restriction; each free end gets its own optional hook (angle=0 disables it). |
| 5 | Creation call | `Rebar.CreateFromCurves` with `RebarStyle.StirrupTie`, same as longitudinal bars but a closed or open curve list depending on type. |
| 6 | Hook geometry | `RebarHookType`: angle 0/45/90/135/180°, length = bar diameter × multiplier (overridable). Fix at 135° (ACI seismic hook) rather than exposing as user input. |

---

## 1. Native shapes vs. custom geometry

Revit's out-of-box shape catalog is per-country and, for UK/metric templates, keyed to **BS 8666:2005** shape-code conventions (confirmed: "the standard shape codes that ship with Revit" are BS8666:2005-based; codes 41–56 cover hooked/closed links, with a "standard rectangular link (stirrup)" among them, and 60-series codes cover open links — Autodesk Community, revitstructureblog.wordpress.com). However, BS 8666 codes describe *topology* (closed vs. open, number of bends), not "hook lands on the top-left vs. top-right corner" — that is a placement-time choice (see Q2), not a distinct shape family. I could not source an authoritative Autodesk-published list mapping literal family names (e.g. "Stirrup - T1") to types 1–4; one third-party note states "M_T2 similar to shape 60" (an open link), the only concrete family-name-to-code pairing found.

Practically, this doesn't matter: `Rebar.CreateFromCurves(..., useExistingShapeIfPossible:true, createNewShape:true)` matches an existing `RebarShape` if one fits, or silently authors a new one if not — this is standard, documented behavior, not a workaround (Autodesk AEC DevBlog "Create stirrup rebar by given model curves via Revit API"; corroborated by modplus.org, which explains Revit falls back to a **non-editable** auto-generated shape only when the curve geometry doesn't match anything in the project — an outcome to expect and accept, not something to engineer around by pre-authoring families).

**Recommendation:** don't hand-author 4 custom `RebarShape` families. Drive all four variants from `CreateFromCurves` with per-type curve lists and hook parameters (Q2, Q5) and let Revit's shape matching/creation handle the family. **UNVERIFIED:** exact shape-browser names in this project's live template; whether type 4's auto-created shape is user-editable afterward.

## 2. Hook overlap corner — Type 1 vs. Type 2

The hook's location is fixed to the curve list's own terminal points: start hook sits at `curves[0].GetEndPoint(0)`, end hook at `curves[last].GetEndPoint(1)` (Jeremy Tammik, "Location of Hooks in a Rebar Shape Family," thebuildingcoder/jeremytammik.github.io). For a closed 4-curve rectangular loop these two points coincide — that shared point *is* the hook-overlap corner. `RebarHookOrientation` (Left/Right, per the companion doc and `CreateFromCurves` docs) is defined **relative to each curve's own local tangent and the shape's normal**, not to the beam's global left/right — it controls whether the hook swings inward or outward at that corner, not *which* corner is used.

**Decisive answer: Type 2 is Type 1 with the curve list's starting vertex rotated one position around the same loop, same winding direction — not a reversed loop.** Reversing winding (CW↔CCW) is the wrong lever: it would flip which local face the hook swings toward (risking an outward-facing hook, which `RebarHookOrientation` would then need to compensate for), whereas simply re-indexing which corner is `curves[0]` (cyclically rotating the same ordered array) moves the overlap point to the adjacent top corner while everything else — winding, orientation, hook type — stays identical. This is one code path: a "starting corner" parameter that selects the array rotation.

**Verdict:** one parameterized construction (corner → array-rotation index), not two separate builds. **UNVERIFIED:** live behavior when `curves[last].EndPoint(1)` isn't bit-exact with `curves[0].EndPoint(0)` (loop-closure tolerance).

## 3. Type 3 — nested double perimeter

`RebarShapeDefinitionBySegments` is documented as **one continuous chain**: "segments are numbered starting with 0... beginning of the shape is end 0 of segment 0... end of the shape is end 1 of segment (NumberOfSegments−1)" (revitapidocs.com) — there is no documented multi-loop or disjoint-loop shape definition, and no source found describing a single `Rebar` element carrying two concentric closed perimeters. `Rebar` itself only comes in two kinds — Shape Driven and Free Form — neither described as multi-loop-per-element for stirrup/tie use.

**What the API supports:** two independent `Rebar` elements — an outer stirrup (`RebarStyle.StirrupTie`, the confirmed outer/centreline rectangle) and an inner stirrup (`RebarStyle.StirrupTie`, a smaller closed rectangle), each with its own `SetLayoutAsMaximumSpacing` call over the *same* zone `arrayLength` so the two coincide along the beam. This doubles the element/set count per zone versus types 1/2/4.

**Flagging the gap (per `CONTEXT.md`'s standing rule — do not invent):** the spec fixes the *outer* rectangle formula but defines nothing for the inner loop. A complete rule would need, at minimum: (a) the inner loop's offset from the outer stirrup's inner face or from `Cover`; (b) whether the inner stirrup's bar diameter equals the outer's; (c) how the inner loop relates to any intermediate/corner bar positions; (d) whether the inner loop gets its own independent hook-overlap corner (type 1/2 rule) or must match the outer's. None of this is in the spec.

**Verdict: park Type 3 for v1.** It is blocked by an undefined dimensioning rule, and even once resolved it requires an architectural change (two elements/sets per zone instead of one) not needed by the other three types. Recommend a Grill-ticket to resolve the inner-loop rule before scheduling.

## 4. Type 4 — open U-shape

`RebarStyle` has exactly two values, Standard and StirrupTie; its docs state it "affects the bend radius and the set of allowable hooks" and rebar auto-constraining — nothing ties it to closed-loop topology (revitapidocs.com `RebarStyle` enum). Separately, `RebarShape.Create`'s hook-angle parameters are explicit that "if 0, the shape will have no start/end hook" (revitapidocs.com `RebarShape.Create` overload) — i.e., the API natively supports a curve chain terminating at two free, unclosed endpoints, each with its own optional non-zero hook angle. That is precisely an open link/U-shape (BS 8666 60-series topology). No source states a closed loop is mandatory for `StirrupTie`.

Distribution: `SetLayoutAsMaximumSpacing` is exposed via `RebarShapeDrivenAccessor` (`rebar.GetShapeDrivenAccessor()`) with no documented restriction to closed shapes — reasoned from the API surface (one accessor type, not a style-gated one), **not confirmed empirically**.

**Verdict: yes, placeable** — `Rebar.CreateFromCurves` with an open 3-segment curve chain, `RebarStyle.StirrupTie`, non-null `RebarHookType` at both `startHook`/`endHook`. **UNVERIFIED:** whether `SetLayoutAsMaximumSpacing` behaves identically for an open shape vs. closed on a live host.

## 5. Creation call for stirrups

**Recommend `Rebar.CreateFromCurves`**, mirroring the longitudinal-bar decision, over `CreateFromRebarShape` — there's no guaranteed stock shape matching this spec's exact corner/hook/nesting combinations, and `createNewShape:true`/`useExistingShapeIfPossible:true` already gives auto-matching for free (Q1), so pre-binding to a specific stock `RebarShape` buys nothing and adds a dependency on template contents.

Concrete call (2023–2025 signature; Revit 2026 deprecates the `RebarHookType`-parameter overload in favor of `BarTerminationsData` — irrelevant for this 2023+ target but note for future upgrades):

```
Rebar.CreateFromCurves(
    doc, RebarStyle.StirrupTie,
    stirrupBarType,
    startHookType, endHookType,          // RebarHookType or null per end
    hostBeam, normalVector,
    curves,                               // closed 4-curve loop (types 1-3) or open 3-curve chain (type 4)
    startHookOrientation, endHookOrientation,  // RebarHookOrientation.Left/Right, held constant across type 1/2
    useExistingShapeIfPossible: true, createNewShape: true)
```

Hooks/orientation: for closed types (1/2), only the loop's start/end (the shared overlap corner) carry a hook — `startHookType`/`endHookType` non-null there, `RebarHookOrientation` fixed per Q2. For type 4, both free ends get a hook. Type 3's outer and inner elements are each their own `CreateFromCurves` call as above.

## 6. Hook geometry for the closure

`RebarHookType` carries an angle (0–π, common values 0/45/90/135/180°), a shape style, and a **multiplier**: default hook straight-segment length = bar diameter × multiplier, overridable via `RebarBarType` (revitapidocs.com `RebarHookType` class). The Autodesk "Rebar Hook Length Parameters" help page confirms an "Auto Calculation" toggle driving Hook Length/Tangent Length from Bar Diameter, disable-able for manual override. 135° is the ACI 318-19 §25.3 / Ch.18 seismic-hook value (≥6·d_b extension) cited across multiple sources; `RebarStyle.StirrupTie` specifically gates "the set of allowable hooks" (revitapidocs.com `RebarStyle`), consistent with stirrup/tie hooks being a restricted subset distinct from standard-bar hooks.

**Recommendation:** fix the hook angle at 135° (code-mandated constant, not a per-beam dimension) sourced from a project `RebarHookType` with Auto Calculation enabled; do not expose hook length as a user input — it is derived from bar diameter, per the API's own mechanism. Expose angle as a single global/project setting only if a non-seismic 90° detail is ever needed, not per-run.

---

## Unverified against a live host

- Exact `RebarShape` family names in this project's live template, and whether an auto-created (type-1/2/4) shape ends up editable or "non-editable" (Q1).
- Loop-closure tolerance behavior when `curves[last].EndPoint(1)` isn't bit-exact with `curves[0].EndPoint(0)` for a closed 4-curve stirrup (Q2).
- Whether `SetLayoutAsMaximumSpacing` behaves identically for an open (type 4) shape vs. a closed one — reasoned from a single shared accessor class, not observed (Q4).
- Whether an auto-created custom shape for a nested inner loop (if the spec gap were resolved) would need to be a second, independent `RebarShape`/`Rebar` or whether Revit's matching would ever merge it with the outer — assumed independent per documented one-chain-per-shape model (Q3).
- Whether `RebarStyle.StirrupTie`'s "restricted set of allowable hooks" actually excludes 45°/90°/180° for stirrups in practice, or just changes bend-radius defaults (Q6) — the enum's remark is not itemized in any source found.

## Is Type 3 implementable now?

**No — blocked.** The API mechanics (two separate elements) are understood well enough to proceed, but the inner loop's dimensioning rule is entirely undefined in the spec, and `CONTEXT.md` forbids inventing detailing rules. Type 3 should be parked pending a spec amendment (Grill-ticket) defining the inner loop's offset/diameter/corner rule; types 1, 2, and 4 have no such blocker and can proceed on the findings above.
