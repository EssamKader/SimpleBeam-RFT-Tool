# -*- coding: utf-8 -*-
"""#45 (U1) -- every ``GuardMessage`` says whether it BLOCKS or WARNS.

Severity used to be implicit: it lived in whether the call site happened
to follow the message with ``script.exit()``. That was readable for as
long as the three pushbuttons existed, and stopped being readable the
moment one window replaced them -- the exits went away and nothing carried
the distinction, so a refusal and a warning arrived at the caller looking
identical.

WHERE THE EXPECTED VALUES BELOW COME FROM. Not from the message wording,
which is the tempting shortcut and would have been wrong at least once
(see the spacing pair). From the behaviour that was VERIFIED on a live
host -- v0.1.0's pushbuttons, read back out of the tag:

    git show v0.1.0:".../Place Main Bars.pushbutton/script.py"

Every guard there was followed by ``forms.alert(...)`` then
``script.exit()`` except the free-end one, which went into a warnings
list and carried on placing. This story records that decision; it does not
revisit it.
"""

import io
import os
import re

import pytest

from rft.core.guards import (
    SEVERITY_BLOCKING,
    SEVERITY_WARNING,
    GuardMessage,
    continuous_run_guard_message,
    free_end_guard_message,
    is_blocking,
    no_support_detected_message,
    stirrup_type3_guard_message,
)
from rft.core.grades import (
    ROLE_TOP_MAIN,
    hook_angle_guard_message,
    hook_style_guard_message,
    missing_bar_type_selection_message,
    missing_hook_type_selection_message,
    no_usable_hook_type_message,
    stirrup_grade_conflict_message,
    unreadable_hook_style_message,
)
from rft.core.spacing import validate_face_spacing

LIB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "SimpleBeamRFT.extension", "lib", "rft",
)

# (a guard, its severity as v0.1.0 actually behaved)
#
# Called with arguments that make each guard FIRE, since a guard that
# returns None tells us nothing about its severity.
GUARDS_AND_SEVERITIES = [
    ("continuous_run_guard_message",
     lambda: continuous_run_guard_message("Start end", 3.0), SEVERITY_BLOCKING),
    ("free_end_guard_message",
     lambda: free_end_guard_message("Start end"), SEVERITY_WARNING),
    ("no_support_detected_message",
     lambda: no_support_detected_message("End end"), SEVERITY_BLOCKING),
    ("stirrup_type3_guard_message",
     stirrup_type3_guard_message, SEVERITY_BLOCKING),
    ("missing_bar_type_selection_message",
     lambda: missing_bar_type_selection_message(ROLE_TOP_MAIN), SEVERITY_BLOCKING),
    ("missing_hook_type_selection_message",
     missing_hook_type_selection_message, SEVERITY_BLOCKING),
    ("no_usable_hook_type_message",
     no_usable_hook_type_message, SEVERITY_BLOCKING),
    # Style 2 is the Standard family, not the Stirrup/Tie family A45 requires.
    ("hook_style_guard_message",
     lambda: hook_style_guard_message(2, "Standard hook"), SEVERITY_BLOCKING),
    ("unreadable_hook_style_message",
     lambda: unreadable_hook_style_message("Some hook"), SEVERITY_BLOCKING),
    # 90 degrees, where A45 requires 135.
    ("hook_angle_guard_message",
     lambda: hook_angle_guard_message(90.0, "90 deg hook"), SEVERITY_BLOCKING),
    ("stirrup_grade_conflict_message",
     lambda: stirrup_grade_conflict_message(
         101, "16M", 101, "16M", ROLE_TOP_MAIN), SEVERITY_BLOCKING),
]


@pytest.mark.parametrize("name,call,expected", GUARDS_AND_SEVERITIES)
def test_each_guard_declares_the_severity_v0_1_0_actually_had(name, call, expected):
    guard = call()
    assert guard is not None, (
        "%s returned None -- these arguments were meant to make it fire, so "
        "this test is no longer checking what it claims to" % name
    )
    assert guard.severity == expected, (
        "%s is declared %r but v0.1.0 treated it as %r. This story records "
        "the existing decision; changing which guards block is a different "
        "story (#52)." % (name, guard.severity, expected)
    )


