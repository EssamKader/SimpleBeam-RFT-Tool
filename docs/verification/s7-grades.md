# S7 Mock-Object Verification Write-up

Ticket [#20](https://github.com/EssamKader/rft-beam-detailing/issues/20) —
steel grades and `RebarBarType` resolution, and (in the same pass)
[#25](https://github.com/EssamKader/rft-beam-detailing/issues/25) — the
stirrup hook angle never being verified as 180°.

Required by `CONTEXT.md`'s standing rule: there is no live Revit host in this
environment, so any ticket touching Revit-API-dependent logic needs a
write-up demonstrating the logic is correct before it can close in review.
**173 tests pass** (145 baseline + 28 new: 20 in `tests/test_grades.py`,
8 added to `tests/test_mock_revit_adapter.py`). What that does and does not
mean is set out below.

## What was implemented

**`lib/rft/core/grades.py` (new, Revit-free).** Owns the §1.1/A34 role→grade
mapping as *data* (`ROLE_GRADE`), not scattered conditionals: stirrups → mild
St 24/35; top main, bottom main, crack/skin **and spacer** bars → high
tensile St 36/52. The spacer row is applied literally and commented as such
— A34's table is the source, not this ticket's own judgement, and a future
reader must not "fix" it back to mild.

The module also owns:
- `bar_type_for_role` — returns the already-selected `RebarBarType` for a
  role, raising `ValueError` if the required slot (mild/high-tensile) was
  never supplied. There is no default.
- `missing_bar_type_selection_message` / `missing_hook_type_selection_message`
  — blocking `GuardMessage`s (reusing the existing `rft.core.guards` shape)
  for a missing explicit selection.
- `hook_angle_guard_message` — blocks when a **read-back** hook angle is not
  180° within a 1° tolerance (this ticket's own design choice, not a spec
  value, same pattern as `CONTINUOUS_RUN_ANGLE_THRESHOLD_DEG`).
- `diameter_consistency_message` — blocks when a typed diameter (Ø_TOP,
  Ø_BTM, Ø_stirrup) disagrees with the selected `RebarBarType`'s own
  diameter by more than 0.5 mm (this ticket's own tolerance).

**`lib/rft/revit/bar_types.py` (new adapter).** `list_bar_types` /
`list_hook_types` enumerate the document's available types for the
dropdown (no filtering, no inference — the engineer picks from the full
list). `bar_type_diameter_mm` and `hook_angle_deg` read back a type's own
diameter and a hook's own angle respectively; both are `SHAPE UNVERIFIED`
(see below).

**All three pushbuttons.** `resolve_bar_type` (and, in `Place Stirrups`,
`resolve_hook_type`) — the by-name-with-fallback-to-first-available
functions — are deleted outright, along with their `RebarBarType name` /
`RebarHookType name` text-box inputs. Each pushbutton now:

1. Calls a `select_*_bar_type`/`select_hook_type` helper that lists the
   document's available types and shows them in a `pyrevit.forms.
   SelectFromList` picker (multiselect off, `name_attr="Name"`).
2. If the picker returns `None` (no types exist, or the engineer cancelled),
   shows `missing_bar_type_selection_message`/`missing_hook_type_selection_
   message` and exits — **no fallback to any default reaches placement.**
3. Resolves the actual bar type via `rft.core.grades.bar_type_for_role`,
   so the role→grade assignment lives in one place, not per-pushbutton.
4. Cross-checks the typed diameter(s) against the selected type's own
   diameter (`bar_type_diameter_mm` + `diameter_consistency_message`) and
   refuses on mismatch, before any anchorage/layout math runs.

Per pushbutton:

- **Place Bottom Bar** (S1): one high-tensile selection (bottom main bars
  are high tensile per A34); Ø_BTM cross-checked.
- **Place Main Bars** (S2/S3): one high-tensile selection, since top AND
  bottom main bars share the same A34 grade; both Ø_TOP and Ø_BTM are
  cross-checked against it (see "Spec tension" below — this is where the
  tension actually surfaces).
- **Place Stirrups** (S5): one mild selection, plus the hook type selection.
  Ø_stirrup is cross-checked. The hook's angle is read back via
  `hook_angle_deg`; if it comes back non-`None` and not within 1° of 180°,
  placement is blocked (`hook_angle_guard_message`). If it comes back
  `None` (issue #25's "cannot be read back at all" case), placement is
  **not** blocked — the pushbutton prints which hook type was used and
  states plainly that its angle could not be verified, and issue #25 stays
  open rather than being falsely marked resolved.

**LD labels** (`LD_top`/`LD_btm` in `Place Main Bars`) already said
"assumes St 36/52" before this ticket (added when A10 landed) — confirmed
unchanged, satisfying this ticket's own acceptance criterion without a
further edit.

**Bend radius independence (§1.1).** Confirmed by reading, not by adding
code: `rft.revit.placement.place_anchored_bar` and `rft.revit.stirrups.
place_stirrup` each take their own `bar_type` argument and pass it straight
through to `Rebar.CreateFromCurves` on a per-call basis. No shared radius
variable, cache, or "beam-wide" bar type exists anywhere in the placement
path — a mild stirrup and a high-tensile main bar in the same beam each
carry whatever bend radius their own selected `RebarBarType` defines,
because they are two entirely separate `CreateFromCurves` calls with two
entirely separate type arguments. Nothing needed to change here; this is a
"confirm it wasn't already broken" finding, not a code change.

## Is #25 fully closed or only narrowed?

**Narrowed, not closed.** Both of its two "what needs deciding" questions
are addressed as far as this environment allows:

1. *Can the angle be read back at all?* Implemented as an attempt
   (`hook_angle_deg`), not an assumption — it tries
   `hook_type.get_Parameter(BuiltInParameter.REBAR_HOOK_ANGLE).AsDouble()`
   (radians) and returns `None` on any failure, rather than guessing 180.
   Whether that parameter and access pattern exist on the real
   `RebarHookType` is still **unconfirmed** — this needs a live host.
2. *What happens when no 180° hook type exists?* The tool now refuses
   outright if the *selection* is missing (no hook type chosen at all), and
   blocks placement if a *read-back* angle is confirmed non-180°. It does
   **not** create a hook type — that remains explicitly out of scope, as
   #25 itself flagged as a bigger decision than this ticket should take.
   When the angle cannot be read back (the likely real-world outcome, since
   the whole read-back shape is unconfirmed), the tool proceeds with a
   loud, named warning rather than blocking — this was the ticket's
   explicit instruction rather than an invented compromise.

The name-matching fallback defect issue #25 originally reported (`return
hook_types[0]`) is fully gone. The angle-verification gap is narrowed to
"verified when readable, honestly flagged as unverified when not" — issue
#25 should stay open, retitled if useful to reflect that the fallback is
fixed and only the read-back shape itself remains to be confirmed live.

## The diameter-consistency choice, and the tension it surfaces

Per this ticket's instructions, the trap ("a typed diameter that disagrees
with the selected type's real diameter") is resolved by **keeping the typed
diameter input and cross-checking it against the selected `RebarBarType`'s
own diameter, refusing on mismatch** — not by deriving the diameter from the
bar type and discarding the typed field. Reasons:

- The pure core (`rft.core.anchorage`, `rft.core.layout`, `rft.core.
  stirrups`) already takes diameters as plain mm floats throughout — LD,
  layer offsets, corner-bar spacing, the stirrup rectangle. Making the core
  read a diameter *from* a Revit object would require it to import Revit
  types, breaking the Revit-free-core rule `CONTEXT.md` makes non-negotiable.
- Refusing on mismatch keeps exactly one number governing the downstream
  math (the typed value, now *proven* consistent with the placed type)
  without adding a second code path that silently prefers one source over
  the other.

**This surfaces a real spec tension in `Place Main Bars`.** A34 assigns the
SAME grade (high tensile) to both top and bottom main bars; A35 says
exactly **two** `RebarBarType` selections total (one mild, one high
tensile) — not one per role. But the defaults (rev 2 §8.1) are Ø_TOP = 12,
Ø_BTM = 16 — genuinely different diameters, both nominally "high tensile."
A single selected `RebarBarType` carries one diameter, so it can agree with
at most one of Ø_TOP/Ø_BTM at a time. With the literal two-selection reading
implemented here, **every default-configuration run of `Place Main Bars`
will refuse** unless the engineer either types matching Ø_TOP/Ø_BTM values
or the selected high-tensile type happens to match one of them (and the
other is refused). This is reported here rather than resolved by inventing
a third selection slot the acceptance criteria does not ask for — a real
decision ticket is needed on whether A35 should be read as "two selections
per grade" or "one selection per (grade, diameter) combination actually
used."

## What is NOT verified, and why it matters

The fakes are written to match the API shape the adapter *assumes*. A green
suite proves the adapter's **logic** is self-consistent. It proves nothing
about whether the real Revit API has those members, signatures or return
types — see the running `SHAPE UNVERIFIED` list in `tests/fake_revit_api.py`.
For this ticket specifically:

- **`RebarBarType.BarNominalDiameter`** — assumed read-only, internal units.
  Documentation also lists `BarModelDiameter` as a plausible alternative;
  which one the real API intends for this cross-check is unconfirmed. If
  wrong, only `rft.revit.bar_types.bar_type_diameter_mm`'s one-line body
  needs to change — the policy function it feeds does not.
- **`RebarHookType.get_Parameter(BuiltInParameter.REBAR_HOOK_ANGLE).
  AsDouble()`** — assumed to exist and return radians. This is the load-
  bearing unknown for #25's remaining half; a live host is required.
- **`pyrevit.forms.SelectFromList.show(items, multiselect=False,
  name_attr=..., title=..., button_name=...)`** — the dropdown/list
  component used for every explicit selection this ticket adds. `pyrevit`
  itself is not installed in this environment, so this is not merely
  shape-unverified like the Revit-API fakes above — it has **never been
  imported or executed at all**. If the real signature differs (argument
  names, positional vs. keyword, or a different class entirely such as
  `CommandSwitchWindow`), every `select_*` helper in all three pushbuttons
  needs a one-line fix at the call site; the surrounding no-fallback logic
  (missing-selection guard, diameter cross-check) is unaffected either way.
- **The three pushbuttons have never executed.** They compile (`ast.parse`)
  and import cleanly under a hand-rolled fake `pyrevit` module built only
  for this check (not part of the test suite, since `pyrevit` fakes are out
  of this ticket's stated scope) — this proves there is no `NameError`/
  `ImportError` from the refactor, nothing about correctness against a real
  Revit session.
- **Whether `RebarStyle.StirrupTie` permits a 180° hook at all** remains the
  load-bearing unknown named in `CONTEXT.md` and in `docs/verification/
  s5-stirrups.md` — unchanged by this ticket, since it is a property of the
  Revit API itself, not of how the hook type is selected.

First live-host session should check, in this order: whether
`SelectFromList.show` behaves as assumed for both bar types and hook types;
whether `BarNominalDiameter` (vs. `BarModelDiameter`) is the right diameter
property; and whether `REBAR_HOOK_ANGLE` reads back a real 180° hook's
angle correctly — that last one directly reopens or finally closes #25.
