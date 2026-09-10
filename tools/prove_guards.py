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

SCRIPT = ("SimpleBeamRFT.extension/RFT-Tools.tab/"
          "Beams.panel/Simple Beam.pushbutton/script.py")
BUNDLE = ("SimpleBeamRFT.extension/RFT-Tools.tab/"
          "Beams.panel/Simple Beam.pushbutton/bundle.yaml")
XAML = ("SimpleBeamRFT.extension/RFT-Tools.tab/"
        "Beams.panel/Simple Beam.pushbutton/SimpleBeamWindow.xaml")
PLAN = "RFT.lib/rft/core/plan.py"
REPORT = "RFT.lib/rft/ui/report.py"
GUARDS = "RFT.lib/rft/core/guards.py"
SPACING = "RFT.lib/rft/core/spacing.py"
SKETCH_PALETTE = "RFT.lib/rft/ui/sketch_palette.py"
T = "tests/test_simple_beam_xaml.py::"
WORKFLOW = ".github/workflows/tests.yml"

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

    # The report moved to rft/ui/report.py, so this case follows it there.
    # The prover reported ANCHOR MISSING rather than passing, which is the
    # behaviour that matters: a case whose anchor has moved must not read
    # as proven.
    (REPORT, "core_plan.face_layer_plans(", "hand_rolled_layer_offsets(",
     "test_report_and_placement_both_use_the_shared_plan",
     "report recomputing ONE of its plan calls by hand"),

    # #49 (U5) added a SECOND ``core_plan.crack_plan(`` call site in this
    # file (``_sketch_crack_plan``, the live sketch's own best-effort
    # crack plan), earlier in the file than the placer's. A bare
    # single-occurrence replace of "core_plan.crack_plan(" now hits that
    # one instead, leaving the placer's call untouched and this case
    # silently unproven -- so the anchor is widened to text unique to the
    # PLACER's call site (``_build_placement_plans``'s own local variable
    # names), which the sketch's call does not share.
    (SCRIPT, 'crack = core_plan.crack_plan(\n                h_mm, b_mm, cover_side_mm, stirrup_dia_mm,',
     'crack = hand_rolled_crack_plan(\n                h_mm, b_mm, cover_side_mm, stirrup_dia_mm,',
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

    # #49's review finding: the pick handler had grown its own copy of the
    # support-detection dict. It agreed with the original key for key,
    # exactly as plan.py's copy of ZONE_LAYOUT_FLAGS agreed -- for three
    # releases, while the report and the placer built different stirrup
    # sets. This mutation puts a second writer back.
    (SCRIPT, "        self._support_detection = _support_detection(",
     '        self._support_detection = {"support_width_start_mm": None}\n'
     "        _unused = _support_detection(",
     "test_the_support_detection_dict_has_exactly_one_writer",
     "a second writer for the support-detection dict"),

    # The report's own half of the shared-plan rule. Its stirrup and crack
    # sections recomputed everything for three releases, and the guard
    # could not see it because the PLACER's calls satisfied the check.
    (REPORT, "core_plan.stirrup_plan(", "hand_rolled_stirrup_zones(",
     "test_report_and_placement_both_use_the_shared_plan",
     "report recomputing the stirrup zones by hand"),

    (REPORT, "core_plan.crack_plan(", "hand_rolled_crack_layers(",
     "test_report_and_placement_both_use_the_shared_plan",
     "report recomputing the crack plan by hand"),

    # NOT text guards -- ordinary tests over an importable module. Proven
    # here anyway, because a re-typed constant is the one kind of defect
    # that arrives looking exactly like correct code, and this one shipped.
    (PLAN, "ZONE_LAYOUT_FLAGS = ZONE_LAYOUT_FLAGS",
     'ZONE_LAYOUT_FLAGS = {\n    "zone1": (True, True),\n'
     '    "zone2": (False, True),\n    "zone3": (False, True),\n}',
     "tests/test_core_plan.py::"
     "test_the_zone_layout_flags_are_the_tested_ones_not_a_second_copy",
     "plan.py holding its own copy of the zone flags again"),

    # The same mutation with today's CORRECT values: a duplicate that
    # agrees is still a duplicate, and this is the one that would slip
    # past a values-only check.
    (PLAN, "ZONE_LAYOUT_FLAGS = ZONE_LAYOUT_FLAGS",
     'ZONE_LAYOUT_FLAGS = {\n    "zone1": (True, True),\n'
     '    "zone2": (False, False),\n    "zone3": (True, True),\n}',
     "tests/test_core_plan.py::test_only_one_module_defines_the_zone_layout_flags",
     "a second copy of the flags, with the right values (today)"),

    # #45. The text check is the one that catches the FOURTEENTH guard --
    # the per-guard table cannot, since a new guard would not be in it.
    (SPACING, "\n                message=message, severity=SEVERITY_BLOCKING,",
     "\n                message=message,",
     "tests/test_guard_severity.py::"
     "test_every_guardmessage_construction_site_in_the_library_declares_one",
     "a guard built without declaring whether it blocks"),

    # And a severity that is declared but WRONG -- downgrading a refusal
    # to a warning, which is the direction that matters.
    (GUARDS, 'message=message, severity=SEVERITY_BLOCKING,\n    )\n\n\ndef free_end_guard_message',
     'message=message, severity=SEVERITY_WARNING,\n    )\n\n\ndef free_end_guard_message',
     "tests/test_guard_severity.py::"
     "test_each_guard_declares_the_severity_v0_1_0_actually_had",
     "a refusal quietly downgraded to a warning"),

    # #49 (U5). The sketch's style-key -> brush mapping is data, not WPF,
    # so it IS importable and tested directly (tests/test_ui_sketch_
    # palette.py) -- proven anyway, since a missing/stale/mistyped entry
    # here is exactly the class of defect that looks like correct code
    # until it draws invisibly on a live host.
    (SKETCH_PALETTE, '    "bar_main": "InkPrimary",\n', "",
     "tests/test_ui_sketch_palette.py::"
     "test_every_sketch_style_key_has_a_brush_mapping",
     "a sketch style key with no brush mapping at all"),

    (SKETCH_PALETTE, '    "caption": "InkMuted",\n}',
     '    "caption": "InkMuted",\n    "not_a_real_style": "InkMuted",\n}',
     "tests/test_ui_sketch_palette.py::"
     "test_no_stale_brush_mapping_for_a_style_that_no_longer_exists",
     "a stale mapping for a style rft.ui.sketch no longer emits"),

    (SKETCH_PALETTE, '"dimension_fail": "DangerRed",',
     '"dimension_fail": "NoSuchBrushXYZ",',
     "tests/test_ui_sketch_palette.py::"
     "test_every_mapped_brush_is_declared_in_the_xaml",
     "a brush name the XAML never declares with x:Key"),

    # #62. The label width estimate and the drawn font size must be the
    # same number: estimate small, draw large, and the clipped tails come
    # straight back with nothing to say so.
    (SCRIPT, "            text_block.FontSize = SKETCH_FONT_SIZE_PX",
     "            text_block.FontSize = 14.0",
     T + "test_the_label_size_estimate_uses_the_font_the_labels_are_drawn_in",
     "the renderer drawing labels at a size it did not estimate"),

    # And the placement itself must stay in the tested module rather than
    # being inlined back into the renderer, where nothing can run it.
    (SCRIPT, "place_labels(boxes, width_px, height_px)",
     "boxes  # place_labels(boxes, width_px, height_px)",
     T + "test_every_label_is_placed_through_the_tested_layout_module",
     "label placement inlined back into the renderer"),

    # #54 (U10). The rule that a restore cannot arm Place holds because
    # four inputs are never stored. tests/test_ui_persistence.py proves
    # that against the real derivation -- but it can only see the field
    # LISTS. A script that slipped a withheld field in on its way past
    # would leave the pure module looking perfectly correct.
    (SCRIPT, "                self._persistable_type_ids(),",
     '                dict(self._persistable_type_ids(),\n'
     '                     crack_bar_type="resurrected"),',
     T + "test_the_script_persists_only_what_the_persistence_module_allows",
     "the script persisting a field that would arm Place"),

    (SCRIPT, "ui_persistence.SETTINGS_SLOT, data, this_project=True)",
     "ui_persistence.SETTINGS_SLOT, data, this_project=False)",
     T + "test_settings_are_stored_per_project_and_never_globally",
     "one job's conventions leaking into every other job"),

    # pyRevit's load_data opens the file directly and RAISES when nothing
    # has been stored -- which is the normal first run on any project.
    #
    # The mutation DELETES the gate, which is the realistic regression:
    # someone "simplifies" two lines that look redundant. The first
    # version of this case flipped the test to `if False and ...` instead
    # and the prover reported MISSED -- because the guard was grepping for
    # "script.data_exists(", which that mutation leaves in place. The
    # guard now parses the method with ast; all three shapes (deleted,
    # short-circuited, and gating without returning) are caught.
    (SCRIPT, "            if not script.data_exists(\n"
             "                    ui_persistence.SETTINGS_SLOT, this_project=True):\n"
             "                return\n", "",
     T + "test_a_first_run_checks_before_loading_stored_data",
     "loading stored data without checking it exists"),

    # The rc3 rename moved the extension, tab, panel and pushbutton and
    # missed this file, so CI failed on every push while the whole suite
    # stayed green -- the only consumer of those paths is a shell command.
    # The mutation is the rename itself, reapplied: put the old extension
    # folder back and require the guard to notice the path is gone.
    (WORKFLOW, "compileall -q RFT.lib",
     "compileall -q SimpleBeamRFT.extension/lib",
     "tests/test_ironpython_compat.py::test_every_path_the_ci_workflow_names_exists",
     "a CI path left behind by a rename"),
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
            # Anything that raises between here and the finally leaves a
            # mutated file behind, which is why the timeout above matters
            # as much as the restore below.
            # A case may name a fully qualified node ("path::test") when
            # its test lives outside the XAML suite; otherwise T applies.
            node = test if "::" in test else T + test
            # ``subprocess.run``, not ``call``, and NOT a bare PIPE.
            #
            # This used to be ``call(..., stdout=PIPE, stderr=STDOUT)``,
            # which hands the child a pipe that nobody ever reads. As long
            # as every failure message was small it worked. Then a guard
            # arrived whose failing assertion printed a 500-line module
            # source as an operand, the child filled the OS pipe buffer,
            # blocked on write, and the parent waited for it forever --
            # with a mutated file sitting in the working tree, because the
            # restore is in the ``finally`` that never ran.
            #
            # ``run`` drains the pipes, and the timeout turns any future
            # hang into a reported failure instead of a stopped tool.
            rc = subprocess.run(
                ["python", "-m", "pytest", node, "-q"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=300,
            ).returncode
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
