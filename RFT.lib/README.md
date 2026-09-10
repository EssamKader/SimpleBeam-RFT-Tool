# `RFT.lib` — the shared library extension

This is a pyRevit **library extension**, not a folder of loose modules.
Any folder whose name ends in `.lib` is collected by
`get_installed_ui_extensions` and added to the module path of **every** UI
extension under the same registered search root:

```python
# pyrevitlib/pyrevit/extensions/extensionmgr.py
def _update_extension_search_paths(ui_ext, lib_ext_list, pyrvt_paths):
    for lib_ext in lib_ext_list:
        ui_ext.add_module_path(lib_ext.directory)
```

That is why `rft` lives here and not in `SimpleBeamRFT.extension/lib/`,
where only the Simple Beam button could have imported it.

Three rules, each guarded by `tests/test_library_extension_layout.py`
because each fails **silently** — the beam tool keeps working on this
machine while a second element cannot import anything:

1. **The folder name must end in `.lib`.** `LibraryExtension.matches` is a
   suffix test. `RFT-lib` is an ordinary folder pyRevit says nothing about.
2. **The package sits at `RFT.lib/rft`, never `RFT.lib/lib/rft`.** The path
   added is this directory itself.
3. **No UI extension may contain its own `rft` copy.** pyRevit's own
   comment: paths internal to an extension "will take precedence over
   paths added by this method." The shadowing copy is the one that drifts.

`RFT.lib` needs no `extension.json` — `LibraryExtension` reads only the
directory name.

## What is in here

| package | contents |
|---|---|
| `rft/core` | pure spec logic in millimetres — no Revit import, no UI. Fully unit-tested |
| `rft/revit` | the Revit API boundary: host validation, bar types, geometry, placement, units |
| `rft/ui` | window-agnostic UI logic: input parsing, review derivation, the report, sketch geometry, label layout, persistence |

`rft/core` and `rft/ui/sketch*` import nothing outside the standard
library, which is what makes them testable under CPython. `rft/revit`
imports `Autodesk.Revit.DB` and can only run inside Revit;
`tests/fake_revit_api.py` stands in for it.

**Which of these a new element can reuse, and which it cannot, is
audited per module in `docs/reuse-for-new-elements.md`.** Read that before
importing from here for a column, wall, slab or footing.

Everything here runs under **IronPython 2.7** in production. The
constraints that implies — the PEP 263 encoding cookie, no f-strings, no
Python-3-only stdlib — are enforced by
`tests/test_ironpython_compat.py`, which walks this folder and the UI
extension.
