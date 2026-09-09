# -*- coding: utf-8 -*-
"""Bar spacing validation and layer decisions (rev 2 sections 6.2-6.4;
A21, A25, A27, A28, A29, A36, A43, A44).

Pure Python: no Revit imports, no Revit types. Every value is a plain
number in millimetres, matching the spec 1:1. Refusals/warnings are always
a `rft.core.guards.GuardMessage` (condition, spec_section, message) --
never a bare string -- reused here rather than re-invented, per this
module's own instructions.

DELIBERATELY DOES NOT VALIDATE CRACK BARS: rev 2 section 5, A25 exempts
them from this section entirely (one bar per side per layer leaves no
horizontal spacing question) -- see
`rft.core.crack_bars.spacing_validation_exemption_note`, which exists
precisely so this module has something concrete to check against. Nothing
in this module is called from `rft.core.crack_bars`, and nothing here
should ever be wired into the crack-bar pushbutton.

Scope: HORIZONTAL spacing only (A21). The vertical layer gap is section
4.1's territory (`Ø_spacer`, `rft.core.layout.spacer_diameter_warning`,
residual question R1, non-blocking) and is untouched here.
"""

import math
from collections import namedtuple

from .guards import GuardMessage

SPACING_SPEC_SECTION = "rev 2 section 6.2-6.4 (A21, A27, A28, A29, A43, A44)"

MAX_LAYERS = 5  # section 6.3: "Up to 5 layers maximum per face" (A28's absolute cap)

OPTION_SINGLE_ROW = 1  # section 6.3 option 1: all bars in one line, no stacking
OPTION_STACKED = 2     # section 6.3 option 2: stacked rows separated by a spacer bar


# --- section 6.2: governing minimum clear spacing ---------------------------


def governing_min_spacing_mm(bar_dia_mm, d_agg_mm=None, user_override_mm=None):
    """section 6.2, A21, A29:

        formula_result = max(25, O_bar, 1.33*D_agg)   when D_agg is DEFINED
        formula_result = 50                           ONLY when D_agg is
                                                        NOT defined

    D_agg governs OVER the 50 mm fallback -- it is not a floor folded into
    the same max(...) as the fallback. `max(25, O_bar, 1.33*D_agg, 50)`
    would over-refuse: e.g. O12 with D_agg=20 mm gives 26.6 mm under the
    correct two-branch formula, but would give 50 mm if 50 were folded in
    as a floor. `d_agg_mm=None` selects the 50 mm branch; passing 0 or any
    other defined number selects the formula branch (A36 ships the field
    blank by default specifically so this fallback governs until the
    engineer sets it).

    A29: `user_override_mm`, if given, acts as a FLOOR ONLY --
    `governing = max(formula_result, user_override)`. An override BELOW
    the formula result is therefore IGNORED entirely, never used to
    reduce spacing below the computed minimum.
    """
    if d_agg_mm is not None:
        formula_result_mm = max(25.0, bar_dia_mm, 1.33 * d_agg_mm)
    else:
        formula_result_mm = 50.0
    if user_override_mm is not None:
        return max(formula_result_mm, user_override_mm)
    return formula_result_mm


# --- section 6.4 (A43-corrected datum): achieved clear spacing --------------


def achieved_clear_spacing_mm(b_mm, cover_side_mm, stirrup_dia_mm, bar_dia_mm, bar_count):
    """A43-corrected section 6.4 achieved clear spacing for `bar_count` bars
    in one face:

        clear = (b - 2*Cover - 2*O_stirrup - n*O_bar) / (n - 1)

    `cover_side_mm` MUST be the beam's own SIDE cover -- a horizontal
    dimension across `b` -- never `cover_top`/`cover_btm` (the S3/S6 review
    finding this ticket's brief names as trap 1; those covers govern
    vertical quantities and never enter this formula).

    As PRINTED, rev 2 section 6.4 gives this formula with "offset per
    section 4" in place of `Cover + O_stirrup`, i.e.
    `clear = (b - 2*offset_1 - n*O_bar)/(n-1)`. Section 4's `offset_1 =
    Cover + O_stirrup + 0.5*O_bar` already contains half a bar diameter, so
    that literal reading subtracts `2*offset_1 = 2*Cover + 2*O_stirrup +
    O_bar` plus `n*O_bar` -- (n+1) bar diameters from a face holding only n
    bars. The corrected formula implemented here (A43, decided by the
    project owner 2026-09-09) uses the CLEAR WIDTH INSIDE THE STIRRUP LEGS
    directly -- the same datum section 6.3's `spacer_length` uses -- and
    is arithmetically IDENTICAL to keeping section 4's offset and
    subtracting only `(n-1)*O_bar` instead of `(n+1)*O_bar`. Implemented in
    the direct (clear-width) form rather than the offset form because it
    needs no per-caller reminder about the +1/-1 correction.

    `bar_count == 1` (n = 1) has NO horizontal spacing question -- returns
    `None` (SKIP), never divides by zero.

    Raises ValueError if `bar_count < 1`.
    """
    if bar_count < 1:
        raise ValueError(
            "bar_count = {!r} is invalid (rev 2 section 6.4): a layer must "
            "hold at least one bar.".format(bar_count)
        )
    if bar_count == 1:
        return None
    return (
        b_mm - 2.0 * cover_side_mm - 2.0 * stirrup_dia_mm - bar_count * bar_dia_mm
    ) / (bar_count - 1)


