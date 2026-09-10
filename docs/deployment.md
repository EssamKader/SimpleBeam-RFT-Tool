# Deployment

## Load from a tagged commit, never from `master` HEAD

Per `CHANGELOG.md`'s "Delivery model" section: a merge to `master` means the
code exists, not that it is safe to load. **No tag has been cut for this
project yet** -- every ticket so far has closed on documentation-only
research and mock-object simulation (`docs/verification/`), because nothing
in this project's development environment can execute Revit API code
(`CONTEXT.md`, "no live Revit host"). The placement path (`Rebar.CreateFromCurves`,
host validation, cover read-back, hook family/angle read-back) has **never
executed against a real Revit session**.

Do not point pyRevit at `master`, and do not point it at the working tree:
a registered search path loads whatever is on disk *now*, so an edit to
`master` silently changes what is loaded inside a running Revit session.
Check the tag out into its own detached worktree and register that instead
-- the loaded copy then cannot drift, while `master` stays editable.

```
git worktree add "<somewhere>/rft-<tag>" <tag>
pyrevit extensions paths add "<somewhere>/rft-<tag>"
```

Then reload pyRevit (its ribbon "Reload" button, or restart Revit). The
equivalent GUI route is pyRevit Settings -> Custom Extension Directories.
To back the install out: `pyrevit extensions paths forget "<path>"`, then
`git worktree remove "<path>"`.

**The registered path is the folder that *contains* `SimpleBeamRFT.extension`,
not the `.extension` folder itself.** pyRevit scans each search path for
child directories whose names end in `.extension`; naming the bundle
directly registers a path with no extensions in it, and the tab never
appears.

*(An earlier draft of this document gave
`pyrevit extend "<repo>/SimpleBeamRFT.extension"` after a
`git checkout <tag>`. That command does not do this job -- verified against
the installed CLI, `pyrevit v6.1.0.26047`: `pyrevit extend` **clones a
third-party extension from a git repo URL** into pyRevit's own extensions
directory (`pyrevit extend (ui | lib) <extension_name> <repo_url>`), so
handing it a local folder path is not a local install at all. `pyrevit
extensions paths add` is the command that registers an existing folder.
The `git checkout <tag>` half was also poor advice on its own: it detaches
the repo's only working tree, so the project's own source and the loaded
copy become the same detached checkout. Corrected on review before the
first install.)*

## What must exist in the model before the buttons work

None of the four pushbuttons falls back to a document default or "the first
one found" for the following -- each is an explicit, blocking selection or
read-back (rev 2 section 1.1, A34/A42; issue #27). Set these up in the
target Revit model/template first, or every pushbutton will refuse at the
first missing selection:

1. **A `RebarBarType` per role.** A `RebarBarType` *is* a diameter in Revit
   (A42), so the normal case of a Ø12 top bar and a Ø16 bottom bar needs two
   separate type elements, not one type reused with a typed diameter. Roles
   used across the four pushbuttons:
   - `ROLE_TOP_MAIN`, `ROLE_BOTTOM_MAIN` -- high tensile St 36/52
     (`rft/core/grades.py`).
   - `ROLE_STIRRUP` -- mild St 24/35. Selected (but not placed) by
     "Place Main Bars" and "Place Crack Bars" too, since its diameter feeds
     the layer-offset and corner-bar-inset formulas both pushbuttons need
     (rev 2 sections 4, 6.1) -- it must be the SAME type element you intend
     to place with "Place Stirrups", or the main bars end up positioned
     against a stirrup diameter that is never actually placed.
   - `ROLE_CRACK` -- high tensile St 36/52, used only by "Place Crack Bars"
     when section 5's h > 700 mm trigger fires.

   **A bar type's NAME routinely disagrees with its diameter, and the name
   is not what the tool uses.** Measured live in the verification model
   after a library import:

   | Type name | Actual `BarNominalDiameter` |
   |---|---|
   | `10M` | **9.50 mm** |
   | `13M` | 12.70 mm |
   | `16M` | **15.90 mm** |
   | `19M` | 19.10 mm |
   | `22M` | 22.20 mm |
   | `25M` | 25.40 mm |

   Those are Imperial #3/#4/#5/#6/#7/#8 bars carrying metric-looking `M`
   designations -- not ECP metric bars. Picking `16M` for what the spec
   calls a Ø16 bar gives **15.9 mm**, and that 15.9 then flows correctly
   through every formula (`LD = 60 × Ø`, the §6.2 minimum spacing, the §4
   layer offsets, the §2.2 clearance), because A42 makes the type's own
   diameter the single source of truth. The tool is not wrong here -- the
   *model* does not contain the bars the spec assumes.

   Two consequences worth knowing before a production run:

   - **The picker labels every type with its measured diameter**
     (`16M  --  15.9 mm`), which is the only place this is visible before
     committing. Read the millimetres, not the name.
   - **If you want true ECP diameters, import or create metric bar types**
     (Ø10, Ø12, Ø16, Ø18, Ø20, Ø22, Ø25) in the target model or template.
     Nothing in the tool requires it -- it details correctly with whatever
     diameter the selected type reports -- but a schedule reading `16M` at
     15.9 mm is not what an ECP drawing set expects.

2. **A `RebarHookType` from the Stirrup/Tie family, at 135 degrees**
   (rev 2 section 7.3, A45, superseding A33's 180 degrees; issue #25/#31,
   verified against a live Revit 2024 host, `RevitAPI 24.3.40.0`).

   **A stock library normally satisfies this already.** The live probe
   found the stock Stirrup/Tie hooks shipping at **90 and 135 degrees**
   (family 1), so the 135-degree hook A45 requires is typically present
   without any setup. What a stock library does *not* ship is a
   Stirrup/Tie hook at **180 degrees** -- every stock 180-degree hook is
   **Standard** family (`REBAR_HOOK_STYLE == 0`), and
   `RebarStyle.StirrupTie` rejects those with an opaque
   `InternalException` whatever the angle. That absence is precisely why
   A45 moved the required angle from A33's 180 to 135.

   *(An earlier draft of this document said the opposite -- that a stock
   template's stirrup hooks are "commonly 180 degrees" and that the hook
   "usually needs creating". That was A33-era reasoning left standing
   after the angle changed. Corrected on review.)*

   **A hook's NAME does not determine its family.** The live model
   contains a hook type called `Stirrup/Tie - 45` whose
   `REBAR_HOOK_STYLE` is **0 (Standard)**, alongside `Standard - 135 deg.`
   at the required angle in the wrong family. "Place Stirrups" therefore
   reads the parameter, never the name: it filters its picker to family 1
   and refuses outright, naming the fix, if the model has none -- it does
   not fall back to any hook found under a matching name.

   Create a Stirrup/Tie-family hook at 135 degrees only if the target
   model genuinely has none (duplicate any Stirrup/Tie hook and set its
   `Hook Angle` to 135; that parameter is writable).

3. **Cover types defined on every exposed face of the beam being
   detailed, and of both its supports.** `RebarHostData.GetRebarHostData(beam)`
   must return non-null and `.IsValidHost()` must return true (structural
   framing, structural usage set, concrete material) before any pushbutton
   proceeds (`docs/research/revit-api-strategy.md` §4). Beyond that, an
   **undefined face `RebarCoverType` silently falls back to a document
   default** rather than erroring -- this project's adapter (issue #30,
   `rft/revit/host.py`) explicitly reads back each face's own cover so a
   silent default can never masquerade as the spec's `Cover` input, and
   raises a `HostValidationError` naming the offending face/element instead.
   Define cover types on: the beam's top, bottom, side and (where an end is
   unsupported) end faces; and each support's own side faces used for the
   support-side cover the anchorage formulas need (rev 2 section 2.4, A8).