def test_the_spacing_guards_block_as_v0_1_0_refused_on_them():
    """The pair whose severity the message wording alone would have got
    right by luck and the current behaviour would have got wrong.

    v0.1.0 collected both faces' spacing guard messages and, if any
    existed, alerted with the title "Spacing violation -- refused" and
    called ``script.exit()``. So: BLOCKING.

    The single window does NOT do that. It prints "REFUSED (section
    6.2-6.4)" in the Review report and places the bars anyway -- nothing
    on the placement path calls ``validate_face_spacing`` at all. That is
    a regression against v0.1.0 and it has its own issue; this test pins
    what the guard IS, which is also what its own message text says.
    Declaring it cannot change behaviour, because nothing reads
    ``severity`` yet.
    """
    # Option 1 ("single wide row") with two layers: a contradiction (A36).
    contradiction = validate_face_spacing(
        "Top face", 1, [3, 3], 300.0, 25.0, 10.0, 16.0, 26.6)
    assert contradiction.guard_messages
    for guard in contradiction.guard_messages:
        assert guard.severity == SEVERITY_BLOCKING
        assert is_blocking(guard)

    # Eight O16 bars across a 300 mm web: nowhere near the minimum.
    too_tight = validate_face_spacing(
        "Top face", 2, [8], 300.0, 25.0, 10.0, 16.0, 26.6)
    assert too_tight.guard_messages
    for guard in too_tight.guard_messages:
        assert guard.severity == SEVERITY_BLOCKING


def test_exactly_one_guard_is_a_warning():
    """The free-end guard, and only it. If a second WARNING appears, either
    a new guard was added (update this test deliberately) or a refusal was
    quietly downgraded, which is the direction that matters.
    """
    warnings = [
        name for name, call, expected in GUARDS_AND_SEVERITIES
        if expected == SEVERITY_WARNING
    ]
    assert warnings == ["free_end_guard_message"]

    guard = free_end_guard_message("Start end")
    assert not is_blocking(guard)


def test_severity_has_no_default_so_it_cannot_be_omitted_by_accident():
    """The acceptance criterion, stated as a test: no default value.

    A default would silently label whatever a migration missed -- and the
    whole point of the field is that the label is a statement someone
    made, not one that fell out of a field ordering.
    """
    with pytest.raises(TypeError):
        GuardMessage(condition="c", spec_section="s", message="m")

    # And the positional form still needs all four.
    with pytest.raises(TypeError):
        GuardMessage("c", "s", "m")


def test_every_guardmessage_construction_site_in_the_library_declares_one():
    """What actually stops the NEXT guard omitting it.

    The behavioural tests above cover the thirteen sites that exist today;
    a fourteenth added tomorrow would not be in their table. This reads
    the library as text instead, so a new construction site fails until it
    says which it is.

    The TypeError above is the backstop, but only for a site some test
    happens to execute -- and several guards in this library are built and
    tested without being wired into the window at all
    (free_end_guard_message, no_support_detected_message and
    stirrup_grade_conflict_message have no caller outside the suite).
    """
    sites = []
    for dirpath, dirnames, filenames in os.walk(LIB):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            text = io.open(path, encoding="utf-8").read()
            rel = os.path.relpath(path, LIB).replace("\\", "/")
            # Each construction call, with everything up to its closing
            # parenthesis -- the calls span several lines.
            for match in re.finditer(r"GuardMessage\(", text):
                start = match.end()
                depth = 1
                i = start
                while i < len(text) and depth:
                    if text[i] == "(":
                        depth += 1
                    elif text[i] == ")":
                        depth -= 1
                    i += 1
                sites.append((rel, text.count("\n", 0, match.start()) + 1,
                              text[start:i]))

    assert sites, "no GuardMessage construction sites found -- pattern broken?"
    undeclared = [
        "%s:%d" % (rel, line) for rel, line, body in sites
        if "severity=" not in body
    ]
    assert not undeclared, (
        "these GuardMessage construction sites do not declare a severity, "
        "so nothing can tell whether they block or warn: %s" % undeclared
    )
    assert len(sites) == 13, (
        "expected 13 construction sites (the count this story migrated); "
        "found %d. A new guard is fine -- update this number deliberately, "
        "having checked its severity against how the caller treats it."
        % len(sites)
    )