LayerSpacingResult = namedtuple(
    "LayerSpacingResult",
    ["layer_index", "bar_count", "governing_min_mm", "achieved_clear_mm", "passes"],
)


def validate_layer_spacing(layer_index, bar_count, b_mm, cover_side_mm, stirrup_dia_mm,
                            bar_dia_mm, governing_min_mm):
    """Validate ONE layer independently (A44: the engineer states the bar
    count per layer and the tool never re-splits it, so every layer is
    checked on its own merits, never against a redistributed total).

    `bar_count == 1` SKIPS the check (A43): `passes=True`,
    `achieved_clear_mm=None` -- there is no horizontal spacing question for
    a single bar.

    Otherwise PASSES when `achieved_clear_mm >= governing_min_mm` -- the
    EXACT-MINIMUM boundary (achieved == governing) PASSES, since section
    6.4 only calls `clear < governing_min_spacing` invalid (strict
    less-than; equality is not a violation).
    """
    achieved_clear_mm = achieved_clear_spacing_mm(
        b_mm, cover_side_mm, stirrup_dia_mm, bar_dia_mm, bar_count
    )
    if achieved_clear_mm is None:
        return LayerSpacingResult(
            layer_index=layer_index, bar_count=bar_count, governing_min_mm=governing_min_mm,
            achieved_clear_mm=None, passes=True,
        )
    passes = achieved_clear_mm >= governing_min_mm
    return LayerSpacingResult(
        layer_index=layer_index, bar_count=bar_count, governing_min_mm=governing_min_mm,
        achieved_clear_mm=achieved_clear_mm, passes=passes,
    )


# --- A44: suggested layer count is REPORTING ONLY, never a split rule ------


def max_bars_per_layer(b_mm, cover_side_mm, stirrup_dia_mm, bar_dia_mm,
                       governing_min_mm, upper_bound=200):
    """The largest bar count that still satisfies `governing_min_mm` in one
    layer, given A43's corrected clear-spacing formula.

    This is the number the engineer can act on DIRECTLY, because it is
    exactly what the pushbutton's "bar count per layer" field takes. The
    achieved clear spacing falls monotonically as the count rises, so the
    search stops at the first count that fails.

    Returns at least 1: a single bar has no horizontal spacing question at
    all (A43), so one bar per layer always satisfies the minimum. Reporting
    only -- see `suggest_min_layer_count`.
    """
    best = 1
    for n in range(2, upper_bound + 1):
        achieved_mm = achieved_clear_spacing_mm(
            b_mm, cover_side_mm, stirrup_dia_mm, bar_dia_mm, n
        )
        if achieved_mm is None or achieved_mm < governing_min_mm:
            break
        best = n
    return best


def suggest_min_layer_count(total_bar_count, b_mm, cover_side_mm, stirrup_dia_mm, bar_dia_mm,
                             governing_min_mm, max_layers=MAX_LAYERS):
    """The smallest layer count `k` in `1..max_layers` for which an EVEN
    split (`ceil(total/k)` bars in the fullest layer) would satisfy
    `governing_min_mm`, so the engineer has a concrete number to re-enter.

    THIS IS REPORTING ONLY, NOT A PLACEMENT/SPLIT RULE. A44 removed the
    tool's authority to redistribute the engineer's stated bars across
    layers -- rev 2 never defined how a total would be split across
    auto-stacked layers, and A44 closes that gap by removing the need for a
    split rule rather than inventing one. This function's return value must
    NEVER be used to actually re-arrange bars; it exists solely so a
    refusal message can name a workable layer count.

    Returns `None` if no `k` in `1..max_layers` satisfies the minimum --
    callers must then report the A28 hard error (unreachable within the
    absolute cap), never a nonexistent suggested count.
    """
    per_layer = max_bars_per_layer(
        b_mm, cover_side_mm, stirrup_dia_mm, bar_dia_mm, governing_min_mm
    )
    k = int(math.ceil(total_bar_count / float(per_layer)))
    if k > max_layers:
        return None
    return k


# --- section 6.3 per-face validation, both options -------------------------


FaceSpacingReport = namedtuple(
    "FaceSpacingReport",
    ["face_label", "layer_results", "passes", "guard_messages"],
)


