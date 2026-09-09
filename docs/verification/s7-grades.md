# S7 Mock-Object Verification Write-up

> **CORRECTED BY ISSUE #25 / A45 (2026-09-09).** Every claim below about a
> **180°** stirrup hook, and every open question about whether
> `RebarStyle.StirrupTie` permits one, has since been settled against a
> live host — and the required angle has changed to **135°**. The real
> constraint turned out to be the hook's **family**
> (`REBAR_HOOK_STYLE`, `0 = Standard`, `1 = Stirrup/Tie`), not its angle:
> a `StirrupTie` rebar rejects a Standard-family hook whatever the angle,
> and accepts a Stirrup/Tie-family hook at 135° *or* 180°. The
> `SHAPE UNVERIFIED` notes on `hook_angle_deg` are retired. See
> `docs/verification/issue-25-stirrup-hook-family-and-angle.md`; this
> document is kept as the record of what was known at the time.


Ticket [#20](https://github.com/EssamKader/rft-beam-detailing/issues/20) —
steel grades and `RebarBarType` resolution, and (in the same pass)
[#25](https://github.com/EssamKader/rft-beam-detailing/issues/25) — the
stirrup hook angle never being verified as 180°. **Reworked by ticket
[#27](https://github.com/EssamKader/rft-beam-detailing/issues/27)**, which
moved bar-type selection from per-GRADE (A35, this doc's original
"diameter-consistency" section) to per-ROLE (**A42**, which supersedes
A35) — see "A42 supersedes A35" below for what changed and why.

Required by `CONTEXT.md`'s standing rule: there is no live Revit host in this
environment, so any ticket touching Revit-API-dependent logic needs a
write-up demonstrating the logic is correct before it can close in review.

**As of #27: 180 tests pass** (173 baseline before #27 + net 7 new). The
diameter-consistency tests #20 added (5 tests in `tests/test_grades.py`)
were **deleted outright** along with `diameter_consistency_message` itself
-- A42 removes the free-text diameter inputs those tests exercised, so
there is nothing left to cross-check. In their place, #27 added: 10 new/
reworked tests in `tests/test_grades.py` (role-picker label, report line,
the stirrup/high-tensile grade-conflict guard) and 6 new tests in
`tests/test_mock_revit_adapter.py` (per-role diameter read-back, the §2.2/
A7 cross-dependency proof, and `existing_rebar_bar_types`). Net: 173 - 5 +
10 + ... see the exact command/output in ticket #27's own report; the
point named explicitly here per that ticket's instructions is that the
count's composition changed, not just its total. What all of this does and
does not mean is set out below.

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
- **(#27/A42)** `role_picker_label` — the label every role's picker must
  carry, built from `ROLE_GRADE` so it can never drift from A34's mapping.
  `role_grade_report_line` — the report line naming both the bar type used
  and the grade A34 requires for that role. `stirrup_grade_conflict_message`
  — the one thing A42 says IS mechanically checkable: the stirrup type must
  not be the same *element* as a type used for a high-tensile role,
  compared by id, never by name.
- ~~`diameter_consistency_message`~~ **deleted by #27** -- see "A42
  supersedes A35" below.

**`lib/rft/revit/bar_types.py` (adapter, reworked by #27).** `list_bar_types` /
`list_hook_types` enumerate the document's available types for the
dropdown (no filtering, no inference — the engineer picks from the full
list). `bar_type_diameter_mm` and `hook_angle_deg` read back a type's own
diameter and a hook's own angle respectively; both are `SHAPE UNVERIFIED`
(see below). **New in #27:** `existing_rebar_bar_types(document,
host_element, rebar_style)` — enumerates `Rebar` already placed on a beam,
filtered by `RebarStyle`, feeding the A42 grade-conflict guard (see below);
also `SHAPE UNVERIFIED` (`Rebar.GetHostId()`, never confirmed here).

**All three pushbuttons.** Each now:

1. Calls one `select_bar_type_for_role(document, role)` helper PER ROLE it
   places — `Place Main Bars` calls it twice (top, bottom), `Place Bottom
   Bar` once (bottom), `Place Stirrups` once (stirrups) — showing the
   document's available types in a `pyrevit.forms.SelectFromList` picker
   (multiselect off, `name_attr="Name"`), titled with
   `rft.core.grades.role_picker_label(role)` so A34's required grade is in
   front of the engineer at the moment of choosing.
2. If the picker returns `None` (no types exist, or the engineer cancelled),
   shows `missing_bar_type_selection_message(role)` and exits — **no
   fallback to any default reaches placement.**
3. Resolves the actual bar type via `rft.core.grades.bar_type_for_role`
   (now a per-role lookup, not a mild/high-tensile pair).
4. Reads the bar's diameter FROM the selected type
   (`bar_type_diameter_mm`) — **there is no more typed diameter to cross-
   check it against** (A42; see "A42 supersedes A35" below).
5. Runs the A42 stirrup/high-tensile grade-conflict guard against any
   Rebar already placed on this beam (`existing_rebar_bar_types` +
   `stirrup_grade_conflict_message`) and refuses on a matching element id.
6. Prints `role_grade_report_line(role, bar_type_name)` in the report, so
   which type was used and which grade A34 required for it are both
   visible after the fact.

Per pushbutton:

- **Place Bottom Bar** (S1): one picker (bottom main bars, high tensile
  per A34); Ø_BTM comes from it.
- **Place Main Bars** (S2/S3): TWO pickers — top main bars and bottom main
  bars, each its own `RebarBarType`, both labelled high tensile per A34.
  This is the change that resolves #27's whole premise: Ø_TOP and Ø_BTM can
  now genuinely differ (the default 12/16 mm case), because each has its
  own selected type rather than sharing one.
- **Place Stirrups** (S5): one picker (stirrups, mild per A34), plus the
  hook type selection. Ø_stirrup comes from the selected stirrup type. The
  hook's angle is read back via `hook_angle_deg`; if it comes back
  non-`None` and not within 1° of 180°, placement is blocked
  (`hook_angle_guard_message`). If it comes back `None` (issue #25's
  "cannot be read back at all" case), placement is **not** blocked — the
  pushbutton prints which hook type was used and states plainly that its
  angle could not be verified, and issue #25 stays open rather than being
  falsely marked resolved.

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

## A42 supersedes A35 (ticket #27)

This section replaces the original "diameter-consistency choice, and the
tension it surfaces" write-up above, which described the tension the S7/#20
implementation created rather than resolved. That tension is now the
**decided history**, not an open problem:

**What #20 (A35, as literally read) did.** Exactly two `RebarBarType`
selections total — one mild, one high tensile — plus typed Ø_TOP/Ø_BTM/
Ø_stirrup inputs cross-checked against whichever selected type's own
diameter applied to that role. Because `Place Main Bars` needs the SAME
high-tensile selection for both top and bottom bars (A34 assigns them the
same grade), and a `RebarBarType` **is** a diameter in Revit, a single
selection could agree with at most one of Ø_TOP/Ø_BTM at a time. **Every
default-configuration run (Ø_TOP=12, Ø_BTM=16, rev 2 §8.1) refused
outright.** This was surfaced honestly as GitHub issue
[#27](https://github.com/EssamKader/rft-beam-detailing/issues/27) rather
than silently patched, and the project owner decided the fix on
2026-09-09: **A42**, one `RebarBarType` selection per bar ROLE, recorded in
`docs/spec-amendments.md`.

**What changed under #27:**

1. **Selection axis moves from grade to role.** `Place Main Bars` now shows
   TWO pickers (top, bottom) instead of one — both still labelled high
   tensile per A34, but each is its own `RebarBarType` element, so Ø12 top
   / Ø16 bottom (or any other pairing) works without refusing.
2. **Diameter is derived, not cross-checked.** `Ø_TOP`/`Ø_BTM`/`Ø_stirrup`
   free-text inputs and `diameter_consistency_message` are deleted
   outright — the selected type's own diameter (`bar_type_diameter_mm`) is
   the only number that ever reaches `LD`, the layer offsets, the stirrup
   rectangle, or the §2.2/A7 clearance term. There is no second source left
   to disagree with it.
3. **Grade becomes unverifiable, so it becomes a label and a report line
   instead.** A `RebarBarType` never carried a grade to begin with (that
   was the root of #20's original A35 tension) — A42 makes this explicit
   rather than pretending a cross-check could ever have closed the gap.
   `role_picker_label` puts A34's required grade on the picker title
   itself; `role_grade_report_line` puts it in the report next to the type
   actually used. Neither can block a wrong pick — only the engineer's
   judgement at selection time can.
4. **One thing IS still mechanically checkable: element-id equality.**
   A `RebarBarType` element cannot be both mild and high tensile at once,
   so if the SAME element is used for stirrups and for a high-tensile
   role, that is a guaranteed error, not a judgement call.
   `stirrup_grade_conflict_message` blocks on this, compared by id, never
   by name (two differently-graded types can share a display name in a
   badly kept office template).

**Where the id-equality guard can actually fire — a real architectural gap
found while implementing #27.** Per A42/#27's own instruction, each
pushbutton gathers only the roles it places: `Place Main Bars` picks TWO
high-tensile types (top, bottom) and no stirrup type; `Place Stirrups`
picks ONE mild type and no high-tensile type. **No single pushbutton run
therefore ever holds both a stirrup selection and a high-tensile selection
at the same time to compare.** To make the guard executable at all rather
than dead code, this ticket adds `rft.revit.bar_types.
existing_rebar_bar_types(document, host_element, rebar_style)`: each
pushbutton also reads back the `RebarBarType`s already used by `Rebar`
elements previously placed on the SAME beam (filtered by `RebarStyle`,
`StirrupTie` vs `Standard`) and runs the id-equality check against those.
This only catches the conflict **across separate pushbutton runs on the
same beam** — e.g. running `Place Stirrups` after `Place Main Bars` already
placed a (wrongly) shared type. It is a genuinely new mechanism, not
requested verbatim by the ticket text, and its own `Rebar.GetHostId()`
assumption is `SHAPE UNVERIFIED` and unusually uncertain (see below) —
flagged here as a design decision made to satisfy "must block" rather than
leave the guard unreachable, not as something the ticket explicitly
specified.

## The two review findings on the A42 rework (ticket #27)

**1. `Ø_stirrup` was left as a typed input in `Place Main Bars`, which put
the stirrup diameter back on two sources of truth.**

The reasoning for keeping it was coherent — that pushbutton places no
stirrup, so why make it pick a stirrup type? — but it resolves the wrong
way. `Ø_stirrup` positions *every main bar* relative to the cage: §4's layer
offsets, §6.1's corner-bar inset and §6.3's spacer length all take it. Type
10 there, place Ø12 stirrups from `Place Stirrups`, and every main bar sits
2 mm off its true cover, clashing with the cage, with nothing in the model
showing it. That is precisely the failure A42 was decided to remove, left
alive in the one place that still had a typed diameter.

`Place Main Bars` now selects a stirrup type too — labelled mild St 24/35,
and reported as "positions the main bars; no stirrup is placed by this
pushbutton" — and derives `Ø_stirrup` from it.

**2. The grade-conflict guard was built on an unconfirmed API and failed
open.**

The instruction asked for a check that the stirrup type is not the same
element as a high-tensile type. Under A42's per-role, per-pushbutton
scoping no single run held both, so the instruction as written asked for
something impossible — the implementer spotted that and said so, which was
the right call.

What it then built to satisfy the letter of the instruction was an
`existing_rebar_bar_types` search over the beam's already-placed rebar,
resting on `Rebar.GetHostId()` — the least-confirmed shape in the project —
and catching `AttributeError` as "not this beam's rebar". So if the
assumption were wrong the guard would silently protect nothing while
looking like a guard. That is the false-confidence pattern this project has
policed since S1, and the reason the `SHAPE UNVERIFIED` rule exists at all.

It has been removed, along with its fake and its two tests. Finding 1 makes
it unnecessary anyway: `Place Main Bars` now holds the stirrup selection and
both high-tensile selections at once, so the comparison runs **in-run**,
by element id, where it can actually fire. The other two pushbuttons say in
a comment why they carry no such guard.

**What neither finding fixes:** two separate runs can still select
different stirrup types — `Place Main Bars` positioning to one, `Place
Stirrups` placing another. Nothing in a single run can detect that. Making
the selections consistent across pushbuttons is what **#21 (S8)**'s
per-project persistence is for, and that is now recorded on #21.

## What is NOT verified, and why it matters

The fakes are written to match the API shape the adapter *assumes*. A green
suite proves the adapter's **logic** is self-consistent. It proves nothing
about whether the real Revit API has those members, signatures or return
types — see the running `SHAPE UNVERIFIED` list in `tests/fake_revit_api.py`.
For this ticket specifically:

- **`RebarBarType.BarNominalDiameter`** — assumed read-only, internal units.
  Documentation also lists `BarModelDiameter` as a plausible alternative;
  which one the real API intends is unconfirmed. Since #27, this is now the
  SOLE diameter feeding `LD`, layer offsets, the stirrup rectangle and the
  §2.2/A7 clearance for every role — more load-bearing than under #20's
  cross-check design, where a typed value was the value actually used. If
  wrong, only `rft.revit.bar_types.bar_type_diameter_mm`'s one-line body
  needs to change — every caller does not.
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
  `CommandSwitchWindow`), every `select_bar_type_for_role`/`select_hook_
  type` call in all three pushbuttons needs a one-line fix at the call
  site; the surrounding no-fallback logic (missing-selection guard, grade-
  conflict guard) is unaffected either way.
- **`Rebar.GetHostId() -> ElementId`** (#27, new) — assumed to exist and
  return the hosting element's own id, used by `existing_rebar_bar_types`
  to find Rebar already placed on a beam for the grade-conflict guard.
  This is the LEAST confirmed shape added in this ticket: unlike the other
  items above, it was not carried forward from a prior ticket's research,
  it was introduced specifically to make the id-equality guard reachable
  (see "A42 supersedes A35" above) and has had no documentation
  cross-check performed against revitapidocs.com in this pass. If wrong,
  the guard silently never fires (an exception inside the `try` in
  `existing_rebar_bar_types` is swallowed as "not this beam's rebar"),
  which is a fail-open failure mode, not fail-closed — worth a live-host
  check before relying on this guard in practice.
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
property, now more load-bearing than before; whether `Rebar.GetHostId()`
exists and behaves as assumed, since the grade-conflict guard fails open
(not closed) if it doesn't; and whether `REBAR_HOOK_ANGLE` reads back a real 180° hook's
angle correctly — that last one directly reopens or finally closes #25.
