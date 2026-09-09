# -*- coding: utf-8 -*-
"""Pure input parsing/validation for the Detail Beam window's Main bars,
Stirrups and Crack bars tabs (issue #48, U4).

No Revit import, no detailing arithmetic (that stays in ``rft.core``) --
this module only turns a TextBox's raw string into a plain Python value,
or refuses to and says why, naming the field. That split is what makes it
testable under plain CPython at all: ``script.py`` imports ``pyrevit`` at
module scope and cannot be imported here.

Blank-vs-zero is the load-bearing distinction in this module (A44; #50/U6's
derivation rule): a blank main-bar count or layer count must parse to
``None`` -- "the engineer has not asked for this face/layer" -- never to
``0``, and never silently defaulted to ``1`` or ``3`` the way the old
"Place Main Bars" pushbutton does. If a blank parsed to a number instead,
every beam would read as requesting main bars regardless of what was
typed, and #50's "requested when a bar type is selected AND a non-blank
count is given" rule would collapse.

Python 2/3 compatible: IronPython 2.7 is the runtime that actually loads
this module in production (``tests/test_ironpython_compat.py`` enforces
the constraints -- no f-strings, PEP 263 cookie above).
"""

# rev 2 section 7.2 / A31: stirrup closure type narrows from (1-4) to
# (1, 2, 4) for v1 -- type 3 (nested double perimeter) is parked, its inner
# loop undefined. The ComboBox this backs offers ONLY these three labels,
# so "3" is never a choice to reject after the fact (this ticket's fourth
# specified constraint) -- this tuple exists so the UI and this validation
# cannot drift apart on what "allowed" means.
ALLOWED_CLOSURE_TYPES = (1, 2, 4)

# section 6.3, A36: 1 = single wide row, 2 = stacked. No other value.
ALLOWED_LAYER_OPTIONS = (1, 2)


def _stripped(text):
    return (text or "").strip()


def parse_optional_positive_int(text, field_label, max_value=None):
    """Blank -> ``None`` (A44: "not requested" -- main bar counts and layer
    counts both ship blank per this ticket). Non-blank -> a positive int,
    range-checked against ``max_value`` when given (layer counts are
    1..``MAX_LAYERS``). Raises ``ValueError`` naming ``field_label`` on any
    failure -- non-integer text, zero, a negative number, or a value above
    ``max_value``.
    """
    stripped = _stripped(text)
    if not stripped:
        return None
    try:
        value = int(stripped)
    except ValueError:
        raise ValueError(
            "{0} must be a whole number, or left blank -- got '{1}'.".format(
                field_label, stripped
            )
        )
    if value < 1:
        raise ValueError(
            "{0} must be a positive whole number -- got {1}.".format(field_label, value)
        )
    if max_value is not None and value > max_value:
        raise ValueError(
            "{0} must be between 1 and {1} -- got {2}.".format(
                field_label, max_value, value
            )
        )
    return value


def parse_positive_float(text, field_label):
    """Never blank: every field this backs (`Ø_spacer`, dense/normal
    stirrup spacing, `s_max`, the `LD` multipliers) ships with a numeric
    default already in its TextBox (A36), so an empty box here means the
    engineer cleared a default, not the field's normal state -- unlike
    ``parse_optional_positive_float``, blank is a validation failure here,
    not a valid "not requested".
    """
    stripped = _stripped(text)
    try:
        value = float(stripped)
    except ValueError:
        raise ValueError(
            "{0} must be a number -- got '{1}'.".format(field_label, stripped)
        )
    if value <= 0:
        raise ValueError(
            "{0} must be positive -- got {1}.".format(field_label, value)
        )
    return value


def parse_optional_positive_float(text, field_label):
    """Blank -> ``None``. Backs `D_agg` (A36: blank means section 6.2's
    50 mm fallback governs) and the section 6.2 minimum-spacing override
    (A29: blank means no floor). A blank must never become ``0.0`` here --
    ``D_agg = 0`` would select the FORMULA branch of
    ``rft.core.spacing.governing_min_spacing_mm`` (a defined, if
    degenerate, aggregate size) instead of the fallback branch that only
    ``None`` selects.
    """
    stripped = _stripped(text)
    if not stripped:
        return None
    try:
        value = float(stripped)
    except ValueError:
        raise ValueError(
            "{0} must be a number, or left blank -- got '{1}'.".format(
                field_label, stripped
            )
        )
    if value <= 0:
        raise ValueError(
            "{0} must be positive when given -- got {1}.".format(field_label, value)
        )
    return value


