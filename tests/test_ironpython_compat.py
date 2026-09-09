# -*- coding: utf-8 -*-
"""Guards against Python-3-only code reaching pyRevit's IronPython 2.7 engine.

This suite runs under CPython 3.10, where every constraint checked here is
invisible: the interpreter that actually executes this extension is
**IronPython 2.7**, i.e. Python 2. Nothing else in the test suite can catch a
Python 2 incompatibility, because the pushbutton scripts are never imported
(that would need ``pyrevit`` and the Revit API) and the library modules are
imported by a Python 3 interpreter that accepts constructs IronPython
rejects outright.

Every check below corresponds to a failure observed on a live host, not to a
hypothetical:

- **Encoding declaration.** `v0.1.0-rc2` failed on every pushbutton with
  ``SyntaxError: Non-ASCII character '\xc2' in ... but no encoding
  declared``. Nine of seventeen library modules carried ``§``, ``°``, ``Ø``
  or ``×`` in a docstring without the PEP 263 cookie that Python 2 requires
  and Python 3 makes optional (UTF-8 being its default source encoding).
"""

import io
import os
import re

EXT_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "RFTBeamDetailing.extension",
)

# PEP 263: the cookie must appear on line 1 or line 2 to be honoured.
CODING_RE = re.compile(r"coding[:=]\s*([-\w.]+)")


def _extension_py_files():
    """Every .py file pyRevit's IronPython engine can load from the bundle."""
    found = []
    for root, dirs, files in os.walk(EXT_ROOT):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(files):
            if name.endswith(".py"):
                found.append(os.path.join(root, name))
    return found


def test_bundle_contains_python_files():
    """Guard the guard: an empty walk would make every test below vacuous."""
    files = _extension_py_files()
    assert len(files) >= 15, "expected the extension's modules, found %d" % len(
        files
    )


def test_every_module_with_non_ascii_declares_an_encoding():
    """Python 2 refuses a source file holding non-ASCII with no PEP 263 cookie.

    Python 3 defaults to UTF-8 and needs no declaration, so CPython imports
    these modules happily while IronPython 2.7 raises SyntaxError at compile
    time -- before any of this project's logic runs.
    """
    offenders = []
    for path in _extension_py_files():
        raw = io.open(path, "rb").read()
        if not any(byte > 127 for byte in bytearray(raw)):
            continue  # pure ASCII needs no declaration
        first_two = raw.decode("utf-8").split("\n")[:2]
        if not any(CODING_RE.search(line) for line in first_two):
            offenders.append(os.path.relpath(path, EXT_ROOT))
    assert not offenders, (
        "these modules hold non-ASCII characters but declare no source "
        "encoding on line 1 or 2, which IronPython 2.7 rejects with "
        "SyntaxError before running anything:\n  " + "\n  ".join(offenders)
    )


def test_no_fstrings():
    """f-strings are a SyntaxError on Python 2, not a runtime failure.

    One f-string anywhere in an imported module takes down the whole button.
    """
    fstring_re = re.compile(r"""(^|[^A-Za-z0-9_'"])[fF](['"])""")
    offenders = []
    for path in _extension_py_files():
        text = io.open(path, encoding="utf-8").read()
        for lineno, line in enumerate(text.split("\n"), start=1):
            if fstring_re.search(line) and "{" in line:
                offenders.append(
                    "%s:%d  %s"
                    % (os.path.relpath(path, EXT_ROOT), lineno, line.strip()[:70])
                )
    assert not offenders, "f-strings are not valid Python 2:\n  " + "\n  ".join(
        offenders
    )


def test_no_python3_only_stdlib_calls():
    """A handful of stdlib additions that exist in CPython 3 but not IronPython 2.7.

    These fail at call time rather than import time, so they would surface as
    a mid-placement crash with a partially detailed beam.
    """
    banned = {
        "math.isclose": "Python 3.5+; compare against an explicit tolerance",
        "math.inf": "Python 3.5+; use float('inf')",
        "math.nan": "Python 3.5+; use float('nan')",
        "subprocess.run": "Python 3.5+",
        "os.scandir": "Python 3.5+",
    }
    offenders = []
    for path in _extension_py_files():
        text = io.open(path, encoding="utf-8").read()
        for lineno, line in enumerate(text.split("\n"), start=1):
            code = line.split("#")[0]
            for name, why in banned.items():
                if name in code:
                    offenders.append(
                        "%s:%d  %s  (%s)"
                        % (os.path.relpath(path, EXT_ROOT), lineno, name, why)
                    )
    assert not offenders, (
        "these calls do not exist in IronPython 2.7:\n  " + "\n  ".join(offenders)
    )
