# -*- coding: utf-8 -*-
"""The sketch's style-key -> XAML brush mapping (issue #49, U5).

PURE DATA. No ``pyrevit``, ``Autodesk`` or WPF import -- a plain dict of
strings, kept in its own module (rather than inline in ``script.py``, which
cannot be imported or tested at all) so the mapping itself is checked two
ways under plain CPython:

1. Every key ``rft.ui.sketch.STYLE_KEYS`` can emit has an entry here
   (``tests/test_ui_sketch.py``), so a new style key added to the drawing
   without a matching brush cannot reach a live host silently -- it would
   draw with WPF's default (black on white), which nothing here can
   execute to notice.
2. Every brush name this module names is declared with an ``x:Key`` in
   ``DetailBeamWindow.xaml`` (``tests/test_detail_beam_xaml.py``), which is
   how a typo'd resource name is caught before it becomes a
   "Cannot find resource" exception at paint time on a live host.

``script.py``'s renderer does no colour arithmetic of its own -- it looks
a style key up here, then ``self.FindResource(name)`` (or the window's
``Window.Resources`` dictionary) for the actual ``SolidColorBrush``. That
split is what keeps the renderer a "walk the list, map, draw" function
with no judgement calls of its own (A48, applied to presentation rather
than to detailing arithmetic, since a colour is not a spec quantity but
a silently-wrong one still misleads the same way a silently-wrong
dimension would).

One brush here, ``PassGreen``, does not exist among the ten brushes
``DetailBeamWindow.xaml`` already declares for #60's palette -- none of
those ten is green, and the notation SVG (docs/ui/sketch-notation.svg)
uses green specifically for "complies" (crack/skin bars, a passing
spacing dimension). It is declared in this ticket's XAML edit, in
``Window.Resources`` alongside the existing ten, never on the ``<Window>``
element itself (the rc6 defect this project already hit once).
"""

# style key (from rft.ui.sketch.STYLE_KEYS) -> XAML x:Key brush name.
STYLE_BRUSH_KEYS = {
    "concrete": "InkPrimary",
    "cover": "InkMuted",
    "stirrup": "SkyBlueDeep",
    "stirrup_outer": "BorderSubtle",
    "bar_main": "InkPrimary",
    "bar_crack": "PassGreen",
    "spacer": "WarningAmber",
    "dimension": "InkMuted",
    "dimension_pass": "PassGreen",
    "dimension_fail": "DangerRed",
    "schematic": "SkyBlueDeep",
    "zone_dense": "SkyBlueDeep",
    "zone_normal": "InkMuted",
    "support": "InkMuted",
    "caption": "InkMuted",
}


def brush_key_for_style(style_key):
    """The XAML ``x:Key`` brush name for one sketch style key.

    Raises ``KeyError`` naming the style key itself if it is not mapped --
    deliberately, rather than a silent fallback brush, so an unmapped
    style key fails loudly the moment the renderer tries to draw it,
    instead of drawing invisibly on a live host that nothing here can
    execute to notice.
    """
    return STYLE_BRUSH_KEYS[style_key]
