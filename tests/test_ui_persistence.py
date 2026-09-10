# -*- coding: utf-8 -*-
"""#54 (U10) -- what the window remembers, and what it must forget.

The test that matters most here is not about storage at all. It is
``test_a_full_restore_leaves_every_section_not_requested``: it runs the
REAL derivation over a full restore and requires every section to read
NOT REQUESTED. That is U10's last acceptance criterion -- restoring values
is not restoring intent -- checked as a property of the two modules
together rather than trusted to the field lists being right.
"""

import pytest

from rft.ui.derivation import compute_review_derivation
from rft.ui.persistence import (
    BEAM_SCOPED_FIELDS,
    CHOICE_FIELDS,
    REQUEST_CONSTITUTING_FIELDS,
    SETTINGS_SLOT,
    SETTINGS_VERSION,
    TEXT_FIELDS,
    TYPE_FIELDS,
    from_store,
    persisted_field_names,
    to_store,
)

FULL_TEXT = {
    "top_layers_tb": "2",
    "bottom_layers_tb": "2",
    "spacer_dia_tb": "16",
    "d_agg_tb": "20",
    "min_spacing_override_tb": "30",
    "ld_top_mult_tb": "55",
    "ld_btm_mult_tb": "55",
    "dense_spacing_tb": "150",
    "normal_spacing_tb": "200",
    "crack_s_max_tb": "200",
}
FULL_CHOICES = {
    "top_face_option_combo": "2 -- stacked rows, separated by a spacer bar",
    "bottom_face_option_combo": "2 -- stacked rows, separated by a spacer bar",
    "closure_type_combo": "1 -- closed loop, hooks meet at the TOP-RIGHT corner",
}
FULL_TYPES = {
    "top_main_bar_type": "8a1f0c22-0000-0000-0000-000000000001",
    "bottom_main_bar_type": "8a1f0c22-0000-0000-0000-000000000002",
    "stirrup_bar_type": "8a1f0c22-0000-0000-0000-000000000003",
}


# --- the criterion that shapes the whole module ---------------------------


def test_a_full_restore_leaves_every_section_not_requested():
    """U10's last acceptance criterion, as a property rather than a
    promise: restore EVERYTHING this module can store, and nothing is
    requested, so Place is disabled and no reinforcement can be placed
    that was not asked for in this session.

    This works only because four inputs are withheld. If a later change
    adds any of them to the stored set, the derivation below starts
    reporting a requested section and this test fails -- which is the
    point of asserting against the real derivation instead of against the
    field lists.
    """
    text, choices, types = from_store(to_store(FULL_TEXT, FULL_CHOICES, FULL_TYPES))
    assert text and choices and types, "the restore under test is not empty"

    # The window after such a restore: bar types selected (their UniqueIds
    # resolved), layer counts filled in -- and the four withheld inputs
    # still unset, which is what `None` means for each argument here.
    review = compute_review_derivation(
        top_bar_type_selected="<restored top type>",
        top_bar_count=None,                       # withheld
        bottom_bar_type_selected="<restored bottom type>",
        bottom_bar_count=None,                    # withheld
        hook_type_selected=None,                  # withheld
        crack_bar_type_selected=None,             # withheld
        h_mm=900.0,                               # a deep beam: h > 700
        layers_top=int(text["top_layers_tb"]),
        layers_btm=int(text["bottom_layers_tb"]),
    )

    assert not review.top_main.requested
    assert not review.bottom_main.requested
    assert not review.stirrups.requested
    assert not review.crack_bars.requested
    assert not review.any_requested, (
        "a restore armed Place. Restoring values must not restore intent "
        "(U10): check which field was added to the persisted set."
    )


def test_the_four_withheld_inputs_are_not_in_any_persisted_list():
    """The structural half of the same rule. The test above would catch a
    withheld field being persisted; this one names it.
    """
    persisted = set(persisted_field_names())
    leaked = sorted(set(REQUEST_CONSTITUTING_FIELDS) & persisted)
    assert not leaked, (
        "these inputs decide whether a section is REQUESTED and must "
        "never be stored: %s" % leaked
    )


def test_beam_dimensions_are_never_persisted():
    """L, b and h are read from the picked beam (A35). Remembering them
    would put the last beam's dimensions in front of a new one -- wrong,
    and plausible, which is the bad combination.
    """
    persisted = set(persisted_field_names())
    leaked = sorted(set(BEAM_SCOPED_FIELDS) & persisted)
    assert not leaked, "beam-scoped fields must not be stored: %s" % leaked


def test_every_withheld_field_says_which_section_it_would_resurrect():
    """The exclusion list is documentation as much as data: someone
    wondering why the hook type is not remembered should find the answer
    beside it.
    """
    assert set(REQUEST_CONSTITUTING_FIELDS) == {
        "top_bar_count_tb", "bottom_bar_count_tb",
        "stirrup_hook_type", "crack_bar_type",
    }
    for field, section in REQUEST_CONSTITUTING_FIELDS.items():
        assert section and isinstance(section, str), field


# --- round trip -----------------------------------------------------------


