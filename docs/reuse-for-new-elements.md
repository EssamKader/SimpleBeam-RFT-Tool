# Starting a new element (columns, walls, slabs, footings)

Written for a future session that begins "detail the reinforcement of a
column." Read this before writing any code, because the single most
important decision — where the shared library lives — has to be made
BEFORE the second element exists, not after.

Nothing in this document is scheduled work. It records what is reusable,
what is not, and what has to be decided first.

---

## 1. The blocker, and the mechanism that solves it

`rft.core`, `rft.revit` and `rft.ui` are element-agnostic in large part
(section 3 below). But today they live at:

```
SimpleBeamRFT.extension/lib/rft/...
```

pyRevit puts a UI extension's own `lib/` folder on **that extension's**
module path only. So a second extension — `ColumnRFT.extension` — could
not `import rft.core.spacing`. The shared code is real but unreachable.

pyRevit has a first-class mechanism for exactly this: a **library
extension**, a folder whose name ends in `.lib`.

Verified in the pyRevit source at
`pyrevitlib/pyrevit/extensions/extensionmgr.py`:

```python
def _update_extension_search_paths(ui_ext, lib_ext_list, pyrvt_paths):
    for lib_ext in lib_ext_list:
        ui_ext.add_module_path(lib_ext.directory)
```

`get_installed_ui_extensions` collects every `.lib` extension found under
the registered search roots and adds each one to the module path of
**every** UI extension. `LIB_EXTENSION_POSTFIX = '.lib'`, and
`LibraryExtension.matches` is a plain suffix test on the folder name.

**The path added is the `.lib` folder ITSELF, not a `lib/` subfolder
inside it.** So the package must sit directly at `RFT.lib/rft/`:

```
<search root>/
├── RFT.lib/                     <- on every extension's sys.path
│   └── rft/
│       ├── core/                (shared: sections, spacing, ties)
│       ├── revit/               (shared: host, bar types, placement)
│       └── ui/                  (shared: parsers, label layout, store)
├── SimpleBeamRFT.extension/     <- thin: button + window + script
└── ColumnRFT.extension/         <- thin: button + window + script
```

Caveats, stated because they are the ones that bite:

- Verified by **reading pyRevit's source, not by running it.** Confirm on
  a live host before committing to the layout.
- An extension's own internal `lib/` paths are added FIRST and therefore
  **take precedence** over `.lib` paths (the source says so explicitly).
  A leftover `SimpleBeamRFT.extension/lib/rft/` would silently shadow the
  shared one. Delete it in the same commit that creates `RFT.lib`.
- Both folders must be under a **registered search root**, which is the
  folder that CONTAINS them — the same root already registered today.

## 2. The decision that has to come first

The extraction is mechanical. Where the shared library is **versioned**
is not, and it cannot be deferred past the second element:

| option | consequence |
|---|---|
| **Monorepo** — `RFT.lib` and every `.extension` in this repo | one tag covers library and all tools; but this repo is named `SimpleBeam-RFT-Tool`, which becomes a lie, so it would be renamed again |
| **Separate `RFT-Lib` repo** | each element repo stays small and independently taggable; but a tag of `ColumnRFT` no longer pins the library it was tested against, so "deploy from a tag" stops being sufficient |
| **Library duplicated per element repo** | independent, and immediately drifts — this project already has two proven cases (`ZONE_LAYOUT_FLAGS`, the support-detection dict) where a duplicate that agreed on the day it was written was still a defect |

No recommendation is recorded here on purpose. It is a Grill question for
the project owner.

The **ribbon** side is already solved and needs no decision: pyRevit
merges tabs BY TITLE across extensions, so any new element declares
`RFT-Tools` as its tab title and lands beside Simple Beam. The rule set
in `v0.3.0-rc3` is **the tab names the domain, the panel names the
element, the button names the case** — a column tool is
`RFT-Tools` / `Columns` / whatever case it handles.

## 3. What is actually reusable

Judged by whether the public signature contains anything beam-shaped.

### Reusable as-is — no beam knowledge at all

| module | why it transfers |
|---|---|
| `revit/units.py` | 19 lines, internal-to-mm both ways |
| `revit/bar_types.py` | collects `RebarBarType` / `RebarHookType`, reads diameter, hook angle and hook style. A column asks the identical questions |
| `revit/placement.py` | `place_anchored_bar`, `run_in_transaction`, `bar_point_at_uv` — a bar in a `u`/`v` frame, which every element has |
| `core/spacing.py` | every signature is `(b_mm, cover_side_mm, stirrup_dia_mm, bar_dia_mm, bar_count)`. `b` is just "the width of the face being checked" — a column face and a wall face ask exactly this |
| `core/layout.py` | `first_layer_offset_mm`, `layer_offset_mm`, `corner_bar_u_positions_mm` — bars stacked inside a closed tie. **Identical arithmetic for a column** |
| `ui/inputs.py` | the field parsers and their refusal messages |
| `ui/sketch_layout.py` | pixel-space label placement. Zero domain knowledge, and it is what made the sketch readable |
| `ui/sketch_palette.py` | style keys |