## Known gaps carried into this deployment

These are recorded in `CHANGELOG.md`'s "Known risks" section and are not
resolved by this ticket (packaging/metadata only, per its own scope):

- The cover read-back API (#23/#30) and the stirrup hook family/angle
  read-backs (#25) **are** confirmed against a live host -- Revit 2024,
  `RevitAPI 24.3.40.0`, including a rotated (45 degree) beam for the face
  classification. What is **not** confirmed is any of it executing through
  the tool's own IronPython path inside pyRevit: every live probe so far
  was driven as C# through a connector, so `pyrevit.forms.SelectFromList
  .show`'s signature and the pushbuttons' own end-to-end behaviour remain
  unexercised. A green test suite plus a live API probe still does not
  equal "the button works".
- Bar-type selections are not shared or persisted between pushbutton runs
  (#21/S8 scope) -- running "Place Main Bars" and "Place Stirrups"
  independently on the same beam can position main bars against a
  different stirrup diameter than the one actually placed if different
  types are picked each time.
- The A7 top/bottom centreline clearance check warns and places anyway; it
  has no defined failure behaviour yet (#26).

## Icons

`icon.png` per pushbutton is the pyRevit convention (confirmed against this
machine's own pyRevit installation, `pyrevitlib/pyrevit/extensions/__init__.py`,
`DEFAULT_ICON_FILE = 'icon' + '.png'`). **No icons ship with this extension yet**, and the
ribbon will render pyRevit's own default glyph for each button until they
do. That is deliberate rather than an oversight.

Generated placeholder glyphs (numbered squares) were produced and then
removed on review. Named `icon.png` they would have presented
machine-generated squares as finished artwork; named anything else --
`icon.placeholder.png`, as first shipped -- pyRevit never reads them at
all, so they were four inert binaries whose only effect was to suggest
icons were handled. This project has twice before removed code that
existed to look complete (`existing_rebar_bar_types` in #27,
`crack_bar_unsupported_end_straight_run_mm` in #19); an unread PNG is the
same thing in a different file format. The requirement is recorded here
instead, which is what a placeholder was standing in for.

**To add icons:** drop a square `icon.png` (32x32 or larger; pyRevit
scales it) into each `*.pushbutton` folder beside its `script.py`.
`DEFAULT_ICON_FILE = 'icon' + '.png'` in this machine's
`pyrevitlib/pyrevit/extensions/__init__.py` is the name pyRevit looks for.
A `icon.dark.png` alongside it is used for dark themes. No code change is
needed -- the buttons pick them up on the next pyRevit reload.
