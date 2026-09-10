# -*- coding: utf-8 -*-
"""What the window remembers between beams, and what it deliberately
forgets (issue #54, U10).

The story is "I am not retyping fifteen fields per beam". The fields worth
remembering are the JOB'S CONVENTIONS -- the stirrup spacings this job
uses, the development-length multipliers, the layer counts, which bar type
is the stirrup. The fields NOT worth remembering are the ones that belong
to one beam: its dimensions, and how many bars this particular moment
needs.

THE RULE THAT SHAPES THIS MODULE. U10's last acceptance criterion says
persistence must never resurrect a REQUESTED state that would place
reinforcement the engineer did not ask for in this session -- restoring
values is not the same as restoring intent. That is not a warning to be
careful; it is a constraint on which fields may be stored at all, because
U6's derivation computes "requested" from the fields themselves:

    top/bottom main bars   requested when its bar TYPE is selected
                           AND its bar COUNT is non-blank
    stirrups               requested when the HOOK TYPE is selected
    crack bars             requested when the CRACK BAR TYPE is selected
                           and h > 700 and both faces are detailed

So four inputs are withheld -- the two main-bar counts, the hook type and
the crack bar type -- and withholding exactly those four is what makes
every section read NOT REQUESTED after a restore, with Place disabled,
however much else is remembered. It is a structural guarantee rather than
a promise, and ``tests/test_ui_persistence.py`` proves it by running the
real derivation over a full restore.

The engineer still types three things instead of fifteen.

WHAT IS NOT HERE, AND WHY

- **L, b, h.** Read from the beam that was picked (A35). Remembering them
  would put the last beam's dimensions in front of a new one, which is
  the most dangerous kind of wrong: plausible.
- **Covers.** This window does not collect them. They are read from the
  beam's own Revit cover parameters and displayed, never typed, so there
  is nothing to remember. U10 lists covers among the fields to persist;
  they became model reads instead, and a value that is not entered cannot
  be re-entered.

HOW TYPES ARE IDENTIFIED. By ``Element.UniqueId``, not ``ElementId`` and
not name. UniqueId survives reopening the model, a name can be edited,
and an ElementId means nothing in another document -- while the storage
is per-project anyway. A UniqueId that no longer resolves, or resolves to
something that is not the expected class, degrades to "not selected",
which the derivation already handles because an unpicked role is the
normal state of a freshly opened window.

STORE PLAIN DATA ONLY. pyRevit's ``script.store_data`` is pickle, and its
own documentation warns that a custom class must exist in the main scope
at load time. So this module stores nothing but dicts of strings, which
cannot fail to unpickle because a module moved.

Python 2/3 compatible: IronPython 2.7 is the runtime that loads this in
production.
"""

# The pyRevit data slot. Named for the tool, not the ticket, because it
# outlives the ticket -- and because pyRevit puts it in a filename.
SETTINGS_SLOT = "SimpleBeamRFT_inputs"

# Bumped whenever the field set or a stored value's MEANING changes.
# Anything carrying a different version is discarded rather than
# half-applied: a partial restore is harder to notice than none at all,
# because the fields that did not restore look like fields the engineer
# simply has not filled in yet.
SETTINGS_VERSION = 1

# Free-text inputs (TextBox contents, stored verbatim as typed).
#
# Stored as TEXT and not as parsed numbers, deliberately: the window's own
# parsers already turn text into values and already say which field is
# unreadable and why (rft.ui.inputs). Storing a parsed float would move
# that judgement in here and give it a second opinion.
TEXT_FIELDS = (
    "top_layers_tb",
    "bottom_layers_tb",
    "spacer_dia_tb",
    "d_agg_tb",
    "min_spacing_override_tb",
    "ld_top_mult_tb",
    "ld_btm_mult_tb",
    "dense_spacing_tb",
    "normal_spacing_tb",
    "crack_s_max_tb",
)

# ComboBox selections that are plain choices rather than elements, stored
# by their exact label. A label whose wording changes will simply fail to
# match and leave the picker unselected -- ui.inputs looks choices up by
# exact label and deliberately does not fall back to parsing the leading
# numeral, so a near-match can never resolve to the wrong option.
CHOICE_FIELDS = (
    "top_face_option_combo",
    "bottom_face_option_combo",
    "closure_type_combo",
)

# Revit element selections, stored by UniqueId. Keyed by the attribute on
# BeamMaterialsSelection they populate, since that -- not the ComboBox --
# is the window's single source of truth per role (A42).
TYPE_FIELDS = (
    "top_main_bar_type",
    "bottom_main_bar_type",
    "stirrup_bar_type",
)

# The four inputs that are NEVER stored, each with the section it would
# otherwise resurrect. Kept as data rather than as a comment so a test can
# assert that none of them appears in the three lists above, and so a
# future field added to those lists trips over this one.
REQUEST_CONSTITUTING_FIELDS = {
    "top_bar_count_tb": "top main bars",
    "bottom_bar_count_tb": "bottom main bars",
    "stirrup_hook_type": "stirrups",
    "crack_bar_type": "crack bars",
}

# Beam-scoped, read from the model, never remembered. Listed for the same
# reason as above: so the exclusion is testable instead of implied.
BEAM_SCOPED_FIELDS = ("l_tb", "b_tb", "h_tb")


def to_store(text_values, choice_values, type_unique_ids):
    """Build the dict handed to ``script.store_data``.

    Only known keys survive, so a caller cannot widen what is persisted by
    passing extra entries -- which is the route by which a
    request-constituting field would get stored by accident.
    """
    return {
        "version": SETTINGS_VERSION,
        "text": _kept(text_values, TEXT_FIELDS),
        "choices": _kept(choice_values, CHOICE_FIELDS),
        "types": _kept(type_unique_ids, TYPE_FIELDS),
    }


def from_store(raw):
    """Validate what came back from ``script.load_data``.

    Returns ``(text, choices, types)`` -- three dicts, empty when there is
    nothing usable. Never raises: this runs while the window is opening,
    and a settings file is not worth failing to open a tool over.

    Anything unexpected is DROPPED rather than coerced. A stored value
    that is not a string is not a field the engineer typed, so guessing
    what it meant would be inventing input.
    """
    if not isinstance(raw, dict):
        return {}, {}, {}
    if raw.get("version") != SETTINGS_VERSION:
        return {}, {}, {}
    return (
        _kept(raw.get("text"), TEXT_FIELDS),
        _kept(raw.get("choices"), CHOICE_FIELDS),
        _kept(raw.get("types"), TYPE_FIELDS),
    )


def _kept(values, allowed):
    """The subset of ``values`` whose keys are allowed and whose values are
    non-empty strings."""
    if not isinstance(values, dict):
        return {}
    kept = {}
    for key in allowed:
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            kept[key] = value
        else:
            # IronPython 2.7: a stored value may come back as `unicode`
            # rather than `str`, and both are text. Checked this way
            # rather than with a name that does not exist under Python 3.
            try:
                is_text = isinstance(value, unicode)  # noqa: F821
            except NameError:
                is_text = False
            if is_text and value.strip():
                kept[key] = value
    return kept


def persisted_field_names():
    """Every field this module will store, for tests and for the report."""
    return tuple(TEXT_FIELDS) + tuple(CHOICE_FIELDS) + tuple(TYPE_FIELDS)