### Reusable after a rename or a split

| module | what to do |
|---|---|
| `core/stirrups.py` | `centreline_leg_dimensions_mm` / `outer_leg_dimensions_mm` / `stirrup_curve_endpoints_mm` / the closure types **are a column tie**, unchanged. `stirrup_zones_mm`, `ZONE_LAYOUT_FLAGS` and `EDGE_OFFSET_MM` are the beam's three-zone rule — split those out |
| `core/guards.py` | `GuardMessage`, `SEVERITY_BLOCKING`, `is_blocking` are the generic contract; the module also imports `anchorage` and `stirrups`. Move the namedtuple to its own module |
| `core/grades.py` | the role-to-grade mapping mechanism is generic and already carries `ROLE_SPACER`; a column adds its own roles. The hook angle/style guards transfer untouched |
| `revit/host.py` | `validate_rebar_host`, `face_normal`, `classify_face_role`, `classify_exposed_faces` work for any rebar host. `read_beam_face_covers_mm` is beam-NAMED but takes `u_dir`/`v_dir`/`axis` — generic once given axes |
| `ui/persistence.py` | the **pattern** transfers whole, including the load-bearing part: withhold the fields that would restore INTENT. The slot name and field lists are per-tool |
| `ui/derivation.py` | same — the U6 "state the derivation in words" pattern transfers, its content does not |

### Do not try to reuse

`core/anchorage.py` (support anchorage `a`/`b`), `core/crack_bars.py`
(`h > 700`), `core/plan.py`, `revit/geometry.py` (beam axis, endpoints,
support detection), `revit/stirrups.py`'s zone layout, `ui/report.py`,
`ui/sketch.py`. These encode the single-span beam case. A column's
geometry module is a new module, not a parameter.

## 4. What transfers better than the code

The code is the smaller half of what this project produced.

1. **`tools/prove_guards.py`** — the mutation prover, 335 lines, 29
   cases. It breaks each guard on purpose and fails if the guard does not
   notice. It found **four checks in this repo that could not fail**: two
   written with a literal backspace byte where an escape belonged, one
   satisfied by a comment, one short-circuited by `if False and ...`.
   Nothing else found any of them. Copy this first, before any element
   code. Two design details are load-bearing: it **refuses to run on a
   target with uncommitted changes** (it damaged the repo once), and it
   uses `subprocess.run` with a timeout rather than `call` with a pipe
   (an unread pipe deadlocks on a large failure message).

2. **`docs/spec-amendments.md`** — the amendment ledger: `A1..A49` plus
   `R`-numbered resolutions, each naming what changed, why, and which
   issue decided it. This is what makes a spec disagreement resolvable
   six months later instead of re-litigated. A new element starts its own
   ledger; it does not extend this one.

3. **`docs/verification/*.md`** — standalone write-ups proving logic by
   mock-object simulation. Mandatory here, because IronPython under
   pyRevit cannot be executed in the dev environment, so a green test
   suite does not cover the Revit API path. Any new element has the same
   gap and needs the same discipline.

4. **`.github/workflows/tests.yml`** plus the test that walks `tests/`
   and `tools/` for third-party imports the workflow does not install.
   CI failed on its first ever run for exactly that reason.

5. **The `ast` lesson.** `ast.parse` reads `script.py` WITHOUT importing
   it, so a guard over un-importable code can be structural rather than a
   substring search. Grep-based guards are defeated by comments and by
   short-circuits; four of them were. Treating "cannot import" as "can
   only grep" is what made them weak.

6. **The release discipline** — `master` means the code exists, a tag
   means it was verified on a live host, and only a tagged commit is ever
   loaded into Revit. `v0.2.0` needed eight candidates and `v0.1.0` six.
   Budget candidates for a new element too.

7. **`docs/ui/sketch-notation.svg`** — authored SVG, true scale, with a
   twelve-row legend mapping drawing to meaning to symbol to spec
   section. It doubles as the renderer's specification, sharing the
   renderer's coordinate convention. Note its own stated limit: it is a
   starting point for clarity and **not a claim of ECP compliance**.

## 5. Order of work for a new element

1. Decide section 2 (where the library lives). Nothing else can start.
2. Extract `RFT.lib` from the beam extension, delete the old `lib/`,
   confirm the beam tool still loads on a live host, tag that. **A
   refactor with no user-visible change deserves its own tag** so a
   regression is bisectable.
3. Copy the prover and the CI workflow into the new element's tests
   before writing element code.
4. Write the new element's spec and open its own amendment ledger.
5. Only then write geometry.

## 6. Known-open, and inherited

Anything unresolved in the beam tool that a new element would inherit
should be read first — currently issue #61 (Place does not refuse on a
spacing violation), #26 and #32 (engineering rulings), and the spacer
gap: `Ø_spacer` is used as a dimension and drawn on the sketch, but no
spacer bar is ever placed and there is no spacer bar-type picker,
contrary to amendment A42's five roles.
