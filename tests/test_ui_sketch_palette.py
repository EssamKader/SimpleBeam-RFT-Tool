# -*- coding: utf-8 -*-
"""#49 (U5) -- the sketch's style-key -> XAML brush mapping.

Two directions, both load-bearing: every style ``rft.ui.sketch`` can emit
must be mapped (or the renderer draws it with WPF's invisible default),
and every brush name this module names must actually be declared in
``SimpleBeamWindow.xaml`` (or the renderer throws "Cannot find resource"
at paint time on a live host -- the same class of defect
``test_simple_beam_xaml.py::test_every_static_resource_reference_is_defined``
already guards for every other ``StaticResource`` in the file).
"""

import io
import os
import re

from rft.ui import sketch
from rft.ui.sketch_palette import STYLE_BRUSH_KEYS, brush_key_for_style

XAML_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "SimpleBeamRFT.extension", "RFT-Tools.tab",
    "Beams.panel", "Simple Beam.pushbutton", "SimpleBeamWindow.xaml",
)


def _declared_xaml_brush_keys():
    text = io.open(XAML_PATH, encoding="utf-8").read()
    return set(re.findall(r'x:Key="([A-Za-z0-9_]+)"', text))


def test_every_sketch_style_key_has_a_brush_mapping():
    missing = sorted(sketch.STYLE_KEYS - set(STYLE_BRUSH_KEYS))
    assert not missing, (
        "these rft.ui.sketch style keys have no brush mapping, so the "
        "renderer would draw them with WPF's invisible default: %s" % missing
    )


def test_no_stale_brush_mapping_for_a_style_that_no_longer_exists():
    stale = sorted(set(STYLE_BRUSH_KEYS) - sketch.STYLE_KEYS)
    assert not stale, (
        "these brush mappings name a style key rft.ui.sketch no longer "
        "emits: %s" % stale
    )


def test_every_mapped_brush_is_declared_in_the_xaml():
    declared = _declared_xaml_brush_keys()
    missing = sorted(set(STYLE_BRUSH_KEYS.values()) - declared)
    assert not missing, (
        "these brush names are used by the sketch palette but never "
        "declared with x:Key in SimpleBeamWindow.xaml, which throws "
        "'Cannot find resource' at paint time on a live host: %s" % missing
    )


def test_brush_key_for_style_raises_on_an_unknown_style():
    try:
        brush_key_for_style("not_a_real_style")
    except KeyError:
        pass
    else:
        raise AssertionError(
            "brush_key_for_style must raise KeyError for an unmapped style, "
            "not silently return a fallback brush."
        )
