# -*- coding: utf-8 -*-
"""The Review tab's derivation rule (issue #50, U6): which sections of
reinforcement are REQUESTED, and the reason string the engineer reads when
a section is not.

Pure Python: no Revit import. The one piece of ``rft.core`` logic this
module leans on is ``crack_bars.crack_reinforcement_triggered`` (the
strict ``h > 700`` predicate, rev 2 section 5) -- reused rather than
reimplemented, since ``rft.core.crack_bars`` itself has no Revit import
and re-typing ``h_mm > 700`` here would be a second copy of that trigger
free to drift from the first (exactly the class of duplication this
project's amendments keep closing). No OTHER detailing arithmetic lives
here; this module only decides REQUESTED/NOT REQUESTED and says why.

The rule (specs/ui-single-window.md U6, docs/spec-amendments.md A42, A50):

- Main bars, per face -- requested when that face's ``RebarBarType`` is
  selected AND its bar count is non-blank. Faces are independent: top can
  be requested with bottom not, and vice versa (#48's blank-count
  semantics is what makes "non-blank" a real distinction -- see
  ``rft.ui.inputs``).
- Stirrups -- requested when the ``RebarHookType`` is selected. The hook
  is stirrup-exclusive (main bars need the stirrup *bar type* for their
  offsets, never the hook), so this can never be confused with a main-bar
  requested state.
- Crack bars -- requested when a crack ``RebarBarType`` is selected AND
  ``h > 700`` (strict) AND both faces are DETAILED, meaning each face has
  its own bar type AND its own layer count. **A50** (ruled 2026-09-10):
  section 5.1's ``H_avail`` spans the innermost top layer to the innermost
  bottom layer, so one face alone cannot produce it -- refuse and name the
  missing face(s), rather than computing ``H_avail`` from an assumed
  layer count (the exact v0.1.0 defect #48 closed). Note this checks the
  LAYER COUNT per face, not the per-layer bar COUNT main bars need -- A26's
  ``H_avail`` is built from ``layer_offset_mm(..., layer_n=layers)``, which
  needs a bar type (for its diameter) and a layer count, never a bar count.

Python 2/3 compatible: IronPython 2.7 is the runtime that loads this module
in production (``tests/test_ironpython_compat.py`` enforces the
constraints -- no f-strings, PEP 263 cookie above).
"""

from collections import namedtuple

from rft.core.crack_bars import crack_reinforcement_triggered

SectionDerivation = namedtuple("SectionDerivation", ["requested", "reason"])

ReviewDerivation = namedtuple(
    "ReviewDerivation",
    ["top_main", "bottom_main", "stirrups", "crack_bars", "any_requested"],
)

# A main face's gap (issue #65), distinct from ``main_bar_face_derivation``'s
# two-field REQUESTED/NOT-REQUESTED rule. ``missing`` names, in the fixed
# order (bar type, layer count), whichever of those two the refusal is
# about -- a bar count is never named here, because a refusal only ever
# fires when a bar count IS present (see ``main_bar_face_gap``).
FaceGap = namedtuple("FaceGap", ["refuses", "missing"])

# This is not itself a numbered rev 2 rule -- it is A42's no-silent-
# fallback principle (rev 2 section 1.1) applied to a gap A42 did not
# originally cover: a face left PARTLY entered. Cited the same way
# ``rft.core.grades.BAR_TYPE_SELECTION_SPEC_SECTION`` cites A42 for a
# missing bar type selection.
FACE_GAP_SPEC_SECTION = "rev 2 section 1.1 (A42) -- issue #65"


def main_bar_face_derivation(face_label, bar_type_selected, bar_count):
    """One face's requested/not-requested state (this ticket's rule):
    requested only when BOTH its ``RebarBarType`` is selected AND its bar
    count is non-blank (``bar_count`` is ``None`` on blank -- #48's
    ``parse_optional_positive_int``, never ``0`` and never a default).
    """
    if bar_type_selected is not None and bar_count is not None:
        return SectionDerivation(
            True, "{}: will be placed ({} bars/layer).".format(face_label, bar_count)
        )
    missing = []
    if bar_type_selected is None:
        missing.append("no bar type selected")
    if bar_count is None:
        missing.append("no bar count entered")
    return SectionDerivation(
        False, "{}: not requested ({}).".format(face_label, ", ".join(missing))
    )


