# Revit API Strategy — Research Findings (RFT Beam Detailing Tool)

Documentation-only research, no live Revit host used. Target: Revit 2023+, pyRevit
(IronPython/CPython) against the .NET API. Every claim is sourced; anything not
confirmable from documentation is flagged and repeated in the final section.

## Summary Table

| # | Question | One-line answer |
|---|---|---|
| 1 | Unit boundary | Keep mm internally, convert only at the API call boundary with `UnitUtils.ConvertToInternalUnits(v, UnitTypeId.Millimeters)` (Revit 2021+); `DisplayUnitType.DUT_MILLIMETERS` is the deprecated pre-2021 form. |
| 2 | Rebar creation | Use `Rebar.CreateFromCurves`; model the §2 bend as a **second curve segment**, not a hook — hooks are fixed-angle catalog shapes sized by a diameter multiplier, not an arbitrary spec-driven length. |
| 3 | Bend radius | **Verdict: unresolved latent conflict.** Revit fillets the vertex between two supplied curves using the `RebarBarType` bend radius, trimming each leg back from the theoretical corner. Whether this contradicts the spec depends on whether `a`/`b` mean "to theoretical corner" or "actual straight run" — the spec doesn't say, and this must be decided before Q2's code is written. |
| 4 | Host prerequisites | Beam must be Structural Framing with a structural `StructuralUsage`, and `RebarHostData.GetRebarHostData(beam).IsValidHost()` must return true; an undefined face cover silently falls back to a default rather than erroring. |
| 5 | Rebar sets | `SetLayoutAsFixedNumber`, `SetLayoutAsMaximumSpacing`, `SetLayoutAsMinimumClearSpacing` all take an explicit `arrayLength` and redistribute spacing evenly to exactly fill it — no leftover gap. `SetLayoutAsNumberWithSpacing` takes **no** `arrayLength` — it's the one rule that can under/over-fill a zone and needs caller-side remainder handling. |
| 6 | Transactions | One `Transaction` per beam (all bars + stirrups), rolled back on any exception before it propagates; `IFailuresPreprocessor` deletes warnings but lets errors abort; `TransactionGroup` reserved for independently-committable steps, not needed here. |

---

## 1. Unit conversion boundary

**Recommendation: keep detailing math in millimetres; convert only at the API boundary.** Converting every input to feet on read forces every spec formula (`a_t = Column_width − Cover − Ø_BTM`, the `L/3` zone math, `Cover + Ø_stirrup + ½Ø_bar`) to be re-derived in feet — an extra translation layer and a second place unit bugs hide, since every intermediate value must be mentally re-checked against the mm spec. Converting only immediately before `XYZ`/`Curve.CreateBound`/parameter `Set()` calls means every function signature and unit test reads 1:1 against the spec.

Modern call: `UnitUtils.ConvertToInternalUnits(value, UnitTypeId.Millimeters)` (and `ConvertFromInternalUnits` for the reverse). `UnitTypeId`/`ForgeTypeId`-based units replaced the enum-based `DisplayUnitType`/`DUT_MILLIMETERS` starting with the **Revit 2021** API; pre-2021 code must use `DisplayUnitType.DUT_MILLIMETERS`. Since this project targets 2023+, use `UnitTypeId` exclusively. Sources: Autodesk Revit API Developers Guide, "Units"; archi-lab, "Handling the Revit 2022 Unit Changes"; Autodesk Community ForgeTypeId thread.

```python
def mm_to_ft(value_mm):
    return UnitUtils.ConvertToInternalUnits(value_mm, UnitTypeId.Millimeters)

def ft_to_mm(value_ft):
    return UnitUtils.ConvertFromInternalUnits(value_ft, UnitTypeId.Millimeters)
```
Every point/curve construction calls `mm_to_ft` inline; no value is ever stored in feet.

## 2. Rebar creation approach for longitudinal bars

`Rebar.CreateFromCurves(doc, style, barType, startHook, endHook, host, norm, curves, startHookOrient, endHookOrient, useExistingShapeIfPossible, createNewShape)` takes an explicit `IList<Curve>` describing the bar's boundary **excluding fillets and hooks**, plus a `RebarHookType` per end (or `null`) and a `RebarHookOrientation` (Left/Right only). Source: revitapidocs.com CreateFromCurves method page (2019/2025 signatures consistent).

