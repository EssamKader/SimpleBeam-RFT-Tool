# Issue #25 — Stirrup hook family and angle

Verification write-up for the two-part stirrup hook guard: the hook's
**family** (`REBAR_HOOK_STYLE`) and its **angle** (`REBAR_HOOK_ANGLE`),
per **A45** (rev 2 §7.3, superseding A33's 180°).

Unlike every write-up before it, most of this one is **not** a mock-object
simulation. It records what was executed against a live host: Revit 2024
(build 24.3.40.26), `RevitAPI 24.3.40.0`, model `RFT_V1_CONTROL`, driven
through an MCP connector. Every write ran inside a `SubTransaction` that
was rolled back; nothing was committed to the model.

## What was executed live

Four `Rebar.CreateFromCurves` calls on a real beam, `RebarStyle.StirrupTie`,
a real 4-curve closed loop inset by the beam's own cover:

| Hook | `REBAR_HOOK_STYLE` | Angle | Result |
|---|---|---|---|
| `Standard - 180 deg.` | 0 | 180° | **`InternalException`: "An internal error has occurred."** |
| `Stirrup/Tie - 135 deg.` | 1 | 135° | Created; reads back 135° |
| Stirrup/Tie hook set to 180° | 1 | 180° | Created; reads back 180° |
| *(none)* | — | — | Created; hook dropped |

**The constraint is the hook's family, not its angle.** A `StirrupTie`
rebar rejects a Standard-family hook whatever its angle, and accepts a
Stirrup/Tie-family hook at either 135° or 180°.

That settles the unknown `CONTEXT.md` had carried since S1 — *"whether
`RebarStyle.StirrupTie` permits 180° hooks"* — as **yes**, and it settles
it in the opposite direction to the first probe's appearance. Stopping at
the first row would have sent us to amend §7.3 on the strength of a
misattributed cause.

## The read-backs, probed on their own terms

- **`REBAR_HOOK_ANGLE` returns radians.** π for a 180° hook, confirmed
  across the model's hook types. `hook_angle_deg`'s existing
  `math.degrees` conversion was already correct and is unchanged; its
  `SHAPE UNVERIFIED` note is retired.
- **`get_Parameter(BuiltInParameter.REBAR_HOOK_STYLE).AsInteger()`** — the
  exact call `hook_style` makes — returns `StorageType.Integer` with a
  value of 0 or 1 for **all 48** hook types in the model. `0 = Standard`,
  `1 = Stirrup/Tie`.
- **`REBAR_HOOK_ANGLE` is writable** on `RebarHookType`
  (`IsReadOnly=False`), which is how the 180° Stirrup/Tie hook in row 3
  was constructed.

## Names lie about family — the guard's whole justification

The live model contains a hook type named **`Stirrup/Tie - 45`** whose
`REBAR_HOOK_STYLE` is **0 (Standard)**. Any name-based selection would pick
it for a stirrup and get the opaque `InternalException`. It also holds
`Standard - 135 deg.` (family 0 at the required angle) and
`Stirrup / Tie - 91` and `Standard - 136`, whose names disagree with the
angles they actually carry (90° and 135°).

This is why the guard reads parameters and never matches on `Name`, and
why the filtered picker is described in code as a convenience rather than
a guarantee.

## The guard, and why it is two separate checks

Both halves are required, and they are reported **separately**:

1. **Family** — `REBAR_HOOK_STYLE` must be `1`. Checked **first**, because
   this is the half that prevents an actual failure, and that failure is
   `InternalException: "An internal error has occurred."` — the least
   diagnosable message Revit produces. The refusal therefore names what was
   selected, what was expected, and that a correct angle does not save it.
   An **unreadable** family **refuses**: there is nothing safe to proceed
   hopefully toward when a wrong family throws opaquely.
2. **Angle** — must be 135° ± 1° (A45). An **unreadable** angle does *not*
   block; it is reported as **UNVERIFIED**, preserving the distinction
   between "read back and checked" and "could not be confirmed".

Collapsing them into one message would tell an engineer holding a
`Standard - 135 deg.` hook that their **angle** was wrong. It is not; the
family is. That misdiagnosis is the specific reason for the split.

An empty filtered list — a model holding only Standard-family hooks — is a
refusal naming the fix (a Stirrup/Tie hook at 135° must exist in the
project), never a fallback to the first hook found, which is the defect
S7 (#20) removed.

## Main bars carry no hook at all

`place_anchored_bar` passes `None` for both hooks, and §2's anchorage is a
**bend built as a second curve segment**, not a `RebarHookType`. There is
therefore no main-bar hook to guard, and no family-0 counterpart was
invented for a selection that does not exist. A comment says so where a
reader would look for one.

## What is verified, and what is not

**Verified live:** the family/angle constraint and its direction; both
read-back calls including storage types and value domains; that 180° is
achievable with a Stirrup/Tie hook; that `REBAR_HOOK_ANGLE` is writable;
that hook names do not determine family.

**Not verified:** the guard *as executed by the pushbutton*. The probes
above were C# driven through a connector; the tool's own IronPython path
has still never run in pyRevit, so `pyrevit.forms.SelectFromList.show`'s
signature remains `SHAPE UNVERIFIED`, and `list_stirrup_hook_types`'
filtering has been exercised only against fakes. A green suite plus a live
API probe still does not equal "the button works".

**Superseded premise, recorded honestly:** A45's rationale states that
*"A33 as written could not be satisfied by any hook type in a stock
library"*. That was true of the model as first probed (15 hook types, no
Stirrup/Tie hook above 135°). The model now holds 48 hook types **including
`Stirrup/Tie - 180 deg.` at family 1** after a library import. So the
*availability* argument for A45 no longer holds; the *practice* argument —
that 135° is what stirrups normally use, stated by the project owner —
does, and that is what the decision rests on. Flagged for the project
owner rather than treated as settled, since a decision should not keep
standing on a premise that has expired.