def main_bar_face_gap(bar_type_selected, bar_count, layer_count):
    """Whether one main face REFUSES Place (issue #65, corrected rule).

    The bar COUNT is the statement of intent for a face; a bar TYPE or a
    LAYER COUNT present alone is not, because either can be a leftover, a
    default, or a value #54's persistence restored on purpose while
    withholding the count (see ``tests/test_ui_persistence.py``'s
    ``test_a_full_restore_leaves_every_section_not_requested`` and this
    module's own regression test against it). So this function refuses a
    face ONLY when a bar count IS entered and either the bar type or the
    layer count for that SAME face is still missing -- never on a bar
    type or layer count present without a count, however it got there.

    This is deliberately ASYMMETRIC with ``main_bar_face_derivation``'s
    two-field REQUESTED rule: a count with a type but no layers is
    REQUESTED (by that rule) yet still refuses here, because it is the
    exact shape that reaches ``core.plan.face_plan`` and raises
    ``TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'``
    from inside an open transaction (confirmed directly against
    ``face_plan``; see ``tests/test_ui_derivation.py``). A count with
    neither type nor layers refuses too, naming both. Every other
    combination -- including a type and layers present with NO count, the
    exact #54 restored-beam state -- is silent.

    Returns a ``FaceGap``: ``refuses`` is ``True`` only when ``bar_count``
    is not ``None`` and at least one of {bar type, layer count} is
    missing; ``missing`` names, in the fixed order (bar type, layer
    count), whichever of those two is absent -- never "bar count", since
    a refusal only ever fires when the count IS present.
    """
    if bar_count is None:
        return FaceGap(False, ())
    missing = []
    if bar_type_selected is None:
        missing.append("bar type")
    if layer_count is None:
        missing.append("layer count")
    return FaceGap(bool(missing), tuple(missing))


def stirrups_derivation(hook_type_selected):
    """Stirrups are requested when the ``RebarHookType`` is selected --
    the hook is stirrup-exclusive, so it cannot be confused with the
    stirrup *bar type* main bars also need for their layer offsets.
    """
    if hook_type_selected is not None:
        return SectionDerivation(True, "Stirrups: will be placed.")
    return SectionDerivation(
        False, "Stirrups: not requested (no RebarHookType selected)."
    )


def crack_bars_derivation(crack_bar_type_selected, h_mm,
                           top_bar_type_selected, layers_top,
                           bottom_bar_type_selected, layers_btm):
    """Crack bars are requested only when ALL of: a crack ``RebarBarType``
    is selected; ``h > 700`` (strict, rev 2 section 5); and both faces are
    detailed -- a bar type AND a layer count on top *and* bottom (A50).

    Checked in that order so the reason names the FIRST cause that blocks,
    matching the reading order an engineer would fix them in: pick a crack
    bar type, confirm ``h`` actually triggers section 5, then detail
    whichever face is still missing.
    """
    if crack_bar_type_selected is None:
        return SectionDerivation(
            False, "Crack bars: not requested (no crack bar type selected)."
        )
    if h_mm is None or not crack_reinforcement_triggered(h_mm):
        h_report = "not yet known" if h_mm is None else "{:.1f} mm".format(h_mm)
        return SectionDerivation(
            False,
            "Crack bars: not requested (h = {} -- rev 2 section 5 requires "
            "h > 700 mm, strict).".format(h_report),
        )
    missing_faces = []
    if top_bar_type_selected is None or layers_top is None:
        missing_faces.append(_missing_face_detail("top", top_bar_type_selected, layers_top))
    if bottom_bar_type_selected is None or layers_btm is None:
        missing_faces.append(_missing_face_detail("bottom", bottom_bar_type_selected, layers_btm))
    if missing_faces:
        return SectionDerivation(
            False,
            "Crack bars: not requested ({} -- A50: H_avail spans the "
            "innermost top layer to the innermost bottom layer, so both "
            "faces must be detailed before it can be computed).".format(
                "; ".join(missing_faces)
            ),
        )
    return SectionDerivation(True, "Crack bars: will be placed.")


def _missing_face_detail(face_name, bar_type_selected, layers):
    missing = []
    if bar_type_selected is None:
        missing.append("no {} main bar type selected".format(face_name))
    if layers is None:
        missing.append("no {} layer count entered".format(face_name))
    return "{} face: {}".format(face_name, ", ".join(missing))


def compute_review_derivation(top_bar_type_selected, top_bar_count,
                               bottom_bar_type_selected, bottom_bar_count,
                               hook_type_selected,
                               crack_bar_type_selected, h_mm,
                               layers_top, layers_btm):
    """The whole Review-tab derivation in one call: each section's
    ``SectionDerivation`` plus ``any_requested``, which is what disables
    Place when nothing at all has been asked for (this ticket's brief).
    """
    top_main = main_bar_face_derivation("Top main bars", top_bar_type_selected, top_bar_count)
    bottom_main = main_bar_face_derivation(
        "Bottom main bars", bottom_bar_type_selected, bottom_bar_count
    )
    stirrups = stirrups_derivation(hook_type_selected)
    crack = crack_bars_derivation(
        crack_bar_type_selected, h_mm,
        top_bar_type_selected, layers_top,
        bottom_bar_type_selected, layers_btm,
    )
    any_requested = top_main.requested or bottom_main.requested or stirrups.requested or crack.requested
    return ReviewDerivation(
        top_main=top_main, bottom_main=bottom_main, stirrups=stirrups,
        crack_bars=crack, any_requested=any_requested,
    )