`Rebar.CreateFromRebarShape(doc, rebarShape, barType, host, origin, xVec, yVec)` instantiates a pre-authored `RebarShape` family at a placement transform, taking its default shape parameters; hooks are stripped before the bounding box is computed. Source: revitapidocs.com CreateFromRebarShape; Autodesk API Developers Guide "Reinforcement."

**Decisive answer: model the §2 bend as a second curve segment, not a hook.** A `RebarHookType` is a fixed catalog element (angle 0–π, shape style, and a diameter multiplier where `hook length = bar diameter × multiplier`, overridable per `RebarBarType`) — it is not driven by an independent length like `b = LD − a`. Using a hook for `b` would make its length a function of bar diameter and a fixed multiplier, silently wrong whenever that multiplier doesn't match `LD − a`. Instead build `curves = [straight run of length a, bent leg of length b]` meeting at one vertex, with `startHook`/`endHook` = `null` — the L-shape *is* the anchorage. This is `RebarStyle.Standard`, not `RebarStyle.StirrupTie`. Source: RebarHookType class docs (revitapidocs.com 2022).

## 3. Bend radius — potential spec conflict

`RebarBarType` carries the bend radius applied at every bend Revit inserts. When `CreateFromCurves` receives a curve list, Revit does not draw a sharp corner at the shared vertex — it inserts a fillet arc of that radius and trims each adjoining straight segment back from the vertex by the arc's tangent length. This is corroborated by `GetCenterlineCurves(adjustForSelfIntersection, suppressHooks, suppressBendRadius, ...)`, whose `suppressBendRadius` parameter exists specifically to return the *unfilleted* chain for comparison against the filleted, as-built one (revitapidocs.com 2023). For a 90° bend the tangent trim equals the bend radius itself (`R·tan(45°) = R`) — standard bend geometry, applied here via a Revit-specific mechanism.

**Verdict: genuine, unresolved conflict risk, hinging on a reading the spec doesn't settle.** The curve list fed to `CreateFromCurves` is the unfilleted, theoretical polyline (vertex = where centrelines would meet at a sharp corner); the rendered bar's straight legs will be shorter than the input curve lengths by the tangent trim. If §2's `a`/`b` mean "distance to the theoretical corner" (the conventional BS8666-style dimensioning), raw `a`/`b` as curve lengths is correct — no conflict. If they mean "actual straight run before the bar curves" (plausible, since they derive from physical clearances like `Column_width − Cover − Ø_BTM`, not an abstract intersection), the curve list must be *lengthened* by the tangent trim first, or the placed bar is short. For a Ø16 bar this trim is on the order of the project's `RebarBarType` bend radius — commonly a few centimetres — not negligible against the 200 mm minimum leg clamp. **The spec must state which convention `a`/`b` use before Q2's curve-construction code is written**, since the two readings yield different curve lengths for identical inputs. UNVERIFIED: the exact numeric bend-radius default, and empirical confirmation of the fillet/trim behaviour (only the parameter's existence is doc-confirmed, not its measured effect).

## 4. Host and constraint prerequisites

`RebarHostData.GetRebarHostData(element)` returns a `RebarHostData`, or null if the category can *never* host rebar. `.IsValidHost()` must additionally return true; if it's false while `GetRebarHostData()` succeeds, the element is host-capable but not currently valid — typically fixed via a structural `StructuralUsage`, an analytical model present (`AnalyticalModelStick` for framing), or a concrete material. Cover is per-face, exposed via `RebarHostData`'s face-cover API or `RebarCoverType`-driven parameters; an undefined face cover falls back to a document default rather than erroring, so "no cover defined" must be explicitly checked, not just caught. Sources: Autodesk API Developers Guide "Reinforcement"/"Rebar"; `IsValidHost`/`GetRebarHostData` method pages; `StructuralUsage` property page.

**Recommendation:** validate `GetRebarHostData(beam)` first (fail fast if null), then `IsValidHost()` (actionable error pointing at `StructuralUsage`), then explicitly read back per-face `RebarCoverType` so a silent default can't masquerade as the spec's `Cover` input.

## 5. Rebar sets for stirrup distribution

All four rules live on `RebarShapeDrivenAccessor` (via `rebar.GetShapeDrivenAccessor()`), replacing pre-2019 `Rebar` methods of the same names.