def parse_layer_option(text, field_label):
    """section 6.3's per-face option: 1 (single wide row) or 2 (stacked)
    only, default 1 (A36). Ships filled (never blank), so an empty box is
    a validation failure here, not "not requested".
    """
    stripped = _stripped(text)
    try:
        value = int(stripped)
    except ValueError:
        raise ValueError(
            "{0} must be 1 or 2 -- got '{1}'.".format(field_label, stripped)
        )
    if value not in ALLOWED_LAYER_OPTIONS:
        raise ValueError(
            "{0} must be 1 (single wide row) or 2 (stacked) -- got {1}.".format(
                field_label, value
            )
        )
    return value


def closure_type_from_label(label):
    """Recovers the closure-type int from a ComboBox label built as
    ``str(n)`` for ``n`` in ``ALLOWED_CLOSURE_TYPES`` (rev 2 section 7.2,
    A31). The ComboBox itself offers only 1, 2 and 4 as items -- type 3 is
    never an option to type or select, not merely refused after the fact
    -- so this is a lookup against a closed set, not free-text parsing.
    Returns ``None`` if nothing is selected yet.
    """
    if label is None:
        return None
    value = int(label)
    if value not in ALLOWED_CLOSURE_TYPES:
        raise ValueError(
            "closure type '{0}' is not one of {1} (rev 2 section 7.2, A31 "
            "-- type 3 is parked).".format(label, ALLOWED_CLOSURE_TYPES)
        )
    return value


def try_parse_float(text):
    """Returns a ``float``, or ``None`` on blank/unparseable text -- never
    raises. Backs the crack-bars tab's live re-evaluation of `h` on every
    keystroke (this ticket's brief: "a half-typed or empty h cannot
    throw"): the caller treats ``None`` as "not a decision yet" and leaves
    whatever enabled/disabled state the tab already has, rather than
    forcing it to a particular value on an in-progress edit.
    """
    stripped = _stripped(text)
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError:
        return None


# --- H_avail's own missing-input reporting (rev 2 section 5.1, A26) --------
#
# H_avail = h - offset_top - offset_btm, where offset_top/offset_btm are the
# INNERMOST main-bar layer's own offset (A26) -- computed from `h`, the top
# and bottom main bar diameters (from the selected RebarBarType), the
# stirrup diameter (same source), and the top/bottom layer counts. This
# module states only WHICH of those is missing; the arithmetic itself
# (``rft.core.layout.layer_offset_mm`` / ``rft.core.crack_bars.
# available_height_mm``) is called by ``script.py``, never duplicated here.

MISSING_H_AVAIL_FIELD_LABELS = {
    "h": "beam height (h)",
    "top_bar_type": "top main bar type",
    "bottom_bar_type": "bottom main bar type",
    "stirrup_bar_type": "stirrup bar type",
    "layers_top": "number of top layers",
    "layers_btm": "number of bottom layers",
}


def missing_h_avail_inputs(h_mm, top_bar_dia_mm, btm_bar_dia_mm, stirrup_dia_mm,
                            layers_top, layers_btm):
    """Which of H_avail's own inputs are still missing (``None``), in a
    fixed, readable order. Returns an empty list once every input H_avail
    needs is present -- the caller then computes and displays the number;
    this function never computes H_avail itself.
    """
    missing = []
    if h_mm is None:
        missing.append(MISSING_H_AVAIL_FIELD_LABELS["h"])
    if top_bar_dia_mm is None:
        missing.append(MISSING_H_AVAIL_FIELD_LABELS["top_bar_type"])
    if btm_bar_dia_mm is None:
        missing.append(MISSING_H_AVAIL_FIELD_LABELS["bottom_bar_type"])
    if stirrup_dia_mm is None:
        missing.append(MISSING_H_AVAIL_FIELD_LABELS["stirrup_bar_type"])
    if layers_top is None:
        missing.append(MISSING_H_AVAIL_FIELD_LABELS["layers_top"])
    if layers_btm is None:
        missing.append(MISSING_H_AVAIL_FIELD_LABELS["layers_btm"])
    return missing


def h_avail_missing_message(missing_fields):
    """A sentence naming which input(s) H_avail (rev 2 section 5.1, A26)
    still needs -- never a number, and never a formatted ``None`` (this
    ticket's brief: `H_avail` must display a sentence naming the missing
    input, not a zero). Callers should only reach this with a non-empty
    ``missing_fields``; an empty list means H_avail IS computable and the
    caller should display the computed value instead.
    """
    return (
        "H_avail cannot be computed yet -- missing: {0} (rev 2 section "
        "5.1, A26; measured to the innermost main-bar layer).".format(
            ", ".join(missing_fields)
        )
    )


def no_beam_picked_h_avail_message():
    """The specific missing-input case where no beam has been picked at
    all yet -- distinct from ``h_avail_missing_message`` because none of
    H_avail's own fields (h, bar types, layer counts) can even be read
    until a beam is picked (A35).
    """
    return (
        "H_avail cannot be computed yet -- missing: a beam picked on the "
        "Beam & Materials tab (rev 2 section 5.1, A26)."
    )