def validate_face_spacing(face_label, option, layer_bar_counts, b_mm, cover_side_mm,
                           stirrup_dia_mm, bar_dia_mm, governing_min_mm, max_layers=MAX_LAYERS):
    """Validate every layer of ONE face independently (section 6.3, A44).
    Top and bottom faces are validated and reported SEPARATELY by calling
    this once per face -- one face failing must never suppress or alter
    the other face's report.

    `option` is section 6.3's per-face input (A36): 1 = single wide row,
    2 = stacked. Cross-checked against the layer count: option 1 selected
    together with MORE THAN ONE layer is a contradiction (a "single wide
    row" cannot also be stacked) and is REFUSED outright here, never
    silently resolved as option 2's behaviour.

    On any layer's spacing violation, BOTH options REFUSE (A44 supersedes
    A27's Option 2 auto-stacking): Option 1 because a single wide row has
    nowhere to go (A27, unchanged), Option 2 because redistributing the
    bars the engineer specified would silently detail something other than
    what was asked for. The refusal reports, per violating layer, the
    governing minimum, the achieved clear spacing, and (A44) the smallest
    layer count that would satisfy the minimum for this face's total bar
    count -- or, if A28's absolute 5-layer cap makes no arrangement
    possible, that hard-error fact instead of an unreachable count.
    """
    guard_messages = []
    n_layers = len(layer_bar_counts)

    if option == OPTION_SINGLE_ROW and n_layers > 1:
        condition = "{}: section 6.3 option 1 selected with {} layers".format(face_label, n_layers)
        message = (
            "{}: REFUSED -- rev 2 section 6.3 option 1 ('single wide row') "
            "was selected together with {} layers (A36). Option 1 means ALL "
            "bars in one line with no stacking, so more than one layer "
            "contradicts the chosen option rather than being something to "
            "silently resolve as option 2's stacking. Either select option "
            "2 (stacked), or reduce this face to a single layer.".format(
                face_label, n_layers
            )
        )
        guard_messages.append(
            GuardMessage(condition=condition, spec_section=SPACING_SPEC_SECTION, message=message)
        )
        return FaceSpacingReport(
            face_label=face_label, layer_results=[], passes=False, guard_messages=guard_messages
        )

    layer_results = [
        validate_layer_spacing(
            i + 1, bar_count, b_mm, cover_side_mm, stirrup_dia_mm, bar_dia_mm, governing_min_mm
        )
        for i, bar_count in enumerate(layer_bar_counts)
    ]
    all_pass = all(r.passes for r in layer_results)

    if not all_pass:
        total_bar_count = sum(layer_bar_counts)
        suggested_k = suggest_min_layer_count(
            total_bar_count, b_mm, cover_side_mm, stirrup_dia_mm, bar_dia_mm, governing_min_mm,
            max_layers=max_layers,
        )
        per_layer_max = max_bars_per_layer(
            b_mm, cover_side_mm, stirrup_dia_mm, bar_dia_mm, governing_min_mm
        )
        for r in layer_results:
            if r.passes:
                continue
            condition = "{}: layer {} spacing violation ({} bars)".format(
                face_label, r.layer_index, r.bar_count
            )
            if suggested_k is None:
                suggestion_text = (
                    "No layer count within the absolute {}-layer cap (A28) "
                    "would satisfy the governing minimum for this face's "
                    "total of {} bars -- this is a HARD ERROR, not an "
                    "unreachable suggested count.".format(max_layers, total_bar_count)
                )
            else:
                # Phrased in the input model's OWN terms -- bars PER LAYER and
                # a layer count -- because that is what the engineer types.
                # Naming a total instead would name an arrangement the form
                # cannot express: this pushbutton takes one count per layer
                # and applies it to every layer of the face, so "11 bars over
                # 2 layers" is not enterable (issue #17 review).
                suggestion_text = (
                    "At most {} bars per layer satisfy this minimum; your {} "
                    "bars in this face would need {} layers at that count "
                    "(reporting only, per A44 -- the tool never re-splits "
                    "the bars you stated; enter the count and layers "
                    "yourself).".format(per_layer_max, total_bar_count, suggested_k)
                )
            message = (
                "{}: REFUSED -- layer {} ({} bars) achieves {:.1f} mm clear "
                "spacing, below the governing minimum of {:.1f} mm (rev 2 "
                "section 6.4, A43's corrected datum). Both section 6.3 "
                "options refuse on this violation (A44 supersedes A27's "
                "Option 2 auto-stacking). {}".format(
                    face_label, r.layer_index, r.bar_count, r.achieved_clear_mm,
                    r.governing_min_mm, suggestion_text,
                )
            )
            guard_messages.append(
                GuardMessage(condition=condition, spec_section=SPACING_SPEC_SECTION, message=message)
            )

    return FaceSpacingReport(
        face_label=face_label, layer_results=layer_results, passes=all_pass,
        guard_messages=guard_messages,
    )