- `SetLayoutAsFixedNumber(numberOfBarPositions, arrayLength, barsOnNormalSide, includeFirstBar, includeLastBar)` — fixed count over a given `arrayLength`; spacing computed to exactly span it.
- `SetLayoutAsMaximumSpacing(spacing, arrayLength, ...)` — count derived from `arrayLength`/`spacing`, redistributed evenly so actual spacing ≤ requested and the length is fully spanned (Autodesk Knowledge Network, "Place a Rebar Set": "the number of rebar changes... maintaining a distance no larger than the maximum").
- `SetLayoutAsMinimumClearSpacing(...)` — same redistribution, constraint is face-to-face clear spacing, diameter-aware.
- `SetLayoutAsNumberWithSpacing(numberOfBars, spacing)` — **no `arrayLength` at all**; per Autodesk's help text it "strictly respects the requested spacing," so covered length `(numberOfBars − 1) × spacing` is an *output*, not something pinnable to a zone boundary.

**Resolves the open §3 remainder question.** Fixed Number, Maximum Spacing, and Minimum Clear Spacing are all safe to hand a computed `L/3` zone as `arrayLength` — no leftover gap, spacing tightens instead. `NumberWithSpacing` is the wrong tool for zone-filling: with no length input, any mismatch between `(n−1)×spacing` and the zone becomes an unhandled leftover the caller must detect and absorb.

**Recommendation:** each `L/3` zone as one rebar set via `SetLayoutAsMaximumSpacing` (dense/normal spacing as the maximum, count auto-derived, 50 mm first-stirrup offset folded into `arrayLength`'s start point) — three sets, never `NumberWithSpacing` for zone bodies.

## 6. Transaction and failure handling

One `Transaction` wraps the entire per-beam placement (all bars + stirrup sets), body in `try/except`: any exception calls `tx.RollBack()` before re-raising, so a half-placed cage never reaches `Commit()`. `TransactionGroup` is only needed if placement splits into several independently-committable steps — for one user action, a single `Transaction` is simpler and faster than `TransactionGroup` + multiple transactions for the same effect. Sources: Autodesk API Developers Guide "Transaction Classes"; Jeremy Tammik, "Using Transaction Groups."

To suppress modal warnings during unattended placement, set `Transaction.SetFailureHandlingOptions(FailureHandlingOptions.SetFailuresPreprocessor(pre))` where `pre` implements `IFailuresPreprocessor.PreprocessFailures`: iterate `GetFailureMessages()`, call `DeleteWarning()`/`DeleteAllWarnings()` for `FailureSeverity.Warning`, return `Continue`; `FailureSeverity.Error` should abort rather than be silently deleted. Sources: `IFailuresPreprocessor` Interface docs; Autodesk API Developers Guide "Handling Failures"; learnrevitapi.com "Suppress Warnings in Revit API."

**Recommendation:** single `Transaction` per beam, custom `IFailuresPreprocessor` deleting warnings but aborting on errors, explicit `RollBack()` on any exception.

---

## Unverified against a live host

- Exact numeric bend-radius default(s) for a real `RebarBarType` (Ø16 and others) in this project's template, and the resulting tangent-trim magnitude at each §2 bend (Q3).
- Empirical confirmation that `Rebar.CreateFromCurves` fillets the vertex between supplied curves rather than rejecting a non-tangent polyline outright (Q2/Q3) — inferred from `GetCenterlineCurves`'s `suppressBendRadius` parameter and general bend geometry, not observed directly.
- Whether `IsValidHost()` on a real structural-framing beam instance returns true out-of-the-box, or needs an explicit `StructuralUsage`/analytical-model fix-up (Q4).
- Behaviour when a beam host has genuinely no `RebarCoverType` on a face (vs. a document default) — needs confirming against an actual un-covered beam (Q4).
- Whether `SetLayoutAsMaximumSpacing`/`MinimumClearSpacing` ever conflict with `includeFirstBar`/`includeLastBar` where two adjoining zone sets meet at an `L/3` boundary (Q5) — "no leftover gap" is documented per-rule in isolation, not for two adjoining sets.
- Whether `DeleteAllWarnings()` interacts differently with rebar-specific warnings (cover violation, insufficient bend space) than with generic element warnings (Q6).