def test_a_full_round_trip_returns_exactly_what_went_in():
    stored = to_store(FULL_TEXT, FULL_CHOICES, FULL_TYPES)
    text, choices, types = from_store(stored)
    assert text == FULL_TEXT
    assert choices == FULL_CHOICES
    assert types == FULL_TYPES


def test_the_stored_blob_is_plain_data_only():
    """pyRevit's store_data is pickle, and its own docs warn that a custom
    class must exist in the main scope at load time. Storing nothing but
    dicts of strings means the blob cannot fail to unpickle because a
    module was renamed -- which this repo did rename, in rc3.
    """
    stored = to_store(FULL_TEXT, FULL_CHOICES, FULL_TYPES)

    def _plain(value):
        if isinstance(value, dict):
            return all(isinstance(k, str) and _plain(v)
                       for k, v in value.items())
        return isinstance(value, (str, int))

    assert _plain(stored), stored
    assert stored["version"] == SETTINGS_VERSION


def test_only_known_keys_are_stored():
    """A caller cannot widen what is persisted by passing extra entries --
    the route by which a withheld field would be stored by accident.
    """
    stored = to_store(
        dict(FULL_TEXT, top_bar_count_tb="3", l_tb="9600"),
        dict(FULL_CHOICES, stirrup_hook_combo="135 deg hook"),
        dict(FULL_TYPES, crack_bar_type="some-uniqueid"),
    )
    assert "top_bar_count_tb" not in stored["text"]
    assert "l_tb" not in stored["text"]
    assert "stirrup_hook_combo" not in stored["choices"]
    assert "crack_bar_type" not in stored["types"]


# --- everything a settings file can be, short of usable ------------------


@pytest.mark.parametrize("raw", [
    None,
    {},
    "not a dict",
    [],
    42,
    {"version": SETTINGS_VERSION + 1, "text": FULL_TEXT},
    {"version": None},
    {"text": FULL_TEXT},                       # no version at all
    {"version": SETTINGS_VERSION, "text": "not a dict"},
    {"version": SETTINGS_VERSION, "text": None, "choices": None, "types": None},
])
def test_unusable_stored_data_yields_defaults_and_never_raises(raw):
    """This runs while the window is opening. A settings file is not worth
    failing to open a tool over, and a HALF-applied one is worse than
    none: the fields that did not restore look like fields the engineer
    has simply not filled in yet.
    """
    assert from_store(raw) == ({}, {}, {})


def test_a_version_bump_discards_rather_than_half_applies():
    old = to_store(FULL_TEXT, FULL_CHOICES, FULL_TYPES)
    old["version"] = SETTINGS_VERSION - 1
    assert from_store(old) == ({}, {}, {})


def test_individually_malformed_values_are_dropped_not_coerced():
    """A stored value that is not text is not something the engineer
    typed, so guessing what it meant would be inventing input.
    """
    text, choices, types = from_store({
        "version": SETTINGS_VERSION,
        "text": {
            "top_layers_tb": "2",
            "bottom_layers_tb": 2,          # a number, not the typed text
            "spacer_dia_tb": None,
            "d_agg_tb": "",                 # blank is not a value
            "ld_top_mult_tb": "   ",        # nor is whitespace
            "dense_spacing_tb": ["150"],
        },
        "choices": {"closure_type_combo": "1 -- closed loop, hooks meet at the TOP-RIGHT corner"},
        "types": {"stirrup_bar_type": "a-unique-id", "top_main_bar_type": 17},
    })
    assert text == {"top_layers_tb": "2"}
    assert choices == {
        "closure_type_combo": "1 -- closed loop, hooks meet at the TOP-RIGHT corner"}
    assert types == {"stirrup_bar_type": "a-unique-id"}


def test_partial_data_restores_only_what_it_has():
    text, choices, types = from_store({
        "version": SETTINGS_VERSION,
        "text": {"dense_spacing_tb": "150"},
    })
    assert text == {"dense_spacing_tb": "150"}
    assert choices == {}
    assert types == {}


# --- the field lists themselves ------------------------------------------


def test_no_field_appears_in_two_lists():
    names = persisted_field_names()
    assert len(names) == len(set(names)), "a field is persisted twice"
    assert len(names) == len(TEXT_FIELDS) + len(CHOICE_FIELDS) + len(TYPE_FIELDS)


def test_the_slot_name_is_stable_and_names_the_tool():
    """It ends up in a filename on disk beside the project, so it must not
    be a ticket number that stops meaning anything.
    """
    assert SETTINGS_SLOT == "SimpleBeamRFT_inputs"


def test_types_are_persisted_for_the_three_roles_that_request_nothing():
    """The stirrup bar type is remembered although the stirrup HOOK is
    not: the bar type positions every main bar (section 4.1's offsets)
    and requests nothing on its own, while the hook type alone is what
    makes stirrups requested.
    """
    assert set(TYPE_FIELDS) == {
        "top_main_bar_type", "bottom_main_bar_type", "stirrup_bar_type"}
    assert "stirrup_hook_type" not in TYPE_FIELDS
    assert "crack_bar_type" not in TYPE_FIELDS
