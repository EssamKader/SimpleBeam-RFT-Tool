# -*- coding: utf-8 -*-
"""Prove every text-based guard by mutation: reintroduce the defect it was
written for, and require it to fail.

WHY THIS EXISTS

Several guards in this repo check source code as TEXT, because the pyRevit
script cannot be imported under CPython (it imports `pyrevit`) and no test
can therefore evaluate it. Text checks are the only thing that CAN run --
and a text check that matches nothing passes silently. Two of them did
exactly that: a regex word boundary had been written into the file as a
literal backspace byte, so the pattern matched nothing, the comparison was
empty, and the test passed against the very defect it was written for.

A guard that has never been shown to fail has not been tested. It has only
been written.

WHY IT RESTORES WITH GIT

An earlier version wrote the original bytes back itself and hit an
OSError mid-restore on Windows, leaving a mutated file in the working
tree. A tool that can damage the repo while checking it is worse than no
tool. So: every target must be COMMITTED AND CLEAN before it is touched,
and restoration is `git checkout --`, which is the operation git exists to
make reliable. The clean-tree precondition is what makes that safe.

Run from the repo root:  python tools/prove_guards.py
"""
import io
import subprocess
import sys

SCRIPT = ("RFTBeamDetailing.extension/RFT Beam Detailing.tab/"
          "Detail Beam.panel/Detail Beam.pushbutton/script.py")
BUNDLE = ("RFTBeamDetailing.extension/RFT Beam Detailing.tab/"
          "Detail Beam.panel/Detail Beam.pushbutton/bundle.yaml")
XAML = ("RFTBeamDetailing.extension/RFT Beam Detailing.tab/"
        "Detail Beam.panel/Detail Beam.pushbutton/DetailBeamWindow.xaml")
T = "tests/test_detail_beam_xaml.py::"

GEOM_ANCHOR = "        # an anchor.\n        self.geometry_mm = None"
CATCH_ANCHOR = ("        except Exception as ex:\n"
                "            # NEVER let this reach the ExternalEvent handler")
CATCH_MUTANT = ("        except ValueError as ex:\n"
                "            # NEVER let this reach the ExternalEvent handler")

# (file, find, replace, test node, what defect this reintroduces)
CASES = [
    (SCRIPT, "review.crack_bars.requested", "review.crack.requested",
     "test_every_review_attribute_the_script_uses_exists",
     "wrong derivation attribute (the rc4 live failure)"),

    (SCRIPT, "    window.show()", "    window.ShowDialog()",
     "test_the_window_is_never_shown_modally",
     "modal window via ShowDialog"),

    (SCRIPT, "    window.show()", "    window.show_dialog()",
     "test_the_window_is_never_shown_modally",
     "modal via show_dialog (the branch that never matched)"),

    (SCRIPT, GEOM_ANCHOR, "        # an anchor.",
     "test_every_beam_scoped_attribute_is_cleared_on_pick",
     "beam-scoped state left stale on re-pick"),

    (SCRIPT, "        if not review.any_requested:\n            return missing\n", "",
     "test_place_preflight_consults_the_same_derivation_that_enables_it",
     "Place guard ignoring the derivation"),

    (BUNDLE, "engine:\n  persistent: true\n", "",
     "test_modeless_window_declares_a_persistent_engine",
     "no persistent engine (the rc2 live failure)"),

    (SCRIPT, "core_plan.face_layer_plans(", "hand_rolled_layer_offsets(",
     "test_report_and_placement_both_use_the_shared_plan",
     "report recomputing ONE of its plan calls by hand"),

    (SCRIPT, "core_plan.crack_plan(", "hand_rolled_crack_plan(",
     "test_report_and_placement_both_use_the_shared_plan",
     "placer recomputing the crack plan by hand"),

    (SCRIPT, CATCH_ANCHOR, CATCH_MUTANT,
     "test_dispatched_work_cannot_fail_silently",
     "dispatch wrapper narrows what it catches"),

    (XAML, '    <Grid Margin="8" Background="{StaticResource SurfaceWhite}">',
     '    <Grid Margin="8" Background="{StaticResource NoSuchBrush}">',
     "test_every_static_resource_reference_is_defined",
     "a StaticResource key that is never declared"),

    (XAML, '        SizeToContent="Manual">',
     '        SizeToContent="Manual" Background="{StaticResource SurfaceWhite}">',
     "test_the_window_element_itself_uses_no_static_resource",
     "StaticResource back on the Window element (the rc6 crash)"),

    (XAML, "<!-- #60: the palette, declared ONCE.",
     "<!-- #60: the palette, declared ONCE and never -- ever -- twice.",
     "test_no_xaml_comment_contains_a_double_hyphen",
     "a double hyphen inside a XAML comment"),

    (SCRIPT, "core_plan.innermost_layer_offset_mm(\n                    geometry[\"cover_top_mm\"]",
     "_face(True).layers[-1].offset_mm  # (\n                    geometry[\"cover_top_mm\"]",
     "test_the_placer_does_not_rebuild_a_face_plan_for_the_crack_offsets",
     "FacePlan rebuilt for the crack offsets (the blank-count crash)"),

    (SCRIPT, "self._support_detection = None\n        self.beam_status_tb.Text", "        self.beam_status_tb.Text",
     "test_every_beam_scoped_attribute_is_cleared_on_pick",
     "cached supports surviving a re-pick"),
]


def _git(*args):
    return subprocess.check_output(("git",) + args).decode("utf-8", "replace")


def _require_clean(paths):
    """Refuse to mutate anything that is not committed and clean.

    This is the precondition that makes `git checkout --` a safe restore:
    if the file had uncommitted work, restoring it would destroy that work
    instead of undoing the mutation.
    """
    dirty = []
    for path in sorted(set(paths)):
        if _git("status", "--porcelain", "--", path).strip():
            dirty.append(path)
    if dirty:
        print("REFUSING TO RUN: these targets have uncommitted changes, so a")
        print("git restore would discard real work rather than a mutation:")
        for path in dirty:
            print("  %s" % path)
        sys.exit(2)


def main():
    _require_clean(case[0] for case in CASES)

    missed = []
    for path, find, replace, test, label in CASES:
        original = io.open(path, encoding="utf-8").read()
        if find not in original:
            print("%-56s ANCHOR MISSING" % label)
            missed.append(label)
            continue
        try:
            io.open(path, "w", encoding="utf-8", newline="\n").write(
                original.replace(find, replace, 1))
            rc = subprocess.call(["python", "-m", "pytest", T + test, "-q"],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        finally:
            _git("checkout", "--", path)
            restored = io.open(path, encoding="utf-8").read()
            if restored != original:
                print("RESTORE FAILED for %s -- fix with:" % path)
                print('  git checkout -- "%s"' % path)
                sys.exit(3)
        if rc == 0:
            missed.append(label)
        print("%-56s %s" % (label, "caught" if rc else "*** MISSED ***"))

    print("")
    print("guards proven: %d of %d" % (len(CASES) - len(missed), len(CASES)))
    if missed:
        print("NOT PROVEN: %s" % missed)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
