# What a pyRevit-hosted WPF window is allowed to be

Research for issue #40, part of the UI Wayfinder (#33).

Established against the pyRevit actually installed on the development
machine — **6.1.0.26047**, attached to Revit 2024.3.4 and 2022, both on the
DEFAULT IronPython 2.7 engine — by reading its source and its own shipped
extensions. Where a claim comes from reading code rather than running it,
that is said so; the executable proof is issue #42.

## The short version

A tabbed window with a code-drawn sketch is **supported and conventional**,
not a workaround. The single risk that remains is bitmap image loading, and
the recommendation is to avoid needing it.

## XAML loading, and where paths resolve — CONFIRMED from source

`pyrevit.forms.WPFWindow(xaml_source, literal_string=False)` takes **either a
file path or literal XAML content**, and loads it with `wpf.LoadComponent`
(`pyrevitlib/pyrevit/forms/_ipy.py`).

The path resolution is the important part, from `WPFWindow._determine_xaml`:

```python
xaml_file = xaml_source
if not op.exists(xaml_file):
    xaml_file = os.path.join(EXEC_PARAMS.command_path, xaml_source)
```

**`EXEC_PARAMS.command_path` is the running pushbutton's own folder.** So
`WPFWindow("RftWindow.xaml")` inside `Detail Beam.pushbutton/` resolves to
the XAML sitting beside `script.py`, with no path juggling. This is the
mechanism, not an inference.

`_determine_xaml` additionally supports localisation, which is worth knowing
about even though this project does not need it yet:

- `<name>.<locale>.xaml` and `<name>.en_us.xaml` — a whole localised window,
  preferred over the base file when present.
- `<name>.ResourceDictionary.<locale>.xaml` — a resource dictionary merged
  **after** `LoadComponent`, deliberately, so the XAML's own `Resources` are
  not replaced.

If Arabic labels are ever wanted alongside English (not currently requested),
that is the supported route and it needs no code of ours.

## Precedent in pyRevit's own extensions — CONFIRMED by inspection

**187 `.xaml` files ship inside pyRevit's own extension bundles.** XAML in a
pushbutton folder is the normal way to build a real UI here. Two findings
matter for this project:

- **`Canvas` and `Path` appear in 8 shipped XAML files**, including
  `AboutWindow.xaml`, which draws the pyRevit logo as vector `Path` `Data`
  with gradient brushes and `LayoutTransform`. **Vector drawing on a Canvas
  is proven in this exact hosting context.** That is the sketch's rendering
  surface, and it is not speculative.
- **`SettingsWindow.xaml` defines a `TabItem` `Style` and `ControlTemplate`**
  (`revitTab` / `revitTabTemplate`) — pyRevit itself styles tabs to sit
  correctly in a Revit-hosted window. No shipped file uses a bare
  `<TabControl>`, so the *container* has no precedent even though the tab
  item styling does. This is the one layout element to prove in #42 rather
  than assume; if `TabControl` misbehaves under pyRevit's injected resources,
  the fallback is the `Expander`/`ListBox`-driven navigation
  `SettingsWindow` actually uses, which reaches the same UX by a different
  control.

Also available and precedented: `ScrollViewer` (4 files) and `DataGrid` (4
files), `Ellipse` and `Rectangle` (3 each).

## Resource injection to expect — CONFIRMED from source

`WPFWindow` writes pyRevit's own theme values into the window's resources
(`pyRevitButtonColor`, `pyRevitButtonForgroundBrush` and siblings) before the
window shows. Consequences:

- Controls inherit a pyRevit-consistent look for free, which is desirable —
  the tool should not look foreign inside Revit.
- **A style of ours that collides with those keys will be overwritten**, so
  the sketch's own colours must use distinct resource keys. Cheap to comply
  with; annoying to debug if forgotten.
- Because `_pending_resource_merge` merges dictionaries *after*
  `LoadComponent`, load order is: our XAML resources → pyRevit's injected
  values → any `.ResourceDictionary` file.

## Bitmap images — THE OPEN RISK

No shipped XAML in the entire pyRevit extension set references
`<Image Source="...">` or `BitmapImage`. So there is **no precedent for a
relative bitmap path resolving from a XAML file loaded this way**, and there
is a concrete reason to expect trouble: `wpf.LoadComponent` on a
`StreamReader`/file has no `pack://application` base URI, which is what WPF
normally resolves a relative `Source` against.

**Recommendation: do not depend on it.** Draw the sketch as vectors on a
`Canvas`, which is precedented, resolution-independent, themeable, and — per
issue #41 — is going to be generated from `rft.core` numbers at runtime
anyway rather than being a picture. If a bitmap is genuinely needed (a
photographed ECP symbol reference, say), the robust route is to load it in
code with an absolute path built from `EXEC_PARAMS.command_path`, not from
XAML. Issue #42 should test the XAML-relative case anyway, because **a
definite "no" is as useful as a yes** and settles image-versus-vector for
good.

## Data binding versus direct control reads — RECOMMENDATION

pyRevit's own forms read control values **directly** (`self.some_tb.Text`)
rather than binding to a view model, and `WPFWindow` exposes no binding
helper. `INotifyPropertyChanged` is implementable from IronPython 2.7 but is
awkward and adds a layer that every future maintainer must understand.

**Recommendation: direct reads, with one explicit `redraw()` call.** Wire
each input's change event to a single function that gathers the current
values, calls the `rft.core` functions, and repaints the Canvas. It matches
the surrounding code, it keeps the "one function computes everything the
drawing shows" property that issue #41 depends on, and it makes the redraw
path trivial to reason about. Two-way binding would buy nothing here, since
the sketch is output-only.

Open question for #42: whether that redraw is **smooth enough on every
keystroke**, or needs debouncing / a redraw on focus-loss instead. That is a
feel judgement that has to be made against the real thing.

## High-DPI and window sizing — UNVERIFIED

The development machine is Windows 11 at an unknown scaling factor, and the
sketch pane needs real estate. `WPFWindow` sets no DPI awareness of its own,
so behaviour follows Revit's process-level setting. Not resolvable by
reading source; #42 must show the window on the real display and record
whether a fixed minimum size is workable or the layout has to be fluid.

## Summary for the map

| Question | Status |
|---|---|
| XAML file loaded from a pushbutton folder | **CONFIRMED** — `EXEC_PARAMS.command_path` join, 187 shipped precedents |
| Vector drawing on a `Canvas` | **CONFIRMED** — 8 shipped precedents incl. gradient `Path` art |
| `TabItem` styling in a Revit-hosted window | **CONFIRMED** — pyRevit's own `revitTab` template |
| `TabControl` as the container | **NO PRECEDENT** — prove in #42; documented fallback exists |
| Relative `<Image Source>` from XAML | **EXPECTED TO FAIL** — avoid; prove either way in #42 |
| Direct control reads + explicit redraw | **RECOMMENDED** — matches pyRevit's own pattern |
| Redraw smoothness per keystroke | **UNVERIFIED** — feel judgement, #42 |
| High-DPI sizing | **UNVERIFIED** — #42, on the real display |
